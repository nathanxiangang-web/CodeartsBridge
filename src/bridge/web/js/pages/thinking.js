function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function badge(s){
const m={RUNNING:'thinking',STARTING:'thinking',QUEUED:'queued',DONE:'done',FAILED:'failed',REVIEW_REQUIRED:'review',ASSISTANCE_REQUIRED:'review',CANCELLED:'done'};
const cls=m[s]||'idle';
const labels={RUNNING:'思考中',STARTING:'启动中',QUEUED:'排队',DONE:'完成',FAILED:'失败',REVIEW_REQUIRED:'待审查',ASSISTANCE_REQUIRED:'需协助',CANCELLED:'已取消'};
return '<span class="mbadge mbadge-'+cls+'">'+(labels[s]||s||'未知')+'</span>';
}
function fmtElapsed(s){s=Math.max(0,s|0);if(s<60)return s+'秒';var m=Math.floor(s/60);if(m<60)return m+'分'+(s%60)+'秒';return Math.floor(m/60)+'时'+(m%60)+'分';}
function mapState(s){s=String(s||'').toUpperCase();if(s==='RUNNING'||s==='STARTING')return 'thinking';if(s==='QUEUED')return 'queued';if(s==='DONE'||s==='CANCELLED'||s==='REVIEW_PASSED')return 'done';if(s==='FAILED'||s==='REVIEW_REQUIRED'||s==='ASSISTANCE_REQUIRED'||s==='FIX_REQUIRED')return 'failed';return 'done';}

var thinkingPoll=null;

