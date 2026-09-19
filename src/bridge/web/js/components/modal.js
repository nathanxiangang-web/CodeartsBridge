function modal(title,body,opts){
const o=opts||{};
const id='modal-'+Date.now();
window._modalClose=function(){document.getElementById(id)?.remove();document.removeEventListener('keydown',onKey)};
function onKey(e){if(e.key==='Escape')window._modalClose()}
const footer=o.footer||`<button class="btn" onclick="window._modalClose()">${t('close')||'Close'}</button>`;
const html=`<div class="modal-overlay" id="${id}" onclick="if(event.target===this)window._modalClose()">
<div class="modal">
<div class="modal-header"><h3>${esc(title)}</h3><button class="modal-close" onclick="window._modalClose()">×</button></div>
<div class="modal-body">${body}</div>
<div class="modal-footer">${footer}</div>
</div></div>`;
document.body.insertAdjacentHTML('beforeend',html);
document.addEventListener('keydown',onKey);
return id;
}