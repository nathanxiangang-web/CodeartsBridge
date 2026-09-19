async function loadSettings(){
const h=await api('/health');
const daemon=h.daemon||null;
const pipeline=h.pipeline||null;
return `
<div class="card"><h2>${t('bridge_config')}</h2>
<p class="muted">${t('version')}: ${esc(h.version||'?')}</p>
<p class="muted">${t('root_dir')}: ${esc(h.bridge_root||'?')}</p>
<p class="muted">${t('api_status')}: ${esc(h.status||'?')}</p>
</div>
<div class="card"><h2>${t('runtime_settings')}</h2>
<p class="muted">${t('settings_readonly')}</p>
<table style="margin-top:12px">
<tr><th>${t('daemon_status')}</th><td>${esc(daemon&&daemon.status||t('not_started'))}</td><td>${esc(daemon&&daemon.updatedAt||'-')}</td></tr>
<tr><th>${t('pipeline_status')}</th><td>${esc(pipeline&&pipeline.status||t('not_started'))}</td><td>cycle ${esc(pipeline?.cycleCount??'-')}</td></tr>
<tr><th>RUNNING tasks</th><td>${h.running||0}</td><td>${t('total')}: ${h.tasks||0}</td></tr>
</table>
</div>`;
}
