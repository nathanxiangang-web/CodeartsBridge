let _taskFilter = '';
let _taskStateFilter = '';

function renderTasks() {
  return `<div class="filter-bar">
    <input type="text" id="task-search" placeholder="搜索 Task ID..." value="${_taskFilter}">
    <select id="task-state-sel">
      <option value="">全部状态</option>
      <option value="RUNNING">RUNNING</option>
      <option value="REVIEW_REQUIRED">REVIEW</option>
      <option value="DONE">DONE</option>
      <option value="FAILED">FAILED</option>
      <option value="QUEUED">QUEUED</option>
    </select>
  </div>
  <div class="card"><div id="tasks-table">加载中...</div></div>`;
}

async function mountTasks() {
  const search = document.getElementById('task-search');
  const sel = document.getElementById('task-state-sel');
  if (search) search.oninput = (e) => { _taskFilter = e.target.value; loadTasksTable(); };
  if (sel) sel.onchange = (e) => { _taskStateFilter = e.target.value; loadTasksTable(); };
  if (sel) sel.value = _taskStateFilter;
  loadTasksTable();
  if (!window._tasksTimer) window._tasksTimer = setInterval(loadTasksTable, 5000);
}

async function loadTasksTable() {
  try {
    let r = await API.tasks();
    let ts = (r && r.tasks) ? r.tasks : (Array.isArray(r) ? r : []);
    if (_taskStateFilter) ts = ts.filter(t => (t.state||t.status) === _taskStateFilter);
    if (_taskFilter) ts = ts.filter(t => (t.taskId||t.id||'').includes(_taskFilter));
    ts.sort((a, b) => (b.taskId||'').localeCompare(a.taskId||''));
    const el = document.getElementById('tasks-table');
    if (!el) return;
    el.innerHTML = '<table><tr><th>Task</th><th>Worker</th><th>State</th><th>Project</th></tr>' +
      ts.map(t => `<tr><td><a href="#task-detail/${t.taskId||t.id}">${t.taskId||t.id||'?'}</a></td><td>${t.workerId||t.assignedWorkerId||'-'}</td><td>${stateBadge(t.state||t.status)}</td><td class="muted">${t.projectId||'-'}</td></tr>`).join('') +
      '</table>';
  } catch (e) {
    const el = document.getElementById('tasks-table');
    if (el) el.innerHTML = '<p class="muted">加载失败</p>';
  }
}
