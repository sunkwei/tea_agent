/**
 * App — 应用主控
 * 协调所有组件、面板切换、连接管理
 */
class App {
  constructor() {
    this.gw = new GatewayClient();
    this.chat = new ChatWidget(this.gw);
    this.canvas = new CanvasPanel(this.gw);
    this._currentPanel = 'chat';
  }

  async init() {
    // 连接 WebSocket
    this.gw.connect();
    
    // 初始化聊天
    await this.chat.init();
    
    // 初始化画布
    await this.canvas.loadFiles();
    
    // 加载会话列表
    this.loadSessions();
    
    // 加载工具列表
    this.loadTools();

    // 监听连接状态
    this.gw.on('connected', () => {
      document.getElementById('statusDot').className = 'status-dot connected';
      document.getElementById('statusText').textContent = '已连接';
    });
    this.gw.on('disconnected', () => {
      document.getElementById('statusDot').className = 'status-dot disconnected';
      document.getElementById('statusText').textContent = '断开';
    });

    // WS canvas 更新
    this.gw.on('canvas_update', (msg) => {
      if (msg.path) this.canvas._addFileItem(msg.path);
    });

    console.log('🍵 Tea Agent WebUI ready');
  }

  // ── 面板切换 ──
  switchPanel(name) {
    this._currentPanel = name;
    // 导航按钮
    document.querySelectorAll('.nav-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.panel === name);
    });
    // 面板
    document.querySelectorAll('.panel').forEach(p => {
      p.classList.toggle('active', p.id === 'panel-' + name);
    });
    // 特殊面板加载
    if (name === 'sessions') this.loadSessions();
    if (name === 'tools') this.loadTools();
    if (name === 'canvas') this.canvas.refresh();
  }

  // ── 会话列表 ──
  async loadSessions() {
    const list = document.getElementById('sessionsList');
    list.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:2rem">加载中...</div>';
    try {
      const res = await this.gw.listSessions();
      const sessions = res.sessions || [];
      list.innerHTML = '';
      if (sessions.length === 0) {
        list.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:2rem">暂无会话</div>';
        return;
      }
      sessions.forEach(s => {
        const div = document.createElement('div');
        div.className = 'session-item';
        div.innerHTML = `<span class="title">${s.title || s.id.slice(0,8)}</span>
                         <span class="meta">${(s.total_tokens || 0).toLocaleString()} tokens</span>`;
        div.onclick = () => {
          this.chat._topicId = s.id;
          this.chat.sessionTitle.textContent = s.title || s.id.slice(0,8);
          this.switchPanel('chat');
        };
        list.appendChild(div);
      });
    } catch(e) {
      list.innerHTML = `<div style="text-align:center;color:var(--red);padding:2rem">⚠️ ${e.message}</div>`;
    }
  }

  // ── 工具列表 ──
  async loadTools() {
    const list = document.getElementById('toolsList');
    list.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:2rem">加载中...</div>';
    try {
      const res = await this.gw.listTools();
      const tools = res.tools || [];
      list.innerHTML = '';
      tools.slice(0, 50).forEach(t => {
        const div = document.createElement('div');
        div.className = 'tool-item';
        div.innerHTML = `<div class="tool-name">${t.name}</div>
                         <div class="tool-desc">${t.description || '无描述'}</div>`;
        list.appendChild(div);
      });
      if (tools.length > 50) {
        list.innerHTML += `<div style="text-align:center;color:var(--text-dim);padding:0.5rem">
                           ...还有 ${tools.length - 50} 个工具</div>`;
      }
    } catch(e) {
      list.innerHTML = `<div style="text-align:center;color:var(--red);padding:2rem">⚠️ ${e.message}</div>`;
    }
  }

  // ── 设置 ──
  setTheme(theme) {
    document.body.classList.toggle('light', theme === 'light');
  }

  async reconnect() {
    const url = document.getElementById('gwUrl').value.trim();
    this.gw.disconnect();
    this.gw = new GatewayClient(url);
    this.chat.gw = this.gw;
    this.canvas.gw = this.gw;
    this.gw.connect();
    this.gw.on('connected', () => {
      document.getElementById('statusDot').className = 'status-dot connected';
      document.getElementById('statusText').textContent = '已连接';
    });
  }
}

// ── 启动 ──
const app = new App();
document.addEventListener('DOMContentLoaded', () => app.init());
