async function loadDag(){
const data=await api('/tasks');
if(data.error)return `<div class="card"><p class="muted">Error: ${esc(data.error)}</p></div>`;
const tasks=data.tasks||[];
const byState={};
tasks.forEach(t=>{const s=t.status||'UNKNOWN';(byState[s]||(byState[s]=[])).push(t)});
let layers='<div class="dag-layers">';
const order=['CREATED','READY','QUEUED','STARTING','RUNNING','REVIEW_REQUIRED','APPROVED','INTEGRATING','DONE','FAILED'];
order.forEach(s=>{
const items=byState[s]||[];
if(items.length===0)return;
layers+=`<div class="dag-layer"><div class="dag-layer-header">${statusBadge(s)} <span class="muted">(${items.length})</span></div><div class="dag-layer-items">`;
items.forEach(t=>{
const deps=t.dependencies||[];
layers+=`<div class="dag-node" data-task="${esc(t.id)}"><span class="dag-node-id">${esc(t.id)}</span>`;
if(deps.length>0)layers+=`<div class="dag-deps"><span class="muted">deps:</span> ${deps.map(d=>esc(d)).join(', ')}</div>`;
layers+='</div>';
});
layers+='</div></div>';
});
layers+='</div>';
return `<div class="card"><h2>Task DAG</h2>${layers}</div>`;
}