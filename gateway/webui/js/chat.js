/**
 * ChatWidget — 流式对话界面
 * 支持 SSE 流式响应 + 工具调用展示 + 思考过程
 */
class ChatWidget {
  constructor(gateway) {
    this.gw = gateway;
    this.container = document.getElementById('messages');
    this.input = document.getElementById('chatInput');
    this.sendBtn = document.getElementById('sendBtn');
    this.sessionTitle = document.getElementById('sessionTitle');
    this._topicId = '';
    this._streaming = false;
    this._abortController = null;
  }

  async init() {
    // 创建新会话
    try {
      const res = await this.gw.createSession('WebUI 会话');
      if (res.id) {
        this._topicId = res.id;
        this.sessionTitle.textContent = res.title || '新会话';
      }
    } catch(e) {
      console.warn('创建会话失败:', e);
    }
    // 绑定事件
    this.gw.on('connected', () => this._onStatus());
    this.gw.on('disconnected', () => this._onStatus());
  }

  // ── 发送消息 ──
  async send() {
    const text = this.input.value.trim();
    if (!text || this._streaming) return;

    this.input.value = '';
    this._setStreaming(true);

    // 添加用户消息
    this.addMessage(text, 'user');
    
    // 添加 AI 消息占位
    const aiDiv = this.addMessage('', 'ai', true);
    const bubble = aiDiv.querySelector('.msg-bubble');
    const thinking = aiDiv.querySelector('.msg-thinking');
    const toolsDiv = aiDiv.querySelector('.msg-tools');

    try {
      // 使用 SSE 流式请求
      const resp = await this.gw.chatStream(
        [{ role: 'user', content: text }],
        this._topicId
      );
      
      if (!resp.ok) {
        bubble.textContent = `HTTP ${resp.status}: ${resp.statusText}`;
        this._setStreaming(false);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        // 解析 SSE 事件
        const lines = buffer.split('\n');
        buffer = lines.pop(); // 保留未完成的行
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim();
            if (data === '[DONE]') continue;
            try {
              const parsed = JSON.parse(data);
              this._handleSSEEvent(parsed, bubble, thinking, toolsDiv);
            } catch(e) {
              // 非 JSON 数据
              if (data) bubble.textContent += data;
            }
          }
        }
      }
      // 处理剩余 buffer
      if (buffer.startsWith('data: ')) {
        const data = buffer.slice(6).trim();
        if (data !== '[DONE]') {
          try {
            this._handleSSEEvent(JSON.parse(data), bubble, thinking, toolsDiv);
          } catch(e) {}
        }
      }
    } catch(e) {
      bubble.textContent = '⚠️ ' + e.message;
      console.error('Chat error:', e);
    }
    
    this._setStreaming(false);
    // 移除光标
    bubble.classList.remove('msg-cursor');
    this._scrollToBottom();
  }

  _handleSSEEvent(parsed, bubble, thinking, toolsDiv) {
    const choices = parsed.choices || [];
    for (const choice of choices) {
      const delta = choice.delta || {};
      if (delta.content) {
        bubble.textContent += delta.content;
        bubble.classList.add('msg-cursor');
        this._scrollToBottom();
      }
      if (choice.finish_reason === 'stop') {
        bubble.classList.remove('msg-cursor');
      }
    }
    // 工具调用
    if (parsed.tool_calls) {
      toolsDiv.innerHTML = parsed.tool_calls.map(t =>
        `<span>🔧 ${t.function?.name || t.name || 'tool'}</span>`
      ).join('');
    }
    if (parsed.type === 'reasoning' && parsed.content) {
      thinking.classList.add('active');
      thinking.textContent = '💭 ' + parsed.content;
    }
    if (parsed.type === 'tool_call') {
      const tc = parsed.tool_calls || [];
      toolsDiv.innerHTML = tc.map(t =>
        `<span>🔧 ${t.function?.name || t.name || 'tool'}</span>`
      ).join('');
    }
    if (parsed.type === 'tool_start') {
      toolsDiv.innerHTML += `<span>🔧 ${parsed.name}</span>`;
    }
    if (parsed.type === 'think' && parsed.text) {
      thinking.classList.add('active');
      thinking.textContent = '💭 ' + parsed.text;
    }
    if (parsed.type === 'think_done') {
      thinking.classList.remove('active');
    }
    if (parsed.type === 'tool_done') {
      // 工具执行完毕
    }
  }

  // ── 消息渲染 ──
  addMessage(text, role, streaming = false) {
    const div = document.createElement('div');
    div.className = `msg msg-${role}`;
    
    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = role === 'user' ? '👤' : '🤖';
    
    const content = document.createElement('div');
    content.className = 'msg-content';
    
    const thinking = document.createElement('div');
    thinking.className = 'msg-thinking';
    content.appendChild(thinking);
    
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    if (streaming) bubble.classList.add('msg-cursor');
    bubble.textContent = text;
    content.appendChild(bubble);
    
    const tools = document.createElement('div');
    tools.className = 'msg-tools';
    content.appendChild(tools);
    
    if (role === 'user') {
      div.appendChild(content);
      div.appendChild(avatar);
    } else {
      div.appendChild(avatar);
      div.appendChild(content);
    }
    
    this.container.appendChild(div);
    this._scrollToBottom();
    return div;
  }

  clear() {
    this.container.innerHTML = '';
  }

  async newSession() {
    this.clear();
    try {
      const res = await this.gw.createSession('WebUI 会话');
      if (res.id) {
        this._topicId = res.id;
        this.sessionTitle.textContent = res.title || '新会话';
      }
    } catch(e) {
      console.warn(e);
    }
  }

  onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.send();
    }
  }

  // ── 内部 ──
  _setStreaming(v) {
    this._streaming = v;
    this.sendBtn.disabled = v;
    this.sendBtn.textContent = v ? '⏳ 思考中...' : '发送';
  }

  _scrollToBottom() {
    this.container.scrollTop = this.container.scrollHeight;
  }

  _onStatus() {
    // 状态变化时刷新会话列表
  }
}
