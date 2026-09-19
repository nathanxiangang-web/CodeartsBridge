async function loadTaskDetail(id){
  if(!id){return `<div class="card"><p class="muted">No task ID. <a href="#tasks">Back to list</a></p></div>`}
  const task=await api("/tasks/"+encodeURIComponent(id));
  if(task.error){return `<div class="card"><p class="muted">Error: ${esc(task.error)}</p><p><a href="#tasks">Back to list</a></p></div>`}
  const ops=allowedOps(task.state);
  const meta=task.meta||{};
  const deps=Array.isArray(task.dependsOn)?task.dependsOn:[];
  const tokens=task.tokens||{};
  const outbox=task.outbox||[];
  const hb=task.lastHeartbeat?fmtTime(task.lastHeartbeat):"-";
  const activity=task.heartbeatThink||task.heartbeatTool||task.heartbeatSummary||task.message||"-";
  const timeout=`${task.targetMinutes||"?"}/${task.softTimeoutMinutes||"?"}/${task.hardTimeoutMinutes||"?"} min (target/soft/hard)`;
  const opsHtml=[
    ops.cancel?`<button class="btn btn-danger" onclick="cancelTask(\x27${esc(id)}\x27)">${t("cancel")}</button>`:"",
    ops.retry?`<button class="btn" onclick="retryTask(\x27${esc(id)}\x27)">Retry</button>`:"",
    ops.reassign?`<button class="btn" onclick="showReassign(\x27${esc(id)}\x27)">Reassign</button>`:"",
    ops.reviewPass?`<button class="btn btn-primary" onclick="reviewPass(\x27${esc(id)}\x27)">Review Pass</button>`:"",
    ops.reviewFix?`<button class="btn" onclick="showReviewFix(\x27${esc(id)}\x27)">Review Fix</button>`:"",
  ].filter(Boolean).join(" ");
  return `
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h2>${esc(task.taskId)}</h2>
      ${badge(task.state)}
    </div>
    <div style="margin:8px 0">${opsHtml}</div>
    <p><a href="#tasks">Back to list</a> | <a href="#dag">DAG</a> | <a href="/api/tasks/${esc(id)}/log" target="_blank">Open log</a></p>
  </div>
  <div class="card"><h2>Overview</h2>
    <table>
      <tr><th>Task ID</th><td>${esc(task.taskId)}</td></tr>
      <tr><th>State</th><td>${badge(task.state)}</td></tr>
      <tr><th>Project</th><td>${esc(task.projectId||"-")}</td></tr>
      <tr><th>Role</th><td>${esc(task.role||"-")}</td></tr>
      <tr><th>Assigned Worker</th><td>${esc(task.workerId||task.assignedWorkerId||"-")}</td></tr>
      <tr><th>Preferred Worker</th><td>${esc(task.preferredWorker||"-")}</td></tr>
      <tr><th>Attempt</th><td>${task.attempt||0}</td></tr>
      <tr><th>Priority</th><td>${task.priority!=null?task.priority:"-"}</td></tr>
      <tr><th>Dependencies</th><td>${deps.length?deps.map(d=>`<span class="badge badge-thinking">${esc(d)}</span>`).join(" "):`<span class="muted">none</span>`}</td></tr>
      <tr><th>Required Skills</th><td>${(task.requiredSkills||[]).map(s=>esc(s)).join(", ")||`<span class="muted">none</span>`}</td></tr>
      <tr><th>Baseline</th><td>${esc(task.baseline||"-")}</td></tr>
      <tr><th>Review Required</th><td>${task.reviewRequired!=null?task.reviewRequired:"-"}</td></tr>
      <tr><th>Independent Review</th><td>${task.independentReview!=null?task.independentReview:"-"}</td></tr>
    </table>
  </div>
  <div class="card"><h2>Objective & Acceptance</h2>
    <pre style="white-space:pre-wrap;font-size:13px">${esc(meta.objective||meta.description||"(no objective in META)")}</pre>
    <h2 style="margin-top:12px">Acceptance Criteria</h2>
    <pre style="white-space:pre-wrap;font-size:13px">${esc(meta.acceptance||meta.acceptanceCriteria||"(not specified)")}</pre>
  </div>
  <div class="card"><h2>Timeline</h2>
    ${timeline(buildTimelineFromTask(task))}
  </div>
  <div class="card"><h2>Execution</h2>
    <table>
      <tr><th>Heartbeat</th><td>${hb}</td></tr>
      <tr><th>Current Activity</th><td>${esc(activity)}</td></tr>
      <tr><th>Execution Timeout</th><td>${timeout}</td></tr>
      <tr><th>Process ID</th><td>${esc(task.processId||"-")}</td></tr>
      <tr><th>Exit Code</th><td>${task.exitCode!=null?task.exitCode:"-"}</td></tr>
      <tr><th>Session ID</th><td>${esc(task.sessionId||"-")}</td></tr>
      <tr><th>Session Mode</th><td>${esc(task.sessionMode||"-")}</td></tr>
      <tr><th>Workspace</th><td>${esc(task.workspace||task.workspaceMode||"-")} ${esc(task.workspacePath||"")}</td></tr>
      <tr><th>Commit SHA</th><td>${esc(task.commitSha||"-")}</td></tr>
      <tr><th>Integration State</th><td>${esc(task.integrationState||"-")}</td></tr>
    </table>
  </div>
  <div class="card"><h2>Tokens</h2>
    <table>
      <tr><th>Input</th><td>${tokens.input||0}</td></tr>
      <tr><th>Output</th><td>${tokens.output||0}</td></tr>
      <tr><th>Total</th><td>${tokens.total||(tokens.input||0)+(tokens.output||0)}</td></tr>
    </table>
  </div>
  <div class="card"><h2>Outbox Files</h2>
    ${outbox.length?`<table><tr><th>Name</th><th>Size</th><th>Modified</th></tr>${outbox.map(f=>`<tr><td><a href="/api/tasks/${esc(id)}/outbox/${encodeURIComponent(f.name)}" target="_blank">${esc(f.name)}</a></td><td>${f.size}</td><td>${fmtTime(f.mtime)}</td></tr>`).join("")}</table>`:`<p class="muted">No outbox files</p>`}
  </div>
  ${task.result?`<div class="card"><h2>Result</h2><pre style="white-space:pre-wrap;font-size:13px">${esc(task.result)}</pre></div>`:""}
  ${task.tests?`<div class="card"><h2>Tests</h2><pre style="white-space:pre-wrap;font-size:13px">${esc(task.tests)}</pre></div>`:""}
  ${task.evidence?`<div class="card"><h2>Evidence</h2><pre style="white-space:pre-wrap;font-size:13px">${esc(task.evidence)}</pre></div>`:""}
  ${task.changedFiles?`<div class="card"><h2>Changed Files</h2><pre style="white-space:pre-wrap;font-size:13px">${esc(task.changedFiles)}</pre></div>`:""}
  <div id="reassign-modal" style="display:none"></div>
  <div id="reviewfix-modal" style="display:none"></div>`;
}
async function showReassign(id){
  const wr=await api("/workers");
  const workers=wr.workers||[];
  const opts=workers.map(w=>`<option value="${esc(w.id)}">${esc(w.id)}</option>`).join("");
  const m=document.getElementById("reassign-modal");
  m.style.display="block";
  m.innerHTML=`<div class="card"><h2>Reassign ${esc(id)}</h2><div class="form-row"><label>Worker</label><select id="ra-worker">${opts}</select><button class="btn btn-primary" onclick="doReassign(\x27${esc(id)}\x27)">Confirm</button><button class="btn" onclick="document.getElementById(\x27reassign-modal\x27).style.display=\x27none\x27">Cancel</button></div></div>`;
}
async function doReassign(id){
  const w=document.getElementById("ra-worker").value;
  const r=await api(`/tasks/${id}/reassign`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({workerId:w})});
  if(r.error){alert(r.error);return}
  loadTaskDetail(id);
}
async function reviewPass(id){
  const r=await api(`/tasks/${id}/review/pass`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})});
  if(r.error){alert(r.error);return}
  loadTaskDetail(id);
}
function showReviewFix(id){
  const m=document.getElementById("reviewfix-modal");
  m.style.display="block";
  m.innerHTML=`<div class="card"><h2>Review Fix ${esc(id)}</h2><div class="form-row"><label>Comment</label><input id="rf-comment" placeholder="Fix instructions"></div><button class="btn btn-primary" onclick="doReviewFix(\x27${esc(id)}\x27)">Submit</button><button class="btn" onclick="document.getElementById(\x27reviewfix-modal\x27).style.display=\x27none\x27">Cancel</button></div>`;
}
async function doReviewFix(id){
  const c=document.getElementById("rf-comment").value.trim();
  const r=await api(`/tasks/${id}/review/fix`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({comment:c})});
  if(r.error){alert(r.error);return}
  loadTaskDetail(id);
}
