"""Durable, retryable deletion limited to explicitly linked pages and a managed folder."""
import hashlib,json,time,uuid,os
from pathlib import Path
from .pipeline import atomic_json
SAFE={'ready','published','failed','interrupted','publish_failed','refresh_failed','needs_manual'}
MANAGED=Path.home()/'Movies'/'片语视频库'
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
class Deletion:
 def __init__(self,store,client_factory):self.store=store;self.client_factory=client_factory;self.root=store.root/'deletions';self.root.mkdir(exist_ok=True)
 def prepare(self,jid):
  with self.store.lock:
   j=self.store.get(jid)
   if j['status'] not in SAFE:raise ValueError('任务正在执行或写入待核对，不能删除')
   source=self.store.root/'jobs'/jid/'source.video'
   sha=digest(source);external=[]
   if MANAGED.exists():
    for p in MANAGED.rglob('*'):
     if p.is_file() and not p.is_symlink() and MANAGED.resolve() in p.resolve().parents and p.suffix.lower() in ('.mp4','.mov','.mkv','.webm') and p.stat().st_size==source.stat().st_size and digest(p)==sha:external.append(str(p))
   # Related records with the exact bytes must not silently survive and reappear.
   jobs=[];pages=set()
   for x in self.store.list():
    p=self.store.root/'jobs'/x['id']/'source.video'
    if p.exists() and p.stat().st_size==source.stat().st_size and digest(p)==sha:
     if x['status'] not in SAFE:raise ValueError('同一视频有活动或待核对任务，请先处理')
     if self.store.db.execute("SELECT 1 FROM sqlite_master WHERE name='card_runs'").fetchone() and self.store.db.execute("SELECT 1 FROM card_runs WHERE jid=? AND status IN ('queued','running')",(x['id'],)).fetchone():raise ValueError('知识卡片正在生成，请完成后删除')
     jobs.append({'id':x['id'],'updated':x['updated']})
     if x.get('page_id'):pages.add(x['page_id'])
   plan={'id':uuid.uuid4().hex,'sha256':sha,'jobs':jobs,'pages':sorted(pages),'external':external,'created':time.time(),'steps':{},'done':False}
   atomic_json(self.root/(plan['id']+'.json'),plan);return plan
 def commit(self,id):
  if len(id)!=32 or any(c not in '0123456789abcdef' for c in id):raise ValueError('无效删除编号')
  path=self.root/(id+'.json')
  with self.store.lock:
   plan=json.loads(path.read_text())
   if plan['done']:return plan
   if not plan['steps']:
    if time.time()-plan['created']>600:raise ValueError('删除核验已过期')
    for x in plan['jobs']:
     j=self.store.get(x['id'])
     if j['updated']!=x['updated'] or j['status'] not in SAFE:raise ValueError('任务已改变，请重新核验')
   # Persistent deletion intent blocks imports even if a later step needs retry.
   marker=self.root/(plan['sha256']+'.blocked');marker.write_text(id)
   client=self.client_factory() if plan['pages'] else None
   try:
    for page in plan['pages']:
     if plan['steps'].get(page):continue
     current=client.request('GET','/pages/'+page)
     if not (current.get('archived') or current.get('in_trash')):client.request('PATCH','/pages/'+page,{'archived':True})
     check=client.request('GET','/pages/'+page)
     if not (check.get('archived') or check.get('in_trash')):raise ValueError('Notion回收校验失败')
     plan['steps'][page]=True;atomic_json(path,plan)
   finally:
    if client:client.close()
   for original in plan['external']:
    key='external:'+original
    if plan['steps'].get(key):continue
    p=Path(original);target=Path.home()/'.Trash'/('片语-'+id+'-'+p.name)
    if p.exists():
     if p.is_symlink() or MANAGED.resolve() not in p.resolve().parents or digest(p)!=plan['sha256']:raise ValueError('外部文件变化，已停止删除')
     if target.exists():raise ValueError('废纸篓目标已存在，请核对文件，未覆盖')
     target.parent.mkdir(exist_ok=True);os.rename(p,target)
    elif not target.exists():raise ValueError('外部文件不在原处或预期废纸篓位置，请人工核对')
    plan['steps'][key]=str(target);atomic_json(path,plan)
   for x in plan['jobs']:
    with self.store.db:self.store.db.execute('UPDATE jobs SET trashed_at=?,updated=? WHERE id=?',(time.time(),time.time(),x['id']))
   plan['done']=True;atomic_json(path,plan);return plan
