"""Author provenance from explicit folder imports and processing lineage."""
import json
from pathlib import Path

def author_properties(schema,author):
 if not author:return {}
 prop=schema.get('作者账号',{});kind=prop.get('type')
 if kind=='multi_select':return {'作者账号':{'multi_select':[{'name':author}]}}
 if kind=='select':return {'作者账号':{'select':{'name':author}}}
 if kind=='rich_text':return {'作者账号':{'rich_text':[{'type':'text','text':{'content':author}}]}}
 raise ValueError('Notion作者账号字段缺失或类型不支持')

def local_author(store,jid):
 seen=set()
 while jid and jid not in seen:
  seen.add(jid);row=store.db.execute('SELECT data FROM library_metadata WHERE id=?',(jid,)).fetchone()
  if row and json.loads(row[0]).get('author'):return json.loads(row[0])['author']
  parent=None
  for name in ['reprocess-origin.json','recognition-parent.json']:
   p=store.root/'jobs'/jid/name
   if p.exists():parent=json.loads(p.read_text()).get('job_id');break
  jid=parent
 return ''
