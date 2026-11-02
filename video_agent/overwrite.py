"""Explicitly confirmed same-page body overwrite; database properties are retained."""
import json
from urllib.parse import urlencode
from .pipeline import atomic_json
from .core import block_batches
from .notion import NotionError
from .refresh import signature
from .duplicates import video_digest

def overwrite_page(client,store,job,plan,result):
    folder=store.root/'jobs'/job['id'];path=folder/'notion-overwrite.json';pid=plan['page_id']
    tag_properties=client.tag_properties(plan['target'],result['tags']) if result.get('tags') else {}
    if path.exists():state=json.loads(path.read_text())
    else:
        remote=[];cursor=None
        while True:
            q='?page_size=100'+('&'+urlencode({'start_cursor':cursor}) if cursor else '')
            d=client.request('GET','/blocks/'+pid+'/children'+q);remote+=d.get('results',[])
            if not d.get('has_more'):break
            cursor=d['next_cursor']
        if any(b.get('has_children') or b['type'] in ('child_page','child_database') for b in remote):raise ValueError('所选页面含嵌套内容、子页面或数据库，不自动覆盖，请选择不写入或新增')
        # Protect edits made since the user reviewed the duplicate dialog.
        page=client.request('GET','/pages/'+pid)
        if plan.get('automatic'):verify_folder_page(page,plan)
        if plan.get('last_edited_time') and page.get('last_edited_time')!=plan['last_edited_time']:raise ValueError('所选页面已被修改，请重新检测并确认覆盖')
        from .media import upload_video
        video=upload_video(client,folder,job['name'],lambda detail:store.update(job['id'],detail=detail))
        latest=client.request('GET','/pages/'+pid)
        if plan.get('automatic'):verify_folder_page(latest,plan)
        if page.get('last_edited_time')!=latest.get('last_edited_time'):raise ValueError('视频上传期间原页面被修改，请重新检测并确认覆盖')
        data=dict(job,source_sha256=video_digest(folder));state={'page_id':pid,'page_url':page.get('url','https://www.notion.so/'+pid.replace('-','')),'old_blocks':remote,'blocks':client.build_blocks(data,result,video),'offset':0,'archived':0,'inflight':False};atomic_json(path,state)
    if state['inflight']:raise NotionError('上次覆盖写入结果不确定，请先核对Notion，已阻止重复写入',True)
    try:
        for batch in block_batches(state['blocks'][state['offset']:]):
            state['inflight']=True;atomic_json(path,state)
            client.request('PATCH','/blocks/'+pid+'/children',{'children':batch})
            state['offset']+=len(batch);state['inflight']=False;atomic_json(path,state)
        for old in state['old_blocks'][state['archived']:]:
            current=client.request('GET','/blocks/'+old['id'])
            if not current.get('archived') and (current.get('has_children') or current.get('last_edited_time')!=old.get('last_edited_time') or signature(current)!=signature(old)):
                raise ValueError('原页面内容在覆盖过程中被修改，已保留新旧内容，请人工核对')
            client.request('PATCH','/blocks/'+old['id'],{'archived':True});state['archived']+=1;atomic_json(path,state)
        if tag_properties:client.sync_tag_properties(pid,tag_properties,state,path)
    except NotionError as e:
        if not e.uncertain:state['inflight']=False;atomic_json(path,state)
        raise
    state['done']=True;atomic_json(path,state)
    atomic_json(folder/'notion-journal.json',{'target':plan['target'],'blocks':state['blocks'],'page_id':pid,'page_url':state['page_url'],'offset':len(state['blocks']),'inflight':False})
    store.update(job['id'],status='published',page_id=pid,page_url=state['page_url'],detail='已覆盖所选页面正文，数据库属性保留',error='')

def verify_folder_page(page,plan):
    from .duplicates import same_id
    target=plan['target'];parent=page.get('parent',{})
    key='data_source_id' if target['kind']=='data_source' else 'page_id'
    if page.get('archived') or page.get('in_trash') or not same_id(parent.get(key),target['id']):
        raise ValueError('原页面已归档或目标已改变')
    stamp=page.get('last_edited_time')
    if not stamp or ('last_edited_time' in plan and stamp!=plan['last_edited_time']):
        raise ValueError('所选页面已被修改或无法核验，请重新确认覆盖')
    return stamp
