"""Bounded durable staging; staging never queues processing."""
import hashlib,json,time,uuid
from pathlib import Path
from .store import CONFIG_VERSION
from .pipeline import atomic_json

class FolderImport:
 def __init__(self,store,capture=None):
  self.capture=capture
  self.store=store;self.root=store.root/'staging';self.root.mkdir(exist_ok=True)
 def cleanup(self):
  cutoff=time.time()-86400
  with self.store.lock:
   for p in self.root.glob('*.json'):
    if p.stat().st_mtime>=cutoff:continue
    item=json.loads(p.read_text())
    if 'action' in item and 'result' not in item:continue
    p.with_suffix('.video').unlink(missing_ok=True);p.unlink()
   for pattern in ('*.video','*.tmp'):
    for p in self.root.glob(pattern):
     if p.stat().st_mtime<cutoff and (pattern=='*.tmp' or not p.with_suffix('.json').exists()):p.unlink()
 def stage(self,path,name,recognition_mode="auto"):
  if recognition_mode not in ('auto','audio','visual','demo'):raise ValueError('无效识别模式')
  with self.store.lock:
   self.cleanup()
   if len(list(self.root.glob('*.video')))>=100:raise ValueError('暂存上限100个文件，请提交或取消')
   path=Path(path)
   if not 0<path.stat().st_size<=2*1024**3:raise ValueError('单文件必须大于0且不超过2GiB')
   if Path(name).suffix.lower() not in ('.mp4','.mov','.mkv','.webm'):raise ValueError('不支持的视频格式')
   h=hashlib.sha256()
   with path.open('rb') as f:
    for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
   fingerprint=hashlib.sha256((h.hexdigest()+CONFIG_VERSION+'_recognition-v1_'+recognition_mode).encode()).hexdigest()
   matches=[j for j in self.store.list() if j['fingerprint']==fingerprint]
   item={'id':uuid.uuid4().hex,'name':str(name)[:1000],'fingerprint':fingerprint,'matches':matches,'created':time.time(),'recognition_mode':recognition_mode}
   video=self.root/(item['id']+'.video');meta=video.with_suffix('.json')
   path.replace(video)
   try:atomic_json(meta,item)
   except Exception:
    video.unlink(missing_ok=True);meta.with_suffix('.json.tmp').unlink(missing_ok=True);raise
   return item
 def read(self,ticket):
  if not isinstance(ticket,str) or len(ticket)!=32 or any(c not in '0123456789abcdef' for c in ticket):raise ValueError('无效暂存编号')
  p=self.root/(ticket+'.json')
  if not p.exists():raise ValueError('暂存已过期')
  return json.loads(p.read_text())
 def pending(self):
  """Recover unsubmitted browser manifests without queuing or expiring files."""
  with self.store.lock:
   by_fingerprint={}
   for job in self.store.list():by_fingerprint.setdefault(job['fingerprint'],[]).append(job)
   items=[]
   for path in sorted(self.root.glob('*.json'),key=lambda p:p.name):
    try:
     item=json.loads(path.read_text())
     if 'action' in item or 'result' in item or not path.with_suffix('.video').is_file():continue
     items.append({'id':item['id'],'name':item['name'],'created':item['created'],'recognition_mode':item.get('recognition_mode','legacy_audio'),'matches':by_fingerprint.get(item['fingerprint'],[])})
    except (OSError,ValueError,KeyError,TypeError):continue
   return sorted(items,key=lambda i:(i['created'],i['id']))
 def cancel(self,ticket):
  with self.store.lock:
   item=self.read(ticket)
   if 'result' in item:return
   if 'action' in item:raise ValueError('选择已提交，请重试原选择')
   (self.root/(ticket+'.video')).unlink(missing_ok=True);(self.root/(ticket+'.json')).unlink()
 def _overwrite_target(self,item,old_id):
  old=self.store.get(old_id)
  safe=('ready','published','failed','interrupted','publish_failed','refresh_failed','needs_manual')
  if any(j['fingerprint']==item['fingerprint'] and j['status'] not in safe for j in self.store.list()):raise ValueError('相同内容有运行中、排队或待核对任务，不能覆盖')
  if old['fingerprint']!=item['fingerprint']:raise ValueError('覆盖目标内容不匹配')
  if old['status'] not in ('ready','published','failed','interrupted','publish_failed','refresh_failed','needs_manual'):raise ValueError('旧任务运行中或写入待核对，不能覆盖')
  return old
 def prepare(self,ticket,old_id):
  with self.store.lock:
   item=self.read(ticket)
   if 'action' in item:
    if item['action']!='overwrite' or item['old_id']!=old_id:raise ValueError('已提交的选择不可更改')
    return {'check_id':item['prepared']['check_id']}
   old=self._overwrite_target(item,old_id)
   plan=None
   if old['page_id']:
    folder=self.store.root/'jobs'/old_id
    target=None
    for name in ('publish-target.json','notion-journal.json'):
     p=folder/name
     if p.exists():
      data=json.loads(p.read_text());target=data.get('target',data)
      if target:break
    if not target:raise ValueError('原页面缺少目标凭据，不能安全自动覆盖')
    plan={'operation':'overwrite','page_id':old['page_id'],'target':target,'automatic':True}
    plan['baseline_error']='Notion凭证缺失，本地结果已保留'
    if self.capture:self.capture(plan)
   check_id=uuid.uuid4().hex
   item['prepared']={'check_id':check_id,'old_id':old_id,'plan':plan}
   atomic_json(self.root/(ticket+'.json'),item)
   return {'check_id':check_id}
 def commit(self,ticket,action,old_id=None,check_id=None,credential_available=True):
  with self.store.lock:
   item=self.read(ticket)
   if action=='overwrite':
    prepared=item.get('prepared') or {}
    if not check_id or prepared.get('check_id')!=check_id or prepared.get('old_id')!=old_id:raise ValueError('请先重新核验所选覆盖目标')
   if 'action' in item:
    if item['action']!=action or item.get('old_id')!=old_id:raise ValueError('已提交的选择不可更改')
    if 'result' in item:return item['result']
    try:existing=self.store.get(ticket)
    except KeyError:pass
    else:
     item['result']=existing;atomic_json(self.root/(ticket+'.json'),item);return existing
   if action not in ('new','overwrite','skip'):raise ValueError('请选择新增、覆盖或跳过')
   plan=None
   if action=='overwrite':
    old=self._overwrite_target(item,old_id)
    plan=item.get('plan',prepared['plan'])
    if (plan or {}).get('page_id')!=(old['page_id'] or None):
     raise ValueError('旧任务关联页面已改变，请重新核验')
   if 'action' not in item:
    if plan and not credential_available:plan=dict(plan,baseline_error='提交时缺少 Notion 凭证，本地结果已保留')
    item.update(action=action,old_id=old_id,plan=plan)
    atomic_json(self.root/(ticket+'.json'),item)
   if action=='skip':result={'skipped':True}
   else:
    jid=ticket
    folder=self.store.root/'jobs'/jid;folder.mkdir(exist_ok=True)
    if not (folder/'source.video').exists():(self.root/(ticket+'.video')).replace(folder/'source.video')
    if plan:atomic_json(folder/'automatic-overwrite.json',plan)
    now=time.time()
    self.store.db.execute('INSERT INTO jobs(id,fingerprint,name,status,detail,error,created,updated,recognition_mode) VALUES (?,?,?,?,?,?,?,?,?)',(jid,item['fingerprint'],Path(item['name']).name[:200],'queued','等待处理','',now,now,item.get('recognition_mode','legacy_audio')));self.store.db.commit();result=self.store.get(jid)
   item.update(result=result,action=action,old_id=old_id);atomic_json(self.root/(ticket+'.json'),item)
   (self.root/(ticket+'.video')).unlink(missing_ok=True);return result

class AutomaticRevisionStore:
 """Hold the revision in processing until its confirmed page is verified."""
 def __init__(self,store):self.store=store;self.root=store.root
 def update(self,jid,**fields):
  if fields.get('status')=='ready':
   fields.update(status='organizing',detail='等待核验原页面')
  self.store.update(jid,**fields)
