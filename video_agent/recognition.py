"""Local, bounded visual evidence extraction. Uncertain evidence stops publication."""
import base64,json,math
from pathlib import Path

class NeedsManual(RuntimeError):pass

def vision(frame):
 import httpx
 r=httpx.post('http://127.0.0.1:11434/api/chat',json={'model':'pianyu-instruct','stream':False,'keep_alive':'30s','messages':[{'role':'user','content':'仅转录图片中实际可见文字，保留英文项目名，不解释、不猜测。无文字则输出空字符串。','images':[base64.b64encode(frame.read_bytes()).decode()]}],'options':{'num_ctx':8192,'num_predict':2048,'temperature':0}},timeout=600,trust_env=False)
 r.raise_for_status()
 payload=r.json()
 if not isinstance(payload,dict) or not isinstance(payload.get('message'),dict) or not isinstance(payload['message'].get('content'),str):raise NeedsManual('视觉模型返回无效文字结果')
 if payload.get('done_reason') not in (None,'stop'):raise NeedsManual('画面文字超过单帧识别预算')
 return payload['message']['content'].strip()

def visual_segments(source,folder,runner,reader=None,representative=False):
 import imageio_ffmpeg
 from PIL import Image,ImageChops,ImageStat
 ffmpeg=imageio_ffmpeg.get_ffmpeg_exe();folder=Path(folder);folder.mkdir(exist_ok=True)
 probe=runner.run([ffmpeg,'-hide_banner','-i',str(source)],timeout=30)
 import re
 metadata=(probe.stderr.decode(errors='replace') if isinstance(probe.stderr,bytes) else probe.stderr)
 match=re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',metadata)
 if not match:raise NeedsManual('无法确认视频长度和画面覆盖范围')
 duration=int(match[1])*3600+int(match[2])*60+float(match[3])
 count=max(1,math.ceil(duration/3))
 if count>120 and not representative:raise NeedsManual('视频超过当前完整画面采样预算，请人工选择口播或分段处理')
 segments=[];previous=None;previous_text=None
 timestamps=sorted(set(max(0,min(duration-.05,t)) for t in ([0,duration/2,max(0,duration-1)] if representative else [i*3 for i in range(count)])))
 for timestamp in timestamps:
  frame=folder/f'{timestamp:.3f}.jpg'
  result=runner.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y','-ss',str(max(0,timestamp)),'-i',str(source),'-frames:v','1','-vf','scale=1280:1280:force_original_aspect_ratio=decrease',str(frame)],timeout=60)
  if result.returncode or not frame.exists():raise NeedsManual('代表画面提取失败')
  with Image.open(frame) as im:small=im.convert('L').resize((64,64))
  if ImageStat.Stat(small).stddev[0]<3:continue
  if previous is not None and ImageStat.Stat(ImageChops.difference(previous,small)).mean[0]<2:continue
  previous=small.copy()
  cache=frame.with_suffix('.txt')
  text=cache.read_text() if cache.exists() else (reader or vision)(frame).strip()
  cache.write_text(text)
  normalized=''.join(text.split()).casefold()
  if not normalized or normalized==previous_text:continue
  previous_text=normalized;segments.append({'start':timestamp,'end':min(duration,timestamp+3),'text':text,'source':'visual'})
 return segments

def speech_pilot(folder,runner):
 import imageio_ffmpeg,sys,os
 from .pipeline import Ollama,MODEL,PROJECT
 audio=folder/'pilot.wav';output=folder/'pilot.json'
 Ollama().unload()
 result=runner.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(folder/'source.video'),'-t','30','-vn','-ac','1','-ar','16000',str(audio)],timeout=60)
 if result.returncode:return ''
 env=os.environ.copy();env['HF_HUB_OFFLINE']='1';env['PATH']=str(PROJECT/'runtimes'/'video-bin')+os.pathsep+env.get('PATH','')
 result=runner.run([sys.executable,'-m','video_agent.transcribe',str(audio),str(output),str(MODEL)],env=env,cwd=PROJECT,timeout=600)
 if result.returncode:raise NeedsManual('试转录失败，无法确认音频证据')
 return ' '.join(s['text'] for s in json.loads(output.read_text()))

def classify_evidence(visual,speech):
 import httpx
 r=httpx.post('http://127.0.0.1:11434/api/chat',json={'model':'pianyu-instruct','stream':False,'keep_alive':0,'format':'json','messages':[{'role':'user','content':'根据以下实际OCR和30秒试转录判断类型。音乐、无意义重复或幻觉不算讲话。只返回JSON mode(audio/visual/demo/unknown),confidence(0到1),reason。visual为静态文字，demo为操作演示且语音与画面互补。证据不足unknown。\n'+json.dumps({'frames':visual,'speech':speech},ensure_ascii=False)}],'options':{'num_ctx':8192,'num_predict':512,'temperature':0}},timeout=600,trust_env=False)
 r.raise_for_status()
 try:decision=json.loads(r.json()['message']['content'])
 except (ValueError,KeyError):raise NeedsManual('类型判断返回无效结果')
 if not isinstance(decision,dict):raise NeedsManual('类型判断结果不是有效对象')
 mode=decision.get('mode')
 if mode not in ('audio','visual','demo') or not isinstance(decision.get('confidence'),(int,float)) or isinstance(decision['confidence'],bool) or not math.isfinite(decision['confidence']) or not .85<=decision['confidence']<=1:raise NeedsManual(str(decision.get('reason','类型判断不确定')))
 if mode in ('audio','demo') and len(speech.strip())<20:raise NeedsManual('缺少可靠讲话证据')
 if mode in ('visual','demo') and not visual:raise NeedsManual('缺少可靠画面证据')
 return decision

def merge_segments(speech,visual):
 def normalized(segment):return ''.join(segment['text'].split()).casefold()
 result=[dict(s,source='speech') for s in speech]
 for segment in visual:
  duplicate=any(normalized(segment)==normalized(s) and abs(segment['start']-s['start'])<=3 for s in speech)
  if not duplicate:result.append(segment)
 return sorted(result,key=lambda s:s['start'])

def recognize(job,folder,runner):
 from .pipeline import atomic_json
 mode=job.get('recognition_mode','legacy_audio')
 if mode=='legacy_audio':return None
 selected=mode;decision={'reason':'按指定模式识别'};segments=[]
 if mode=='auto':
  pilot=visual_segments(folder/'source.video',folder/'frames',runner,representative=True)
  atomic_json(folder/'recognition.json',{'requested_mode':mode,'preflight_evidence':pilot,'reason':'正在核验音频与类型'})
  speech=speech_pilot(folder,runner)
  decision=classify_evidence(pilot,speech);selected=decision['mode']
  decision['preflight_evidence']=pilot
  decision['coverage']={'preflight_frames':'start, middle, end','speech_seconds':30}
 decision.update(requested_mode=mode,selected_mode=selected)
 atomic_json(folder/'recognition.json',decision)
 if selected in ('visual','demo'):
  segments=visual_segments(folder/'source.video',folder/'frames',runner)
  if not segments:raise NeedsManual('代表画面没有可靠文字')
  decision.setdefault('coverage',{})['visual_interval_seconds']=3
 decision.update(requested_mode=mode,selected_mode=selected,evidence=segments)
 atomic_json(folder/'recognition.json',decision)
 return None if selected=='audio' else segments
