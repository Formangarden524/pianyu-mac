'use strict';
class QueueSelection {
 constructor(){this.ids=new Set()}
 toggle(id,on){on?this.ids.add(id):this.ids.delete(id)}
 all(ids){this.ids=new Set(ids)}
 unpublished(jobs){this.all(jobs.filter(j=>!j.page_id&&!j.page_url&&['ready','publish_failed'].includes(j.status)).map(j=>j.id))}
 clear(){this.ids.clear()}
 prune(ids){const available=new Set(ids);for(const id of this.ids)if(!available.has(id))this.ids.delete(id)}
 snapshot(){return [...this.ids]}
}
function publishableSelection(records,ids){const selected=new Set(ids);return records.filter(j=>selected.has(j.id)&&['ready','published','publish_failed','refresh_failed'].includes(j.status)).map(j=>j.id)}
function quickPublishChoices(items){return Object.fromEntries(items.filter(i=>!i.error).map(i=>[i.id,{action:i.check.duplicates.length?'skip':'create'}]))}
function recognitionSelection(records,ids){const selected=new Set(ids);return records.filter(j=>selected.has(j.id)&&['needs_manual','failed','interrupted'].includes(j.status)).map(j=>j.id)}
if(typeof module!=='undefined')module.exports={QueueSelection,quickPublishChoices,publishableSelection,recognitionSelection};
const queueSelection=new QueueSelection();let queueEnabled=false,queueBusy=false,queueBatch=null,lastQueueRender='';
function updateBatchDock(text){
 const dock=document.querySelector('#queue-batch-dock');dock.hidden=false;document.querySelector('#queue-batch-dock-message').textContent=text;
}
function renderQueueSelection(){
 const q=s=>document.querySelector(s),count=queueSelection.ids.size,publishCount=publishableSelection(jobs,queueSelection.snapshot()).length;
 const modeCount=recognitionSelection(jobs,queueSelection.snapshot()).length;
 q('#queue-recognition-apply').disabled=!queueEnabled||queueBusy||!modeCount||!q('#queue-recognition-mode').value;
 q('#queue-recognition-apply').textContent='按此模式继续所选任务'+(modeCount?'（'+modeCount+'）':'');
 q('#queue-recognition-mode').disabled=queueBusy;
 q('#queue-selection-count').textContent='已选 '+count+' 项';
 q('#queue-publish').textContent=publishCount?'写入 Notion（'+publishCount+'）':count?'等待处理完成':'写入 Notion';q('#queue-publish').classList.toggle('primary',publishCount>0);q('#queue-publish').classList.toggle('quiet',!publishCount);q('#queue-publish').title='只有已完成转录整理的任务才能写入；等待处理的任务不计入';
 for(const id of ['queue-publish','queue-reprocess','queue-trash'])q('#'+id).disabled=!queueEnabled||queueBusy||!count;
 q('#queue-publish').disabled=!queueEnabled||queueBusy||!publishCount;
 q('#queue-all').disabled=!visibleQueueJobs().length;q('#queue-unpublished').disabled=!visibleQueueJobs().some(j=>!j.page_id&&!j.page_url&&['ready','publish_failed'].includes(j.status));q('#queue-clear').disabled=!count;q('#queue-trash-view').disabled=!queueEnabled;
 document.querySelectorAll('.queue-check').forEach(e=>{e.checked=queueSelection.ids.has(e.value);e.disabled=false});
}
function queueRow(job,button){
 const row=node('div','queue-item'),check=node('input','queue-check');check.type='checkbox';check.value=job.id;check.checked=queueSelection.ids.has(job.id);check.disabled=false;check.setAttribute('aria-label','选择任务：'+job.name);check.onchange=()=>{queueSelection.toggle(job.id,check.checked);renderQueueSelection()};row.append(check,button);return row;
}
function clearDeletedPreview(ids){
 if(ids.includes(selected)){
  selected=null;preview.select(null);current=null;document.querySelector('#result-view').hidden=true;document.querySelector('#empty-preview').hidden=false;document.querySelector('#preview-title').textContent='结果预览';document.querySelector('#preview-status').textContent='等待选择';
 }
}
if(typeof document!=='undefined'){
 const q=s=>document.querySelector(s),dialog=q('#queue-batch-dialog');
 const names={publish:'批量写入 Notion',reprocess:'批量重新处理',trash:'移入本地回收站'};
 q('#queue-all').onclick=()=>{queueSelection.all(visibleQueueJobs().map(j=>j.id));renderQueueSelection()};q('#queue-unpublished').onclick=()=>{queueSelection.unpublished(visibleQueueJobs());renderQueueSelection()};q('#queue-clear').onclick=()=>{queueSelection.clear();renderQueueSelection()};
 function setQueueBusy(on){queueBusy=on;renderQueueSelection();q('#queue-batch-close').disabled=false;q('#queue-batch-submit').disabled=on;q('#queue-batch-quick').disabled=on}
 function choicesValid(){return queueBatch?.action!=='publish'||queueBatch.items.every(item=>item.error||queueBatch.choices[item.id]?.action)}
 function renderReview(){
  const batch=queueBatch;if(!batch)return;q('#queue-batch-items').replaceChildren();
  const eligible=batch.items.filter(i=>!i.error).length;
  q('#queue-batch-message').textContent='已核验 '+batch.items.length+' 项，可提交 '+eligible+' 项。'+(batch.action==='trash'?'只隐藏本地任务，视频和处理结果保留，可在回收站恢复；不会删除原始文件夹视频或 Notion 页面。':batch.action==='reprocess'?'从原视频重新转录，旧结果保留。已关联 Notion 的任务完成后自动覆盖原页面正文（包括手写正文），保留数据库属性；无关联页面只生成本地结果。':'可一键写入：未重复的新增，重复的跳过。需要覆盖或另外新增时，可逐项选择后提交；覆盖会替换正文（包括手写正文），保留数据库属性。');
  for(const item of batch.items){
   const row=node('div','batch-row');row.append(node('strong','',item.name));
   if(item.error)row.append(node('p','batch-error','不可操作：'+item.error));
   else if(batch.action==='publish'){
    const duplicates=item.check.duplicates,select=node('select','');select.setAttribute('aria-label','写入方式：'+item.name);
    const options=duplicates.length?[['','请选择处理方式'],['overwrite','覆盖已有记录'],['skip','跳过，不写入'],['new','另外新增一条']]:[['create','新增写入'],['skip','跳过，不写入']];
    for(const [value,label] of options){const option=node('option','',label);option.value=value;select.append(option)}
    const choice=batch.choices[item.id]||(batch.choices[item.id]={action:duplicates.length?'':'create'});select.value=choice.action;row.append(node('p','',duplicates.length?'发现 '+duplicates.length+' 条匹配记录':'未发现重复记录'),select);
    const target=node('select','');target.setAttribute('aria-label','覆盖目标：'+item.name);
    for(const record of duplicates){const option=node('option','',(record.title||'未命名')+' · '+record.reason);option.value=record.id;target.append(option)}
    if(duplicates.length){choice.page_id=duplicates[0].id;target.onchange=()=>choice.page_id=target.value;row.append(target)}
    target.hidden=choice.action!=='overwrite';select.onchange=()=>{choice.action=select.value;target.hidden=choice.action!=='overwrite';q('#queue-batch-submit').disabled=!choicesValid()};
   }else row.append(node('p','',batch.action==='trash'?'将移入本地回收站':item.plan?'重处理完成后自动覆盖关联 Notion 页面：'+item.plan.page_id:'重新生成本地结果，未关联 Notion'));
   q('#queue-batch-items').append(row);
  }
  q('#queue-batch-quick').hidden=batch.action!=='publish'||!eligible;
  q('#queue-batch-submit').hidden=!eligible;q('#queue-batch-submit').textContent='确认提交 '+eligible+' 项';q('#queue-batch-submit').disabled=!choicesValid();
 }
 async function prepare(action){
  const chosen=queueSelection.snapshot();const ids=action==='publish'?publishableSelection(jobs,chosen):chosen;if(!ids.length||queueBusy||!queueEnabled)return;
  if(action==='publish'&&ids.length<chosen.length)toast('仅核验 '+ids.length+' 个可写入任务，其余尚未完成或状态待核对，已排除');
  if(queueBatch&&!queueBatch.done){
   const same=queueBatch.action===action&&JSON.stringify(queueBatch.items.map(i=>i.id).sort())===JSON.stringify(ids.slice().sort());
   if(queueBatch.submitted||(same&&queueBatch.items.some(i=>!i.error))){dialog.showModal();toast('当前批次尚未确认，请先确认或放弃该批次');return;}
   queueBatch=null;
  }
  if(ids.length>200){toast('每批最多选择200个任务，请减少勾选');return}
  if(!contentLeave(()=>prepare(action)))return;
  renderResult();
  queueBatch=null;setQueueBusy(true);q('#queue-batch-title').textContent=names[action];q('#queue-batch-message').textContent='正在核验 '+ids.length+' 项，请稍候…';q('#queue-batch-items').replaceChildren();q('#queue-batch-submit').hidden=true;q('#queue-batch-quick').hidden=true;q('#queue-batch-discard').hidden=true;q('#queue-batch-close').textContent='收起到后台';updateBatchDock('正在核验 '+ids.length+' 项，可继续浏览和编辑…');
  try{queueBatch=await api('/api/batch/prepare',{method:'POST',body:JSON.stringify({action,ids})});queueBatch.choices={};renderReview();q('#queue-batch-discard').hidden=false;updateBatchDock('核验完成，'+queueBatch.items.length+' 项等待确认');if(!dialog.open)toast('批次核验完成，点击右下角“查看批次”确认写入')}
  catch(e){q('#queue-batch-message').textContent=e.message;updateBatchDock('批次核验失败，点击查看原因')}
  finally{setQueueBusy(false);q('#queue-batch-submit').disabled=!queueBatch||!choicesValid()}
 }
 async function trashSelected(){
  const ids=queueSelection.snapshot();if(!ids.length||queueBusy||!queueEnabled)return;
  if(!contentLeave(trashSelected))return;
  setQueueBusy(true);
  try{
   const batch=await api('/api/batch/prepare',{method:'POST',body:JSON.stringify({action:'trash',ids})});
   const result=await api('/api/batch/'+batch.id+'/commit',{method:'POST',body:JSON.stringify({choices:{}})});
   const removed=result.items.filter(i=>i.ok).map(i=>i.id),failed=result.items.filter(i=>!i.ok);
   clearDeletedPreview(removed);for(const id of removed)queueSelection.toggle(id,false);
   await refresh();toast('已移入回收站 '+removed.length+' 项，可恢复。'+(failed.length?'失败 '+failed.length+' 项：'+failed.map(i=>i.error).join('；'):''));
  }catch(e){toast(e.message)}finally{setQueueBusy(false)}
 }
 for(const action of ['publish','reprocess'])q('#queue-'+action).onclick=()=>prepare(action);
 q('#queue-trash').onclick=trashSelected;
 q('#queue-recognition-mode').onchange=renderQueueSelection;
 async function applyRecognitionMode(){
  const ids=recognitionSelection(jobs,queueSelection.snapshot()),mode=q('#queue-recognition-mode').value;
  if(queueBusy||!queueEnabled||!ids.length||!['audio','visual','demo'].includes(mode))return;
  if(ids.length>200){toast('每批最多200项，请减少选择');return}
  if(!contentLeave(applyRecognitionMode))return;
  setQueueBusy(true);let succeeded=0;const failures=[];
  const note=q('#queue-recognition-note');
  try{
   for(let i=0;i<ids.length;i++){
    note.textContent='正在提交 '+(i+1)+' / '+ids.length+'，可继续浏览其他任务…';
    try{await api('/api/jobs/'+ids[i]+'/recognition-mode',{method:'POST',body:JSON.stringify({mode})});succeeded++;queueSelection.toggle(ids[i],false)}
    catch(e){failures.push((jobs.find(j=>j.id===ids[i])?.name||ids[i])+'：'+e.message)}
   }
   note.textContent='已提交 '+succeeded+' 项，失败 '+failures.length+' 项。任务在后台依次识别。'+failures.join('；');
   await refresh();toast('识别模式批量提交完成：成功 '+succeeded+'，失败 '+failures.length);
  }finally{setQueueBusy(false)}
 }
 q('#queue-recognition-apply').onclick=applyRecognitionMode;

 q('#queue-batch-close').onclick=()=>{dialog.close();if(!queueBusy&&(!queueBatch||queueBatch.done)){queueBatch=null;q('#queue-batch-dock').hidden=true}};
 q('#queue-batch-resume').onclick=()=>{if(!dialog.open)dialog.showModal()};
 q('#queue-batch-discard').onclick=()=>{if(queueBusy||queueBatch?.submitted)return;queueBatch=null;dialog.close();q('#queue-batch-dock').hidden=true;toast('已放弃本次核验，未提交任何操作')};
 dialog.addEventListener('cancel',()=>{if(!queueBusy&&(!queueBatch||queueBatch.done)){queueBatch=null;q('#queue-batch-dock').hidden=true}});
 async function submitBatch(){
  const batch=queueBatch;if(!batch||batch.done||queueBusy||!choicesValid())return;batch.submitted=true;q('#queue-batch-discard').hidden=true;updateBatchDock('批次提交中，可继续浏览其他任务…');q('#queue-batch-quick').hidden=true;setQueueBusy(true);q('#queue-batch-message').textContent='正在提交所选项，请勿重复点击…';q('#queue-batch-items').querySelectorAll('select').forEach(e=>e.disabled=true);
  try{
   const result=await api('/api/batch/'+batch.id+'/commit',{method:'POST',body:JSON.stringify({choices:batch.choices})});
   const successful=result.items.filter(i=>i.ok&&!i.skipped),skipped=result.items.filter(i=>i.skipped),failed=result.items.filter(i=>!i.ok);
   q('#queue-batch-message').textContent='提交完成：成功 '+successful.length+' 项，跳过 '+skipped.length+' 项，失败 '+failed.length+' 项。'+(batch.action==='reprocess'?'成功项已进入串行处理队列，可关闭窗口查看。':batch.action==='publish'?'成功项已进入 Notion 写入队列，实际写入状态见左侧任务。':'');
   q('#queue-batch-items').replaceChildren();for(const item of result.items){const row=node('div','batch-row');row.append(node('strong','',item.name),node('p',item.ok?'':'batch-error',item.error||(item.skipped?'已跳过':batch.action==='trash'?'已移入本地回收站':'已提交任务'+(item.job_id?' · '+item.job_id.slice(0,8):''))));q('#queue-batch-items').append(row)}
   if(batch.action==='trash')clearDeletedPreview(successful.map(i=>i.id));for(const item of result.items)if(item.ok)queueSelection.toggle(item.id,false);
   batch.done=true;updateBatchDock('提交完成：成功 '+successful.length+'，跳过 '+skipped.length+'，失败 '+failed.length);q('#queue-batch-close').textContent='关闭';q('#queue-batch-submit').hidden=true;await refresh();
  }catch(e){q('#queue-batch-message').textContent=e.message+'。可再次点击确认，原批次不会重复入队。'}
  finally{setQueueBusy(false);if(!batch.done)q('#queue-batch-items').querySelectorAll('select').forEach(e=>e.disabled=true)}
 }
 q('#queue-batch-submit').onclick=submitBatch;
 q('#queue-batch-quick').onclick=async()=>{if(!queueBatch||queueBatch.action!=='publish'||queueBusy||queueBatch.submitted)return;queueBatch.choices=quickPublishChoices(queueBatch.items);await submitBatch()};
 q('#queue-trash-view').onclick=async()=>{
  if(!queueEnabled)return;
  q('#trash-items').replaceChildren();q('#trash-message').textContent='正在读取回收站…';q('#trash-dialog').showModal();
  try{const records=await api('/api/trash');q('#trash-message').textContent=records.length?'共 '+records.length+' 项。视频和本地结果均保留，恢复不会重新处理或写入 Notion。':'回收站为空';
   for(const job of records){const row=node('div','batch-row');row.append(node('strong','',job.name));const button=node('button','quiet','恢复任务');button.onclick=async()=>{button.disabled=true;try{await api('/api/trash/'+job.id+'/restore',{method:'POST'});button.textContent='已恢复';await refresh()}catch(e){toast(e.message);button.disabled=false}};row.append(button);q('#trash-items').append(row)}
  }catch(e){q('#trash-message').textContent=e.message}
 };
 q('#trash-close').onclick=()=>q('#trash-dialog').close();
}
