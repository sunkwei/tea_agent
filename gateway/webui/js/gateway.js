/**
 * GatewayClient — REST + WebSocket 封装
 * 所有与 Gateway 后端的通信集中在这里
 */
class GatewayClient {
  constructor(baseUrl = 'http://127.0.0.1:18789') {
    this.base = baseUrl;
    this.ws = null;
    this._handlers = {};
    this._connected = false;
    this._reconnectTimer = null;
  }

  // ── REST API ──

  async api(method, path, body) {
    const url = this.base + path;
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(url, opts);
    if (!resp.ok) {
      const text = await resp.text().catch(() => '');
      throw new Error(`HTTP ${resp.status}: ${text.slice(0,200)}`);
    }
    return resp.json();
  }

  health() { return this.api('GET', '/health'); }

  listTools() { return this.api('GET', '/api/tools'); }

  listSessions() { return this.api('GET', '/api/sessions'); }

  createSession(title) { return this.api('POST', '/api/sessions/create', { title }); }

  async chat(messages, topicId = '') {
    return this.api('POST', '/api/chat', { messages, topic_id: topicId });
  }

  /** 流式聊天 — 返回 ReadableStream */
  chatStream(messages, topicId = '') {
    const url = this.base + '/api/chat';
    const body = JSON.stringify({ messages, topic_id: topicId, stream: true });
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    });
  }

  // ── Canvas API ──

  canvasPush(path, content) {
    return this.api('POST', '/api/canvas/push', { path, content });
  }

  a2uiPush(surface, components) {
    return this.api('POST', '/a2ui/push', { surface, components });
  }

  // ── WebSocket ──

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    const proto = this.base.startsWith('https') ? 'wss' : 'ws';
    const host = this.base.replace(/^https?:\/\//, '');
    const url = `${proto}://${host}/ws`;
    
    this.ws = new WebSocket(url);
    this.ws.onopen = () => {
      this._connected = true;
      this._emit('connected');
      if (this._reconnectTimer) {
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = null;
      }
    };
    this.ws.onclose = () => {
      this._connected = false;
      this._emit('disconnected');
      // 自动重连
      this._reconnectTimer = setTimeout(() => this.connect(), 3000);
    };
    this.ws.onerror = () => {
      this._emit('error', 'WebSocket 错误');
    };
    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        this._emit(msg.type, msg);
        this._emit('message', msg);
      } catch (err) {
        console.warn('WS parse error:', err);
      }
    };
  }

  disconnect() {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this._connected = false;
  }

  wsSend(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  ping() { this.wsSend({ type: 'ping' }); }

  // ── 事件系统 ──

  on(event, handler) {
    if (!this._handlers[event]) this._handlers[event] = [];
    this._handlers[event].push(handler);
    return () => this.off(event, handler);
  }

  off(event, handler) {
    const handlers = this._handlers[event];
    if (handlers) this._handlers[event] = handlers.filter(h => h !== handler);
  }

  _emit(event, data) {
    const handlers = this._handlers[event];
    if (handlers) handlers.forEach(h => { try { h(data); } catch(e) { console.warn(e); } });
  }

  get connected() { return this._connected; }
}
