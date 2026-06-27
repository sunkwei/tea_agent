/**
 * CanvasPanel — 可视化工作区控制
 */
class CanvasPanel {
  constructor(gateway) {
    this.gw = gateway;
    this.frame = document.getElementById('canvasFrame');
    this.empty = document.getElementById('canvasEmpty');
    this.fileList = document.getElementById('canvasFileList');
    this.a2uiInput = document.getElementById('a2uiInput');
    this._currentFile = 'index.html';
  }

  async refresh() {
    // 刷新当前文件
    if (this._currentFile && this.frame.style.display !== 'none') {
      this.frame.src = '/canvas/' + this._currentFile;
    }
    await this.loadFiles();
  }

  async loadFiles() {
    try {
      const res = await this.gw.api('GET', '/health');
      // 尝试发现文件
      const candidates = ['index.html'];
      for (const f of candidates) {
        try {
          const resp = await fetch('/canvas/' + f);
          if (resp.ok) this._addFileItem(f);
        } catch(e) {}
      }
    } catch(e) {
      console.warn('Load files error:', e);
    }
  }

  _addFileItem(name) {
    // 去重
    const existing = this.fileList.querySelector(`[data-file="${name}"]`);
    if (existing) return;

    const div = document.createElement('div');
    div.className = 'canvas-file-item';
    div.dataset.file = name;
    div.textContent = '📄 ' + name;
    div.onclick = () => this.openFile(name);
    this.fileList.appendChild(div);
  }

  openFile(name) {
    this._currentFile = name;
    // 高亮
    this.fileList.querySelectorAll('.canvas-file-item').forEach(el =>
      el.classList.toggle('active', el.dataset.file === name));
    
    this.frame.style.display = 'block';
    this.empty.style.display = 'none';
    this.frame.src = '/canvas/' + name;
  }

  openA2UI() {
    document.getElementById('a2uiPanel').classList.toggle('open');
  }

  openNewTab() {
    if (this._currentFile) {
      window.open('/canvas/' + this._currentFile, '_blank');
    }
  }

  async pushA2UI() {
    try {
      const json = JSON.parse(this.a2uiInput.value);
      const res = await this.gw.a2uiPush(json.surface || 'main', json.components || []);
      if (res.ok) {
        this.openFile(`_a2ui_${res.surface}.html`);
      }
    } catch(e) {
      alert('JSON 格式错误: ' + e.message);
    }
  }

  loadExample() {
    this.a2uiInput.value = JSON.stringify({
      surface: 'main',
      components: [
        {id: 't1', component: {Text: {text: '🦞 Tea Agent Canvas', usageHint: 'h1'}}},
        {id: 't2', component: {Text: {text: 'A2UI 协议 — Agent 用 JSON 描述 UI', usageHint: 'h2'}}},
        {id: 'd1', component: {Text: {text: '这是由 Agent 通过 A2UI 协议动态渲染的内容。'}}}
      ]
    }, null, 2);
  }
}
