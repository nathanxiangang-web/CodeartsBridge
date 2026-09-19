function stateBadge(s) {
  const m = {RUNNING:'running',DONE:'done',FAILED:'failed',REVIEW_REQUIRED:'review',QUEUED:'idle',READY:'idle',STARTING:'running',ASSISTANCE_REQUIRED:'failed',CANCELLED:'idle',REVIEW_PASSED:'done',FIX_REQUIRED:'review',INTEGRATING:'running'};
  return `<span class="badge badge-${m[s]||'idle'}">${s||'?'}</span>`;
}

function elapsed(ts) {
  if (!ts) return '-';
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60);
  if (m < 60) return m + ':' + String(s % 60).padStart(2, '0');
  return Math.floor(m / 60) + 'h' + (m % 60) + 'm';
}

async function renderOverview() {
  let html = '<div class="grid grid-4">';
  let health = null, workers = [], tasks = [];

  try { health = await API.health(); } catch {}
  try { const r = await API.workers(); workers = r.workers || []; } catch {}
  try { const r = await API.tasks(); tasks = r.tasks || []; } catch {}

  const cls = health && health.status === 'healthy' ? 'badge-done' : 'badge-failed';
  html += `<div class="card stat"><div class="num"><span class="badge ${cls}">${health?health.status:'DOWN'}</span></div><div class="label">Bridge</div></div>`;

  const online = workers.filter(w => w.online !== false);
  html += `<div class="card stat"><div class="num">${online.length}/${workers.length}</div><div class="label">Workers 在线</div></div>`;

  const running = tasks.filter(t => (t.state||t.status) === 'RUNNING' || (t.state||t.status) === 'STARTING').length;
  const review = tasks.filter(t => (t.state||t.status) === 'REVIEW_REQUIRED').length;
  const failed = tasks.filter(t => (t.state||t.status) === 'FAILED').length;
  html += `<div class="card stat"><div class="num">${running}</div><div class="label">运行中</div></div>`;
  html += `<div class="card stat"><div class="num">${review}</div><div class="label">待审查</div></div>`;
  html += `</div>`;

  html += `<div class="card stat"><div class="num" style="color:var(--red)">${failed}</div><div class="label">失败</div></div>`;

  html += '<div class="grid grid-2"><div class="card"><h3>Workers</h3><div id="ov-workers">加载中...</div></div>';
  html += '<div class="card"><h3>最近任务</h3><div id="ov-tasks">加载中...</div></div></div>';

  return html;
}

async function mountOverview() {
  await _refreshOverview();
  if (!window._ovTimer) window._ovTimer = setInterval(_refreshOverview, 5000);
}

async function _refreshOverview() {
  let workers = [], tasks = [];
  try { const r = await API.workers(); workers = r.workers || []; } catch {}
  try { const r = await API.tasks(); tasks = r.tasks || []; } catch {}

  const el = document.getElementById('ov-workers');
  if (el) el.innerHTML = workers.map(w => {
    const current = Array.isArray(w.currentTasks) && w.currentTasks.length
      ? (w.currentTasks[0].taskId || '')
      : (w.currentTask || '');
    const st = w.online === false ? 'OFFLINE' : (current ? 'RUNNING' : 'IDLE');
    const cls = st === 'OFFLINE' ? 'badge-offline' : (st === 'RUNNING' ? 'badge-running' : 'badge-idle');
    return `<div class="worker-row"><span class="badge ${cls}">${st}</span><span>${w.id||w.workerId||'?'}</span><span class="muted">${current}</span></div>`;
  }).join('') || '<p class="muted">无 Worker</p>';

  const el2 = document.getElementById('ov-tasks');
  if (el2) {
    const recent = tasks.slice(0, 10);
    el2.innerHTML = '<table><tr><th>Task</th><th>Worker</th><th>State</th></tr>' +
      recent.map(t => `<tr><td><a href="#task-detail/${t.taskId||t.id}">${t.taskId||t.id||'?'}</a></td><td>${t.workerId||t.assignedWorkerId||'-'}</td><td>${stateBadge(t.state||t.status)}</td></tr>`).join('') +
      '</table>';
  }
}

