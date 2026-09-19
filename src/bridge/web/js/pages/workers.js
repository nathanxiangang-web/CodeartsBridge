async function loadWorkers(){
const r=await api('/workers');
return `
<div class="card"><h2>${t('workers_list')}</h2>
<table><tr><th>${t('id')}</th><th>${t('enabled')}</th><th>${t('transport')}</th><th>${t('host')}</th><th>${t('capabilities')}</th><th>${t('concurrency')}</th><th>${t('model')}</th><th>${t('cli_path')}</th></tr>
${(r.workers||[]).map(w=>`<tr><td>${esc(w.id)}</td><td>${w.enabled!==false?'✅':'❌'}</td><td>${esc(w.transport||'ssh')}</td><td>${esc(w.host||t('local'))}</td><td>${esc((w.capabilities||[]).join(', ')||'-')}</td><td>${esc(w.concurrencyLimit??1)}</td><td>${esc(w.model||'-')}</td><td>${esc(w.cliPath||'-')}</td></tr>`).join('')}
</table></div>`;
}
