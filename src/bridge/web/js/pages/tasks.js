let _taskFilter = '';
let _taskStateFilter = '';
let _lastTasks = [];

const TASK_HIDDEN_KEY = 'codeartsbridge.hiddenTasks.v1';
const TERMINAL_TASK_STATES = new Set([
  'DONE', 'FAILED', 'CANCELLED', 'BLOCKED', 'AUTH_REQUIRED', 'INTEGRATION_FAILED'
]);

function _taskId(task) {
  return String((task && (task.taskId || task.id)) || '');
}

function _readHiddenTaskIds() {
  try {
    const raw = localStorage.getItem(TASK_HIDDEN_KEY);
    const ids = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(ids) ? ids.map(String) : []);
  } catch {
    return new Set();
  }
}

function _saveHiddenTaskIds(ids) {
  try {
    localStorage.setItem(TASK_HIDDEN_KEY, JSON.stringify(Array.from(ids)));
  } catch {}
}

function _updateHiddenTaskUi() {
  const hidden = _readHiddenTaskIds();
  const count = document.getElementById('task-hidden-count');
  const restore = document.getElementById('task-restore-hidden');
  if (count) count.textContent = String(hidden.size);
  if (restore) restore.classList.toggle('hidden', hidden.size === 0);
}

function clearFinishedTaskDisplay() {
  const hidden = _readHiddenTaskIds();
  for (const task of _lastTasks) {
    const state = task.state || task.status || '';
    const id = _taskId(task);
    if (id && TERMINAL_TASK_STATES.has(state)) hidden.add(id);
  }
  _saveHiddenTaskIds(hidden);
  _updateHiddenTaskUi();
  loadTasksTable();
}

function restoreHiddenTaskDisplay() {
  try { localStorage.removeItem(TASK_HIDDEN_KEY); } catch {}
  _updateHiddenTaskUi();
  loadTasksTable();
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
    <button type="button" class="ui-btn" id="task-clear-finished">清除已结束</button>
    <button type="button" class="ui-btn hidden" id="task-restore-hidden">恢复隐藏 (<span id="task-hidden-count">0</span>)</button>
    <span class="muted task-display-note">仅清除本浏览器显示，不删除任务</span>
  </div>
  <div class="card"><div id="tasks-table">加载中...</div></div>`;
}

async function mountTasks() {
  const search = document.getElementById('task-search');
  const sel = document.getElementById('task-state-sel');
  const clearFinished = document.getElementById('task-clear-finished');
  const restoreHidden = document.getElementById('task-restore-hidden');
  if (search) search.oninput = (e) => { _taskFilter = e.target.value; loadTasksTable(); };
  if (sel) sel.onchange = (e) => { _taskStateFilter = e.target.value; loadTasksTable(); };
  if (sel) sel.value = _taskStateFilter;
  if (clearFinished) clearFinished.onclick = clearFinishedTaskDisplay;
  if (restoreHidden) restoreHidden.onclick = restoreHiddenTaskDisplay;
  _updateHiddenTaskUi();
  loadTasksTable();
  if (!window._tasksTimer) window._tasksTimer = setInterval(loadTasksTable, 5000);
}

async function loadTasksTable() {
  try {
    let r = await API.tasks();
    let ts = (r && r.tasks) ? r.tasks : (Array.isArray(r) ? r : []);
    _lastTasks = ts.slice();

    const hidden = _readHiddenTaskIds();
    ts = ts.filter(t => !hidden.has(_taskId(t)));

    if (_taskStateFilter) ts = ts.filter(t => (t.state||t.status) === _taskStateFilter);
    if (_taskFilter) ts = ts.filter(t => _taskId(t).includes(_taskFilter));

    const ACTIVE_STATES = new Set(['RUNNING','STARTING','QUEUED','REVIEW_REQUIRED','APPROVED','INTEGRATING','INTEGRATED','ASSISTANCE_REQUIRED']);
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
      return `<tr><td><a href="#task-detail/${t.taskId||t.id}">${t.taskId||t.id||'?'}</a></td><td>${t.workerId||t.assignedWorkerId||'-'}</td><td>${stateBadge(state)}</td><td class="muted">${t.projectId||'-'}</td><td class="muted">${_fmtShort(updated)}</td><td class="muted">${elapsedStr}</td></tr>`;
    }).join('');

    el.innerHTML = '<table><tr><th>Task</th><th>Worker</th><th>State</th><th>Project</th><th>更新</th><th>耗时</th></tr>' +
      rows +
      '</table>' +
      (ts.length ? '' : '<p class="muted task-empty">当前没有需要显示的任务</p>');

    _updateHiddenTaskUi();
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
