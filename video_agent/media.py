"""Upload original video bytes to Notion; never substitutes a localhost URL."""
import json,math,mimetypes
from .pipeline import atomic_json
from .notion import NotionError

PART_SIZE=10*1024*1024

def upload_video(client,folder,name,progress=None):
    source=folder/'source.video';size=source.stat().st_size
    if not size:raise ValueError('原视频为空')
    path=folder/'notion-upload.json';state=json.loads(path.read_text()) if path.exists() else {}
    mime=mimetypes.guess_type(name)[0] or 'application/octet-stream'
    try:
        if state.get('id'):
            info=client.request('GET','/file_uploads/'+state['id'])
            if info.get('status')=='uploaded':return video_block(state['id'],name)
            if info.get('status')!='pending':state={}
        if not state.get('id'):
            multi=size>20*1024*1024
            payload={'filename':name,'content_type':mime,'mode':'multi_part' if multi else 'single_part'}
            if multi:payload['number_of_parts']=math.ceil(size/PART_SIZE)
            info=client.request('POST','/file_uploads',payload)
            if not info.get('id'):raise ValueError('Notion上传响应缺少ID')
            state={'id':info['id'],'multi':multi,'sent':0};atomic_json(path,state)
        with source.open('rb') as f:
            count=math.ceil(size/PART_SIZE) if state['multi'] else 1
            for i in range(state['sent'],count):
                if state['multi']:f.seek(i*PART_SIZE);body=f.read(PART_SIZE)
                else:body=f
                if progress:progress(f'上传原视频 {i+1}/{count} 段')
                client.request('POST','/file_uploads/'+state['id']+'/send',files={'file':(name,body,mime)},form={'part_number':str(i+1)} if state['multi'] else {})
                state['sent']=i+1;atomic_json(path,state)
        if state['multi']:client.request('POST','/file_uploads/'+state['id']+'/complete',{})
        info=client.request('GET','/file_uploads/'+state['id'])
        if info.get('status')!='uploaded':raise ValueError('Notion原视频尚未上传完成，请稍后重试')
        return video_block(state['id'],name)
    except NotionError as e:
        # Upload transfer can be retried; no page blocks have been changed yet.
        if e.uncertain:path.unlink(missing_ok=True)
        raise NotionError('原视频上传未完成：'+str(e),False) from None


def video_block(upload_id,name):
    return {'object':'block','type':'video','video':{'type':'file_upload','file_upload':{'id':upload_id},'caption':[{'type':'text','text':{'content':name[:200]}}]}}
