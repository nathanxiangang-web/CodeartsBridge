function table(headers,rows,opts){
const o=opts||{};
let h=headerRow(headers,o);
let b=bodyRows(rows,headers,o);
return `<table class="data-table">${h}${b}</table>`;
}
function headerRow(headers,o){
if(o.noHeader)return '';
return '<thead><tr>'+headers.map(h=>`<th>${esc(h)}</th>`).join('')+'</tr></thead>';
}
function bodyRows(rows,headers,o){
if(!rows||rows.length===0)return `<tbody><tr><td colspan="${headers.length}" class="muted center">${o.emptyText||'No data'}</td></tr></tbody>`;
return '<tbody>'+rows.map(r=>`<tr>${headers.map((h,i)=>`<td>${r[i]||''}</td>`).join('')}</tr>`).join('')+'</tbody>';
}