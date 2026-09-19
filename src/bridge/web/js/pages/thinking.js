async function loadThinking(){
const r=await api('/workers');
const workers=(r.workers||[])
.filter(w=>w.enabled!==false)
.sort((a,b)=>String(a.id||'').localeCompare(String(b.id||'')));
return `
<div class="monitor-grid">
${workers.map((w,i)=>{
const host=(w.host||w.id||'?').replace(/^[^@]+@/,'');
return `<div class="monitor-window" id="monitor-${i}">
<div class="monitor-header"><span class="monitor-host">${esc(host)}</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="${esc(w.id||'')}"></span></div>
<div class="monitor-log" id="log-${i}"></div>
</div>`;
}).join('')}
</div>`;
}
let thinkingPoll=null;
function initThinking(){
if(thinkingPoll)clearTimeout(thinkingPoll);
if(window._timerTick)clearInterval(window._timerTick);
const slotData={};
const seenEventIds={};
const slotCount=document.querySelectorAll('.monitor-window').length;
let historyLoaded=false;

async function pollLogs(){
try{
const r=await api('/tasks');
const activeByWorker={};
const activityRank={RUNNING:3,STARTING:2,QUEUED:1};
for(const task of(r.tasks||[])){
const tid=task.taskId;
let wid=task.workerId||(task.meta&&task.meta.workerId)||'';
let taskState=String(task.state||'').toUpperCase();
if(!activityRank[taskState])continue;
if(!wid){
try{
const st=await api(`/tasks/${tid}`);
wid=st.workerId||(st.meta&&st.meta.workerId)||'';
taskState=String(st.state||taskState).toUpperCase();
}catch(e){}
}
if(!wid||!activityRank[taskState])continue;
const current=activeByWorker[wid];
if(!current||activityRank[taskState]>activityRank[current.state])activeByWorker[wid]={tid,state:taskState};
}
for(let i=0;i<slotCount;i++){
const hdr=document.querySelector(`#monitor-${i} .monitor-header`);
const logEl=document.getElementById('log-'+i);
if(!hdr||!logEl)continue;
const hostEl=hdr.querySelector('.monitor-host');
const host=hostEl?hostEl.textContent:'?';
const wEl=hdr.querySelector('.monitor-tid');
const wid=wEl?wEl.getAttribute('data-worker'):'';
const info=activeByWorker[wid];
if(info){
const{tid,state}=info;
try{
const log=await api(`/tasks/${tid}/log`);
const events=log.events||[];
const tc=log.toolCount||0;
const rc=log.reasoningCount||0;
const ms=mapState(state);
const taskChanged=slotData[i]&&slotData[i].tid!==tid;
if(taskChanged)logEl.innerHTML='';
slotData[i]={host,state,ms,tid,rc,tc,startTime:log.startTime||0,elapsed:log.elapsed||0};
let elapsed=ms==='thinking'&&log.startTime>0?Math.floor((Date.now()-log.startTime)/1000):(log.elapsed||0);
hdr.innerHTML=`<span class="monitor-host">${esc(host)}</span> ${badge(state)} <span class="monitor-timer">⏱${fmtElapsed(elapsed)}</span> <span class="muted" style="font-size:10px">思考${rc} 工具${tc}</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="${esc(wid)}">${esc(tid)}</span>`;
const seen=seenEventIds[tid]||(seenEventIds[tid]=new Set());
const fresh=[];
for(const e of events){
const key=e.id||`${e.time||''}|${e.type||''}|${e.text||''}|${e.status||''}`;
if(seen.has(key))continue;
seen.add(key);
fresh.push(e);
}
while(seen.size>300)seen.delete(seen.values().next().value);
if(fresh.length){
let html='';
for(const e of fresh){
let icon='',cls='log-line log-fadein';
if(e.type==='reasoning'){icon='💭';cls+=' log-info';}
else if(e.type==='tool'){icon='🔧';cls+=' log-tool';}
else if(e.type==='step'){icon='▶️';cls+=' log-ok';}
let txt=(e.text||'').slice(0,150);
if((e.text||'').length>150)txt+=' …';
html+=`<div class="${cls}">${icon} ${esc(txt)}</div>`;
}
if(logEl.childElementCount===0)logEl.innerHTML=html;else logEl.insertAdjacentHTML('beforeend',html);
logEl.scrollTop=logEl.scrollHeight;
}
}catch(e){}
}else{
if(slotData[i]){
const lastTid=slotData[i].tid||'';
slotData[i].ms='done';
hdr.innerHTML=`<span class="monitor-host">${esc(host)}</span> <span class="muted" style="font-size:11px">空闲</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="${esc(wid)}">${esc(lastTid)}</span>`;
}else{
hdr.innerHTML=`<span class="monitor-host">${esc(host)}</span> <span class="muted" style="font-size:11px">空闲</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="${esc(wid)}"></span>`;
logEl.innerHTML='';
}
}
}
}catch(e){}
if(!historyLoaded){historyLoaded=true;}
}

async function loadHistory(){
try{
const r=await api('/tasks');
for(const task of(r.tasks||[])){
if(mapState(task.state||'')!=='done')continue;
try{
let wid=task.workerId||(task.meta&&task.meta.workerId)||'';
let taskState=task.state;
if(!wid){
const st=await api(`/tasks/${task.taskId}`);
wid=st.workerId||(st.meta&&st.meta.workerId)||'';
taskState=st.state||taskState;
}
if(!wid)continue;
for(let i=0;i<slotCount;i++){
const wEl=document.querySelector(`#monitor-${i} .monitor-tid`);
if(!wEl||wEl.getAttribute('data-worker')!==wid||slotData[i])continue;
const log=await api(`/tasks/${task.taskId}/log`);
const events=log.events||[];
if(!events.length)continue;
const tid=task.taskId;
const hostEl=document.querySelector(`#monitor-${i} .monitor-host`);
slotData[i]={host:hostEl?hostEl.textContent:'?',state:taskState,ms:'完成',tid,rc:log.reasoningCount||0,tc:log.toolCount||0,startTime:0,elapsed:log.elapsed||0};
seenEventIds[tid]=new Set(events.map(e=>e.id||`${e.time||''}|${e.type||''}|${e.text||''}|${e.status||''}`));
const hdr=document.querySelector(`#monitor-${i} .monitor-header`);
const logEl=document.getElementById('log-'+i);
if(hdr)hdr.innerHTML=`<span class="monitor-host">${esc(slotData[i].host)}</span> ${badge(taskState)} <span class="monitor-timer">⏱${fmtElapsed(log.elapsed||0)}</span> <span class="muted" style="font-size:10px">思考${slotData[i].rc} 工具${slotData[i].tc}</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="${esc(wid)}">${esc(tid)}</span>`;
if(logEl)logEl.innerHTML=events.map(e=>{
let icon='',cls='log-line';
if(e.type==='reasoning'){icon='💭';cls+=' log-info';}
else if(e.type==='tool'){icon='🔧';cls+=' log-tool';}
else if(e.type==='step'){icon='▶️';cls+=' log-ok';}
let txt=(e.text||'').slice(0,150);
if((e.text||'').length>150)txt+=' …';
return `<div class="${cls}">${icon} ${esc(txt)}</div>`;
}).join('');
break;
}
}catch(e){}
}
}catch(e){}
}

function tickTimers(){
for(let i=0;i<slotCount;i++){
const d=slotData[i];
if(!d||d.ms!=='thinking'||!d.startTime)continue;
const hdr=document.querySelector(`#monitor-${i} .monitor-header`);
if(!hdr)continue;
const elapsed=Math.floor((Date.now()-d.startTime)/1000);
const curWidEl=hdr.querySelector('.monitor-tid');
const curWid=curWidEl?curWidEl.getAttribute('data-worker')||'':'';
hdr.innerHTML=`<span class="monitor-host">${esc(d.host)}</span> ${badge(d.state)} <span class="monitor-timer">⏱${fmtElapsed(elapsed)}</span> <span class="muted" style="font-size:10px">思考${d.rc} 工具${d.tc}</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="${esc(curWid)}">${esc(d.tid)}</span>`;
}
}
function schedulePoll(){pollLogs().finally(()=>{thinkingPoll=setTimeout(schedulePoll,2000)})}
loadHistory();
schedulePoll();
window._timerTick=setInterval(tickTimers,1000);
}
function clearThinkingLog(){document.querySelectorAll('.monitor-log').forEach(log=>{log.innerHTML=''})}
