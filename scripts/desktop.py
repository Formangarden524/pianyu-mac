"""Release launcher: manages this folder's web process, never shared Ollama."""
import fcntl,json,os,subprocess,sys,time
from pathlib import Path
import httpx,psutil
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'outputs'/'desktop'
URL='http://127.0.0.1:8765'
def request(path):
    r=httpx.get(URL+path,timeout=5,trust_env=False);r.raise_for_status();return r.json()
def event(action,**data):
    with (DATA/'events.jsonl').open('a') as f:f.write(json.dumps({'time':time.time(),'action':action,**data},ensure_ascii=False)+'\n')
def process():
    record=DATA/'process.json'
    if not record.exists():return None
    data=json.loads(record.read_text())
    try:
        p=psutil.Process(data['pid'])
        if abs(p.create_time()-data['created'])>.01:return None
        args=p.cmdline()
        if 'video_agent.app:create_app' not in args or Path(p.cwd()).resolve()!=ROOT:raise RuntimeError('进程身份不匹配，拒绝操作')
        return p if p.is_running() and p.status()!=psutil.STATUS_ZOMBIE else None
    except psutil.NoSuchProcess:return None

def status():
    p=process();data={'running':bool(p),'pid':p.pid if p else None}
    if p:
        data.update(rss_mb=round(p.memory_info().rss/1024**2),uptime_seconds=round(time.time()-p.create_time()))
        try:data['progress']=request('/api/progress')
        except Exception:data['health']='unavailable'
    event('status',**data);print(json.dumps(data,ensure_ascii=False,indent=2));return data

def start():
    p=process()
    if p:
        request('/api/health');print('工作台已启动');subprocess.run(['open',URL],check=False);return
    import socket
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',8765))
        except OSError:raise RuntimeError('8765端口已被占用，未接管其他工作台；请先停止另一份实例')
    r=httpx.get('http://127.0.0.1:11434/api/tags',trust_env=False,timeout=5);r.raise_for_status()
    if not any(m['name'].split(':')[0]=='pianyu-instruct' for m in r.json().get('models',[])):raise RuntimeError('请先下载模型，未找到 pianyu-instruct')
    model=ROOT/'runtimes/whisper-small-mlx'
    if not (model/'config.json').exists() or not any((model/n).exists() for n in ['weights.npz','weights.safetensors']):raise RuntimeError('请先下载完整 Whisper 模型')
    with (DATA/'web.log').open('ab') as log:
        child=subprocess.Popen([str(ROOT/'.venv-video/bin/python'),'-m','uvicorn','video_agent.app:create_app','--factory','--host','127.0.0.1','--port','8765','--no-access-log'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    record={'pid':child.pid,'created':psutil.Process(child.pid).create_time()}
    (DATA/'process.json').write_text(json.dumps(record));event('start',**record)
    for _ in range(60):
        if child.poll() is not None:raise RuntimeError('启动失败，请查看 outputs/desktop/web.log')
        try:request('/api/health');subprocess.run(['open',URL],check=False);print('工作台已打开');return
        except httpx.HTTPError:time.sleep(.25)
    raise RuntimeError('服务仍未就绪，请查看状态与日志；进程记录已保留')

def stop():
    p=process()
    if not p:print('此目录的工作台未运行');return
    progress=request('/api/progress');health=request('/api/health')
    if any(progress.get(k,0) for k in ['queued','processing','writing']) or health.get('active_card_tasks'):raise RuntimeError('任务正在执行或排队，请等待队列结束后停止')
    p.terminate()
    try:p.wait(timeout=20)
    except psutil.TimeoutExpired:raise RuntimeError('进程仍在安全退出，未强制终止；稍后查看状态')
    (DATA/'process.json').unlink(missing_ok=True);event('stop');print('工作台已停止；共享 Ollama 保持运行')

if __name__=='__main__':
    DATA.mkdir(parents=True,exist_ok=True)
    with (DATA/'control.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            action=sys.argv[1] if len(sys.argv)>1 else 'status'
            if action not in ('start','stop','status'):raise ValueError('无效命令')
            {'start':start,'stop':stop,'status':status}[action]()
        except Exception as e:event('error',message=str(e));print('操作未完成：'+str(e));sys.exit(1)
