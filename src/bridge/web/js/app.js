const PAGES = {
  overview: { render: renderOverview, mount: mountOverview },
  tasks: { render: renderTasks, mount: mountTasks },
  'task-detail': { render: renderTaskDetail, mount: null },
  thinking: { render: renderThinking, mount: mountThinking },
};

let _currentPage = '';
let _currentArg = null;
let _pageTimer = null;

function _clearPageTimer() {
  if (_pageTimer) { clearInterval(_pageTimer); _pageTimer = null; }
  if (window._ovTimer) { clearInterval(window._ovTimer); window._ovTimer = null; }
  if (window._tasksTimer) { clearInterval(window._tasksTimer); window._tasksTimer = null; }
  if (window._timerTick) { clearInterval(window._timerTick); window._timerTick = null; }
  if (window.thinkingPoll) { clearTimeout(window.thinkingPoll); window.thinkingPoll = null; }
}

async function navigate() {
  const hash = location.hash.slice(1) || 'overview';
  const parts = hash.split('/');
  const page = parts[0];
  const arg = parts[1];

  if (page === _currentPage && arg === _currentArg) return;

  const pageChanged = (page !== _currentPage);
  if (pageChanged) _clearPageTimer();
  _currentPage = page;
  _currentArg = arg;

  document.querySelectorAll('.nav-link').forEach(a => {
    a.classList.toggle('active', a.dataset.page === page);
  });

  const p = PAGES[page] || PAGES.overview;
  const el = document.getElementById('content');
  try {
    if (pageChanged) {
      el.innerHTML = '<p class="muted">加载中...</p>';
      const html = await p.render(arg);
      el.innerHTML = html;
    }
    if (p.mount) await p.mount(arg);
  } catch (e) {
    el.innerHTML = '<div class="card"><p class="muted">加载失败: ' + e.message + '</p></div>';
  }
}

window.addEventListener('hashchange', () => { _currentPage = ''; navigate(); });
document.addEventListener('DOMContentLoaded', () => {
  SSE.start();
  navigate();
});
