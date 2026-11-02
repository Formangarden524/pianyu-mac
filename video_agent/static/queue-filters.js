'use strict';
const QUEUE_FILTERS={all:{label:'全部'},needs_manual:{label:'待选择模式',statuses:['needs_manual']},queued:{label:'排队中',statuses:['queued','publish_queued','refresh_queued']},processing:{label:'转录／整理',statuses:['recognizing','extracting','transcribing','organizing']},writing:{label:'写入中',statuses:['publishing','refreshing']},completed:{label:'文案已完成',statuses:['ready','published']},ready:{label:'待写入确认',statuses:['ready']},published:{label:'已写入 Notion',statuses:['published']},failed:{label:'失败／中断',statuses:['failed','interrupted','publish_failed','refresh_failed']},needs_review:{label:'写入待核对',statuses:['publish_uncertain','refresh_uncertain']}};
function filterQueue(records,key){const states=QUEUE_FILTERS[key]?.statuses;return states?records.filter(j=>states.includes(j.status)):records.slice()}
if(typeof module!=='undefined')module.exports={filterQueue,QUEUE_FILTERS};
let queueFilter='all';
function visibleQueueJobs(){return filterQueue(jobs,queueFilter)}
function setQueueFilter(key,scroll=false){
 if(!QUEUE_FILTERS[key])return;
 if(queueFilter!==key){queueFilter=key;queueSelection.clear()}
 if(key==='ready')queueSelection.unpublished(visibleQueueJobs());
 const panel=document.querySelector('.queue');panel.open=true;renderJobs();
 document.querySelectorAll('.progress-stat[data-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.filter===queueFilter)));
 if(scroll)panel.scrollIntoView({behavior:'smooth',block:'start'});
}
function renderQueueFilters(){
 const el=document.querySelector('#queue-filters');
 for(const [key,{label}] of Object.entries(QUEUE_FILTERS)){
  let button=el.querySelector('[data-filter="'+key+'"]');
  if(!button){button=node('button','queue-filter');button.dataset.filter=key;button.onclick=()=>setQueueFilter(key);el.append(button)}
  button.textContent=label+' '+filterQueue(jobs,key).length;button.setAttribute('aria-pressed',String(queueFilter===key));button.disabled=false;
 }
 const visible=visibleQueueJobs();
 document.querySelector('#queue-filter-summary').textContent=QUEUE_FILTERS[queueFilter].label+' · 显示 '+visible.length+' / '+jobs.length+' 条'+(selected&&!visible.some(j=>j.id===selected)?'；当前预览不在此分类，点击列表任务查看。':'；点击任务查看右侧文案。');
}
