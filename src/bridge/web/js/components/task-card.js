function taskCard(task){
  const id=esc(task.taskId||"");
  const state=task.state||"";
  const project=esc(task.projectId||"-");
  const worker=esc(task.workerId||"-");
  const role=esc(task.role||"-");
  const attempt=task.attempt||0;
  const priority=task.priority!=null?task.priority:"-";
  const deps=Array.isArray(task.dependsOn)?task.dependsOn:[];
  const depBadge=deps.length?`<span class="badge badge-thinking">${deps.length}</span>`:`<span class="muted">0</span>`;
  const dur=fmtDurationFromTask(task);
  const updated=fmtTime(task.updatedAt||task.doneAt||task.finishedAt);
  return `<div class="card task-card" onclick="location.hash=\x27#task-detail/${id}\x27" style="cursor:pointer">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <strong>${id}</strong>
      ${badge(state)}
    </div>
    <div class="muted" style="margin-top:6px;font-size:12px">
      ${project} / ${role} / ${worker} &middot; attempt ${attempt} &middot; P${priority} &middot; deps ${depBadge} &middot; ${dur} &middot; upd ${updated}
    </div>
  </div>`;
}
function fmtDurationFromTask(task){
  const start=task.startedAt||task.runningAt||task.queuedAt;
  if(!start)return "0s";
  const end=task.finishedAt||task.doneAt||task.cancelledAt||task.failedAt||task.updatedAt;
  const s=parseIso(start),e=end?parseIso(end):Date.now();
  if(!s)return "0s";
  return fmtElapsedSec(Math.max(0,Math.floor((e-s)/1000)));
}
function fmtElapsedSec(sec){
  if(!sec||sec<0)return "0s";
  const m=Math.floor(sec/60),h=Math.floor(m/60);
  if(h>0)return h+"h"+(m%60)+"m";
  if(m>0)return m+"m"+(sec%60)+"s";
  return sec+"s";
}
function fmtTime(iso){
  if(!iso)return "-";
  const d=new Date(iso);
  if(isNaN(d.getTime()))return esc(String(iso).slice(0,19));
  const now=Date.now(),diff=now-d.getTime();
  if(diff<60000)return "just now";
  if(diff<3600000)return Math.floor(diff/60000)+"m ago";
  if(diff<86400000)return Math.floor(diff/3600000)+"h ago";
  return d.toISOString().slice(0,10);
}
function parseIso(iso){
  if(!iso)return 0;
  const d=new Date(iso);
  return isNaN(d.getTime())?0:d.getTime();
}
