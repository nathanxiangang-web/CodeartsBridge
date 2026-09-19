async function renderTaskDetail(id) {
  if (!id) return '<div class="card"><p class="muted">未指定任务 <a href="#tasks">返回列表</a></p></div>';

  let task = {}, log = {};
  try { task = await API.task(id); } catch {}
  try { log = await API.taskLog(id); } catch {}

  const t = task.task || task;
  const s = t.state || t.status || '?';
  let html = `<div class="card"><h3>${t.taskId || id}</h3>`;
  html += `<div class="detail-row"><span class="k">状态</span><span class="v">${stateBadge(s)}</span></div>`;
  html += `<div class="detail-row"><span class="k">Worker</span><span class="v">${t.workerId||t.assignedWorkerId||'-'}</span></div>`;
  html += `<div class="detail-row"><span class="k">项目</span><span class="v">${t.projectId||'-'}</span></div>`;
  html += `<div class="detail-row"><span class="k">尝试</span><span class="v">${t.attempt||1}</span></div>`;
  html += `<div class="detail-row"><span class="k">耗时</span><span class="v">${elapsed(log.startTime)}</span></div>`;
  html += `<div class="detail-row"><span class="k">消息</span><span class="v">${t.message||'-'}</span></div>`;
  html += '</div>';

  if (log.events && log.events.length) {
    html += '<div class="card"><h3>最近事件</h3><ul class="timeline">';
    log.events.slice(-20).reverse().forEach(e => {
      const cls = e.type === 'reasoning' ? 'evt-reasoning' : (e.type === 'tool_use' ? 'evt-tool' : 'evt-step');
      html += `<li class="${cls}"><span class="ts">${e.timestamp||''}</span>${e.type}: ${(e.part||e.text||'').slice(0,120)}</li>`;
    });
    html += '</ul></div>';
  }

  return html;
}
