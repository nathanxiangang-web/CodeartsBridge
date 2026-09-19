async function loadDashboard(){
const [h,tasks,workers]=await Promise.all([api('/health'),api('/tasks'),api('/workers')]);
const allTasks=tasks.tasks||[];
const allWorkers=workers.workers||[];
const byState={};
allTasks.forEach(t=>{const s=t.state||'UNKNOWN';(byState[s]||(byState[s]=[])).push(t)});
const running=byState.RUNNING||[];
const review=byState.REVIEW_REQUIRED||[];
const failed=byState.FAILED||[];
const blocked=byState.BLOCKED||[];
const assistance=byState.ASSISTANCE_REQUIRED||[];
const ready=(byState.READY||[]).concat(byState.QUEUED||[]);
const onlineWorkers=allWorkers.filter(w=>w.online&&w.enabled!==false);
const disabledWorkers=allWorkers.filter(w=>w.enabled===false);
const idleWorkers=onlineWorkers.filter(w=>!w.currentTasks||w.currentTasks.length===0);
const daemon=h.daemon||{};
const pipeline=h.pipeline||{};
return `
<div class="card"><h2>${t('bridge_status')}</h2>
<p class="muted">${t('version')} ${esc(h.version||'?')} · ${esc(h.bridge_root||'')}</p>
<div class="grid">
<div class="stat"><div class="num" style="color:${daemon.status==='running'?'#3fb950':'#f85149'}">${esc(daemon.status||'-')}</div><div class="label">${t('daemon_status')}</div></div>
<div class="stat"><div class="num">${esc(pipeline.status||'-')}</div><div class="label">${t('pipeline_status')}</div></div>
<div class="stat"><div class="num">${running.length}</div><div class="label">RUNNING</div></div>
<div class="stat"><div class="num" style="color:${review.length>0?'#f0883e':'inherit'}">${review.length}</div><div class="label">REVIEW</div></div>
</div></div>
<div class="card"><h2>${t('workers_title')}</h2><div class="grid">
<div class="stat"><div class="num" style="color:#3fb950">${onlineWorkers.length}</div><div class="label">Online</div></div>
<div class="stat"><div class="num" style="color:#8b949e">${idleWorkers.length}</div><div class="label">Idle</div></div>
<div class="stat"><div class="num" style="color:#8b949e">${disabledWorkers.length}</div><div class="label">${t('disabled')}</div></div>
<div class="stat"><div class="num">${allWorkers.length}</div><div class="label">${t('enabled')}</div></div>
</div>
${onlineWorkers.map(w=>workerCard(w)).join('')}
</div>
<div class="card"><h2>${t('recent_tasks')}</h2>
<div class="grid">
<div class="stat"><div class="num">${running.length}</div><div class="label">Running</div></div>
<div class="stat"><div class="num">${ready.length}</div><div class="label">Waiting</div></div>
<div class="stat"><div class="num" style="color:${review.length>0?'#f0883e':'inherit'}">${review.length}</div><div class="label">Review</div></div>
<div class="stat"><div class="num" style="color:${failed.length>0?'#f85149':'inherit'}">${failed.length}</div><div class="label">Failed</div></div>
<div class="stat"><div class="num" style="color:${blocked.length>0?'#f85149':'inherit'}">${blocked.length}</div><div class="label">Blocked</div></div>
<div class="stat"><div class="num" style="color:${assistance.length>0?'#f85149':'inherit'}">${assistance.length}</div><div class="label">Assistance</div></div>
</div>
<table><tr><th>${t('id')}</th><th>${t('state')}</th><th>${t('project')}</th><th>${t('worker')}</th><th>${t('role')}</th></tr>
${allTasks.slice(0,15).map(task=>`<tr style="cursor:pointer" onclick="location.hash='task-detail/${esc(task.taskId)}'"><td>${esc(task.taskId)}</td><td>${statusBadge(task.state)}</td><td>${esc(task.projectId)}</td><td>${esc(task.workerId||'-')}</td><td>${esc(task.role)}</td></tr>`).join('')}
</table></div>
${review.length>0?`<div class="card"><h2>${t('review_queue')}</h2><table><tr><th>${t('id')}</th><th>${t('project')}</th><th>${t('role')}</th></tr>
${review.map(task=>`<tr style="cursor:pointer" onclick="location.hash='review'"><td>${esc(task.taskId)}</td><td>${esc(task.projectId)}</td><td>${esc(task.role)}</td></tr>`).join('')}
</table></div>`:''}
${failed.length>0?`<div class="card"><h2>Recent Failures</h2><table><tr><th>${t('id')}</th><th>${t('project')}</th><th>${t('worker')}</th></tr>
${failed.slice(0,5).map(task=>`<tr style="cursor:pointer" onclick="location.hash='task-detail/${esc(task.taskId)}'"><td>${esc(task.taskId)}</td><td>${esc(task.projectId)}</td><td>${esc(task.workerId||'-')}</td></tr>`).join('')}
</table></div>`:''}`;
}
