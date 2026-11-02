"""Reviewed queue operations, durable per-item receipts, and reversible local trash."""
import hashlib,json,os,shutil,time,uuid
from pathlib import Path
from .pipeline import atomic_json

SAFE={'ready','published','failed','interrupted','publish_failed','refresh_failed','needs_manual'}
PUBLISHABLE={'ready','published','publish_failed','refresh_failed'}

class BatchService:
    def __init__(self,store,capture=None,check_publish=None,publish=None):
        self.store=store;self.root=store.root;self.lock=store.lock;self.capture=capture;self.check_publish=check_publish;self.publish=publish
        self.directory=self.root/'batches';self.directory.mkdir(exist_ok=True)
    def _stamp(self,job):
        result=self.root/'jobs'/job['id']/'result.json'
        return {'updated':job['updated'],'status':job['status'],'page_id':job['page_id'],'result':hashlib.sha256(result.read_bytes()).hexdigest() if result.exists() else None}
    def _eligible(self,job,action):
        if job['status'] not in (PUBLISHABLE if action=='publish' else SAFE):raise ValueError('任务正在执行、排队或写入结果待核对，暂不能操作')
        if action=='reprocess':
            with self.lock:
                placeholders=','.join('?' for _ in SAFE)
                if self.store.db.execute('SELECT 1 FROM jobs WHERE fingerprint=? AND trashed_at IS NULL AND status NOT IN ('+placeholders+')',(job['fingerprint'],*SAFE)).fetchone():raise ValueError('相同视频有执行中、排队或待核对任务，请完成后重新处理')
        if action!='publish':
            with self.lock:
                exists=self.store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='card_runs'").fetchone()
                if exists and self.store.db.execute("SELECT 1 FROM card_runs WHERE jid=? AND status IN ('queued','running')",(job['id'],)).fetchone():raise ValueError('知识卡片正在生成或排队，请完成后操作')
    def _target_plan(self,job):
        folder=self.root/'jobs'/job['id'];target=None
        auto=folder/'automatic-overwrite.json'
        inherited=json.loads(auto.read_text()) if auto.exists() else {}
        page_id=job['page_id'] or inherited.get('page_id')
        if not page_id:
            if auto.exists():raise ValueError('原自动覆盖关联无效，不能安全重新处理')
            return None
        for name in ('publish-target.json','notion-journal.json'):
            p=folder/name
            if p.exists():
                data=json.loads(p.read_text());target=data.get('target',data)
                if target:break
        if not target and inherited.get('page_id')==page_id:target=inherited.get('target')
        if not target:raise ValueError('原记录缺少关联目标，不能安全自动覆盖')
        plan={'operation':'overwrite','automatic':True,'page_id':page_id,'target':target,'baseline_error':'无法核验原Notion页面或凭证缺失'}
        if self.capture:self.capture(plan)
        if plan.get('baseline_error') or not plan.get('last_edited_time'):raise ValueError(plan.get('baseline_error') or '无法确认原页面版本')
        return plan
    def prepare(self,action,ids):
        if action not in ('publish','reprocess','trash'):raise ValueError('无效批量操作')
        if not isinstance(ids,list) or not 1<=len(ids)<=200 or any(not isinstance(i,str) for i in ids):raise ValueError('每批请选择1至200个任务')
        batch={'id':uuid.uuid4().hex,'action':action,'created':time.time(),'items':[]}
        targets=set()
        for jid in dict.fromkeys(ids):
            item={'id':jid,'name':jid}
            try:
                with self.lock:
                    job=self.store.get(jid);item['name']=job['name'];self._eligible(job,action);item['stamp']=self._stamp(job)
                if action=='publish':
                    item['check']=self.check_publish(jid)
                elif action=='reprocess':
                    if not (self.root/'jobs'/jid/'source.video').is_file():raise ValueError('原始视频缺失，不能重新处理')
                    item['plan']=self._target_plan(job);item['revision_id']=uuid.uuid4().hex
                    if item['plan']:
                        pid=item['plan']['page_id'].replace('-','').lower()
                        if pid in targets:raise ValueError('本批已有另一任务覆盖同一Notion页面，请只选择其中一项重处理')
                        targets.add(pid)
                with self.lock:
                    if self._stamp(self.store.get(jid))!=item['stamp']:raise ValueError('核验期间任务已改变，请重新选择')
            except (ValueError,KeyError) as e:item['error']=str(e).strip("'")
            except Exception:item['error']='核验失败，请检查服务或连接后重试'
            batch['items'].append(item)
        atomic_json(self.directory/(batch['id']+'.json'),batch)
        return batch
    def _read(self,bid):
        if not isinstance(bid,str) or len(bid)!=32 or any(c not in '0123456789abcdef' for c in bid):raise ValueError('无效批量编号')
        p=self.directory/(bid+'.json')
        if not p.is_file():raise ValueError('批量操作不存在，请重新选择')
        return json.loads(p.read_text()),p
    def _publish_receipt(self,jid,bid):
        folder=self.root/'jobs'/jid
        for p in [folder/'publish-plan.json',*folder.glob('publication-history/*/publish-plan.json')]:
            if p.exists() and json.loads(p.read_text()).get('batch_id')==bid:return True
        return False
    def _reprocess(self,item):
        jid=item['revision_id'];folder=self.root/'jobs'/jid
        try:return self.store.get(jid)
        except KeyError:pass
        old=self.store.get(item['id']);folder.mkdir(exist_ok=True)
        dest=folder/'source.video'
        if not dest.exists():
            source=self.root/'jobs'/old['id']/'source.video'
            try:os.link(source,dest)
            except OSError:shutil.copyfile(source,dest)
        if item.get('plan'):atomic_json(folder/'automatic-overwrite.json',item['plan'])
        atomic_json(folder/'reprocess-origin.json',{'job_id':old['id']})
        now=time.time()
        with self.store.db:
            self.store.db.execute('INSERT INTO jobs(id,fingerprint,name,status,detail,error,created,updated,recognition_mode) VALUES (?,?,?,?,?,?,?,?,?)',(jid,old['fingerprint'],old['name'],'queued','等待全新重处理'+('，完成后自动覆盖原Notion' if item.get('plan') else ''),'',now,now,old.get('recognition_mode','legacy_audio')))
        return self.store.get(jid)
    def commit(self,bid,choices=None):
        choices=choices or {}
        if not isinstance(choices,dict):raise ValueError('批量选择格式不正确')
        with self.lock:
            batch,path=self._read(bid)
            if 'choices' in batch and batch['choices']!=choices:raise ValueError('已提交选择不可改变，请勿重复提交')
            if batch.get('done'):return {'id':bid,'action':batch['action'],'items':[i['result'] for i in batch['items']]}
            if 'choices' not in batch:
                if time.time()-batch['created']>600:raise ValueError('核验已过期，请重新选择')
                batch['choices']=choices;atomic_json(path,batch)
            targets=set()
            for item in batch['items']:
                if 'result' in item:continue
                result={'id':item['id'],'name':item['name'],'ok':False}
                try:
                    if item.get('error'):raise ValueError(item['error'])
                    action=batch['action'];choice=choices.get(item['id'],{})
                    if action=='publish' and choice.get('action')=='skip':result.update(ok=True,skipped=True)
                    elif action=='reprocess' and (self.root/'jobs'/item['revision_id']/'source.video').exists() and self.store.db.execute('SELECT 1 FROM jobs WHERE id=?',(item['revision_id'],)).fetchone():
                        result.update(ok=True,job_id=item['revision_id'])
                    elif action=='publish' and self._publish_receipt(item['id'],bid):result.update(ok=True,job_id=item['id'])
                    elif action=='trash' and item.get('started') and self.store.get(item['id'],include_trashed=True)['trashed_at'] is not None:result.update(ok=True)
                    else:
                        job=self.store.get(item['id']);self._eligible(job,action)
                        if self._stamp(job)!=item['stamp']:raise ValueError('任务或文案自核验后已改变，请重新选择')
                        item['started']=True;atomic_json(path,batch)
                        if action=='trash':
                            with self.store.db:self.store.db.execute('UPDATE jobs SET trashed_at=?,updated=? WHERE id=?',(time.time(),time.time(),job['id']))
                            result.update(ok=True)
                        elif action=='reprocess':
                            revision=self._reprocess(item);result.update(ok=True,job_id=revision['id'])
                        else:
                            if not isinstance(choice,dict):raise ValueError('请选择写入方式')
                            if choice.get('action')=='overwrite':
                                pid=str(choice.get('page_id','')).replace('-','').lower()
                                if pid in targets:raise ValueError('本批已有任务覆盖同一Notion页面，该项未提交')
                                targets.add(pid)
                            payload={**choice,'check_id':item['check']['check_id']}
                            self.publish(item['id'],payload,bid);result.update(ok=True,job_id=item['id'])
                except (ValueError,KeyError) as e:result['error']=str(e).strip("'")
                except Exception:result['error']='提交失败，请检查任务状态或本地服务；不会自动重复写入'
                item['result']=result;atomic_json(path,batch)
            batch['done']=True;atomic_json(path,batch)
            return {'id':bid,'action':batch['action'],'items':[i['result'] for i in batch['items']]}
    def trash_list(self):return self.store.list(trashed=True)
    def restore(self,jid):
        with self.lock:
            job=self.store.get(jid,include_trashed=True)
            if job['trashed_at'] is None:return job
            with self.store.db:self.store.db.execute('UPDATE jobs SET trashed_at=NULL,updated=? WHERE id=?',(time.time(),jid))
            return self.store.get(jid)
