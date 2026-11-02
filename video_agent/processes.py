"""Own child lifetimes so a restart cannot overlap an old ASR worker."""
import subprocess,threading

class ProcessRunner:
    def __init__(self):self.lock=threading.RLock();self.children=set();self.stopped=False
    def active_count(self):
        with self.lock:return len(self.children)
    def run(self,args,timeout,**kwargs):
        with self.lock:
            if self.stopped:raise RuntimeError('服务正在停止，已保留完成阶段')
            p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs);self.children.add(p)
        try:
            out,err=p.communicate(timeout=timeout)
            if self.stopped:raise RuntimeError('服务已停止，已保留完成阶段')
            return subprocess.CompletedProcess(args,p.returncode,out,err)
        except subprocess.TimeoutExpired:
            p.kill();p.communicate();raise RuntimeError('本地处理超时，已保留完成阶段') from None
        finally:
            if p.poll() is None:p.kill();p.wait()
            with self.lock:self.children.discard(p)
    def stop(self):
        with self.lock:
            self.stopped=True;children=list(self.children)
            for p in children:
                if p.poll() is None:p.terminate()
        for p in children:
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:p.kill();p.wait()
