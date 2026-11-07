"""Non-destructive content projection over explicit processing lineage."""
import json
from .titles import clean_title
from .chinese import simplified
class Library:
 def __init__(self,store):
  self.store=store
  with store.lock,store.db:store.db.execute('CREATE TABLE IF NOT EXISTS library_metadata (id TEXT PRIMARY KEY,data TEXT NOT NULL,version INTEGER NOT NULL)')
 def metadata(self,id):
  r=self.store.db.execute('SELECT data,version FROM library_metadata WHERE id=?',(id,)).fetchone()
  return {**(json.loads(r[0]) if r else {}),'version':r[1] if r else 0}
 def list(self,q='',tag='',sort='new',favorite=False,author='',offset=0,limit=30):
  with self.store.lock:
   jobs=self.store.list();all_jobs={j['id']:j for j in jobs+self.store.list(trashed=True)};parents={}
   for id in all_jobs:
    for name in ['recognition-parent.json','reprocess-origin.json']:
     p=self.store.root/'jobs'/id/name
     if p.exists():
      try:
       parent=json.loads(p.read_text()).get('job_id')
       if parent in all_jobs and parent!=id:parents[id]=parent
      except (ValueError,OSError):pass
   def root(id):
    seen=set()
    while id in parents and id not in seen:seen.add(id);id=parents[id]
    return id
   groups={}
   for j in jobs:
    p=self.store.root/'jobs'/j['id']/'result.json'
    if not p.exists():continue
    try:data=json.loads(p.read_text())
    except (ValueError,OSError):continue
    if not isinstance(data.get('clean'),str) or not data['clean'].strip():continue
    groups.setdefault(root(j['id']),[]).append((j,data))
   items=[];tags=set();authors=set()
   for id,versions in groups.items():
    versions.sort(key=lambda x:x[0]['created'],reverse=True);j,d=versions[0];meta=self.metadata(id);primary=d.get('tags',{}).get('primary','');secondary=d.get('tags',{}).get('secondary','');text=simplified(d['clean']);name=clean_title(j['name'])
    if primary:tags.add(primary)
    if meta.get('author'):authors.add(meta['author'])
    if q.casefold() not in (name+'\n'+text+'\n'+meta.get('author','')).casefold():continue
    if tag and tag not in (primary,secondary):continue
    if favorite and not meta.get('favorite'):continue
    if author and meta.get('author')!=author:continue
    sync='已同步 Notion' if j['status']=='published' else '重复已跳过' if '重复' in j['detail'] else '已整理' if j['status']=='ready' else '同步需关注'
    items.append({'id':id,'job_id':j['id'],'name':name,'excerpt':text[:140],'primary':primary,'secondary':secondary,'created':all_jobs[id]['created'],'sync':sync,'versions':len(versions),'history':[{'id':v[0]['id'],'created':v[0]['created'],'status':v[0]['status'],'page_url':v[0].get('page_url')} for v in [(attempt,None) for attempt in sorted(jobs,key=lambda x:x['created'],reverse=True) if root(attempt['id'])==id]],'metadata':meta,'page_url':j.get('page_url')})
   items.sort(key=lambda x:x['name'] if sort=='title' else x['created'],reverse=sort=='new')
   return {'items':items[offset:offset+limit],'total':len(items),'tags':sorted(tags),'authors':sorted(authors)}
 def save(self,id,data,expected):
  allowed={'favorite','author','source_url','published_date'}
  if not isinstance(data,dict) or not set(data)<=allowed:raise ValueError('来源字段无效')
  if 'favorite' in data and not isinstance(data['favorite'],bool):raise ValueError('收藏设置无效')
  for k,v in data.items():
   if k!='favorite' and (not isinstance(v,str) or len(v)>2000):raise ValueError('字段内容无效或过长')
  if data.get('source_url') and not data['source_url'].startswith(('https://','http://')):raise ValueError('来源链接须为http或https')
  if data.get('published_date'):
   from datetime import date
   try:date.fromisoformat(data['published_date'])
   except ValueError:raise ValueError('发布时间须为有效日期')
  with self.store.lock:
   self.store.get(id,include_trashed=True);old=self.metadata(id)
   if old.pop('version')!=expected:raise ValueError('信息已变化，请刷新后重试')
   value={**old,**data}
   with self.store.db:self.store.db.execute('INSERT OR REPLACE INTO library_metadata VALUES (?,?,?)',(id,json.dumps(value,ensure_ascii=False),expected+1))
   return {**value,'version':expected+1}
