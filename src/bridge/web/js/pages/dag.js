async function loadDag(){
const data=await api('/tasks');
if(data.error)return `<div class="card"><p class="muted">Error: ${esc(data.error)}</p></div>`;
const tasks=data.tasks||[];
const byState={};
tasks.forEach(t=>{const s=t.state||'UNKNOWN';(byState[s]||(byState[s]=[])).push(t)});
const taskMap={};
tasks.forEach(t=>{taskMap[t.taskId]=t});
let layers='<div class="dag-layers">';
const order=['CREATED','READY','QUEUED','STARTING','RUNNING','REVIEW_REQUIRED','APPROVED','INTEGRATING','DONE','FAILED','BLOCKED','ASSISTANCE_REQUIRED'];
order.forEach(s=>{
const items=byState[s]||[];
if(items.length===0)return;
layers+=`<div class="dag-layer"><div class="dag-layer-header">${statusBadge(s)} <span class="muted">(${items.length})</span></div><div class="dag-layer-items">`;
items.forEach(t=>{
const deps=t.dependsOn||t.dependencies||[];
const isBlocked=deps.some(d=>{const dep=taskMap[d];return dep&&!['DONE','APPROVED','INTEGRATED'].includes(dep.state)});
layers+=`<div class="dag-node${isBlocked?' dag-node-blocked':''}" data-task="${esc(t.taskId)}" onclick="location.hash='task-detail/${esc(t.taskId)}'" style="cursor:pointer">`;
layers+=`<div class="dag-node-id">${esc(t.taskId)}</div>`;
layers+=`<div class="dag-node-info"><span class="muted">${esc(t.role||'')}</span> ${esc(t.workerId||'-')} <span class="muted">a${t.attempt||0}</span></div>`;
if(deps.length>0)layers+=`<div class="dag-deps"><span class="muted">deps:</span> ${deps.map(d=>{const dep=taskMap[d];const done=dep&&['DONE','APPROVED','INTEGRATED'].includes(dep.state);return `<span class="${done?'dag-dep-done':'dag-dep-pending'}" onclick="event.stopPropagation();location.hash='task-detail/${esc(d)}'">${esc(d)}</span>`}).join(', ')}</div>`;
if(isBlocked)layers+=`<div class="dag-blocked-reason">blocked by pending deps</div>`;
layers+='</div>';
});
layers+='</div></div>';
});
layers+='</div>';
return `<div class="card"><h2>Task DAG</h2><p class="muted">Click any node to view task detail. Click dependency to jump.</p>${layers}</div>`;
}
