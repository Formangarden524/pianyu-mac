"""Update the same Notion page, only replacing verifiably agent-owned blocks."""
import json
from collections import Counter
from urllib.parse import urlencode
from .core import block_batches
from .pipeline import atomic_json
from .notion import NotionError

def signature(block):
    kind=block['type'];body=block.get(kind,{})
    texts=body.get('rich_text',body.get('caption',[]))
    def rich(t):
        a=t.get('annotations',{});style=tuple(a.get(k,False) for k in ('bold','italic','strikethrough','underline','code'))+(a.get('color','default'),)
        return (t.get('plain_text',t.get('text',{}).get('content','')),t.get('href') or (t.get('text',{}).get('link') or {}).get('url'),style)
    return kind,tuple(rich(t) for t in texts),body.get('language') if kind=='code' else None

def verify_owned_blocks(expected,remote):
    ids=[];cursor=0
    counts=Counter(signature(b) for b in expected);actual=Counter(signature(b) for b in remote)
    if any(actual[k]!=n for k,n in counts.items()):raise ValueError('页面存在相同文字的额外块或内容已改变，无法确定归属，已停止替换')
    for b in expected:
        while cursor<len(remote) and signature(remote[cursor])!=signature(b):cursor+=1
        if cursor>=len(remote):raise ValueError('页面原有内容已被手动修改，无法安全识别全部Agent块，已停止自动替换')
        if remote[cursor].get('has_children'):raise ValueError('原有块包含新增子笔记，已停止替换以保留内容')
        ids.append(remote[cursor]['id']);cursor+=1
    return ids

def refresh_page(client,store,job,result):
    folder=store.root/'jobs'/job['id'];old_path=folder/'notion-journal.json';path=folder/'notion-refresh.json'
    old=json.loads(old_path.read_text())
    tag_properties=client.tag_properties(old['target'],result['tags']) if result.get('tags') else {}
    if old.get('inflight'):raise NotionError('原始发布结果尚待核对，不能更新',True)
    if path.exists():state=json.loads(path.read_text())
    else:
        remote=[];cursor=None
        while True:
            query='?page_size=100'+('&'+urlencode({'start_cursor':cursor}) if cursor else '')
            d=client.request('GET','/blocks/'+job['page_id']+'/children'+query);remote+=d['results']
            if not d.get('has_more'):break
            cursor=d['next_cursor']
        owned=verify_owned_blocks(old['blocks'],remote)
        from .media import upload_video
        video=upload_video(client,folder,job['name'],lambda detail:store.update(job['id'],detail=detail))
        state={'page_id':job['page_id'],'old_ids':owned,'blocks':client.build_blocks(job,result,video),'offset':0,'archived':0,'inflight':False,'done':False};atomic_json(path,state)
    if state['inflight']:raise NotionError('更新页面时上次响应不确定，请先在Notion核对，禁止重复追加',True)
    if state['done']:
        store.update(job['id'],status='published',detail='Notion 排版与原视频已更新',error='');return
    try:
        for batch in block_batches(state['blocks'][state['offset']:]):
            state['inflight']=True;atomic_json(path,state)
            client.request('PATCH','/blocks/'+state['page_id']+'/children',{'children':batch})
            state['offset']+=len(batch);state['inflight']=False;atomic_json(path,state)
        # All replacement blocks must be confirmed before old blocks are archived.
        for block_id in state['old_ids'][state['archived']:]:
            # Re-check immediately before archiving; uploads and LLM analysis can take time.
            current=client.request('GET','/blocks/'+block_id)
            expected=old['blocks'][state['old_ids'].index(block_id)]
            if not current.get('archived') and (current.get('has_children') or signature(current)!=signature(expected)):
                raise ValueError('旧块在更新期间被修改，已停止归档；新内容和用户笔记均保留')
            client.request('PATCH','/blocks/'+block_id,{'archived':True})
            state['archived']+=1;atomic_json(path,state)
        if tag_properties:client.sync_tag_properties(job['page_id'],tag_properties,state,path)
    except NotionError as e:
        if not e.uncertain:state['inflight']=False;atomic_json(path,state)
        raise
    state['done']=True;atomic_json(path,state)
    atomic_json(old_path,{**old,'blocks':state['blocks'],'offset':len(state['blocks']),'layout_version':'code-video-v2','inflight':False})
    store.update(job['id'],status='published',detail='Notion 排版与原视频已更新',error='')

class RefreshStore:
    """Keep publish controls locked while an existing page is being reanalyzed."""
    def __init__(self,store):self.store=store;self.root=store.root
    def update(self,jid,**fields):
        if 'status' in fields:fields['status']='refreshing'
        self.store.update(jid,**fields)
