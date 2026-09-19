let _sse=null;
let _sseConnected=false;
let _sseListeners=[];
let _sseReconnectTimer=null;

const _sseEventTypes=[
  'task.created','task.state_changed',
  'assignment.created','assignment.started','assignment.finished',
  'worker.online','worker.offline',
  'runtime.heartbeat','runtime.timeout','runtime.cancelled',
  'review.required','review.completed',
  'integration.started','integration.completed'
];

function _emitSse(type,event){
  try{
    const data=JSON.parse(event.data);
    if(type&&!data.type)data.type=type;
    _sseListeners.forEach(fn=>fn(data));
  }catch{}
}

const SSE = {
  start() {
    if(_sse){try{_sse.close()}catch{}}
    if(_sseReconnectTimer){clearTimeout(_sseReconnectTimer);_sseReconnectTimer=null;}
    try {
      // Bridge exposes the SSE stream at /api/events.
      _sse = new EventSource('/api/events');
      _sse.onopen = () => { _sseConnected = true; };
      _sse.onmessage = (e) => _emitSse('message',e);
      _sseEventTypes.forEach(type=>{
        _sse.addEventListener(type,e=>_emitSse(type,e));
      });
      _sse.onerror = () => {
        _sseConnected = false;
        if (_sse) { try{_sse.close()}catch{} _sse=null; }
        _sseReconnectTimer=setTimeout(() => this.start(), 3000);
      };
    } catch {
      _sseConnected=false;
      _sseReconnectTimer=setTimeout(() => this.start(), 5000);
    }
  },
  on(fn) { _sseListeners.push(fn); },
  isConnected() { return _sseConnected; },
};
