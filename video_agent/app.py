"""Loopback-only GUI and a single durable worker."""
import asyncio,contextlib,fcntl,json,os,threading,time,uuid,logging
from pathlib import Path
from urllib.parse import unquote,quote
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse,Response
from fastapi.staticfiles import StaticFiles
from .chinese import simplified_result
from .auto_publish import choose_action
from .store import Store
from .content import ContentService
from .batch import BatchService
from .progress import progress_snapshot
from .tags import ensure_tags
from .folder_import import FolderImport,AutomaticRevisionStore
from .pipeline import Pipeline,PROJECT,MODEL,atomic_json
from .notion import NotionClient,NotionError
from .processes import ProcessRunner
from .refresh import RefreshStore,refresh_page
from .credentials import KeychainVault,CredentialError
from .duplicates import find_duplicates,same_id
from .overwrite import overwrite_page,verify_folder_page

MAX_UPLOAD=2*1024**3
STATIC=Path(__file__).parent/'static'

def create_app(root=None,worker=True,vault=None,notion_factory=None):
    runner=ProcessRunner()
    root=Path(root or PROJECT/'outputs'/'video-agent');store=Store(root);stop=threading.Event();config_lock=threading.RLock()
    settings_path=root/'settings.json'
    saved=json.loads(settings_path.read_text()) if settings_path.exists() else {}
    make_notion=notion_factory or NotionClient
    vault=vault if vault is not None else KeychainVault(root)
    credential_error=''
    try:persisted_token=vault.load()
    except CredentialError as e:persisted_token='';credential_error=str(e)
    config={'token':os.environ.get('NOTION_TOKEN','') or persisted_token,'kind':saved.get('kind','page'),'target':saved.get('target',os.environ.get('NOTION_TARGET','')),'resolved':None,'auto_publish':saved.get('auto_publish',True),'duplicate_policy':saved.get('duplicate_policy','skip')}
    def snapshot():
        nonlocal credential_error
        with config_lock:
            if not config['token']:
                try:
                    config['token']=vault.load()
                    credential_error=''
                except CredentialError as e:credential_error=str(e)
            return dict(config)
    def capture(plan):
        token=snapshot()['token']
        if not token:return
        client=make_notion(token)
        try:
            plan['last_edited_time']=verify_folder_page(client.request('GET','/pages/'+plan['page_id']),plan)
            del plan['baseline_error']
        except (NotionError,ValueError):plan['baseline_error']='提交时无法核验原页面，本地结果已保留'
        finally:client.close()
    folder_import=FolderImport(store,capture)
    content=ContentService(store)
    batches=BatchService(store,capture=capture)
    def worker_loop():
        while not stop.is_set():
            job=store.claim()
            if not job:
                model=Pipeline(store).ollama
                if content.pending():
                    try:content.run_next(model.chat)
                    finally:model.unload()
                else:stop.wait(1)
                continue
            publishing=job['status']=='publishing'
            refreshing=job['status']=='refreshing'
            try:
                if publishing or refreshing:
                    cfg=snapshot();client=make_notion(cfg['token'])
                    try:
                        if refreshing:
                            folder=root/'jobs'/job['id']
                            old_result=folder/'result.json'
                            if old_result.exists() and not (folder/'result-before-v2.json').exists():
                                atomic_json(folder/'result-before-v2.json',json.loads(old_result.read_text()))
                            if not (folder/'proofread.json').exists():Pipeline(RefreshStore(store),runner=runner).process(job)
                        result=simplified_result(json.loads((root/'jobs'/job['id']/'result.json').read_text()))
                        if refreshing:
                            old=json.loads((root/'jobs'/job['id']/'notion-journal.json').read_text())
                            if old['target']['kind']=='data_source':result=ensure_tags(store,job,result)
                            refresh_page(client,store,job,result)
                        else:
                            target=json.loads((root/'jobs'/job['id']/'publish-target.json').read_text())
                            plan_path=root/'jobs'/job['id']/'publish-plan.json'
                            plan=json.loads(plan_path.read_text()) if plan_path.exists() else {'operation':'create','target':target}
                            if plan['operation']=='overwrite':
                                if plan['target']['kind']=='data_source':result=ensure_tags(store,job,result)
                                overwrite_page(client,store,job,plan,result)
                            else:
                                duplicates=find_duplicates(client,target,job,root/'jobs'/job['id'])
                                if duplicates and plan['operation']!='new':
                                    store.update(job['id'],status='ready',detail='检测到已有记录，请重新选择覆盖、不写入或新增');continue
                                if target['kind']=='data_source':result=ensure_tags(store,job,result)
                                client.publish(store,job,target,result)
                    finally:client.close()
                else:
                    auto=root/'jobs'/job['id']/'automatic-overwrite.json'
                    automatic=auto.exists()
                    Pipeline(AutomaticRevisionStore(store) if automatic else store,runner=runner).process(job)
                    if store.get(job['id'])['status']=='needs_manual':continue
                    if automatic:
                        plan=json.loads(auto.read_text());cfg=snapshot()
                        if plan.get('baseline_error') or not plan.get('last_edited_time') or not cfg['token']:
                            store.update(job['id'],status='publish_failed',error=plan.get('baseline_error') or '缺少凭证或原页面版本，本地结果已保留',detail='自动覆盖失败');continue
                        client=make_notion(cfg['token'])
                        try:
                            page=client.request('GET','/pages/'+plan['page_id'])
                            verify_folder_page(page,plan)
                            store.begin_write(job['id'],plan,automatic=True)
                        except ValueError as e:
                            store.update(job['id'],status='publish_failed',error=str(e),detail='本地结果已保留')
                        finally:client.close()
                    elif snapshot()['auto_publish'] and store.get(job['id'])['status']=='ready':
                        try:
                            check=check_publish(job['id'])
                            action,page_id=choose_action(check['duplicates'],snapshot()['duplicate_policy'])
                            if action=='skip':store.update(job['id'],detail='重复记录已自动跳过；可手动写入')
                            else:commit_publish(job['id'],{'check_id':check['check_id'],'action':action,'page_id':page_id})
                        except Exception as e:
                            message=str(e.detail) if isinstance(e,HTTPException) else (str(e) if isinstance(e,ValueError) else '连接异常，请检查 Notion 设置后重试')
                            token=snapshot()['token']
                            if token:message=message.replace(token,'[已隐藏]')
                            store.update(job['id'],status='publish_failed',error=message[:500],detail='自动写入未完成，本地结果已保留')
            except NotionError as e:
                status=('refresh_uncertain' if e.uncertain else 'refresh_failed') if refreshing else ('publish_uncertain' if e.uncertain else 'publish_failed')
                store.update(job['id'],status=status,error=str(e),detail='需核对 Notion' if e.uncertain else '写入失败，可重试')
            except Exception as e:
                # Avoid returning credentials, request headers, or raw HTTP errors.
                message=str(e) if isinstance(e,(ValueError,RuntimeError)) else '处理失败，请检查模型服务、依赖或文件；已有阶段已保留'
                cfg=snapshot()
                if cfg['token']:message=message.replace(cfg['token'],'[已隐藏]')
                store.update(job['id'],status='refresh_failed' if refreshing else ('publish_uncertain' if publishing else 'failed'),error=message[:500],detail='更新失败，可继续' if refreshing else ('写入结果待核对' if publishing else '处理失败，可重试'))
    @contextlib.asynccontextmanager
    async def lifespan(app):
        thread=None;handle=None
        if worker:
            handle=(root/'agent.lock').open('a+')
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('已有一个 Agent 在使用该数据目录，请勿重复启动')
            handle.seek(0);handle.truncate();handle.write(str(os.getpid()));handle.flush();store.recover();content.recover()
            thread=threading.Thread(target=worker_loop,daemon=True,name='video-agent-worker');thread.start()
        yield
        stop.set()
        await asyncio.to_thread(runner.stop)
        # Keep the exclusive directory lock until the worker and any HTTP write finish.
        if thread:await asyncio.to_thread(thread.join)
        if handle:handle.close()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None);app.state.store=store;app.state.content=content;app.state.batches=batches
    @app.middleware('http')
    async def guard(request,call_next):
        host=request.headers.get('host','');port=os.environ.get('VIDEO_AGENT_PORT','8765')
        allowed={f'127.0.0.1:{port}',f'localhost:{port}'}
        if host not in allowed:return JSONResponse({'detail':'仅允许本机同源访问'},403)
        if request.method not in ('GET','HEAD'):
            origin=request.headers.get('origin')
            if (origin and origin not in {'http://'+h for h in allowed}) or request.headers.get('x-video-agent')!='1':
                return JSONResponse({'detail':'跨站请求已拒绝'},403)
        response=await call_next(request)
        response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"})
        return response
    def get_job(jid):
        try:return store.get(jid)
        except KeyError:raise HTTPException(404,'任务不存在')
    @app.get('/')
    def index():return FileResponse(STATIC/'index.html')
    @app.get('/api/health')
    def health():
        weights=any((MODEL/n).exists() for n in ('weights.npz','weights.safetensors'))
        return {'active_card_tasks':content.pending(),'queue_batch_enabled':True,'content_tools_enabled':True,'folder_import_enabled':True,'asr_ready':(MODEL/'config.json').exists() and weights,'model':'pianyu-instruct','upload_limit_gib':2,'data_directory':str(root),'notion_configured':bool(snapshot()['token'])}
    @app.get('/api/jobs')
    def jobs():return store.visible_list()
    @app.get('/api/progress')
    def progress():return progress_snapshot(store,folder_import)
    @app.get('/api/folder/pending')
    def pending_folder():return folder_import.pending()
    @app.post('/api/upload')
    async def upload(request:Request):
        mode=request.headers.get('x-recognition-mode','auto')
        if mode not in ('auto','audio','visual','demo'):raise HTTPException(400,'无效识别模式')
        name=unquote(request.headers.get('x-filename','video.mp4'))
        if Path(name).suffix.lower() not in {'.mp4','.mov','.mkv','.webm'}:raise HTTPException(400,'支持 MP4、MOV、MKV、WEBM')
        path=root/(uuid.uuid4().hex+'.upload');total=0
        try:
            with path.open('xb') as f:
                async for chunk in request.stream():
                    total+=len(chunk)
                    if total>MAX_UPLOAD:raise HTTPException(413,'单个视频上限2GiB')
                    f.write(chunk)
            if not total:raise HTTPException(400,'文件为空')
            return await asyncio.to_thread(store.import_file,path,name,mode)
        finally:path.unlink(missing_ok=True)
    @app.post('/api/folder/stage')
    async def folder_stage(request:Request):
        mode=request.headers.get('x-recognition-mode','auto')
        if mode not in ('auto','audio','visual','demo'):raise HTTPException(400,'无效识别模式')
        name=unquote(request.headers.get('x-filename','video.mp4'));path=root/(uuid.uuid4().hex+'.upload');total=0
        try:
            with path.open('xb') as f:
                async for chunk in request.stream():
                    total+=len(chunk)
                    if total>MAX_UPLOAD:raise HTTPException(413,'单个视频上限2GiB')
                    f.write(chunk)
            return await asyncio.to_thread(folder_import.stage,path,name,mode)
        except ValueError as e:raise HTTPException(400,str(e))
        finally:path.unlink(missing_ok=True)
    @app.post('/api/folder/{ticket}/prepare')
    async def folder_prepare(ticket:str,request:Request):
        data=await request.json()
        try:return await asyncio.to_thread(folder_import.prepare,ticket,data.get('old_id'))
        except (ValueError,KeyError) as e:raise HTTPException(409,str(e))
    @app.post('/api/folder/{ticket}/commit')
    async def folder_commit(ticket:str,request:Request):
        data=await request.json()
        if not data.get('confirmed'):raise HTTPException(409,'请确认覆盖会自动更新关联Notion页面')
        try:return await asyncio.to_thread(folder_import.commit,ticket,data.get('action'),data.get('old_id'),data.get('check_id'),bool(snapshot()['token']))
        except (ValueError,KeyError) as e:raise HTTPException(409,str(e))
    @app.delete('/api/folder/{ticket}')
    def folder_cancel(ticket:str):
        try:folder_import.cancel(ticket);return {'cancelled':True}
        except ValueError as e:raise HTTPException(404,str(e))
    @app.get('/api/jobs/{jid}')
    def detail(jid:str):
        job=get_job(jid);path=root/'jobs'/job['id']/'result.json'
        with store.lock:return {'job':job,'result':simplified_result(json.loads(path.read_text())) if path.exists() else None,**content.detail(jid),'recognition':json.loads((path.parent/'recognition.json').read_text()) if (path.parent/'recognition.json').exists() else {}}
    @app.post('/api/jobs/{jid}/recognition-mode')
    async def change_recognition_mode(jid:str,request:Request):
        data=await request.json();mode=data.get('mode') if isinstance(data,dict) else None
        if mode not in ('audio','visual','demo'):raise HTTPException(400,'请选择明确的识别模式')
        old=get_job(jid)
        if old['status'] not in ('needs_manual','failed','interrupted'):raise HTTPException(409,'仅待人工判断、失败或中断任务可更换模式')
        try:
            def previous_revision():
                for item in store.list():
                    parent=root/'jobs'/item['id']/'recognition-parent.json'
                    if item.get('recognition_mode')==mode and parent.exists() and json.loads(parent.read_text()).get('job_id')==jid:return item
            with store.lock:
                prior=previous_revision()
                if prior:return prior
            plan=await asyncio.to_thread(batches._target_plan,old)
            with store.lock:
                if store.get(jid)['updated']!=old['updated']:raise ValueError('任务已改变，请刷新后重试')
                prior=previous_revision()
                if prior:return prior
                new=store.change_recognition_mode(jid,mode)
                if plan:atomic_json(root/'jobs'/new['id']/'automatic-overwrite.json',plan)
                return new
        except (ValueError,KeyError) as e:raise HTTPException(409,str(e))
    @app.post('/api/jobs/{jid}/content')
    async def save_content(jid:str,request:Request):
        get_job(jid);data=await request.json()
        try:return await asyncio.to_thread(content.save_clean,jid,data.get('text'),data.get('version'))
        except ValueError as e:raise HTTPException(409,str(e))
    @app.post('/api/jobs/{jid}/cards')
    def generate_cards(jid:str):
        get_job(jid)
        try:return content.enqueue(jid)
        except ValueError as e:raise HTTPException(409,str(e))
    @app.post('/api/jobs/{jid}/cards/edit')
    async def edit_cards(jid:str,request:Request):
        get_job(jid);data=await request.json()
        try:return await asyncio.to_thread(content.save_card,jid,data.get('content'),data.get('version'))
        except ValueError as e:raise HTTPException(409,str(e))
    @app.get('/api/jobs/{jid}/cards/{generation}/{page}.png')
    def download_card(jid:str,generation:str,page:int):
        job=get_job(jid)
        if len(generation)!=32 or any(c not in '0123456789abcdef' for c in generation) or not 1<=page<=100:raise HTTPException(404,'卡片不存在')
        path=root/'jobs'/job['id']/'cards'/generation/(str(page)+'.png')
        if not path.is_file():raise HTTPException(404,'卡片不存在')
        return FileResponse(path,filename=Path(job['name']).stem+'-知识卡片-'+str(page)+'.png',media_type='image/png')
    @app.post('/api/jobs/{jid}/retry')
    def retry(jid:str):
        get_job(jid)
        try:return store.retry(jid)
        except ValueError as e:raise HTTPException(409,str(e))
    @app.get('/api/jobs/{jid}/download/{kind}')
    def download(jid:str,kind:str):
        job=get_job(jid);mapping={'original':'transcript.txt','clean':'clean.txt','srt':'transcript.srt','json':'result.json'}
        if kind not in mapping:raise HTTPException(404,'导出类型不存在')
        if kind=='clean':
            with store.lock:
                result_path=root/'jobs'/job['id']/'result.json'
                if result_path.exists():
                    return Response(json.loads(result_path.read_text())['clean'],media_type='text/plain; charset=utf-8',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(Path(job['name']).stem+'-clean.txt')})
        p=root/'jobs'/job['id']/mapping[kind]
        if not p.exists():raise HTTPException(404,'结果尚未生成')
        return FileResponse(p,filename=Path(job['name']).stem+('-'+mapping[kind]),media_type='application/octet-stream')
    def public_config():
        c=snapshot();return {'auto_publish':c['auto_publish'],'duplicate_policy':c['duplicate_policy'],'has_token':bool(c['token']),'kind':c['kind'],'target':c['target'],'validated':c['resolved'] is not None,'credential_storage':'macOS登录钥匙串，服务重启后自动读取','credential_error':credential_error}
    @app.get('/api/settings')
    def settings():return public_config()
    @app.post('/api/settings')
    async def save_settings(request:Request):
        nonlocal credential_error
        data=await request.json()
        if data.get('kind','page') not in ('page','database','data_source'):raise HTTPException(400,'目标类型无效')
        if data.get('duplicate_policy','skip') not in ('skip','overwrite','new'):raise HTTPException(400,'无效重复处理方式')
        if 'auto_publish' in data and not isinstance(data['auto_publish'],bool):raise HTTPException(400,'自动写入设置无效')
        with config_lock:
            try:
                if data.get('clear_token'):vault.delete();config['token']=''
                elif data.get('token'):
                    value=str(data['token']).strip();vault.save(value)
                    if vault.load()!=value:raise CredentialError('钥匙串回读校验失败，密钥未持久保存，请检查钥匙串权限后重试')
                    config['token']=value
            except CredentialError as e:raise HTTPException(503,str(e))
            credential_error=''
            config['kind']=data.get('kind',config['kind']);config['target']=str(data.get('target',config['target'])).strip();config['resolved']=None
            config['auto_publish']=data.get('auto_publish',config['auto_publish']);config['duplicate_policy']=data.get('duplicate_policy',config['duplicate_policy'])
            atomic_json(settings_path,{k:config[k] for k in ('kind','target','auto_publish','duplicate_policy')})
        return public_config()
    @app.post('/api/settings/test')
    def test_settings():
        c=snapshot();client=None
        try:
            client=make_notion(c['token']);resolved=client.resolve(c['kind'],c['target'])
            with config_lock:
                if config['token']!=c['token'] or config['target']!=c['target'] or config['kind']!=c['kind']:raise ValueError('设置已改变，请重新测试')
                config['resolved']=resolved
            pending=root/'pending-refresh.json';count=0
            if pending.exists():
                for jid in json.loads(pending.read_text()):
                    try:store.begin_refresh(jid);count+=1
                    except (ValueError,KeyError):pass
                pending.unlink()
            return {'ok':True,'target':resolved,'refresh_queued':count}
        except (ValueError,NotionError) as e:raise HTTPException(400,str(e))
        finally:
            if client:client.close()
    @app.post('/api/jobs/{jid}/publish/check')
    def check_publish(jid:str):
        job=get_job(jid);c=snapshot()
        if not c['resolved']:
            if not c['token']:raise HTTPException(400,'先在设置中保存并测试 Notion 连接')
            probe=make_notion(c['token'])
            try:resolved=probe.resolve(c['kind'],c['target'])
            except (NotionError,ValueError) as e:raise HTTPException(400,str(e))
            finally:probe.close()
            with config_lock:
                if config['token']!=c['token'] or config['target']!=c['target'] or config['kind']!=c['kind']:raise HTTPException(409,'设置已改变，请重新检测')
                config['resolved']=resolved
            c=snapshot()
        if job['status'] not in ('ready','published','publish_failed','refresh_failed'):raise HTTPException(409,'任务当前无法写入，或上次写入结果需要先核对')
        client=make_notion(c['token'])
        try:
            duplicates=find_duplicates(client,c['resolved'],job,root/'jobs'/job['id'])
            check={'check_id':uuid.uuid4().hex,'target':c['resolved'],'duplicates':duplicates,'created':time.time()}
            atomic_json(root/'jobs'/job['id']/'duplicate-check.json',check)
            return check
        except (NotionError,ValueError) as e:raise HTTPException(400,str(e))
        finally:client.close()
    @app.post('/api/jobs/{jid}/publish')
    async def publish(jid:str,request:Request):
        data=await request.json()
        return commit_publish(jid,data)
    def commit_publish(jid,data,batch_id=None):
        job=get_job(jid);c=snapshot()
        path=root/'jobs'/job['id']/'duplicate-check.json'
        if not path.exists():raise HTTPException(409,'请先检测Notion已有记录')
        check=json.loads(path.read_text())
        if data.get('check_id')!=check['check_id'] or time.time()-check['created']>600:raise HTTPException(409,'检测已过期，请重新检测')
        if c['resolved']!=check['target']:raise HTTPException(409,'Notion目标已改变，请重新检测')
        action=data.get('action')
        if action=='skip':return {'skipped':True,'detail':'未写入Notion'}
        if action not in ('create','new','overwrite'):raise HTTPException(409,'请选择覆盖、不写入或新增')
        if action=='create' and check['duplicates']:raise HTTPException(409,'已发现重复记录，请明确选择处理方式')
        chosen=next((p for p in check['duplicates'] if same_id(p['id'],data.get('page_id'))),None)
        if action=='overwrite' and not chosen:raise HTTPException(409,'只能覆盖本次检测到的所选记录')
        plan={'operation':action,'target':check['target'],'page_id':chosen['id'] if chosen else None,'last_edited_time':chosen.get('last_edited_time','') if chosen else ''}
        if batch_id:plan['batch_id']=batch_id
        try:return store.begin_write(jid,plan)
        except ValueError as e:raise HTTPException(409,str(e))
    @app.post('/api/jobs/{jid}/refresh-notion')
    def refresh_notion(jid:str):
        get_job(jid)
        if not snapshot()['token']:raise HTTPException(400,'请先在设置中填写 Notion 密钥')
        try:return store.begin_refresh(jid)
        except ValueError as e:raise HTTPException(409,str(e))
    def batch_check(jid):
        try:return check_publish(jid)
        except HTTPException as e:raise ValueError(str(e.detail))
    def batch_publish(jid,data,bid):
        try:return commit_publish(jid,data,bid)
        except HTTPException as e:raise ValueError(str(e.detail))
    batches.check_publish=batch_check;batches.publish=batch_publish
    @app.post('/api/batch/prepare')
    async def prepare_batch(request:Request):
        data=await request.json()
        if not isinstance(data,dict):raise HTTPException(400,'批量参数无效')
        try:return await asyncio.to_thread(batches.prepare,data.get('action'),data.get('ids'))
        except ValueError as e:raise HTTPException(409,str(e))
    @app.post('/api/batch/{bid}/commit')
    async def commit_batch(bid:str,request:Request):
        data=await request.json()
        if not isinstance(data,dict):raise HTTPException(400,'批量参数无效')
        try:return await asyncio.to_thread(batches.commit,bid,data.get('choices'))
        except ValueError as e:raise HTTPException(409,str(e))
    @app.get('/api/trash')
    def trash():return batches.trash_list()
    @app.post('/api/trash/{jid}/restore')
    def restore_task(jid:str):
        try:return batches.restore(jid)
        except KeyError:raise HTTPException(404,'回收站任务不存在')
    app.mount('/static',StaticFiles(directory=STATIC),name='static')
    return app
