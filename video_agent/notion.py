"""Bounded official Notion API writer with durable write-intent journal."""
import json,re,time,datetime
from pathlib import Path
import httpx
from .core import notion_blocks,code_blocks,block_batches
from .pipeline import atomic_json
from .titles import title_properties

class NotionError(RuntimeError):
    def __init__(self,message,uncertain=False,status_code=None):super().__init__(message);self.uncertain=uncertain;self.status_code=status_code

def parse_id(value):
    value=value.strip().split('?')[0].rstrip('/')
    matches=re.findall(r'[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',value)
    if not matches:raise ValueError('请输入有效的 Notion 页面/数据库链接或 ID')
    return matches[-1]

class NotionClient:
    def __init__(self,token,transport=None):
        if not token:raise ValueError('请先填写 Notion Integration 密钥')
        self.client=httpx.Client(base_url='https://api.notion.com/v1',headers={'Authorization':'Bearer '+token,'Notion-Version':'2025-09-03'},timeout=40,follow_redirects=False,trust_env=False,transport=transport)
        self.last_request=0
    def close(self):self.client.close()
    def request(self,method,path,data=None,files=None,form=None):
        if not path.startswith('/') or '://' in path:raise ValueError('invalid API path')
        wait=.38-(time.monotonic()-self.last_request)
        if wait>0:time.sleep(wait)
        try:
            self.last_request=time.monotonic();r=self.client.request(method,path,files=files,data=form,timeout=180) if files is not None else self.client.request(method,path,json=data)
        except httpx.HTTPError:
            raise NotionError('Notion 网络连接中断；写入操作的结果需要核对',uncertain=method!='GET') from None
        if not r.is_success:
            uncertain=method!='GET' and r.status_code>=500
            raise NotionError(f'Notion 返回 HTTP {r.status_code}。请检查目标授权、Integration权限或稍后重试。',uncertain=uncertain,status_code=r.status_code)
        try:return r.json()
        except ValueError:raise NotionError('Notion 响应无法解析，需要核对写入结果',uncertain=method!='GET') from None
    def resolve(self,kind,value):
        target=parse_id(value)
        if kind=='page':
            page=self.request('GET','/pages/'+target)
            if page.get('object')!='page' or page.get('archived') or page.get('in_trash'):raise ValueError('目标页面不可用')
            return {'kind':'page','id':target,'title_property':'title'}
        if kind=='database':
            db=self.request('GET','/databases/'+target);sources=db.get('data_sources',[])
            if len(sources)!=1:raise ValueError('该数据库有多个或没有数据源，请改选“数据源”并填写具体 data_source_id')
            target=sources[0]['id']
        elif kind!='data_source':raise ValueError('目标类型不支持')
        source=self.request('GET','/data_sources/'+target)
        titles=[k for k,v in source.get('properties',{}).items() if v.get('type')=='title']
        if len(titles)!=1:raise ValueError('无法找到数据源的标题属性')
        return {'kind':'data_source','id':target,'title_property':titles[0]}
    def tag_properties(self,target,tags):
        if target['kind']!='data_source':return {}
        from .tags import validate_tags
        tags=validate_tags(tags)
        source=self.request('GET','/data_sources/'+target['id']);schema=source.get('properties',{})
        properties={}
        for key,aliases in [('primary',('主标签','1级标签','一级标签')),('secondary',('二级标签','2级标签'))]:
            names=[name for name in aliases if name in schema]
            if len(names)!=1:raise ValueError('数据库需有明确的主标签与二级标签字段，请检查字段名称')
            name=names[0];kind=schema[name].get('type')
            if kind not in ('select','multi_select'):raise ValueError('数据库标签字段必须为选择或多选类型：'+name)
            value={'name':tags[key]};properties[name]={kind:[value] if kind=='multi_select' else value}
        return properties
    @staticmethod
    def tag_hash(properties):
        import hashlib
        return hashlib.sha256(json.dumps(properties,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    def sync_tag_properties(self,page_id,properties,state,path):
        if not properties or state.get('tags_hash')==self.tag_hash(properties):return
        state['inflight']=True;atomic_json(path,state)
        self.request('PATCH','/pages/'+page_id,{'properties':properties})
        state['tags_hash']=self.tag_hash(properties);state['inflight']=False;atomic_json(path,state)
    def publish(self,store,job,target,result):
        tag_properties=self.tag_properties(target,result['tags']) if result.get('tags') else {}
        folder=store.root/'jobs'/job['id'];journal=folder/'notion-journal.json'
        from .duplicates import video_digest
        job=dict(job,source_sha256=video_digest(folder))
        if journal.exists():state=json.loads(journal.read_text())
        else:
            from .media import upload_video
            video=upload_video(self,folder,job['name'],lambda message:store.update(job['id'],detail=message))
            blocks=self.build_blocks(job,result,video)
            state={'target':target,'blocks':blocks,'page_id':None,'page_url':None,'offset':0,'inflight':False};atomic_json(journal,state)
        if state['inflight']:raise NotionError('上一次写入响应不确定，请先在 Notion 核对；已阻止重复写入',True)
        blocks=state['blocks']
        try:
            while state['offset']<len(blocks):
                batch=next(block_batches(blocks[state['offset']:]))
                state['inflight']=True;atomic_json(journal,state)
                if not state['page_id']:
                    frozen=state['target'];parent={'type':'page_id','page_id':frozen['id']} if frozen['kind']=='page' else {'type':'data_source_id','data_source_id':frozen['id']}
                    body={'parent':parent,'properties':title_properties(frozen,job['name']),'children':batch}
                    body['properties'].update(tag_properties)
                    response=self.request('POST','/pages',body)
                    if not response.get('id'):raise NotionError('Notion创建响应缺少页面ID，请核对',True)
                    state['page_id']=response['id'];state['page_url']=response.get('url','')
                    if tag_properties:state['tags_hash']=self.tag_hash(tag_properties)
                else:self.request('PATCH','/blocks/'+state['page_id']+'/children',{'children':batch})
                state['offset']+=len(batch);state['inflight']=False;atomic_json(journal,state)
                store.update(job['id'],page_id=state['page_id'],page_url=state['page_url'],publish_offset=state['offset'],detail=f"Notion 已写 {state['offset']}/{len(blocks)} 块")
            self.sync_tag_properties(state['page_id'],tag_properties,state,journal)
        except NotionError as e:
            if not e.uncertain:state['inflight']=False;atomic_json(journal,state)
            raise
        store.update(job['id'],status='published',detail='已写入 Notion',error='')

    @staticmethod
    def build_blocks(job,result,video):
        blocks=notion_blocks('原始视频','')+[video]
        for title,key in [('整理文案','clean'),('认知盲区与认知误区摘要','summary'),('关键词：盲区、边界与误区','keywords')]:blocks+=code_blocks(title,result[key])
        blocks+=notion_blocks('来源',f"文件：{job['name']}\n任务标识：{job['id']}"+(f"\n视频指纹：{job['source_sha256']}" if job.get('source_sha256') else ''))
        return blocks
