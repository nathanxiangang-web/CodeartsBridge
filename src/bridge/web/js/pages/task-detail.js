async function renderTaskDetail(id) {
  if (!id) return '<div class="card"><p class="muted">未指定任务 <a href="#tasks">返回列表</a></p></div>';

  let task = {}, log = {};
  try { task = await API.task(id); } catch {}
  try { log = await API.taskLog(id); } catch {}

  const t = task.task || task;
  const s = t.state || t.status || '?';
  const worker = t.workerId || t.assignedWorkerId || '-';
  const project = t.projectId || '-';
  const attempt = t.attempt || 1;
  const msg = t.message || '-';
  const exitCode = t.exitCode;
  const commitSha = t.commitSha || null;

  let html = `<div class="card"><h3>${t.taskId || id}</h3>`;
  html += `<div class="detail-row"><span class="k">状态</span><span class="v">${stateBadge(s)}</span></div>`;
  html += `<div class="detail-row"><span class="k">Worker</span><span class="v">${worker}</span></div>`;
  html += `<div class="detail-row"><span class="k">项目</span><span class="v">${project}</span></div>`;
  html += `<div class="detail-row"><span class="k">角色</span><span class="v">${t.role||'-'}</span></div>`;
  html += `<div class="detail-row"><span class="k">尝试</span><span class="v">${attempt}</span></div>`;
  html += `<div class="detail-row"><span class="k">退出码</span><span class="v">${exitCode ?? '-'}</span></div>`;
  html += `<div class="detail-row"><span class="k">消息</span><span class="v">${msg}</span></div>`;
  html += '</div>';

  const started = t.startedAt || t.runningAt;
  const finished = t.finishedAt || t.doneAt || t.failedAt || t.cancelledAt;
  let html2 = '<div class="card"><h3>时间</h3>';
  html2 += `<div class="detail-row"><span class="k">创建</span><span class="v">${fmtTime(t.createdAt)}</span></div>`;
  if (t.queuedAt) html2 += `<div class="detail-row"><span class="k">排队</span><span class="v">${fmtTime(t.queuedAt)}</span></div>`;
  if (started) html2 += `<div class="detail-row"><span class="k">开始</span><span class="v">${fmtTime(started)}</span></div>`;
  if (finished) html2 += `<div class="detail-row"><span class="k">完成</span><span class="v">${fmtTime(finished)}</span></div>`;
  if (started) html2 += `<div class="detail-row"><span class="k">耗时</span><span class="v">${elapsed(started)}</span></div>`;
  if (t.lastEventAt) html2 += `<div class="detail-row"><span class="k">最后事件</span><span class="v">${fmtTime(t.lastEventAt)}</span></div>`;
  html2 += '</div>';
  html += html2;

  if (commitSha) {
    html += `<div class="card"><h3>集成</h3>`;
    html += `<div class="detail-row"><span class="k">commitSha</span><span class="v"><code>${commitSha}</code></span></div>`;
    html += '</div>';
  }

  const outbox = t.outbox || [];
  if (outbox.length > 0) {
    html += '<div class="card"><h3>Outbox 文件</h3><div class="outbox-list">';
    for (const f of outbox) {
      const fname = f.name || f;
      const fsize = f.size ? ` (${f.size} bytes)` : '';
      html += `<div class="outbox-item"><span class="outbox-name">${fname}</span><span class="muted">${fsize}</span></div>`;
    }
    html += '</div></div>';

    for (const want of ['RESULT.md', 'TESTS.md', 'DIFF.stat']) {
      const found = outbox.find(f => (f.name || f) === want);
      if (!found) continue;
      try {
        const resp = await fetch(`/api/tasks/${id}/outbox/${want}`);
        if (resp.ok) {
          const text = await resp.text();
          const preview = text.length > 2000 ? text.slice(0, 2000) + '\n...(truncated)' : text;
          html += `<div class="card"><h3>${want}</h3><pre class="outbox-content">${escapeHtml(preview)}</pre></div>`;
        }
      } catch {}
    }
  }

  if (log.events && log.events.length) {
    html += '<div class="card"><h3>最近事件</h3><ul class="timeline">';
    log.events.slice(-30).reverse().forEach(e => {
      const cls = e.type === 'reasoning' ? 'evt-reasoning' : (e.type === 'tool_use' || e.type === 'tool' ? 'evt-tool' : 'evt-step');
      const txt = (e.part || e.text || '').slice(0, 150);
      html += `<li class="${cls}"><span class="ts">${fmtTime(e.timestamp || e.time)}</span>${e.type}: ${escapeHtml(txt)}</li>`;
    });
    html += '</ul></div>';
  }

  return html;
}

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function fmtTime(ts) {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    return d.toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  } catch { return String(ts).slice(0, 19); }
}
