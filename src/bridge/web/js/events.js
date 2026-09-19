let _sse=null;
let _sseConnected=false;
let _sseCursor=0;
let _sseListeners=[];

const SSE = {
  start() {
    try {
      _sse = new EventSource('/api/events/stream');
      _sseConnected = true;
      _sse.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          _sseListeners.forEach(fn => fn(data));
        } catch {}
      };
      _sse.onerror = () => {
        _sseConnected = false;
        if (_sse) _sse.close();
        setTimeout(() => this.start(), 3000);
      };
    } catch {
      setTimeout(() => this.start(), 5000);
    }
  },
  on(fn) { _sseListeners.push(fn); },
  isConnected() { return _sseConnected; },
};
