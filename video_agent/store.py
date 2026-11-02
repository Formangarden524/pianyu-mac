"""SQLite job ledger; source files are content-addressed and never overwritten."""
import hashlib,json,sqlite3,threading,uuid,time
from pathlib import Path

CONFIG_VERSION='whisper-small-v1_qwen-instruct-v1'
ACTIVE=('recognizing','extracting','transcribing','organizing')
class Store:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);(self.root/'jobs').mkdir(exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(str(self.root/'jobs.sqlite3'),check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,fingerprint TEXT UNIQUE,name TEXT,status TEXT,detail TEXT,error TEXT,page_id TEXT,page_url TEXT,publish_offset INTEGER DEFAULT 0,created REAL,updated REAL)')
            # Rebuild the legacy UNIQUE fingerprint table transactionally, preserving rows.
            if 'fingerprint TEXT UNIQUE' in self.db.execute("SELECT sql FROM sqlite_master WHERE name='jobs'").fetchone()[0]:
                self.db.execute('ALTER TABLE jobs RENAME TO jobs_legacy')
                schema=self.db.execute("SELECT sql FROM sqlite_master WHERE name='jobs_legacy'").fetchone()[0]
                self.db.execute(schema.replace('jobs_legacy','jobs').replace('fingerprint TEXT UNIQUE','fingerprint TEXT'))
                self.db.execute('INSERT INTO jobs SELECT * FROM jobs_legacy')
                self.db.execute('DROP TABLE jobs_legacy')
                self.db.execute('CREATE INDEX IF NOT EXISTS jobs_fingerprint ON jobs(fingerprint)')
            if 'trashed_at' not in {r[1] for r in self.db.execute('PRAGMA table_info(jobs)')}:
                self.db.execute('ALTER TABLE jobs ADD COLUMN trashed_at REAL')
            if 'recognition_mode' not in {r[1] for r in self.db.execute('PRAGMA table_info(jobs)')}:
                self.db.execute("ALTER TABLE jobs ADD COLUMN recognition_mode TEXT DEFAULT 'legacy_audio'")
    def get(self,jid,include_trashed=False):
        with self.lock: r=self.db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if r is None or (r['trashed_at'] is not None and not include_trashed): raise KeyError('任务不存在')
        return dict(r)
    def list(self,trashed=False):
        with self.lock:return [dict(r) for r in self.db.execute('SELECT * FROM jobs WHERE trashed_at IS '+('NOT NULL' if trashed else 'NULL')+' ORDER BY created DESC')]
    def visible_list(self):
        # Keep immutable recognition history, but show one current revision.
        records=self.list();superseded=set()
        for item in records+self.list(trashed=True):
            path=self.root/'jobs'/item['id']/'recognition-parent.json'
            if path.exists():
                try:superseded.add(json.loads(path.read_text())['job_id'])
                except (ValueError,KeyError):pass
        return [j for j in records if j['id'] not in superseded or j['status'] not in ('needs_manual','failed','interrupted')]
    def update(self,jid,**fields):
        allowed={'status','detail','error','page_id','page_url','publish_offset'}
        if not set(fields)<=allowed:raise ValueError('invalid update')
        fields['updated']=time.time()
        with self.lock:
            self.db.execute('UPDATE jobs SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),jid));self.db.commit()
    def import_file(self,path,name,recognition_mode="auto",force_new=False):
        if recognition_mode not in ("auto","audio","visual","demo"):raise ValueError("无效识别模式")
        path=Path(path);h=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        fingerprint=hashlib.sha256((h.hexdigest()+CONFIG_VERSION+"_recognition-v1_"+recognition_mode).encode()).hexdigest()
        with self.lock:
            old=self.db.execute('SELECT * FROM jobs WHERE fingerprint=? AND trashed_at IS NULL',(fingerprint,)).fetchone()
            if old and not force_new:path.unlink(missing_ok=True);return dict(old)
            jid=uuid.uuid4().hex;folder=self.root/'jobs'/jid;folder.mkdir()
            path.replace(folder/'source.video');now=time.time()
            self.db.execute('INSERT INTO jobs(id,fingerprint,name,status,detail,error,created,updated) VALUES (?,?,?,?,?,?,?,?)',(jid,fingerprint,Path(name).name[:200],'queued','等待处理','',now,now));self.db.execute('UPDATE jobs SET recognition_mode=? WHERE id=?',(recognition_mode,jid));self.db.commit()
        return self.get(jid)
    def recover(self):
        with self.lock:
            self.db.execute("UPDATE jobs SET status='interrupted',detail='服务中断，可继续' WHERE status IN ('recognizing','extracting','transcribing','organizing')")
            for row in self.db.execute("SELECT id,status FROM jobs WHERE status IN ('publishing','publish_queued')").fetchall():
                journal=self.root/'jobs'/row['id']/'notion-journal.json'
                try: state=json.loads(journal.read_text()) if journal.exists() else None
                except (ValueError,OSError):state={'inflight':True}
                if row['status']=='publish_queued' and state is None:
                    plan_path=journal.with_name('publish-plan.json')
                    try:plan=json.loads(plan_path.read_text())
                    except (OSError,ValueError):plan={}
                    if isinstance(plan,dict) and plan.get('automatic'):continue
                    status,detail='ready','尚未发送写入请求，请重新确认发布'
                elif state is not None and not state.get('inflight',True):
                    status,detail='publish_failed','已有写入检查点，可在核对后继续'
                else:status,detail='publish_uncertain','上次写入结果待核对，请先查看Notion'
                self.db.execute('UPDATE jobs SET status=?,detail=? WHERE id=?',(status,detail,row['id']))
            self.db.commit()
            for row in self.db.execute("SELECT id FROM jobs WHERE status IN ('refreshing','refresh_queued')").fetchall():
                p=self.root/'jobs'/row['id']/'notion-refresh.json'
                try: state=json.loads(p.read_text()) if p.exists() else {}
                except (ValueError,OSError):state={'inflight':True}
                status='published' if state.get('done') else ('refresh_uncertain' if state.get('inflight') else 'refresh_failed')
                self.db.execute('UPDATE jobs SET status=?,detail=? WHERE id=?',(status,'更新中断，请核对后继续',row['id']))
            self.db.commit()
    def retry(self,jid):
        with self.lock:
            job=self.get(jid)
            if job['status'] not in ('failed','interrupted'):raise ValueError('仅失败或中断任务可继续；写入结果不确定时请先核对Notion')
            self.update(jid,status='queued',error='',detail='继续处理，复用已有阶段')
        return self.get(jid)
    def claim(self):
        with self.lock:
            r=self.db.execute("SELECT id FROM jobs WHERE trashed_at IS NULL AND status IN ('queued','publish_queued','refresh_queued') ORDER BY created LIMIT 1").fetchone()
            if not r:return None
            job=self.get(r['id']);publishing=job['status']=='publish_queued'
            refreshing=job['status']=='refresh_queued'
            self.update(r['id'],status='refreshing' if refreshing else ('publishing' if publishing else 'extracting'),detail='更新既有页面' if refreshing else ('写入 Notion' if publishing else '检查音轨'));return self.get(r['id'])
    def begin_publish(self,jid):
        with self.lock:
            job=self.get(jid)
            if job['status'] not in ('ready','publish_failed'):raise ValueError('仅预览就绪或明确写入失败的任务可以写入')
            self.update(jid,status='publish_queued',detail='等待写入 Notion');return self.get(jid)

    def begin_refresh(self,jid):
        with self.lock:
            job=self.get(jid)
            if not job['page_id'] or job['status'] not in ('published','refresh_failed'):raise ValueError('仅已发布或明确更新失败的页面可更新')
            journal=self.root/'jobs'/jid/'notion-refresh.json'
            if journal.exists() and json.loads(journal.read_text()).get('done'):
                journal.replace(journal.with_name('notion-refresh-history-'+uuid.uuid4().hex+'.json'))
            self.update(jid,status='refresh_queued',error='',detail='等待重新整理并更新原页面')
            return self.get(jid)

    def begin_write(self,jid,plan,*,automatic=False):
        with self.lock:
            job=self.get(jid)
            allowed=('organizing',) if automatic else ('ready','published','publish_failed','refresh_failed')
            if job['status'] not in allowed:raise ValueError('当前任务状态不允许写入')
            folder=self.root/'jobs'/jid
            history=folder/'publication-history'/uuid.uuid4().hex
            history.mkdir(parents=True)
            for name in ('notion-journal.json','notion-refresh.json','notion-overwrite.json','publish-plan.json','publish-target.json'):
                f=folder/name
                if f.exists():f.replace(history/name)
            from .pipeline import atomic_json
            atomic_json(folder/'publish-plan.json',plan);atomic_json(folder/'publish-target.json',plan['target'])
            self.update(jid,status='publish_queued',error='',detail='等待覆盖原记录' if plan['operation']=='overwrite' else '等待新增写入')
            return self.get(jid)

    def change_recognition_mode(self,jid,mode):
        import shutil
        if mode not in ('auto','audio','visual','demo'):raise ValueError('无效识别模式')
        with self.lock:
            old=self.get(jid)
            if old['status'] not in ('needs_manual','failed','interrupted'):raise ValueError('仅待人工判断、失败或中断任务可切换模式')
            source=self.root/'jobs'/jid
            temporary=self.root/('revision-'+uuid.uuid4().hex)
            import os
            os.link(source/'source.video',temporary)
            # Force a fresh revision even when this mode was attempted before.
            job=self.import_file(temporary,old['name'],mode,force_new=True)
            if job['id']==jid:raise ValueError('请选择不同识别模式')
            target=self.root/'jobs'/job['id']
            (target/'recognition-parent.json').write_text(json.dumps({'job_id':jid}))
            # Preserve any pending automatic plan as evidence, never activate it implicitly.
            for name in ('automatic-overwrite.json','publish-plan.json'):
                if (source/name).exists():shutil.copyfile(source/name,target/('prior-'+name))
            return job
