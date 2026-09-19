async function loadWorkers(){
const r=await api('/workers');
const workers=r.workers||[];
return `
<div class="card"><h2>${t('workers_list')}</h2>
<div class="grid">
<div class="stat"><div class="num" style="color:#3fb950">${workers.filter(w=>w.online&&w.enabled!==false).length}</div><div class="label">Online</div></div>
<div class="stat"><div class="num" style="color:#f0883e">${workers.filter(w=>w.enabled!==false&&!w.online).length}</div><div class="label">Offline</div></div>
<div class="stat"><div class="num" style="color:#8b949e">${workers.filter(w=>w.enabled===false).length}</div><div class="label">Disabled</div></div>
</div>
</div>
<div class="card"><h2>Worker Details</h2>
${workers.map(w=>{
const status=w.enabled===false?'disabled':(w.online?'online':'offline');
const cls={online:'success',offline:'warning',disabled:'default'}[status];
let info=`<div class="worker-info"><span class="muted">Transport:</span> ${esc(w.transport||'ssh')} <span class="muted">Concurrency:</span> ${w.concurrencyLimit||1} <span class="muted">Model:</span> ${esc(w.model||'-')}</div>`;
let taskInfo='';
if(w.currentTasks&&w.currentTasks.length>0){taskInfo=`<div class="worker-task"><span class="muted">Current:</span> ${w.currentTasks.map(tid=>`<a href="#task-detail/${esc(tid)}" style="color:var(--accent-blue)">${esc(tid)}</a>`).join(', ')}</div>`}
let hbInfo='';
if(w.lastHeartbeat){hbInfo=`<div class="worker-task"><span class="muted">Last heartbeat:</span> ${esc(w.lastHeartbeat)}</div>`}
return `<div class="worker-card"><div class="worker-header"><span class="worker-name">${esc(w.id)}</span>${badge(status,cls)}</div>${info}${taskInfo}${hbInfo}<div class="worker-task"><span class="muted">Host:</span> ${esc(w.host||'local')} <span class="muted">CLI:</span> ${esc(w.cliPath||'-')}</div><div class="worker-task"><span class="muted">Capabilities:</span> ${esc((w.capabilities||[]).join(', ')||'-')}</div></div>`;
}).join('')}
</div>`;
}
