let _taskFilter = '';
let _taskStateFilter = '';
let _lastTasks = [];

const TERMINAL_TASK_STATES = new Set([
  'DONE', 'FAILED', 'CANCELLED', 'BLOCKED', 'AUTH_REQUIRED', 'INTEGRATION_FAILED',
  'REVIEW_REQUIRED', 'ASSISTANCE_REQUIRED', 'REVIEW_PASSED', 'FIX_REQUIRED'
]);

function _taskId(task) {
  return String((task && (task.taskId || task.id)) || '');
}

function renderTasks() {
  return `<div class="filter-bar">
    <input type="text" id="task-search" placeholder="搜索 Task ID..." value="${_taskFilter}">
    <select id="task-state-sel">
      <option value="">全部状态</option>
      <option value="RUNNING">RUNNING</option>
      <option value="STARTING">STARTING</option>
      <option value="QUEUED">QUEUED</option>
      <option value="REVIEW_REQUIRED">REVIEW</option>
      <option value="APPROVED">APPROVED</option>
      <option value="INTEGRATING">INTEGRATING</option>
      <option value="INTEGRATED">INTEGRATED</option>
      <option value="DONE">DONE</option>
      <option value="FAILED">FAILED</option>
      <option value="ASSISTANCE_REQUIRED">ASSISTANCE</option>
      <option value="CANCELLED">CANCELLED</option>
      <option value="BLOCKED">BLOCKED</option>
      <option value="INTEGRATION_FAILED">INTEG_FAILED</option>
    </select>
    <button type="button" class="ui-btn" id="task-batch-delete">一键删除已结束</button>
  </div>
  <div class="card"><div id="tasks-table">加载中...</div></div>`;
}

async function mountTasks() {
  const search = document.getElementById('task-search');
  const sel = document.getElementById('task-state-sel');
  const batchDelete = document.getElementById('task-batch-delete');
  if (search) search.oninput = (e) => { _taskFilter = e.target.value; loadTasksTable(); };
  if (sel) sel.onchange = (e) => { _taskStateFilter = e.target.value; loadTasksTable(); };
  if (sel) sel.value = _taskStateFilter;
  if (batchDelete) batchDelete.onclick = _batchDeleteFinished;
  loadTasksTable();
  if (!window._tasksTimer) window._tasksTimer = setInterval(loadTasksTable, 5000);
}

async function loadTasksTable() {
  try {
    let r = await API.tasks();
    let ts = (r && r.tasks) ? r.tasks : (Array.isArray(r) ? r : []);
    _lastTasks = ts.slice();

    if (_taskStateFilter) ts = ts.filter(t => (t.state||t.status) === _taskStateFilter);
    if (_taskFilter) ts = ts.filter(t => _taskId(t).includes(_taskFilter));

    const ACTIVE_STATES = new Set(['RUNNING','STARTING','QUEUED','APPROVED','INTEGRATING','INTEGRATED']);
    ts.sort((a, b) => {
      const aActive = ACTIVE_STATES.has(a.state || a.status || '');
      const bActive = ACTIVE_STATES.has(b.state || b.status || '');
      if (aActive !== bActive) return aActive ? -1 : 1;
      const aTime = a.updatedAt || a.finishedAt || a.createdAt || '';
      const bTime = b.updatedAt || b.finishedAt || b.createdAt || '';
      return bTime.localeCompare(aTime);
    });

    const el = document.getElementById('tasks-table');
    if (!el) return;

    const rows = ts.map(t => {
      const state = t.state || t.status || '?';
      const updated = t.updatedAt || t.finishedAt || t.createdAt || '';
      const elapsedStr = (t.startedAt && t.finishedAt) ? _fmtElapsed(t.startedAt, t.finishedAt) : '-';
      const id = _taskId(t);
      const delBtn = t.deleteRequested
        ? `<span class="muted">删除中</span>`
        : `<button type="button" class="ui-btn ui-btn-sm task-delete-btn" data-task-id="${id}">删除</button>`;
      return `<tr><td><a href="#task-detail/${id}">${id||'?'}</a></td><td>${t.workerId||t.assignedWorkerId||'-'}</td><td>${stateBadge(state)}</td><td class="muted">${t.projectId||'-'}</td><td class="muted">${_fmtShort(updated)}</td><td class="muted">${elapsedStr}</td><td>${delBtn}</td></tr>`;
    }).join('');

    el.innerHTML = '<table><tr><th>Task</th><th>Worker</th><th>State</th><th>Project</th><th>更新</th><th>耗时</th><th>操作</th></tr>' +
      rows +
      '</table>' +
      (ts.length ? '' : '<p class="muted task-empty">当前没有需要显示的任务</p>');

    el.querySelectorAll('.task-delete-btn').forEach(btn => {
      btn.onclick = () => _deleteTask(btn.dataset.taskId);
    });
  } catch (e) {
    const el = document.getElementById('tasks-table');
    if (el) el.innerHTML = '<p class="muted">加载失败</p>';
  }
}
function _fmtShort(ts) {
  if (!ts) return '-';
  try { return new Date(ts).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}); }
  catch { return String(ts).slice(5,16); }
}

async function _deleteTask(taskId) {
  if (!taskId) return;
  const ok = confirm(
    `删除任务 ${taskId}？\n\n` +
    `删除任务记录不会取消正在运行的 Worker。\n` +
    `正在运行的任务会继续执行，结束后自动清理记录。`
  );
  if (!ok) return;
  try {
    const { status, data } = await API.deleteTask(taskId);
    if (status === 200) {
      alert(`任务 ${taskId} 已删除。`);
    } else if (status === 202) {
      alert(`任务 ${taskId} 仍在运行，已标记为延迟删除。\n任务结束后将自动清理记录。`);
    } else {
      alert(`删除失败: ${data.error || '未知错误'}`);
    }
    loadTasksTable();
  } catch (e) {
    alert(`删除失败: ${e}`);
  }
}

async function _batchDeleteFinished() {
  const finished = _lastTasks.filter(t => TERMINAL_TASK_STATES.has(t.state || t.status || ''));
  if (!finished.length) {
    alert('没有已结束的任务可删除。');
    return;
  }
  const ok = confirm(
    `将删除 ${finished.length} 个已结束任务。\n\n` +
    `删除任务记录不会取消正在运行的 Worker。\n` +
    `正在运行的任务会继续执行，结束后自动清理记录。`
  );
  if (!ok) return;
  let deleted = 0, pending = 0, failed = 0;
  for (const t of finished) {
    const id = _taskId(t);
    try {
      const { status } = await API.deleteTask(id);
      if (status === 200) deleted++;
      else if (status === 202) pending++;
      else failed++;
    } catch { failed++; }
  }
  alert(`删除完成：已删除 ${deleted}，延迟删除 ${pending}，失败 ${failed}。`);
  loadTasksTable();
}

function _fmtElapsed(start, end) {
  try {
    const ms = new Date(end) - new Date(start);
    if (ms < 0) return '-';
    const s = Math.floor(ms / 1000);
    if (s < 60) return s + 's';
    const m = Math.floor(s / 60);
    if (m < 60) return m + 'm' + (s % 60) + 's';
    const h = Math.floor(m / 60);
    return h + 'h' + (m % 60) + 'm';
  } catch { return '-'; }
}
