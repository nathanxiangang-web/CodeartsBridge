async function loadReview(){
const r=await api('/tasks');
const reviewTasks=(r.tasks||[]).filter(task=>String(task.state||'').toUpperCase()==='REVIEW_REQUIRED');
const rows=await Promise.all(reviewTasks.map(async task=>{
const [detail,ob]=await Promise.all([api(`/tasks/${task.taskId}`),api(`/tasks/${task.taskId}/outbox`)]);
const files=ob.files||[];
const meta=detail.meta||{};
const objective=meta.objective||meta.description||'-';
const acceptance=meta.acceptance||meta.acceptanceCriteria||'-';
const lastMod=files.length>0?files.map(f=>f.mtime||'').sort().pop():'';
const fileList=files.length===0?`<p class="muted">${t('no_output_files')}</p>`:
files.map(f=>`<div class="outbox-file" onclick="viewOutboxFile('${esc(task.taskId)}','${esc(f.name)}')"><span class="file-icon">📄</span> ${esc(f.name)} <span class="muted">(${f.size}B)</span></div>`).join('');
const resultFile=files.find(f=>f.name==='RESULT.md'||f.name==='result');
const testsFile=files.find(f=>f.name==='TESTS.md'||f.name==='tests');
return `<tr><td><a href="#task-detail/${esc(task.taskId)}" style="color:var(--accent-blue)">${esc(task.taskId)}</a></td><td>${esc(task.projectId)}</td><td>${esc(task.role)}</td><td>${esc(task.workerId||'-')}</td><td>${task.attempt||0}</td><td class="muted">${esc(lastMod)}</td><td>
<button class="btn btn-primary" onclick="reviewPass('${esc(task.taskId)}')">${t('pass')}</button>
<button class="btn btn-danger" onclick="reviewFix('${esc(task.taskId)}')">${t('fix')}</button>
</td></tr>
<tr class="outbox-row"><td colspan="7"><div class="outbox-box">
<h3>Objective</h3><pre style="white-space:pre-wrap;font-size:12px;margin-bottom:8px">${esc(objective)}</pre>
<h3>Acceptance Criteria</h3><pre style="white-space:pre-wrap;font-size:12px;margin-bottom:8px">${esc(acceptance)}</pre>
<h3>${t('output_files')}</h3>${fileList}
${detail.changedFiles?`<h3>Changed Files</h3><pre style="white-space:pre-wrap;font-size:12px">${esc(detail.changedFiles)}</pre>`:''}
${detail.integrationState?`<h3>Integration State</h3><p>${esc(detail.integrationState)}</p>`:''}
</div></td></tr>`;
}));
return `
<div class="card"><h2>${t('review_queue')}</h2>
${reviewTasks.length===0?`<p class="muted">${t('no_review')}</p>`:''}
<table><tr><th>${t('id')}</th><th>${t('project')}</th><th>${t('role')}</th><th>Worker</th><th>Attempt</th><th>${t('event_time')}</th><th>${t('actions')}</th></tr>
${rows.join('')}
</table></div>
<div id="fileModal" class="modal" style="display:none" onclick="if(event.target===this)this.style.display='none'">
<div class="modal-content"><div class="modal-header"><h3 id="modalFileName"></h3><button class="btn" onclick="document.getElementById('fileModal').style.display='none'">✕</button></div><pre id="modalFileContent" class="file-content"></pre></div>
</div>`;
}
async function reviewPass(taskId){
if(!confirm(`${taskId}: ${t('pass')}?`))return;
const result=await api(`/tasks/${taskId}/review/pass`,{
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({reviewerId:'web'})
});
if(result.error||result.success===false){alert(result.error||t('review_action_failed'));return}
navigate('review');
}
async function reviewFix(taskId){
const instruction=prompt(t('fix_instruction'));
if(instruction===null)return;
const comment=instruction.trim();
if(!comment){alert(t('fix_instruction'));return}
const result=await api(`/tasks/${taskId}/review/fix`,{
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({reviewerId:'web',comment})
});
if(result.error||result.success===false){alert(result.error||t('review_action_failed'));return}
navigate('review');
}
async function viewOutboxFile(taskId,filename){
const r=await api(`/tasks/${taskId}/outbox/${encodeURIComponent(filename)}`);
document.getElementById('modalFileName').textContent=filename;
document.getElementById('modalFileContent').textContent=r.content||r.error||'';
document.getElementById('fileModal').style.display='flex';
}
