function timeline(events){
  const items=(events||[]).map(ev=>{
    const cls=ev.active?"timeline-item active":"timeline-item";
    const dot=ev.active?`<span class="timeline-dot active"></span>`:`<span class="timeline-dot"></span>`;
    const label=esc(ev.label||"");
    const time=ev.time?`<span class="muted timeline-time">${fmtTime(ev.time)}</span>`:"";
    const note=ev.note?`<div class="muted timeline-note">${esc(ev.note)}</div>`:"";
    return `<div class="${cls}">${dot}<div class="timeline-content"><span class="timeline-label">${label}</span>${time}${note}</div></div>`;
  }).join("");
  return `<div class="timeline">${items||`<span class="muted">No events</span>`}</div>`;
}
function buildTimelineFromTask(task){
  const events=[];
  if(task.createdAt)events.push({label:"Created",time:task.createdAt,active:task.state==="CREATED"});
  if(task.queuedAt)events.push({label:"Queued",time:task.queuedAt,active:task.state==="QUEUED"||task.state==="READY"});
  if(task.startedAt)events.push({label:"Started",time:task.startedAt,active:task.state==="STARTING"});
  if(task.runningAt)events.push({label:"Running",time:task.runningAt,active:task.state==="RUNNING"});
  if(task.finishedAt)events.push({label:"Finished",time:task.finishedAt,active:task.state==="FINISHED"});
  if(task.state==="REVIEW_REQUIRED"||task.state==="REVIEW_PASSED")events.push({label:"Reviewed",time:task.updatedAt,active:task.state==="REVIEW_REQUIRED"});
  if(task.doneAt||task.state==="DONE"||task.state==="INTEGRATED")events.push({label:"Done",time:task.doneAt||task.updatedAt,active:task.state==="DONE"||task.state==="INTEGRATED"});
  if(task.cancelledAt)events.push({label:"Cancelled",time:task.cancelledAt,active:true});
  if(task.failedAt)events.push({label:"Failed",time:task.failedAt,active:true});
  return events;
}
