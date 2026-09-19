let _sse=null;
let _sseConnected=false;
let _sseCursor=0;
let _sseReconnectTimer=null;
let _sseReconnectDelay=1000;
const _seenEventIds=new Set();
const _subscribers=[];
function eventsConnect(){
if(_sse){try{_sse.close()}catch(e){}}
if(typeof EventSource==='undefined'){eventsDegraded();return}
try{
_sse=new EventSource('/api/events?cursor='+_sseCursor);
_sse.onopen=function(){_sseConnected=true;_sseReconnectDelay=1000;eventsNotify({type:'_connected'})};
_sse.onerror=function(){_sseConnected=false;_sse.close();_sse=null;eventsNotify({type:'_disconnected'});eventsScheduleReconnect()};
_sse.onmessage=function(e){
try{
const d=JSON.parse(e.data);
if(d.seq){_sseCursor=Math.max(_sseCursor,d.seq)}
if(d.eventId&&_seenEventIds.has(d.eventId))return;
if(d.eventId)_seenEventIds.add(d.eventId);
if(_seenEventIds.size>500){const arr=Array.from(_seenEventIds);_seenEventIds.clear();arr.slice(-250).forEach(x=>_seenEventIds.add(x))}
eventsNotify(d);
}catch(e){}
};
}catch(e){eventsDegraded()}
}
function eventsScheduleReconnect(){
if(_sseReconnectTimer)clearTimeout(_sseReconnectTimer);
_sseReconnectTimer=setTimeout(function(){_sseReconnectDelay=Math.min(_sseReconnectDelay*2,30000);eventsConnect()},_sseReconnectDelay);
}
function eventsDegraded(){
_sseConnected=false;
eventsNotify({type:'_degraded'});
if(!_ssePollTimer)_ssePollTimer=setInterval(eventsPoll,2000);
}
let _ssePollTimer=null;
async function eventsPoll(){
try{
const r=await api('/events?cursor='+_sseCursor);
const events=r.events||[];
events.forEach(function(d){
if(d.seq){_sseCursor=Math.max(_sseCursor,d.seq)}
if(d.eventId&&_seenEventIds.has(d.eventId))return;
if(d.eventId)_seenEventIds.add(d.eventId);
eventsNotify(d);
});
}catch(e){}
}
function eventsNotify(evt){
for(let i=0;i<_subscribers.length;i++){
try{_subscribers[i](evt)}catch(e){}
}
}
function eventsSubscribe(fn){
_subscribers.push(fn);
if(_subscribers.length===1)eventsConnect();
return function(){
const i=_subscribers.indexOf(fn);
if(i>=0)_subscribers.splice(i,1);
if(_subscribers.length===0){if(_sse){_sse.close();_sse=null}if(_ssePollTimer){clearInterval(_ssePollTimer);_ssePollTimer=null}}
};
}
function eventsIsConnected(){return _sseConnected}