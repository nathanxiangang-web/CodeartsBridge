async function loadProjects(){
const r=await api('/projects');
return `
<div class="card"><h2>${t('projects_list')}</h2>
<table><tr><th>${t('id')}</th><th>${t('transport')}</th><th>${t('project_root')}</th><th>${t('ssh_host')}</th><th>${t('run_mode')}</th><th>${t('model')}</th></tr>
${(r.projects||[]).map(p=>`<tr><td>${esc(p.id||p.projectId)}</td><td>${esc(p.transport||'local')}</td><td>${esc(p.projectRoot||'-')}</td><td>${esc(p.sshHost||'-')}</td><td>${esc(p.runMode||'auto')}</td><td>${esc(p.model||'-')}</td></tr>`).join('')}
</table></div>
<div class="card"><h2>${t('add_project')}</h2>
<div class="form-row"><label>${t('project_id')}</label><input id="pj-id" placeholder="bridge-dev"></div>
<div class="form-row"><label>${t('project_root')}</label><input id="pj-root" placeholder="/path/to/project"></div>
<div class="form-row"><label>${t('transport')}</label><select id="pj-transport"><option value="local">local</option><option value="ssh">ssh</option><option value="ssh-shell">ssh-shell</option><option value="remote-worktree">remote-worktree</option></select></div>
<div class="form-row"><label>${t('ssh_host')}</label><input id="pj-host" placeholder="user@host · ${t('optional')}"></div>
<div class="form-row"><label>${t('remote_bridge_root')}</label><input id="pj-remote-root" placeholder="/remote/bridge · ${t('optional')}"></div>
<div class="form-row"><label>${t('remote_workspace_root')}</label><input id="pj-workspace-root" placeholder="/remote/workspaces · ${t('optional')}"></div>
<div class="form-row"><label>${t('remote_cli_path')}</label><input id="pj-cli" placeholder="codearts · ${t('optional')}"></div>
<div class="form-row"><label>${t('run_mode')}</label><select id="pj-mode"><option value="auto">auto</option><option value="manual">manual</option><option value="sandbox">sandbox</option></select></div>
<div class="form-row"><label>${t('model')}</label><input id="pj-model" placeholder="${t('optional')}"></div>
<div class="form-row"><label>${t('timeout_minutes')}</label><input id="pj-timeout" type="number" min="1" value="60"></div>
<button class="btn btn-primary" onclick="addProject()">${t('add')}</button>
</div>`;
}
async function addProject(){
const id=document.getElementById('pj-id').value.trim();
const projectRoot=document.getElementById('pj-root').value.trim();
if(!id||!projectRoot){alert('Project ID / Project Root required');return}
const body={
id,
projectRoot,
transport:document.getElementById('pj-transport').value,
runMode:document.getElementById('pj-mode').value,
timeoutMinutes:Number(document.getElementById('pj-timeout').value)||60
};
const optional={
sshHost:document.getElementById('pj-host').value.trim(),
remoteBridgeRoot:document.getElementById('pj-remote-root').value.trim(),
remoteWorkspaceRoot:document.getElementById('pj-workspace-root').value.trim(),
remoteCliPath:document.getElementById('pj-cli').value.trim(),
model:document.getElementById('pj-model').value.trim()
};
for(const[k,v]of Object.entries(optional))if(v)body[k]=v;
const result=await api('/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
if(result.error){alert(result.error);return}
location.reload();
}
