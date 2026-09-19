async function loadTasks(){
const [r,projectsResult,workersResult]=await Promise.all([api('/tasks'),api('/projects'),api('/workers')]);
const projects=projectsResult.projects||[];
const workers=workersResult.workers||[];
return `
<div class="card"><h2>${t('tasks_list')}</h2>
<table><tr><th>${t('id')}</th><th>${t('state')}</th><th>${t('project')}</th><th>${t('worker')}</th><th>${t('role')}</th><th>${t('attempt')}</th><th>${t('actions')}</th></tr>
${(r.tasks||[]).map(task=>`<tr><td>${esc(task.taskId)}</td><td>${badge(task.state)}</td><td>${esc(task.projectId)}</td><td>${esc(task.workerId||'-')}</td><td>${esc(task.role)}</td><td>${task.attempt||0}</td>
<td><button class="btn" onclick="cancelTask('${esc(task.taskId)}')">${t('cancel')}</button></td></tr>`).join('')}
</table></div>
<div class="card"><h2>${t('create_task')}</h2>
<div class="form-row"><label>${t('task_id')}</label><input id="tk-id"></div>
<div class="form-row"><label>${t('project')}</label><select id="tk-project"><option value="">-- ${t('project')} --</option>${projects.map(p=>{const id=p.id||p.projectId||'';return `<option value="${esc(id)}">${esc(id)}</option>`}).join('')}</select></div>
<div class="form-row"><label>${t('worker')}</label><select id="tk-worker"><option value="">${t('auto')}</option>${workers.filter(w=>w.enabled!==false).map(w=>`<option value="${esc(w.id)}">${esc(w.id)} · ${esc((w.capabilities||[]).join('/'))}</option>`).join('')}</select></div>
<div class="form-row"><label>${t('role')}</label><select id="tk-role"><option value="architect">${t('architect')}</option><option value="implement" selected>${t('implement')}</option><option value="review">${t('review')}</option><option value="test">${t('test')}</option></select></div>
<div class="form-row"><label>${t('task_file')}</label><input id="tk-file" placeholder="${t('optional')}"></div>
<button class="btn btn-primary" onclick="createTask()">${t('create')}</button>
</div>`;
}
async function createTask(){
const taskId=document.getElementById('tk-id').value.trim();
const projectId=document.getElementById('tk-project').value.trim();
if(!taskId||!projectId){alert('Task ID / Project required');return}
const body={task_id:taskId,project_id:projectId,role:document.getElementById('tk-role').value};
const w=document.getElementById('tk-worker').value.trim();if(w)body.worker_id=w;
const f=document.getElementById('tk-file').value.trim();if(f)body.task_file=f;
const result=await api('/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
if(result.error){alert(result.error);return}
location.reload();
}
async function cancelTask(id){
await api(`/tasks/${id}/cancel`,{method:'POST'});
location.reload();
}
