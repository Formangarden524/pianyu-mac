let jobs=[],selected=null,current=null,tab='clean',settings={};
const preview=new PreviewState();
function selectJob(id){if(!contentLeave(()=>{selectJob(id);renderJobs();loadSelected()}))return;selected=id;preview.select(id);current=null;$('#result-view').hidden=true;$('#empty-preview').hidden=false;$('#preview-title').textContent='正在读取任务…';$('#preview-status').textContent='加载中';}
const $=s=>document.querySelector(s);
const labels={queued:'等待处理',recognizing:'识别视频',needs_manual:'待选择识别模式',extracting:'提取音频',transcribing:'语音转录',organizing:'整理文案',ready:'预览就绪',failed:'处理失败',interrupted:'已中断',publish_queued:'等待写入',publishing:'写入中',published:'已存 Notion',publish_failed:'写入失败',publish_uncertain:'写入待核对',refresh_queued:'等待更新',refreshing:'更新原页面',refresh_failed:'更新失败',refresh_uncertain:'更新待核对'};
async function api(path,options={}){const r=await fetch(path,{...options,headers:{'X-Video-Agent':'1',...(options.body instanceof File?{}:{'Content-Type':'application/json'}),...options.headers}});let d;try{d=await r.json()}catch{throw Error('服务返回异常，请检查启动终端')}if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请求失败');return d;}
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$('#toast').hidden=true,6500)}
function node(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function renderJobs(){const visible=visibleQueueJobs();queueSelection.prune(visible.map(j=>j.id));renderQueueFilters();renderQueueSelection();const signature=JSON.stringify([jobs,selected,queueFilter]);if(signature===lastQueueRender)return;lastQueueRender=signature;const el=$('#jobs');el.replaceChildren();$('#count').textContent=visible.length===jobs.length?jobs.length:visible.length+' / '+jobs.length;if(!visible.length){const empty=node('div','empty');empty.append(node('b','',jobs.length?'此分类暂无任务':'还没有视频'),node('p','',jobs.length?'切换其他分类或点击“全部”查看。':'先添加一个短视频，开始第一次转录。'));el.append(empty);return}for(const j of visible){const button=node('button','job'+(selected===j.id?' selected':''));button.append(node('span','job-icon','▶'));const body=node('div','job-body');body.append(node('div','job-name',j.name));const bottom=node('div','job-bottom');bottom.append(node('span','status '+j.status,labels[j.status]||j.status),node('span','job-detail',j.detail));body.append(bottom);button.append(body);button.onclick=()=>{selectJob(j.id);renderJobs();loadSelected()};el.append(queueRow(j,button))}}
function renderResult(){if(!current)return;const {job,result}=current;$('#preview-title').textContent=job.name;$('#preview-status').textContent=labels[job.status]||job.status;$('#preview-status').className='status '+job.status;$('#empty-preview').hidden=true;$('#result-view').hidden=false;$('#task-message').textContent=job.error||(!result?job.detail:'');$('#result-text').textContent=result?(tab==='summary'?'认知盲区与认知误区摘要\n\n'+result.summary+'\n\n关键词：盲区、边界与误区\n\n'+result.keywords:tab==='cards'?'':result[tab]):'处理完成后，文字会出现在这里。';$('#publish').hidden=!['ready','publish_failed','published','refresh_failed'].includes(job.status);$('#retry').hidden=!['failed','interrupted'].includes(job.status);$('#refresh-notion').hidden=true;$('#download-txt').hidden=!result;$('#download-srt').hidden=!result;$('#download-txt').href='/api/jobs/'+job.id+'/download/'+(tab==='original'?'original':'clean');$('#download-srt').href='/api/jobs/'+job.id+'/download/srt';$('#notion-link').hidden=true;if(job.page_url&&/^https:\/\/(www\.)?notion\.(so|site)\//.test(job.page_url)){$('#notion-link').href=job.page_url;$('#notion-link').hidden=false}$('#publish-note').textContent=['publish_uncertain','refresh_uncertain'].includes(job.status)?'写入结果不确定，已阻止重复提交。请先在 Notion 核对页面；本地结果始终可导出。':'写入前请核对识别结果。原视频与文字将上传到Notion。整理稿、认知摘要和关键词放入代码块。';contentRender();renderRecognition();}
async function loadSelected(){const id=selected;if(!id)return;const request=preview.request(id);try{const data=await api('/api/jobs/'+id);if(!preview.accept(id,data,request))return;if(JSON.stringify(current)!==JSON.stringify(data)){current=data;renderResult()}}catch(e){if(id===selected)toast(e.message)}}
async function refresh(){try{jobs=await api('/api/jobs');if(selected&&!jobs.some(j=>j.id===selected)&&!contentDraft.value)clearDeletedPreview([selected]);renderJobs();folderStatus();loadQueueProgress();await loadSelected()}catch(e){toast('连接本地服务失败：'+e.message)}}
async function upload(files){const recognitionMode=$('#recognition-mode').value;$('#choose').disabled=true;try{let n=0;for(const file of files){if(file.size>2*1024**3){toast(file.name+' 超过2GiB，已跳过');continue}$('#choose').textContent='添加 '+(++n)+'/'+files.length+'…';const j=await api('/api/upload',{method:'POST',body:file,headers:{'X-Recognition-Mode':recognitionMode,'X-Filename':encodeURIComponent(file.name),'Content-Type':'application/octet-stream'}});selectJob(j.id);await refresh()}toast('已加入队列；相同内容的视频会自动去重')}catch(e){toast(e.message)}finally{$('#choose').disabled=false;$('#choose').textContent='＋ 添加视频';$('#files').value=''}}
$('#choose').onclick=()=>$('#files').click();$('#files').onchange=e=>upload([...e.target.files]);const drop=$('#drop');for(const name of ['dragover','dragenter'])drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('drag')});for(const name of ['dragleave','drop'])drop.addEventListener(name,e=>{e.preventDefault();drop.classList.remove('drag')});drop.addEventListener('drop',e=>upload([...e.dataTransfer.files]));
for(const button of document.querySelectorAll('.tab')){const activate=()=>{tab=button.dataset.tab;document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b===button));renderResult()};button.onclick=()=>{if(contentLeave(activate))activate()}};
$('#refresh').onclick=refresh;$('#home').onclick=refresh;
$('#refresh-notion').onclick=async()=>{const id=preview.current?.job.id;if(!id||id!==selected)return;try{await api('/api/jobs/'+id+'/refresh-notion',{method:'POST'});toast('已加入更新队列，会沿用原Notion页面');refresh()}catch(e){toast(e.message);if(e.message.includes('设置'))openSettings()}};
$('#retry').onclick=async()=>{try{await api('/api/jobs/'+selected+'/retry',{method:'POST'});toast('已加入继续处理队列');refresh()}catch(e){toast(e.message)}};
let duplicateState=null;
function updateDuplicateLink(){if(!duplicateState)return;const record=duplicateState.duplicates.find(x=>x.id===$('#duplicate-record').value);$('#duplicate-link').hidden=true;if(record&&/^https:\/\/(www\.)?(notion\.so|notion\.site|app\.notion\.com)\//.test(record.url)){$('#duplicate-link').href=record.url;$('#duplicate-link').hidden=false;}}
async function sendWrite(state,action){return api('/api/jobs/'+state.jobId+'/publish',{method:'POST',body:JSON.stringify({check_id:state.check_id,action,page_id:$('#duplicate-record').value})});}
$('#publish').onclick=async()=>{const id=preview.publishId();if(!id){toast('请等待当前任务预览加载完成');return;}const name=current.job.name;$('#publish').disabled=true;try{const d=await api('/api/jobs/'+id+'/publish/check',{method:'POST'});const state={...d,jobId:id};if(d.duplicates.length){duplicateState=state;$('#duplicate-description').textContent='视频「'+name+'」匹配到 '+d.duplicates.length+' 条已有记录。请选择本次处理方式。';$('#duplicate-record').replaceChildren();for(const r of d.duplicates){const o=node('option','',r.title+' · '+r.reason);o.value=r.id;$('#duplicate-record').append(o);}updateDuplicateLink();$('#duplicate-dialog').showModal();}else{await sendWrite(state,'create');toast('未发现重复，已加入写入队列');refresh();}}catch(e){toast(e.message);if(e.message.includes('设置'))openSettings()}finally{$('#publish').disabled=false}};
$('#duplicate-record').onchange=updateDuplicateLink;$('#duplicate-close').onclick=()=>{$('#duplicate-dialog').close();duplicateState=null;};
for(const [id,action] of [['duplicate-skip','skip'],['duplicate-new','new'],['duplicate-overwrite','overwrite']]){$('#'+id).onclick=async()=>{const state=duplicateState;if(!state)return;const buttons=[...document.querySelectorAll('#duplicate-dialog button')];buttons.forEach(b=>b.disabled=true);try{await sendWrite(state,action);$('#duplicate-dialog').close();duplicateState=null;toast(action==='skip'?'本次未写入Notion':action==='overwrite'?'已确认覆盖所选记录，任务已排队':'已确认另外新增一条，任务已排队');refresh()}catch(e){toast(e.message)}finally{buttons.forEach(b=>b.disabled=false)}};}
async function openSettings(){try{settings=await api('/api/settings');$('#auto-publish').checked=settings.auto_publish!==false;$('#duplicate-policy').value=settings.duplicate_policy||'skip';$('#notion-kind').value=settings.kind;$('#notion-target').value=settings.target;$('#notion-token').value='';$('#token-state').textContent=settings.has_token?'当前已有密钥；留空保持不变。':'尚未设置密钥。';$('#settings-result').textContent=settings.credential_error||(settings.validated?'连接已验证。':'');$('#settings').showModal()}catch(e){toast(e.message)}}
$('#settings-open').onclick=openSettings;$('#settings-top').onclick=openSettings;$('#settings-close').onclick=()=>$('#settings').close();
$('#settings-form').onsubmit=async e=>{e.preventDefault();$('#save-settings').disabled=true;$('#settings-result').textContent='正在验证目标权限…';try{await api('/api/settings',{method:'POST',body:JSON.stringify({auto_publish:$('#auto-publish').checked,duplicate_policy:$('#duplicate-policy').value,token:$('#notion-token').value,kind:$('#notion-kind').value,target:$('#notion-target').value})});$('#notion-token').value='';$('#token-state').textContent='密钥已安全保存在macOS钥匙串，重启后自动读取。';const d=await api('/api/settings/test',{method:'POST'});$('#settings-result').textContent='✓ 连接成功。'+(d.refresh_queued?'已开始更新 '+d.refresh_queued+' 个原有页面。':'预览后可以写入 Notion。');toast('Notion 连接成功')}catch(e){$('#settings-result').textContent=e.message}finally{$('#save-settings').disabled=false}};
$('#clear-token').onclick=async()=>{try{await api('/api/settings',{method:'POST',body:JSON.stringify({clear_token:true,kind:$('#notion-kind').value,target:$('#notion-target').value})});$('#notion-token').value='';$('#token-state').textContent='密钥已清除。';$('#settings-result').textContent=''}catch(e){toast(e.message)}};
async function health(){try{const h=await api('/api/health');folderEnabled=h.folder_import_enabled===true;queueEnabled=h.queue_batch_enabled===true;renderQueueSelection();folderRows();$('#health').textContent=(h.asr_ready?'● Whisper 本地模型已就绪':'○ Whisper 模型未安装，请查看使用指南')+'　·　Qwen：'+h.model+'　·　任务与结果保存在本机'}catch(e){$('#health').textContent='本地服务未连接'}}
let stagedFolder=[],folderEnabled=false,busy='',generation=0,batch=null;
const safeHistory=new Set(['ready','published','failed','interrupted','publish_failed','refresh_failed']);
const canOverwrite=i=>i.matches.length && i.matches.every(j=>safeHistory.has((jobs.find(x=>x.id===j.id)||j).status));
function folderStatus(){
 const status=$('#folder-status');
 if(!folderEnabled){status.textContent='文件夹导入升级尚未就绪，请在服务升级后刷新页面。';return}
 if(!batch){status.textContent='选择文件夹以扫描视频';return}
 const counts={queued:0,processing:0,success:0,failure:0};
 for(const id of batch.ids){const s=jobs.find(j=>j.id===id)?.status||'queued';
 const k=['ready','published'].includes(s)?'success':s.endsWith('queued')?'queued':['recognizing','extracting','organizing','transcribing','publishing','refreshing'].includes(s)?'processing':'failure';counts[k]++}
 status.textContent=batch.name+' · '+(busy||batch.note)+' · 已扫描 '+batch.scanned+'/'+batch.total+' · 非视频 '+batch.other+' · 已暂存 '+batch.staged+' · 待提交 '+stagedFolder.length+' · 排队 '+counts.queued+' · 处理中 '+counts.processing+' · 成功 '+counts.success+' · 失败 '+(counts.failure+batch.errors.length+stagedFolder.filter(i=>i.error).length)+' · 跳过 '+batch.skipped;
}
$('#choose-folder').onclick=()=>{if(folderEnabled&&!busy&&!stagedFolder.length)$('#folder-files').click()};
function folderRows(){const el=$('#folder-manifest');el.replaceChildren();for(const item of stagedFolder){const row=node('div','');row.append(node('span','',item.name+' · '+({auto:'自动',audio:'口播优先',visual:'画面文字优先',demo:'软件演示'}[item.recognition_mode]||'自动')+' · '+(item.matches.length?item.matches.map(j=>(labels[j.status]||j.status)+(j.page_id?' · 已关联Notion':'')).join(' / '):'新视频')+' '));const select=node('select');for(const [value,label] of [['new','新增（按自动写入设置）'],['overwrite','覆盖（重处理并更新原Notion）'],['skip','跳过']]){const o=node('option','',label);o.value=value;if(value==='overwrite'&&!canOverwrite(item))o.disabled=true;select.append(o)}select.disabled=!!busy;select.value=item.action;select.onchange=()=>item.action=select.value;row.append(select);if(item.matches.length){const old=node('select');for(const j of item.matches){const o=node('option','',j.name+' · '+j.status+' · '+j.id.slice(0,8));o.value=j.id;old.append(o)}old.disabled=!!busy;old.value=item.old_id;old.onchange=()=>item.old_id=old.value;row.append(old)}if(item.error)row.append(node('span','',item.error));el.append(row)}
 for(const id of ['new','overwrite','skip','commit','cancel'])$('#folder-'+id).disabled=!folderEnabled||!!busy||!stagedFolder.length;
 $('#choose-folder').disabled=!folderEnabled||!!busy||!!stagedFolder.length;
 $('#folder-errors').replaceChildren(...(batch?.errors||[]).map(msg=>node('div','',msg)));
 $('#folder-errors-panel').hidden=!(batch?.errors?.length);$('#folder-errors-summary').textContent='错误明细（'+(batch?.errors?.length||0)+'）· 点击展开／收起';
 $('#folder-manifest-panel').hidden=!stagedFolder.length;$('#folder-manifest-summary').textContent='待提交文件清单（'+stagedFolder.length+'）· 点击展开后逐项设置';
 folderStatus()}
$('#folder-files').onchange=async e=>{
 if(!folderEnabled||busy||stagedFolder.length)return;
 const recognitionMode=$('#recognition-mode').value;const seq=++generation,files=[...e.target.files];busy='正在扫描';
 batch={name:files[0]?.webkitRelativePath.split('/')[0]||'文件夹',total:files.length,scanned:0,other:0,staged:0,skipped:0,ids:[],errors:[],note:'请核对清单'};
 folderRows();
 try{for(const file of files){if(seq!==generation)break;
 const name=file.webkitRelativePath||file.name;batch.scanned++;
 if(!/\.(mp4|mov|mkv|webm)$/i.test(name)){batch.other++;continue}
 try{if(!file.size||file.size>2*1024**3)throw Error('文件为空或超过2GiB');
 const i=await api('/api/folder/stage',{method:'POST',body:file,headers:{'X-Recognition-Mode':recognitionMode,'X-Filename':encodeURIComponent(name),'Content-Type':'application/octet-stream'}});
 i.action=i.matches.length?'skip':'new';i.old_id=i.matches[0]?.id;stagedFolder.push(i);batch.staged++;
 }catch(err){batch.errors.push(name+'：'+err.message)}folderRows()}
 }finally{busy='';e.target.value='';folderRows()}};
for(const action of ['new','overwrite','skip'])$('#folder-'+action).onclick=()=>{if(!folderEnabled||busy)return;for(const i of stagedFolder)i.action=action==='overwrite'&&!canOverwrite(i)?(i.matches.length?'skip':'new'):action;folderRows()};
async function finishFolder(cancel){
 if(!folderEnabled||busy||!stagedFolder.length)return;
 ++generation;
 const snapshot=stagedFolder.map(i=>({...i}));
 busy=cancel?'正在取消':'正在核验覆盖目标';folderRows();
 try{
 if(!cancel){
  for(const item of snapshot.filter(i=>i.action==='overwrite')){
   try{
    const prepared=await api('/api/folder/'+item.id+'/prepare',{method:'POST',body:JSON.stringify({old_id:item.old_id})});
    item.check_id=prepared.check_id;
   }catch(e){
    stagedFolder.find(i=>i.id===item.id).error=e.message;
    batch.note='预检失败，请核对清单';return;
   }
  }
 const dialog=$('#folder-dialog');
 const approved=await new Promise(resolve=>{
  dialog.returnValue='';
  dialog.onclose=()=>resolve(dialog.returnValue==='submit');
  dialog.showModal();
 });
 if(!approved)return;
  busy='正在提交';folderRows();
 }
 const remaining=[];for(const i of snapshot){try{
 if(cancel)await api('/api/folder/'+i.id,{method:'DELETE'});
 else{const r=await api('/api/folder/'+i.id+'/commit',{method:'POST',body:JSON.stringify({action:i.action,old_id:i.action==='overwrite'?i.old_id:null,check_id:i.check_id,confirmed:true})});if(r.skipped)batch.skipped++;else batch.ids.push(r.id)}
 }catch(e){i.error=e.message;remaining.push(i)}}
 stagedFolder=remaining;batch.note=remaining.length?'部分操作失败，请核对清单':cancel?'暂存已取消':batch.ids.length?'已提交':'已跳过，无任务排队';await refresh();
 }finally{busy='';folderRows()}}
$('#folder-cancel').onclick=()=>finishFolder(true);
$('#folder-commit').onclick=()=>finishFolder(false);
folderRows();refresh();health();setInterval(refresh,2500);

let recognitionContinuing=false,recognitionResolvedFor=null;
function renderRecognition(){
 if(recognitionResolvedFor!==current.job.id){recognitionResolvedFor=current.job.id;$('#recognition-manual-mode').value=''}
 $('#recognition-continue').disabled=recognitionContinuing||!['audio','visual','demo'].includes($('#recognition-manual-mode').value);
 const allowed=['needs_manual','failed','interrupted'].includes(current.job.status);
 $('#recognition-resolve').hidden=!allowed;
 const info=current.recognition||current.result?.recognition||{};
 const names={auto:'自动',audio:'口播优先',visual:'画面文字优先',demo:'软件演示',legacy_audio:'原语音流程'};$('#recognition-decision-note').hidden=!info.selected_mode;$('#recognition-decision-note').textContent=info.selected_mode?'识别方式：'+(names[info.selected_mode]||info.selected_mode)+' · '+(info.reason||''):'';
 $('#recognition-reason').textContent=info.reason||current.job.error||current.job.detail||'请选择适合视频内容的识别模式。';
 $('#recognition-continue').textContent=current.job.status==='needs_manual'?'按所选模式继续':'更换识别模式重试';
}
async function continueRecognition(){
 const id=selected;if(recognitionContinuing||!id||current?.job.id!==id||!['needs_manual','failed','interrupted'].includes(current.job.status))return;
 if(!contentLeave(continueRecognition))return;
 const mode=$('#recognition-manual-mode').value;if(!['audio','visual','demo'].includes(mode))return;
 recognitionContinuing=true;$('#recognition-continue').disabled=true;
 try{const data=await api('/api/jobs/'+id+'/recognition-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});if(selected===id)selectJob(data.job?.id||data.id);await refresh();toast('已创建新任务，原任务保留');}catch(e){toast(e.message)}finally{recognitionContinuing=false;$('#recognition-continue').disabled=!['audio','visual','demo'].includes($('#recognition-manual-mode').value)}
}
$('#recognition-continue').onclick=continueRecognition;
$('#recognition-manual-mode').onchange=()=>{$('#recognition-continue').disabled=recognitionContinuing||!['audio','visual','demo'].includes($('#recognition-manual-mode').value)};
