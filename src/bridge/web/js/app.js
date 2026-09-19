const pages={dashboard:loadDashboard,projects:loadProjects,tasks:loadTasks,workers:loadWorkers,review:loadReview,metrics:loadMetrics,thinking:loadThinking,settings:loadSettings}
async function navigate(page){
document.querySelectorAll('.nav-link').forEach(a=>a.classList.remove('active'));
document.querySelector(`[data-page="${page}"]`)?.classList.add('active');
const fn=pages[page]||loadDashboard;
try{document.getElementById('content').innerHTML=await fn()}catch(e){document.getElementById('content').innerHTML=`<div class="card"><p class="muted">${t('error')}: ${esc(e)}</p></div>`}
if(page==='thinking')initThinking();
}

window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)||'dashboard'));
window.addEventListener('load',()=>navigate(location.hash.slice(1)||'dashboard'));