function mapState(s){const k=String(s).toLowerCase();const q=['created','ready','queued','starting','fix_required','fixing','retryable'];const th=['running','assistance_required','integrating'];const d=['done','review_required','review_passed','verifying','integrated','cancelled','failed','blocked','auth_required','approved'];if(q.includes(k))return'queued';if(th.includes(k))return'thinking';if(d.includes(k))return'done';return'queued'}
function ts(s){const m=mapState(s);return(stateMap[m]&&stateMap[m][lang])||s}
function badge(s){const m=mapState(s);return `<span class="badge badge-${m}">${ts(s)}</span>`}
function esc(s){return String(s??'').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]))}
function fmtElapsed(sec){
if(!sec||sec<0)return '0秒';
const m=Math.floor(sec/60),h=Math.floor(m/60);
if(h>0)return `${h}时${m%60}分${sec%60}秒`;
if(m>0)return `${m}分${sec%60}秒`;
return `${sec}秒`;
}
