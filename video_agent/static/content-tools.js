class DraftState {
  constructor(){this.value=null;}
  begin(id,kind,version,text){return this.value={id,kind,version,original:text,text};}
  change(text){if(this.value)this.value.text=text;}
  dirty(){return !!this.value&&this.value.text!==this.value.original;}
  acceptSave(ticket,text){return this.value===ticket&&this.value.text===text;}
  cancel(){this.value=null;}
}
if(typeof module!=='undefined')module.exports={DraftState};
const contentDraft=new DraftState();let contentSaving=false,leaveAction=null;
function rememberDraft(){try{if(contentDraft.value)localStorage.setItem('video-agent-draft',JSON.stringify(contentDraft.value));else localStorage.removeItem('video-agent-draft')}catch{}}
function contentLeave(action){
 if(contentSaving){toast('正在保存，请稍候');return false}
 if(!contentDraft.value)return true;
 if(!contentDraft.dirty()){contentDraft.cancel();rememberDraft();return true}
 leaveAction=action;document.querySelector('#draft-dialog').showModal();return false;
}
function contentRender(){
 const q=s=>document.querySelector(s),result=current?.result,cards=current?.cards||{};
 if(!result){q('#content-toolbar').hidden=true;q('#content-editor').hidden=true;q('#card-gallery').hidden=true;return}
 q('#content-toolbar').hidden=false;
 if(!contentDraft.value){try{const saved=JSON.parse(localStorage.getItem('video-agent-draft'));if(saved&&saved.id===selected&&['clean','cards'].includes(saved.kind)&&typeof saved.text==='string'){
   contentDraft.value=saved;tab=saved.kind;document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));toast('已恢复未保存草稿，请保存或取消');
 }}catch{}}
 const editing=!!contentDraft.value;
 q('#copy-content').disabled=contentSaving;
 q('#edit-content').hidden=editing||!['clean','cards'].includes(tab)||(tab==='cards'&&!cards.content);
 q('#edit-content').disabled=!['ready','published','publish_failed','refresh_failed'].includes(current.job.status)||['queued','running'].includes(cards.status)&&tab==='cards';
 q('#save-content').hidden=q('#cancel-content').hidden=!editing;q('#save-content').disabled=q('#cancel-content').disabled=contentSaving;
 q('#generate-cards').hidden=editing;q('#generate-cards').disabled=['queued','running'].includes(cards.status)||!['ready','published','publish_failed','refresh_failed'].includes(current.job.status);
 q('#generate-cards').textContent=cards.status==='queued'?'卡片已排队…':cards.status==='running'?'Qwen 生成中…':cards.content?'重新生成卡片':'生成知识卡片';
 q('#publish').disabled=editing||contentSaving;
 q('#content-editor').hidden=!editing;q('#result-text').hidden=editing||tab==='cards';q('#card-gallery').hidden=editing||tab!=='cards';
 q('#content-note').textContent=editing?'修改仅保存到本地；已写入的 Notion 页面需要另行选择覆盖。':cards.error||(cards.stale?'整理文案已修改，当前卡片基于旧文案，请重新生成。':tab==='cards'?'本地 Qwen 提炼 · 高清 PNG · 请核对后使用':'');
 if(editing){q('#content-editor').querySelectorAll('textarea').forEach(e=>e.disabled=contentSaving);return;}
 if(tab==='cards'){
  const el=q('#card-gallery');el.replaceChildren();
  if(!cards.generation){el.append(node('p','small',['queued','running'].includes(cards.status)?'正在等待本地模型生成，完成后会自动显示。':'点击“生成知识卡片”，将整理文案制作成可下载的图片。'));return}
  for(let i=1;i<=cards.pages;i++){
   const figure=node('figure','knowledge-card');const url='/api/jobs/'+current.job.id+'/cards/'+cards.generation+'/'+i+'.png';const img=node('img','');img.src=url;img.alt=(cards.content.title||'知识卡片')+' · 第'+i+'张';img.loading='lazy';figure.append(img);const link=node('a','quiet','下载 PNG · 第 '+i+' / '+cards.pages+' 张');link.href=url;link.download='知识卡片-'+i+'.png';figure.append(link);el.append(figure);
  }
 }
}
if(typeof document!=='undefined'){
 const q=s=>document.querySelector(s);
 q('#copy-content').onclick=async()=>{
  let text;if(contentDraft.value)text=contentDraft.value.kind==='cards'?cardPlain(JSON.parse(contentDraft.value.text)):contentDraft.value.text;
  else if(tab==='cards')text=current?.cards?.content?cardPlain(current.cards.content):'';
  else text=q('#result-text').textContent;
  if(!text){toast('当前没有可复制内容');return}
  try{await navigator.clipboard.writeText(text);toast('已复制到剪贴板')}catch{const area=document.createElement('textarea');area.value=text;document.body.append(area);area.select();const ok=document.execCommand('copy');area.remove();toast(ok?'已复制到剪贴板':'复制失败，请手动选择文字复制')}
 };
 q('#edit-content').onclick=()=>{
  if(!current?.result)return;
  const kind=tab==='cards'?'cards':'clean',text=kind==='cards'?JSON.stringify(current.cards.content):current.result.clean;
  contentDraft.begin(current.job.id,kind,kind==='cards'?current.cards.version:current.content_version,text);rememberDraft();buildEditor();contentRender();
 };
 function buildEditor(){
  const d=contentDraft.value;if(!d)return;const el=q('#content-editor');el.replaceChildren();
  if(d.kind==='clean'){const area=node('textarea','clean-editor');area.setAttribute('aria-label','编辑整理文案');area.value=d.text;area.oninput=()=>{contentDraft.change(area.value);rememberDraft()};el.append(area)}
  else{let data;try{data=JSON.parse(d.text)}catch{data={}};for(const [key,label] of Object.entries(cardFields)){const wrap=node('label','',label);const area=node('textarea','card-field');area.setAttribute('aria-label','编辑卡片'+label);area.value=data[key]||'';area.rows=key==='title'?2:3;area.oninput=()=>{data[key]=area.value;contentDraft.change(JSON.stringify(data));rememberDraft()};wrap.append(area);el.append(wrap)}}
 }
 const renderBase=contentRender;contentRender=function(){const d=contentDraft.value;renderBase();if(!d&&contentDraft.value)buildEditor()};
 q('#cancel-content').onclick=()=>{contentDraft.cancel();rememberDraft();renderResult()};
 q('#save-content').onclick=async()=>{
  const ticket=contentDraft.value;if(!ticket||contentSaving)return;const text=ticket.text;contentSaving=true;contentRender();
  try{
   const payload=ticket.kind==='cards'?{content:JSON.parse(text),version:ticket.version}:{text,version:ticket.version};
   await api('/api/jobs/'+ticket.id+(ticket.kind==='cards'?'/cards/edit':'/content'),{method:'POST',body:JSON.stringify(payload)});
   if(contentDraft.acceptSave(ticket,text)){contentDraft.cancel();rememberDraft()}
   toast('已保存到本地，旧版本已保留');await loadSelected();
  }catch(e){toast(e.message)}finally{contentSaving=false;renderResult()}
 };
 q('#generate-cards').onclick=async()=>{
  const id=current?.job.id;if(!id||id!==selected||contentDraft.value)return;
  q('#generate-cards').disabled=true;
  try{await api('/api/jobs/'+id+'/cards',{method:'POST'});if(id===selected){tab='cards';document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));await loadSelected()}toast('已加入本地 Qwen 队列，生成完成后可下载图片')}catch(e){toast(e.message)}finally{if(id===selected)contentRender()}
 };
 q('#draft-keep').onclick=()=>{q('#draft-dialog').close();leaveAction=null};
 q('#draft-discard').onclick=()=>{contentDraft.cancel();rememberDraft();q('#draft-dialog').close();const action=leaveAction;leaveAction=null;action?.()};
 q('#draft-dialog').addEventListener('cancel',()=>{leaveAction=null});
}
const cardFields={title:'标题',core:'核心观点',blind_spots:'认知盲区',misconceptions:'常见误区',boundaries:'适用边界',actions:'行动建议'};
function cardPlain(data){return Object.entries(cardFields).map(([k,label])=>label+'\n'+data[k]).join('\n\n')}
