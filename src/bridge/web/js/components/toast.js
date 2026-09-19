function toast(msg,kind){
const k=kind||'info';
const el=document.createElement('div');
el.className=`toast toast-${k}`;
el.textContent=msg;
document.body.appendChild(el);
setTimeout(()=>el.classList.add('toast-show'),10);
setTimeout(()=>{el.classList.remove('toast-show');setTimeout(()=>el.remove(),300)},3000);
}