'use strict';
const $=id=>document.getElementById(id);let renderedSignature="";let offset=0,total=0,current=null,editing=false,loading=false,sequence=0,detailSequence=0;const limit=24;
async function api(path,options={}){const r=await fetch(path,{...options,headers:{'X-Video-Agent':'1','Content-Type':'application/json',...options.headers}});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请求失败');return d}
function node(tag,text){const e=document.createElement(tag);e.textContent=text;return e}
function options(id,values,label){const old=$(id).value;$(id).replaceChildren();const base=node('option',label);base.value='';$(id).append(base);for(const v of values){const o=node('option',v);o.value=v;$(id).append(o)}$(id).value=values.includes(old)?old:''}
async function load(){const seq=++sequence;try{const params=new URLSearchParams({q:$('search').value,sort:$('sort').value,tag:$('tag').value,author:$('author-filter').value,favorite:$('favorites').checked,offset,limit});const d=await api('/api/library?'+params);if(seq!==sequence)return;const signature=JSON.stringify(d);if(signature===renderedSignature)return;renderedSignature=signature;total=d.total;if(offset&&offset>=total){offset=Math.max(0,Math.floor((total-1)/limit)*limit);return load()}options('tag',d.tags,'全部主题');options('author-filter',d.authors,'全部作者');$('count').textContent='共 '+total+' 条内容';$('cards').replaceChildren();for(const item of d.items){const c=node('button','');c.className='card';c.append(node('span',[item.primary,item.secondary].filter(Boolean).join(' · ')||'未分类'),node('h2',item.name),node('p',item.excerpt),node('footer',new Date(item.created*1000).toLocaleDateString('zh-CN')+' · '+item.sync+(item.metadata.favorite?' · 已收藏':'')));c.setAttribute('aria-pressed',String(current?.item.id===item.id));c.dataset.contentId=item.id;c.onclick=()=>open(item);$('cards').append(c)}if(!d.items.length)$('cards').append(node('p','这里还没有匹配的内容。添加视频，或换一个关键词试试。'));$('prev').disabled=!offset;$('next').disabled=offset+limit>=total;$('page').textContent=total?(offset/limit+1)+' / '+Math.ceil(total/limit):''}catch(e){$('notice').textContent='内容库暂时无法读取：'+e.message}}
function dirty(){return editing&&$('draft').value!==current?.data.result.clean}
async function open(item){if(dirty()){$('leave').hidden=false;return}const seq=++detailSequence;try{const data=await api('/api/jobs/'+item.job_id);if(seq!==detailSequence)return;current={item,data};editing=false;$('editor').hidden=true;$('text').hidden=false;$('leave').hidden=true;$('title').textContent=item.name;$('meta').textContent=[item.primary,item.secondary].filter(Boolean).join(' · ');$('sync').textContent=item.sync;$('text').textContent=data.result.clean;$('detail-note').textContent='';$('favorite').textContent=item.metadata.favorite?'取消收藏':'收藏';$('author').value=item.metadata.author||'';$('source').value=item.metadata.source_url||'';$('published').value=item.metadata.published_date||'';$('download').href='/api/jobs/'+item.job_id+'/download/clean';$('video').src='/api/jobs/'+item.job_id+'/video';$('notion').hidden=!/^https:\/\/(?:(?:www|app)\.)?notion\.(?:so|site|com)\//i.test(item.page_url||'');if(!$('notion').hidden)$('notion').href=item.page_url;$('edit').disabled=!['ready','published','publish_failed','refresh_failed'].includes(data.job.status);$('history').replaceChildren(...item.history.map(h=>node('p',new Date(h.created*1000).toLocaleString('zh-CN')+' · '+h.status+' · '+h.id.slice(0,8))));$('reader-empty').hidden=true;document.querySelectorAll('.card').forEach(c=>c.setAttribute('aria-pressed',String(c.dataset.contentId===item.id)));if(!$('detail').open)$('detail').show()}catch(e){$('notice').textContent=e.message}}
function close(){if(dirty()){$('leave').hidden=false;return}$('video').pause();$('detail').close();$('reader-empty').hidden=false;document.querySelectorAll('.card').forEach(c=>c.setAttribute('aria-pressed','false'));++detailSequence}
$('close').onclick=close;$('detail').addEventListener('cancel',e=>{if(dirty()){e.preventDefault();$('leave').hidden=false}else $('video').pause()});$('edit').onclick=()=>{editing=true;$('draft').value=current.data.result.clean;$('editor').hidden=false;$('text').hidden=true};$('cancel-edit').onclick=()=>{editing=false;$('editor').hidden=true;$('text').hidden=false;$('leave').hidden=true};$('save').onclick=async()=>{if(!current)return;$('save').disabled=true;try{const d=await api('/api/jobs/'+current.item.job_id+'/content',{method:'POST',body:JSON.stringify({text:$('draft').value,version:current.data.content_version})});editing=false;const data=await api('/api/jobs/'+current.item.job_id);current.data=data;$('text').textContent=data.result.clean;$('editor').hidden=true;$('text').hidden=false;$('leave').hidden=true;$('detail-note').textContent='已保存本地文案；Notion更新请在高级工作台执行。';await load()}catch(e){$('detail-note').textContent=e.message+'；草稿已保留。'}finally{$('save').disabled=false}};
async function metadata(fields){const item=current.item;const d=await api('/api/library/'+item.id+'/metadata',{method:'POST',body:JSON.stringify({fields,version:item.metadata.version})});item.metadata=d;$('favorite').textContent=d.favorite?'取消收藏':'收藏';await load()}
$('favorite').onclick=async()=>{try{await metadata({favorite:!current.item.metadata.favorite})}catch(e){$('detail-note').textContent=e.message}};$('save-meta').onclick=async()=>{try{await metadata({author:$('author').value,source_url:$('source').value,published_date:$('published').value});$('detail-note').textContent='来源信息已保存'}catch(e){$('detail-note').textContent=e.message}};$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(editing?$('draft').value:current.data.result.clean);$('detail-note').textContent='已复制'}catch{$('detail-note').textContent='复制失败，可选中文字后复制'}};
let timer;for(const id of ['search','sort','tag','author-filter','favorites'])$(id).addEventListener(id==='search'?'input':'change',()=>{clearTimeout(timer);timer=setTimeout(()=>{offset=0;load()},200)});$('prev').onclick=()=>{offset=Math.max(0,offset-limit);load()};$('next').onclick=()=>{offset+=limit;load()};
async function upload(files){
 if(loading)return;
 loading=true;
 $('add').disabled=$('folder').disabled=true;
 let added=0;
 const duplicates=[],errors=[];
 const videos=files.filter(f=>/\.(mp4|mov|mkv|webm)$/i.test(f.name));
 const details=$('upload-details');
 details.hidden=true;
 details.open=false;
 $('upload-list').replaceChildren();
 try{
  for(const [i,file] of videos.entries()){
   $('upload-note').textContent='检查并添加视频 '+(i+1)+' / '+videos.length;
   try{
    if(!file.size||file.size>2*1024**3)throw Error('文件为空或超过2GiB');
    const author=(file.webkitRelativePath||'').split('/').slice(-2,-1)[0]||'';
    const job=await api('/api/upload',{method:'POST',body:file,headers:{
     'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name),
     'X-Recognition-Mode':'auto','X-Author':encodeURIComponent(author)
    }});
    if(job.duplicate)duplicates.push(file.name+'（已添加）');
    else added++;
   }catch(e){errors.push(file.name+'（'+e.message+'）')}
  }
  $('upload-note').textContent=videos.length
   ? '新增 '+added+' 条 · 已添加，跳过 '+duplicates.length+' 条 · 未能导入 '+errors.length+' 条'
   : '未找到支持的视频。';
  for(const entry of [...duplicates,...errors])$('upload-list').append(node('li',entry));
  details.hidden=!duplicates.length&&!errors.length;
  await progress();
 }finally{
  loading=false;
  $('add').disabled=$('folder').disabled=false;
  $('files').value=$('folders').value='';
 }
}
$('add').onclick=()=>$('files').click();$('folder').onclick=()=>$('folders').click();$('files').onchange=e=>upload([...e.target.files]);$('folders').onchange=e=>upload([...e.target.files]);
async function progress(){try{const p=await api('/api/progress');$('notice').textContent=(p.queued+p.processing+p.writing?'后台正在处理 '+(p.queued+p.processing+p.writing)+' 条。':'当前没有正在处理的内容。')+((p.failed+p.needs_review+p.needs_manual)?' '+(p.failed+p.needs_review+p.needs_manual)+' 条任务记录需关注，请在任务中心查看。':'')}catch{$('notice').textContent='后台连接暂时中断，已有阅读和编辑不会清空。'}}
load();progress();setInterval(()=>{if(!document.hidden){load();progress()}},10000);

let deletionPlan=null,deleting=false;
$('delete-content').onclick=async()=>{if(dirty()){$('leave').hidden=false;return}try{deletionPlan=await api('/api/jobs/'+current.item.job_id+'/delete/check',{method:'POST'});$('delete-scope').textContent='将回收 '+deletionPlan.pages.length+' 个关联Notion页面、'+deletionPlan.jobs.length+' 个本地任务副本、'+deletionPlan.external.length+' 个外部原视频。保留指纹，防止再次录入。'+(!deletionPlan.external.length?' 管理目录中未匹配到外部原视频，本次不会处理其他目录。':'');$('delete-paths').textContent=deletionPlan.external.join('\n');$('delete-status').textContent='本地副本保留在可恢复回收站，外部文件移入macOS废纸篓。';$('delete-confirm').disabled=false;$('delete-dialog').showModal()}catch(e){$('detail-note').textContent=e.message}};
$('delete-cancel').onclick=()=>{if(!deleting)$('delete-dialog').close()};
$('delete-confirm').onclick=async()=>{if(!deletionPlan||deleting)return;deleting=true;$('delete-confirm').disabled=true;try{await api('/api/deletions/'+deletionPlan.id+'/commit',{method:'POST'});$('delete-dialog').close();editing=false;close();current=null;renderedSignature='';await load();$('notice').textContent='已完成联动回收，保留删除指纹。可在各自回收站查看。'}catch(e){$('delete-status').textContent=e.message+'。可点击执行删除重试同一批次。'}finally{deleting=false;$('delete-confirm').disabled=false}};
