const pages={dashboard:loadDashboard,projects:loadProjects,tasks:loadTasks,'task-detail':loadTaskDetail,dag:loadDag,workers:loadWorkers,review:loadReview,metrics:loadMetrics,thinking:loadThinking,settings:loadSettings}
async function navigate(page){
const parts=page.split('/');
const base=parts[0];
const arg=parts.slice(1).join('/');
document.querySelectorAll('.nav-link').forEach(a=>a.classList.remove('active'));
document.querySelector(`[data-page="${base}"]`)?.classList.add('active');
const fn=pages[base]||loadDashboard;
try{document.getElementById('content').innerHTML=await fn(arg||'')}catch(e){document.getElementById('content').innerHTML=`<div class="card"><p class="muted">${t('error')||'Error'}: ${esc(String(e))}</p></div>`}
if(base==='thinking')initThinking();
}
window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)||'dashboard'));
window.addEventListener('load',()=>navigate(location.hash.slice(1)||'dashboard'));
