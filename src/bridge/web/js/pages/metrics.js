async function loadMetrics(){
const m=await api('/metrics');
const c=await api('/cost');
const w=await api('/workers');
const activeWorkers=(w.workers||[]).filter(x=>x.enabled).length;
const fpr=(m.first_pass_rate||0)*100;
const avgCycle=m.avg_total_cycle_time_seconds;
const totalTasks=m.total_tasks||0;
const fmtSec=s=>s==null?'N/A':(s<60?`${s.toFixed(1)}s`:`${(s/60).toFixed(1)}m`);
let html=`
<div class="card"><h2>${t('metrics_summary')}</h2><div class="grid">
<div class="stat"><div class="num" style="color:#3fb950">${fpr.toFixed(1)}%</div><div class="label">${t('metrics_first_pass_rate')}</div></div>
<div class="stat"><div class="num">${fmtSec(avgCycle)}</div><div class="label">${t('metrics_avg_cycle')}</div></div>
<div class="stat"><div class="num">${totalTasks}</div><div class="label">${t('metrics_total_tasks')}</div></div>
<div class="stat"><div class="num" style="color:#58a6ff">${activeWorkers}</div><div class="label">${t('metrics_active_workers')}</div></div>
</div></div>`;
const wp=m.workerPerformance||[];
html+=`
<div class="card"><h2>${t('metrics_worker_perf')}</h2>
<table><tr><th>${t('worker')}</th><th>${t('total')}</th><th>${t('metrics_completed')}</th><th>${t('metrics_success_rate')}</th><th>${t('metrics_avg_duration')}</th></tr>
${wp.length?wp.map(p=>`<tr><td>${esc(p.workerId)}</td><td>${p.tasks}</td><td>${p.completed}</td><td>${(p.successRate*100).toFixed(1)}%</td><td>${fmtSec(p.avgDurationSeconds)}</td></tr>`).join(''):`<tr><td colspan="5" class="muted">${t('no_tasks')}</td></tr>`}
</table></div>`;
const roles=m.role_task_counts||{};
const roleVals=Object.values(roles);
const maxRole=roleVals.length?Math.max(...roleVals):1;
html+=`
<div class="card"><h2>${t('metrics_task_dist')}</h2>
${roleVals.length?Object.entries(roles).map(([r,n])=>{
const pct=Math.round(n/maxRole*100);
return `<div style="margin:6px 0"><span style="display:inline-block;width:100px;font-size:13px">${esc(r)}</span><span style="display:inline-block;vertical-align:middle;width:${pct}%;max-width:300px;height:14px;background:#1f6feb;border-radius:3px"></span> <span style="font-size:12px;color:#8b949e">${n}</span></div>`;
}).join(''):`<p class="muted">${t('no_tasks')}</p>`}
</div>`;
const byRole=c.byRole||[];
const byProject=c.byProject||[];
html+=`
<div class="card"><h2>${t('metrics_cost_breakdown')}</h2>
${c.hasCostData?`<p class="muted">${t('metrics_total_cost')}: $${(c.totalEstimatedCost||0).toFixed(4)} · ${t('metrics_total_tokens')}: ${c.totalTokens||0}</p>`:`<p class="muted">${t('metrics_no_cost_data')}</p>`}
<table><tr><th>${t('role')}</th><th>${t('total')}</th><th>${t('metrics_tokens')}</th><th>${t('metrics_est_cost')}</th></tr>
${byRole.length?byRole.map(r=>`<tr><td>${esc(r.key)}</td><td>${r.tasks}</td><td>${r.tokens}</td><td>$${(r.estimatedCost||0).toFixed(4)}</td></tr>`).join(''):`<tr><td colspan="4" class="muted">${t('no_tasks')}</td></tr>`}
</table>
<h3 style="margin:12px 0 6px;font-size:13px;color:#8b949e">${t('project')}</h3>
<table><tr><th>${t('project')}</th><th>${t('total')}</th><th>${t('metrics_tokens')}</th><th>${t('metrics_est_cost')}</th></tr>
${byProject.length?byProject.map(p=>`<tr><td>${esc(p.key)}</td><td>${p.tasks}</td><td>${p.tokens}</td><td>$${(p.estimatedCost||0).toFixed(4)}</td></tr>`).join(''):`<tr><td colspan="4" class="muted">${t('no_tasks')}</td></tr>`}
</table></div>`;
return html;
}
