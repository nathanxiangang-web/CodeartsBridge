async function loadDashboard(){
const h=await api('/health');
const tasks=await api('/tasks');
const workers=await api('/workers');
const byState={};
(tasks.tasks||[]).forEach(t=>{byState[t.state]=(byState[t.state]||0)+1});
const enabled=(workers.workers||[]).filter(w=>w.enabled!==false).length;
const disabled=(workers.workers||[]).filter(w=>w.enabled===false).length;
const daemon=h.daemon||null;
const pipeline=h.pipeline||null;
return `
<div class="card"><h2>${t('bridge_status')}</h2>
<p class="muted">${t('version')} ${esc(h.version||'?')} · ${t('root_dir')}: ${esc(h.bridge_root||'?')}</p>
<div class="grid">
<div class="stat"><div class="num">${esc(daemon&&daemon.status||'-')}</div><div class="label">${t('daemon_status')}</div></div>
<div class="stat"><div class="num">${esc(pipeline&&pipeline.status||'-')}</div><div class="label">${t('pipeline_status')}</div></div>
<div class="stat"><div class="num">${h.running||0}</div><div class="label">RUNNING tasks</div></div>
</div>
${daemon&&daemon.updatedAt?`<p class="muted" style="margin-top:10px">${t('daemon_status')} · ${t('runtime_updated')}: ${esc(daemon.updatedAt)}</p>`:''}
</div>
<div class="card"><h2>${t('workers_title')}</h2><div class="grid">
<div class="stat"><div class="num" style="color:#3fb950">${enabled}</div><div class="label">${t('enabled')}</div></div>
<div class="stat"><div class="num" style="color:#8b949e">${disabled}</div><div class="label">${t('disabled')}</div></div>
<div class="stat"><div class="num">${(workers.workers||[]).length}</div><div class="label">${t('total')}</div></div>
</div></div>
<div class="card"><h2>${t('tasks_title')}</h2><div class="grid">
${Object.entries(byState).map(([s,n])=>`<div class="stat"><div class="num">${n}</div><div class="label">${esc(ts(s))}</div></div>`).join('')}
${Object.keys(byState).length===0?`<p class="muted">${t('no_tasks')}</p>`:''}
</div></div>
<div class="card"><h2>${t('recent_tasks')}</h2>
<table><tr><th>${t('id')}</th><th>${t('state')}</th><th>${t('project')}</th><th>${t('role')}</th></tr>
${(tasks.tasks||[]).slice(0,10).map(task=>`<tr><td>${esc(task.taskId)}</td><td>${badge(task.state)}</td><td>${esc(task.projectId)}</td><td>${esc(task.role)}</td></tr>`).join('')}
</table></div>`;
}