async function renderThinking(){
var r=await API.get('workers');
var workers=((r&&r.workers)?r.workers:(Array.isArray(r)?r:[])).filter(function(w){return w.enabled!==false;}).sort(function(a,b){return String(a.id||'').localeCompare(String(b.id||''));});
var html='<div class="monitor-grid">';
workers.forEach(function(w,i){
var ep=w.endpoint||'';
var host=ep.replace(/^https?:\/\//,'').replace(/:\d+.*$/,'')||w.id||'?';
html+='<div class="monitor-window" id="monitor-'+i+'"><div class="monitor-header"><span class="monitor-host">'+esc(host)+'</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="'+esc(w.id||'')+'"></span></div><div class="monitor-log" id="log-'+i+'"></div></div>';
});
return html+'</div>';
}

async function mountThinking(){
if(thinkingPoll)clearTimeout(thinkingPoll);
if(window._timerTick)clearInterval(window._timerTick);
var slotData={};
var seenEventIds={};
var slotCount=document.querySelectorAll('.monitor-window').length;

async function pollLogs(){
try{
var r=await API.get('tasks');
var tasks=(r&&r.tasks)?r.tasks:(Array.isArray(r)?r:[]);
var activeByWorker={};
var activityRank={RUNNING:3,STARTING:2,QUEUED:1};
for(var ti=0;ti<tasks.length;ti++){
var task=tasks[ti];
var tid=task.taskId;
var wid=task.workerId||(task.meta&&task.meta.workerId)||'';
var taskState=String(task.state||'').toUpperCase();
if(!activityRank[taskState])continue;
if(!wid){try{var st=await API.get('tasks/'+tid);wid=st.workerId||(st.meta&&st.meta.workerId)||'';taskState=String(st.state||taskState).toUpperCase();}catch(e){}}
if(!wid||!activityRank[taskState])continue;
var current=activeByWorker[wid];
if(!current||activityRank[taskState]>activityRank[current.state])activeByWorker[wid]={tid:tid,state:taskState};
}
for(var i=0;i<slotCount;i++){
var hdr=document.querySelector('#monitor-'+i+' .monitor-header');
var logEl=document.getElementById('log-'+i);
if(!hdr||!logEl)continue;
var hostEl=hdr.querySelector('.monitor-host');
var host=hostEl?hostEl.textContent:'?';
var wEl=hdr.querySelector('.monitor-tid');
var wid=wEl?wEl.getAttribute('data-worker'):'';
var info=activeByWorker[wid];
if(info){
var tid=info.tid;var state=info.state;
try{
var log=await API.get('tasks/'+tid+'/log');
var events=log.events||[];
var tc=log.toolCount||0;
var rc=log.reasoningCount||0;
var ms=mapState(state);
var taskChanged=slotData[i]&&slotData[i].tid!==tid;
if(taskChanged)logEl.innerHTML='';
slotData[i]={host:host,state:state,ms:ms,tid:tid,rc:rc,tc:tc,startTime:log.startTime||0,elapsed:log.elapsed||0};
var elapsed=ms==='thinking'&&log.startTime>0?Math.floor((Date.now()-log.startTime)/1000):(log.elapsed||0);
hdr.innerHTML='<span class="monitor-host">'+esc(host)+'</span> '+badge(state)+' <span class="monitor-timer">⏱'+fmtElapsed(elapsed)+'</span> <span class="muted" style="font-size:10px">思考'+rc+' 工具'+tc+'</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="'+esc(wid)+'">'+esc(tid)+'</span>';
var seen=seenEventIds[tid]||(seenEventIds[tid]=new Set());
var fresh=[];
for(var ei=0;ei<events.length;ei++){
var e=events[ei];
var key=e.id||(e.time||'')+'|'+(e.type||'')+'|'+(e.text||'')+'|'+(e.status||'');
if(seen.has(key))continue;
seen.add(key);fresh.push(e);
}
while(seen.size>300)seen.delete(seen.values().next().value);
if(fresh.length){
var fhtml='';
for(var fi=0;fi<fresh.length;fi++){
var e=fresh[fi];
var icon='',cls='log-line log-fadein';
if(e.type==='reasoning'){icon='💭';cls+=' log-info';}
else if(e.type==='tool'||e.type==='tool_use'){icon='🔧';cls+=' log-tool';}
else if(e.type==='step'){icon='▶️';cls+=' log-ok';}
var txt=(e.text||e.part||'').slice(0,150);
if((e.text||e.part||'').length>150)txt+=' …';
fhtml+='<div class="'+cls+'">'+icon+' '+esc(txt)+'</div>';
}
if(logEl.childElementCount===0)logEl.innerHTML=fhtml;else logEl.insertAdjacentHTML('beforeend',fhtml);
logEl.scrollTop=logEl.scrollHeight;
}
}catch(e){}
}else{
if(slotData[i]){var lastTid=slotData[i].tid||'';slotData[i].ms='done';hdr.innerHTML='<span class="monitor-host">'+esc(host)+'</span> <span class="muted" style="font-size:11px">空闲</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="'+esc(wid)+'">'+esc(lastTid)+'</span>';}
else{hdr.innerHTML='<span class="monitor-host">'+esc(host)+'</span> <span class="muted" style="font-size:11px">空闲</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="'+esc(wid)+'"></span>';logEl.innerHTML='';}
}
}
}catch(e){}
}

function tickTimers(){
for(var i=0;i<slotCount;i++){
var d=slotData[i];
if(!d||d.ms!=='thinking'||!d.startTime)continue;
var hdr=document.querySelector('#monitor-'+i+' .monitor-header');
if(!hdr)continue;
var elapsed=Math.floor((Date.now()-d.startTime)/1000);
var curWidEl=hdr.querySelector('.monitor-tid');
var curWid=curWidEl?curWidEl.getAttribute('data-worker')||'':'';
hdr.innerHTML='<span class="monitor-host">'+esc(d.host)+'</span> '+badge(d.state)+' <span class="monitor-timer">⏱'+fmtElapsed(elapsed)+'</span> <span class="muted" style="font-size:10px">思考'+d.rc+' 工具'+d.tc+'</span> <span class="monitor-tid muted" style="font-size:10px" data-worker="'+esc(curWid)+'">'+esc(d.tid)+'</span>';
}
}

function schedulePoll(){pollLogs().finally(function(){thinkingPoll=setTimeout(schedulePoll,2000)});}
schedulePoll();
window._timerTick=setInterval(tickTimers,1000);
}
