'use strict';
let queueProgressLoading=false,queuePendingRecovering=false;
async function loadQueueProgress(){
 if(queueProgressLoading)return;queueProgressLoading=true;
 const q=s=>document.querySelector(s);
 try{
  const p=await api('/api/progress');
  const fields={total:'任务记录',needs_manual:'待选择模式',completed:'文案已完成',queued:'排队中',processing:'转录／整理',writing:'写入中',published:'已写入 Notion',ready:'待写入确认',failed:'失败／中断',needs_review:'写入待核对'};
  p.completed=p.ready+p.published;
  const counts=q('#queue-progress-counts');
  for(const [key,label] of Object.entries(fields)){
   const filter=key==='total'?'all':key;let box=counts.querySelector('[data-filter="'+filter+'"]');
   if(!box){box=node('button','progress-stat');box.dataset.filter=filter;box.title='点击筛选处理队列：'+label;box.append(node('strong',''),node('span','',label));box.onclick=()=>setQueueFilter(filter,true);counts.append(box)}
   box.querySelector('strong').textContent=String(p[key]||0);box.setAttribute('aria-pressed',String(queueFilter===filter));box.disabled=false;
  }
  q('#queue-progress-bar').max=p.total||1;q('#queue-progress-bar').value=p.settled;
  q('#queue-progress-caption').textContent='已结束 '+p.settled+' / '+p.total+' 条任务（含失败与待核对）；已生成文案 '+p.text_ready+' 条。任务记录含历史版本。';
  q('#queue-progress-active').replaceChildren();
  if(p.active.length){for(const job of p.active)q('#queue-progress-active').append(node('p','',job.name+' · '+(labels[job.status]||job.status)+' · '+job.detail))}
  else q('#queue-progress-active').append(node('p','',p.queued?'队列等待工作线程领取任务…':'当前没有正在执行的任务'));
  q('#pending-staging-note').textContent=p.pending?'另有 '+p.pending+' 个视频仅暂存、尚未提交（新视频 '+p.pending_new+'，与现有任务重复 '+p.pending_matches+'），不会自动进入处理队列。':'没有未提交的暂存视频。';
  q('#recover-folder').hidden=!p.pending;q('#recover-folder').textContent='恢复待提交清单（'+p.pending+'）';q('#recover-folder').disabled=queuePendingRecovering||!!busy||!!stagedFolder.length;
  q('#queue-progress-update').textContent='每2.5秒自动更新';
 }catch{q('#queue-progress-update').textContent='进度更新失败，请刷新重试；已有数字可能过期'}
 finally{queueProgressLoading=false}
}
if(typeof document!=='undefined')document.querySelector('#recover-folder').onclick=async()=>{
 if(queuePendingRecovering||busy)return;
 if(stagedFolder.length){toast('当前已有待提交清单，请先提交或取消，再恢复其他暂存');return}
 queuePendingRecovering=true;document.querySelector('#recover-folder').disabled=true;
 try{
  const pending=await api('/api/folder/pending');
  if(busy||stagedFolder.length){toast('当前清单已发生变化，请先处理当前清单');return}
  stagedFolder=pending.map(item=>({...item,action:item.matches.length?'skip':'new',old_id:item.matches[0]?.id}));
  batch={name:'恢复的暂存视频',total:pending.length,scanned:pending.length,other:0,staged:pending.length,skipped:0,ids:[],errors:[],note:'仅恢复清单，尚未提交；已匹配任务默认跳过'};
  folderRows();document.querySelector('#folder-manifest-panel').open=true;
  toast('已恢复 '+pending.length+' 项；新视频默认新增，已有任务默认跳过。核对后点击“确认提交所选项”。');
 }catch(e){toast(e.message)}finally{queuePendingRecovering=false;loadQueueProgress()}
};
