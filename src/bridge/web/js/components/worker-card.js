function workerCard(w){
const status=w.enabled?(w.online?'online':'offline'):'disabled';
const cls={online:'success',offline:'warning',disabled:'default'}[status];
let tasks='';
if(w.currentTask){tasks=`<div class="worker-task"><span class="muted">Current:</span> ${esc(w.currentTask)}</div>`}
return `<div class="worker-card">
<div class="worker-header">
<span class="worker-name">${esc(w.id)}</span>
${badge(status,cls)}
</div>
<div class="worker-info">
<span class="muted">Transport:</span> ${esc(w.transport||'ssh')}
<span class="muted">Tasks:</span> ${w.completedTasks||0} completed
</div>
${tasks}
</div>`;
}