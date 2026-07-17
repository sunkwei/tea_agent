
(function(){
'use strict';

/* ═══════════════════════════════════════════════════════
   Tea Agent GUI2 — Core Application Script
   ═══════════════════════════════════════════════════════ */

// ── State ──
let currentTopicId = null;
let isStreaming = false;
let abortController = null;
let _taskPanelOpen = false;
let _taskPanelSuppressAutoOpen = false;
let _pendingUsage = null;
let _activeTheme = localStorage.getItem('ta-theme') || 'dark';
let _pendingImages = [];
let _userNearBottom = true;
let _toolCallState = null; // tool call tracking during streaming
let _messageQueue = []; // 排队消息队列：isStreaming 时入队，生成完后自动发送
let _streamGeneration = 0; // 递增标记，防止过期流的 finally 干扰新流

// ── 后台处理轮询 ──
let _backgroundPollTimer = null; // polling interval id
let _backgroundPollTopic = null; // topic being polled

// ── Queue List Render ──
function renderQueueList() {
  const container = $('queue-list');
  if (!container) return;
  if (_messageQueue.length === 0) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = _messageQueue.map(function(item, i) {
    let preview = item.text || '(图片)';
    if (preview.length > 28) preview = preview.slice(0, 28) + '…';
    return '<span class="queue-item" title="' + esc(item.text || '(图片)') + '">'
      + '<span class="q-text">' + esc(preview) + '</span>'
      + '<button class="q-cancel" onclick="cancelQueuedMessage(' + i + ')" title="取消排队">✕</button>'
      + '</span>';
  }).join('');
}

// ── Cancel Single Queued Message ──
window.cancelQueuedMessage = function(index) {
  if (index < 0 || index >= _messageQueue.length) return;
  const removed = _messageQueue[index];
  _messageQueue.splice(index, 1);
  renderQueueList();
  // 更新按钮显示
  const sendBtn = $('send-btn');
  if (_messageQueue.length > 0) {
    sendBtn.textContent = '⏳ 排队 ' + _messageQueue.length;
    sendBtn.className = 'btn btn-p warning';
  } else {
    sendBtn.textContent = '⏹ 中断';
    sendBtn.className = 'btn btn-p danger';
  }
  toast('🗑 已取消: ' + (removed.text || '(图片)'), 'success');
};

// ── DOM Helpers ──
const $ = id => document.getElementById(id);
const esc = t => { if (!t) return ''; const d = document.createElement('div'); d.textContent = t; return d.innerHTML; };
const escAttr = t => String(t).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

// ── 标题管理 ──
/** 同步设置工具栏标题 + 浏览器标签页标题 */
function setTitle(title) {
  $('tt').textContent = title;
  document.title = title;
}
/** 标记当前对话已完成（浏览器标签页追加"(已完成)"，幂等） */
function markTitleDone() {
  const tt = $('tt');
  if (!tt || !tt.textContent) return;
  const base = tt.textContent.replace(/\(已完成\)$/, '');
  document.title = base + '(已完成)';
}
/** 清除浏览器标题的"(已完成)"后缀（仅影响浏览器标签页，不修改工具栏标题） */
function clearTitleDone() {
  const cur = document.title;
  const clean = cur.replace(/\(已完成\)$/, '');
  if (clean !== cur) document.title = clean;
}

function showModal(id) { $(id).classList.add('open'); }
function closeModal(id) { $(id).classList.remove('open'); }
// Close modals on Escape
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal.open').forEach(m => closeModal(m.id));
  }
});

// ── Toast ──
function toast(msg, type) {
  let el = $('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.background = type === 'error' ? 'rgba(248,81,73,.9)' : type === 'success' ? 'rgba(63,185,80,.9)' : 'rgba(88,166,255,.9)';
  el.style.opacity = '1';
  setTimeout(() => { el.style.opacity = '0'; }, 2500);
}

// ── Theme ──
function applyTheme() {
  const t = _activeTheme;
  document.documentElement.setAttribute('data-theme', t);
  const btn = $('theme-btn');
  if (btn) btn.textContent = t === 'dark' ? '🌙' : '☀️';
  localStorage.setItem('ta-theme', t);
}
window.toggleTheme = function() {
  _activeTheme = _activeTheme === 'dark' ? 'light' : 'dark';
  applyTheme();
};
applyTheme();

// ── Smart Scrolling ──
function _isNearBottom() {
  const m = $('msgs');
  if (!m) return true;
  return m.scrollHeight - m.scrollTop - m.clientHeight < 100;
}
function scrollBottom() {
  if (!_userNearBottom) return;
  const m = $('msgs');
  if (!m) return;
  m.scrollTop = m.scrollHeight;
}
// Track user scroll position
$('msgs').addEventListener('scroll', function() {
  _userNearBottom = _isNearBottom();
});

// ── Keyboard Shortcuts ──
document.addEventListener('keydown', function(e) {
  // Don't trigger shortcuts when typing in input or modals
  const tag = e.target.tagName;
  const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

  if (e.ctrlKey && e.key === 'n') {
    e.preventDefault(); newTopic();
  } else if (e.ctrlKey && e.key === 'k') {
    e.preventDefault(); showSearchModal();
  } else if (e.ctrlKey && e.key === 'j') {
    e.preventDefault(); toggleTaskPanel();
  } else if (e.ctrlKey && e.key === 'M' && e.shiftKey) {
    e.preventDefault(); showMemoryModal();
  } else if (e.key === 'Escape' && isStreaming) {
    e.preventDefault(); interruptChat();
  }
});

// ═══════════════════════════════════════════════
//  SLASH COMMAND MENU — 输入 "/" 弹出候选命令
// ═══════════════════════════════════════════════

const _slashCommands = [
  { name: '/help',       icon: '❓', desc: '显示快捷键帮助',         action: 'showHelp' },
  { name: '/new',        icon: '➕', desc: '新对话',                 action: 'newTopic' },
  { name: '/clear',      icon: '🗑', desc: '清空当前对话',           action: 'clearChat' },
  { name: '/review',     icon: '🔎', desc: '代码审查 — 审查指定文件', action: 'review' },
  { name: '/explain',    icon: '📖', desc: '解释代码 — 解释文件/代码片段', action: 'explain' },
  { name: '/refactor',   icon: '🔧', desc: '重构建议 — 分析重构方案', action: 'refactor' },
  { name: '/search',     icon: '🔍', desc: '搜索对话和记忆',         action: 'search', shortcut: 'Ctrl+K' },
  { name: '/memory',     icon: '🧠', desc: '管理长期记忆',           action: 'memory', shortcut: 'Ctrl+Shift+M' },
  { name: '/task',       icon: '📋', desc: '任务面板 (Plan/TODO)',   action: 'task',   shortcut: 'Ctrl+J' },
  { name: '/export',     icon: '📄', desc: '导出 PDF',               action: 'export' },
  { name: '/config',     icon: '⚙',  desc: '查看/切换配置',         action: 'config' },
  { name: '/theme',      icon: '🌙', desc: '切换深色/浅色主题',      action: 'theme' },
  { name: '/screenshot', icon: '📷', desc: '全屏截图发送',           action: 'screenshot' },
  { name: '/plan',       icon: '📋', desc: '创建/查看执行计划',      action: 'plan' },
  { name: '/todo',       icon: '✅', desc: '查看待办清单',           action: 'todo' },
  { name: '/status',     icon: '📊', desc: '查看系统状态与模型信息',  action: 'status' },
  { name: '/reload',     icon: '🔄', desc: '重新加载工具（新能力）',  action: 'reload' },
  { name: '/models',     icon: '🤖', desc: '查看当前加载的模型',     action: 'models' },
];

let _cmdMenuActive = -1;   // 当前高亮索引
let _cmdMenuVisible = false;

function _getCmdInput() {
  const el = $('ci');
  const val = el ? el.value : '';
  // 只在输入框开头是 "/" 且没有空格时触发（单命令模式）
  const match = val.match(/^(\/\S*)$/);
  return match ? match[1] : null;
}

function _filterCommands(query) {
  if (!query || query === '/') return _slashCommands;
  const q = query.toLowerCase();
  return _slashCommands.filter(function(cmd) {
    return cmd.name.toLowerCase().startsWith(q) || cmd.name.toLowerCase().indexOf(q) > 0;
  });
}

function _renderCmdMenu(filtered) {
  let menu = $('cmd-menu');
  if (!menu) {
    menu = document.createElement('div');
    menu.id = 'cmd-menu';
    menu.className = 'cmd-menu';
    $('ia').appendChild(menu);
  }

  if (!filtered || filtered.length === 0) {
    menu.innerHTML = '<div class="cmd-no-results">没有匹配的命令</div>';
    menu.classList.add('show');
    _cmdMenuActive = -1;
    _cmdMenuVisible = true;
    return;
  }

  let html = '<div class="cmd-menu-header">命令</div>';
  filtered.forEach(function(cmd, i) {
    const active = i === _cmdMenuActive ? ' active' : '';
    const sc = cmd.shortcut ? '<span class="cmd-item-shortcut">' + cmd.shortcut + '</span>' : '';
    html += '<div class="cmd-item' + active + '" data-index="' + i + '" onmouseenter="_cmdMenuActive=' + i + ';document.querySelector(\'.cmd-item.active\')?.classList.remove(\'active\');this.classList.add(\'active\');" onclick="_execSlashCmd(\'' + cmd.name + '\')">'
      + '<span class="cmd-item-icon">' + cmd.icon + '</span>'
      + '<span class="cmd-item-text">'
      + '<div class="cmd-item-name">' + esc(cmd.name) + '</div>'
      + '<div class="cmd-item-desc">' + esc(cmd.desc) + '</div>'
      + '</span>'
      + sc
      + '</div>';
  });
  menu.innerHTML = html;
  menu.classList.add('show');
  _cmdMenuVisible = true;
}

function _closeCmdMenu() {
  const menu = $('cmd-menu');
  if (menu) menu.classList.remove('show');
  _cmdMenuVisible = false;
  _cmdMenuActive = -1;
}

/** 执行斜杠命令 */
function _execSlashCmd(cmdName) {
  _closeCmdMenu();
  const input = $('ci');
  if (input) {
    input.value = '';
    input.style.height = 'auto';
    $('send-btn').disabled = true;
  }

  const cmd = _slashCommands.find(function(c) { return c.name === cmdName; });
  if (!cmd) return;

  switch (cmd.action) {
    case 'showHelp':
      // 在消息区域显示快捷键列表
      const helpMsg = '**📖 Tea Agent GUI 快捷键**\n\n'
        + '| 快捷键 | 功能 |\n|--------|------|\n'
        + '| `Enter` | 发送消息 |\n| `Shift+Enter` | 换行 |\n'
        + '| `Ctrl+N` | 新对话 |\n| `Ctrl+K` | 搜索 |\n'
        + '| `Ctrl+Shift+M` | 记忆管理 |\n| `Ctrl+J` | 任务面板 |\n'
        + '| `Escape` | 中断/关闭 |\n\n'
        + '可用斜杠命令：\n'
        + _slashCommands.map(function(c) {
            const sc = c.shortcut ? ' (' + c.shortcut + ')' : '';
            return '- `' + c.name + '` — ' + c.desc + sc;
          }).join('\n');
      addMessage('assistant', helpMsg);
      toast('📖 已显示帮助信息', 'success');
      break;
    case 'newTopic':
      window.newTopic();
      break;
    case 'clearChat':
      window.clearChat();
      break;
    case 'search':
      window.showSearchModal();
      break;
    case 'memory':
      window.showMemoryModal();
      break;
    case 'task':
      window.toggleTaskPanel();
      break;
    case 'export':
      window.showExportModal();
      break;
    case 'config':
      window.showConfigModal();
      break;
    case 'theme':
      window.toggleTheme();
      break;
    case 'screenshot':
      // 直接触发全屏截图
      window.captureFullScreen();
      break;
    case 'review': {
      // 弹出 prompt 让用户输入文件路径
      const reviewPath = prompt('🔎 代码审查 — 输入文件路径（或粘贴代码）：', '');
      if (reviewPath) {
        _closeCmdMenu();
        $('ci').value = '请审查以下代码：\n\n' + reviewPath;
        $('ci').style.height = 'auto';
        $('ci').style.height = Math.min($('ci').scrollHeight, 120) + 'px';
        $('send-btn').disabled = false;
        toast('🔎 补充说明后按 Enter 发送', 'info');
      }
      break;
    }
    case 'explain': {
      const explainPath = prompt('📖 解释代码 — 输入文件路径（或粘贴代码片段）：', '');
      if (explainPath) {
        _closeCmdMenu();
        $('ci').value = '请解释以下代码的工作原理：\n\n' + explainPath;
        $('ci').style.height = 'auto';
        $('ci').style.height = Math.min($('ci').scrollHeight, 120) + 'px';
        $('send-btn').disabled = false;
        toast('📖 补充问题后按 Enter 发送', 'info');
      }
      break;
    }
    case 'refactor': {
      const refactorPath = prompt('🔧 重构建议 — 输入文件路径（或粘贴代码）：', '');
      if (refactorPath) {
        _closeCmdMenu();
        $('ci').value = '请为以下代码提供重构建议：\n\n' + refactorPath;
        $('ci').style.height = 'auto';
        $('ci').style.height = Math.min($('ci').scrollHeight, 120) + 'px';
        $('send-btn').disabled = false;
        toast('🔧 补充要求后按 Enter 发送', 'info');
      }
      break;
    }
    case 'status':
      // 发消息询问状态（AI 会调用 system tools 返回真实信息）
      $('ci').value = '/status';
      sendMessage();
      toast('📊 正在获取系统状态...', 'info');
      break;
    case 'reload':
      $('ci').value = '请执行 toolkit_reload() 重新加载工具';
      sendMessage();
      toast('🔄 已发送重载指令', 'info');
      break;
    case 'models':
      $('ci').value = '/models';
      sendMessage();
      toast('🤖 正在获取模型信息...', 'info');
      break;
    case 'plan':
      window.toggleTaskPanel();
      toast('📋 请在任务面板查看 Plan', 'info');
      break;
    case 'todo':
      window.toggleTaskPanel();
      toast('✅ 请在任务面板查看 TODO', 'info');
      break;
    default:
      break;
  }
}

// ── Input handler (值变化后触发，解决 / 敲完不弹菜单) ──
window.onInput = function(e) {
  const val = e.target.value;
  // 刚输入 "/" 时立即展示菜单（不依赖 setTimeout）
  if (val === '/') {
    _cmdMenuActive = -1;
    _renderCmdMenu(_slashCommands);
    _cmdMenuVisible = true;
    return;
  }
  // 已输入 /xxx，更新过滤
  if (val.startsWith('/') && !val.includes(' ')) {
    _cmdMenuActive = -1;
    _renderCmdMenu(_filterCommands(val));
    _cmdMenuVisible = true;
    return;
  }
  // 非命令模式
  if (_cmdMenuVisible) _closeCmdMenu();
};

// ── Keydown handler (Enter/Send/Arrow keys) ──
window.onInputKeydown = function(e) {
  const el = e.target;
  const val = el.value;
  const isCmdMode = /^\/\S*$/.test(val);

  // ── 斜杠命令模式 ──
  if (isCmdMode) {
    const query = _getCmdInput();
    if (query !== null) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const filtered = _filterCommands(query);
        if (filtered.length === 0) return;
        _cmdMenuActive = Math.min(_cmdMenuActive + 1, filtered.length - 1);
        _renderCmdMenu(filtered);
        // 确保高亮项可见
        const activeEl = document.querySelector('.cmd-item.active');
        if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        const filtered = _filterCommands(query);
        if (filtered.length === 0) return;
        _cmdMenuActive = Math.max(_cmdMenuActive - 1, 0);
        _renderCmdMenu(filtered);
        const activeEl = document.querySelector('.cmd-item.active');
        if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const filtered = _filterCommands(query);
        if (_cmdMenuActive >= 0 && _cmdMenuActive < filtered.length) {
          _execSlashCmd(filtered[_cmdMenuActive].name);
          return;
        }
        // 如果没选中但输入了完整命令，也尝试执行
        const exact = _slashCommands.find(function(c) { return c.name === val.trim(); });
        if (exact) {
          _execSlashCmd(exact.name);
          return;
        }
        // 否则当作普通消息发送
        _closeCmdMenu();
        sendMessage();
        return;
      }
      if (e.key === 'Escape') {
        _closeCmdMenu();
        e.preventDefault();
        return;
      }
      if (e.key === 'Tab') {
        e.preventDefault();
        const filtered = _filterCommands(query);
        if (filtered.length === 1 && filtered[0].name !== val.trim()) {
          // 自动补全唯一匹配
          el.value = filtered[0].name;
          el.style.height = 'auto';
          el.style.height = Math.min(el.scrollHeight, 120) + 'px';
        }
        return;
      }
      // 输入字符时更新过滤
      setTimeout(function() {
        const newQuery = _getCmdInput();
        if (newQuery !== null) {
          _cmdMenuActive = -1;
          _renderCmdMenu(_filterCommands(newQuery));
        } else {
          _closeCmdMenu();
        }
      }, 0);
    }
  } else if (val.indexOf('/') === 0 && e.key === 'Backspace' && val.length === 1) {
    // 只剩下 "/" 时退格 → 关闭菜单
    _closeCmdMenu();
  } else {
    // 非命令模式，关闭菜单
    _closeCmdMenu();
  }

  // ── Enter 发送 (非命令模式) ──
  if (e.key === 'Enter' && !e.shiftKey && !isCmdMode) {
    e.preventDefault();
    sendMessage();
  }

  // Auto-resize
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  // Enable/disable send button
  $('send-btn').disabled = !el.value.trim() && _pendingImages.length === 0;
};

// 点击其他地方关闭命令菜单
document.addEventListener('click', function(e) {
  if (!e.target.closest('#ci') && !e.target.closest('#cmd-menu')) {
    _closeCmdMenu();
  }
});

// ── Screenshot ──
window.toggleScreenshotMenu = function(e) {
  e.stopPropagation();
  const menu = $('ss-menu');
  if (!menu) return;
  menu.classList.toggle('show');
};
document.addEventListener('click', function(e) {
  const menu = $('ss-menu');
  if (menu && !e.target.closest('.ss-dropup')) menu.classList.remove('show');
});
window.captureFullScreen = async function() {
  $('ss-menu').classList.remove('show');
  const btn = $('ss-btn'); btn.textContent = '⏳'; btn.disabled = true;
  try {
    const res = await fetch('/api/screenshot/full');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const d = await res.json();
    if (!d.ok) throw new Error(d.error || '截图失败');
    _pendingImages.push('data:image/png;base64,' + d.image_base64);
    updateImagePreview();
  } catch(e) {
    alert('截图失败: ' + e.message);
  } finally {
    btn.textContent = '📷'; btn.disabled = false;
  }
};
window.captureInteractive = async function() {
  $('ss-menu').classList.remove('show');
  const btn = $('ss-btn'); btn.textContent = '⏳'; btn.disabled = true;
  try {
    const res = await fetch('/api/screenshot/interactive', { method: 'POST' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const d = await res.json();
    if (!d.ok) throw new Error(d.error || '截图失败');
    _pendingImages.push('data:image/png;base64,' + d.image_base64);
    updateImagePreview();
  } catch(e) {
    alert('截图失败: ' + e.message);
  } finally {
    btn.textContent = '📷'; btn.disabled = false;
  }
};

// ── Image Upload ──
window.onFilesSelected = function(e) {
  const files = e.target.files;
  for (const f of files) {
    if (!f.type.startsWith('image/')) continue;
    const reader = new FileReader();
    reader.onload = function(ev) {
      _pendingImages.push(ev.target.result);
      updateImagePreview();
    };
    reader.readAsDataURL(f);
  }
  e.target.value = '';
};
// Paste image support
$('ci').addEventListener('paste', function(e) {
  const items = e.clipboardData && e.clipboardData.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      const file = item.getAsFile();
      const reader = new FileReader();
      reader.onload = function(ev) {
        _pendingImages.push(ev.target.result);
        updateImagePreview();
      };
      reader.readAsDataURL(file);
      return;
    }
  }
});
function updateImagePreview() {
  const area = $('img-preview-area');
  if (!area) return;
  if (_pendingImages.length === 0) { area.innerHTML = ''; return; }
  area.innerHTML = _pendingImages.map((img, i) =>
    '<div class="img-preview-item"><img src="' + img + '" onclick="window.openImageOverlay(this.src)"><button class="remove-img" onclick="removeImage(' + i + ')">✕</button></div>'
  ).join('');
  $('send-btn').disabled = !$('ci').value.trim() && _pendingImages.length === 0;
}
window.removeImage = function(i) {
  _pendingImages.splice(i, 1);
  updateImagePreview();
};
window.openImageOverlay = function(src) {
  const overlay = document.createElement('div');
  overlay.className = 'img-overlay';
  overlay.innerHTML = '<img src="' + src + '">';
  overlay.addEventListener('click', function() { overlay.remove(); });
  document.body.appendChild(overlay);
};

// ══════════════════════════════════════════════════
//  ADD MESSAGE — with Markdown formatting
// ══════════════════════════════════════════════════

let _msgCounter = 0; // 全局递增消息计数器

function addMessage(role, content, images) {
  const welcome = document.querySelector('.welcome');
  if (welcome) welcome.remove();

  const div = document.createElement('div');
  div.className = 'msg ' + (role === 'user' ? 'user' : 'assistant');
  div.dataset.msgIdx = _msgCounter++; // 给每条消息一个唯一递增索引

  let html = '<div class="msg-label">' + (role === 'user' ? '你' : 'Tea Agent') + '</div>';
  html += '<div class="msg-bubble">';

  // Images
  if (images && images.length > 0) {
    html += '<div class="msg-images">';
    images.forEach(function(img) {
      html += '<img src="' + esc(img) + '" onclick="window.openImageOverlay(this.src)">';
    });
    html += '</div>';
  }

  // Markdown formatted content (only for assistant messages; user messages are plain)
  if (role === 'assistant') {
    html += formatMarkdown(content || '');
  } else {
    html += esc(content || '');
  }
  html += '</div>';
  div.innerHTML = html;
  $('msgs').appendChild(div);
  scrollBottom();
  return div.querySelector('.msg-bubble');
}

function addLoading() {
  const welcome = document.querySelector('.welcome');
  if (welcome) welcome.remove();
  const div = document.createElement('div');
  div.className = 'loading-indicator';
  div.id = 'loading-indicator';
  div.innerHTML = '<div class="spinner"></div><span>思考中...</span>';
  $('msgs').appendChild(div);
  scrollBottom();
}
function removeLoading() {
  const el = $('loading-indicator');
  if (el) el.remove();
}

// ── 历史会话跳转栏 ──
/**
 * 渲染跳转栏：遍历 #msgs 中的 .msg.user，生成可点击的 chip
 * 每个 chip 显示用户消息的前 20 字摘要，点击滚动到对应消息
 */
function renderJumpBar() {
  const bar = document.getElementById('jump-bar');
  if (!bar) return;
  const userMsgs = document.querySelectorAll('#msgs .msg.user');
  // 少于 2 条用户消息时隐藏跳转栏
  if (userMsgs.length < 2) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = '';
  let html = '<span class="jump-bar-label">📜 跳转</span>';
  userMsgs.forEach(function(msg) {
    const idx = msg.dataset.msgIdx;
    // 提取消息文本摘要（前 20 字）
    const bubble = msg.querySelector('.msg-bubble');
    let snippet = '';
    if (bubble) {
      snippet = bubble.textContent.replace(/\s+/g, ' ').trim();
    }
    // 去掉图片占位文字，截取前 20 字
    snippet = snippet.replace(/\(图片\)/g, '').trim();
    if (snippet.length > 20) snippet = snippet.slice(0, 20) + '…';
    if (!snippet) snippet = '(图片)';
    html += '<span class="jump-chip" onclick="jumpToMessage(' + idx + ')" title="' + escAttr(bubble ? bubble.textContent.trim().slice(0, 60) : '') + '">'
      + esc(snippet) + '</span>';
  });
  bar.innerHTML = html;
}

/** 滚动到指定 data-msg-idx 的消息 */
window.jumpToMessage = function jumpToMessage(idx) {
  const el = document.querySelector('.msg[data-msg-idx="' + idx + '"]');
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  // 高亮闪烁效果
  el.classList.add('jump-highlight');
  setTimeout(function() { el.classList.remove('jump-highlight'); }, 1500);
}

// ══════════════════════════════════════════════════
//  FORMAT MARKDOWN
// ══════════════════════════════════════════════════

function formatMarkdown(text) {
  if (!text) return '';
  let html = esc(text).replace(/\r\n/g, '\n');

  // Protect code blocks
  const codeBlocks = [];
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function(match, lang, code) {
    const idx = codeBlocks.length;
    const langLabel = lang ? '<span class="code-lang">' + esc(lang) + '</span>' : '';
    const trimmedCode = code.trimEnd();
    codeBlocks.push(
      '<div class="code-block-wrapper">'
      + '<div class="code-block-header">'
      + langLabel
      + '<button class="copy-btn" onclick="copyCode(this)" data-code="' + escAttr(trimmedCode) + '">📋 复制</button>'
      + '</div>'
      + '<pre><code class="lang-' + esc(lang) + '">' + esc(trimmedCode) + '</code></pre>'
      + '</div>'
    );
    return '\x00CODE' + idx + '\x00';
  });

  // Inline code — 直接渲染原文，不做占位符保护
  html = html.replace(/`([^`]+)`/g, function(match, code) {
    return '<code class="md-inline-code">' + esc(code) + '</code>';
  });

  // 🆕 Protect existing markdown links [text](url) from URL auto-linking
  const mdLinks = [];
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, text, url) {
    const idx = mdLinks.length;
    mdLinks.push('<a class="md-link" href="' + escAttr(url) + '" target="_blank" rel="noopener">' + text + '</a>');
    return '\x00MDLINK' + idx + '\x00';
  });

  // 🆕 URL auto-linking — convert bare URLs to clickable links
  html = html.replace(/(https?:\/\/[^\s<>"']+)/g, function(match, url) {
    return '<a class="md-link md-autolink" href="' + escAttr(url) + '" target="_blank" rel="noopener">' + url + '</a>';
  });

  // 🆕 Restore protected markdown links
  html = html.replace(/\x00MDLINK(\d+)\x00/g, function(m, idx) { return mdLinks[idx] || ''; });

  // 🆕 #topic:UUID — convert to clickable topic link (e.g. #topic:abc12345-...)
  html = html.replace(/#topic:([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/gi, function(match, uuid) {
    return '<a class="md-link md-topic-link" href="#" data-topic="' + uuid + '" onclick="openTopic(\'' + uuid + '\',\'\')">📌 ' + uuid.slice(0, 8) + '</a>';
  });

  // Headers
  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h5">$1</h5>');
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>');

  // Tables
  const tableBlocks = [];
  html = html.replace(/^\|(.+)\|[ \t]*[\r\n]+\|[\-:|\s]+\|[ \t]*[\r\n]+((?:^\|.+\|[ \t]*[\r\n]?)+)/gm, function(match, headerRow, bodyRows) {
    const h = headerRow.split('|').map(function(c, i) { return '<th>' + c.trim() + '</th>'; }).join('');
    const rows = bodyRows.trim().split('\n').map(function(line) {
      const cells = line.replace(/^\||\|$/g, '').split('|').map(function(c) { return '<td>' + c.trim() + '</td>'; }).join('');
      return '<tr>' + cells + '</tr>';
    }).join('');
    const idx = tableBlocks.length;
    tableBlocks.push('<table class="md-table"><thead><tr>' + h + '</tr></thead><tbody>' + rows + '</tbody></table>');
    return '\x00TABLE' + idx + '\x00';
  });

  // Lists (unordered)
  const listBlocks = [];
  html = html.replace(/^(\s*[-*+]\s+.+(?:\n\s*[-*+]\s+.+)*)$/gm, function(match) {
    const items = match.split('\n').map(function(line) {
      return '<li class="md-li">' + line.replace(/^\s*[-*+]\s+/, '') + '</li>';
    }).join('');
    const idx = listBlocks.length;
    listBlocks.push('<ul class="md-ul">' + items + '</ul>');
    return '\x00ULIST' + idx + '\x00';
  });
  // Lists (ordered)
  html = html.replace(/^(\s*\d+\.\s+.+(?:\n\s*\d+\.\s+.+)*)$/gm, function(match) {
    const items = match.split('\n').map(function(line) {
      return '<li class="md-li">' + line.replace(/^\s*\d+\.\s+/, '') + '</li>';
    }).join('');
    const idx = listBlocks.length;
    listBlocks.push('<ol class="md-ol">' + items + '</ol>');
    return '\x00OLIST' + idx + '\x00';
  });

  // Blockquotes
  html = html.replace(/^&gt;\s(.+)$/gm, '<blockquote class="md-blockquote">$1</blockquote>');
  // Horizontal rules
  html = html.replace(/^---$/gm, '<hr class="md-hr">');

  // Convert newlines to <br>
  html = html.replace(/\n/g, '<br>');

  // Bold, italic, strikethrough (links already handled above)
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="md-strong">$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em class="md-em">$1</em>');
  html = html.replace(/~~([^~]+)~~/g, '<del class="md-del">$1</del>');

  // Restore tables
  html = html.replace(/\x00TABLE(\d+)\x00/g, function(m, idx) { return tableBlocks[idx] || ''; });
  // Restore lists
  html = html.replace(/\x00ULIST(\d+)\x00/g, function(m, idx) { return listBlocks[idx] || ''; });
  html = html.replace(/\x00OLIST(\d+)\x00/g, function(m, idx) { return listBlocks[idx] || ''; });
  // Restore code blocks
  html = html.replace(/\x00CODE(\d+)\x00/g, function(m, idx) { return codeBlocks[idx] || ''; });

  // 🆕 Download link icons — add emoji icon for .zip/.exe/.pdf/.7z/.rar/.msi/.dmg/.apk/.tar.gz
  html = html.replace(/(<a\s[^>]*href="[^"]*\.(zip|exe|pdf|7z|rar|msi|dmg|apk|tar\.gz)"[^>]*>)([\s\S]*?)(<\/a>)/gi, function(match, openTag, ext, text, closeTag) {
    const icons = { zip: '📦', exe: '⚙️', pdf: '📄', '7z': '📦', rar: '📦', msi: '⚙️', dmg: '💿', apk: '📱', 'tar.gz': '📦' };
    const icon = icons[ext.toLowerCase()] || '📎';
    return openTag + icon + ' ' + text + closeTag;
  });

  return html;
}

// ── Copy Code Button ──
window.copyCode = function(btn) {
  const code = btn.getAttribute('data-code');
  if (!code) return;
  navigator.clipboard.writeText(code).then(function() {
    btn.textContent = '✅ 已复制';
    setTimeout(function() { btn.textContent = '📋 复制'; }, 2000);
  }).catch(function() {
    const ta = document.createElement('textarea');
    ta.value = code;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    btn.textContent = '✅ 已复制';
    setTimeout(function() { btn.textContent = '📋 复制'; }, 2000);
  });
};

// ══════════════════════════════════════════════════
//  SSE CHAT — Rich Event Stream
// ══════════════════════════════════════════════════

// Interrupt current chat
window.interruptChat = async function() {
  // 清空排队消息
  if (_messageQueue.length > 0) {
    _messageQueue = [];
    renderQueueList();
    toast('🛑 已清空排队消息', 'error');
  }
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
  if (currentTopicId) {
    try {
      await fetch('/api/chat/abort', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic_id: currentTopicId }),
        signal: AbortSignal.timeout(3000),
      });
    } catch(e) { /* ignore */ }
  }
  removeLoading();
  const bubbleText = document.getElementById('bubble-text');
  if (bubbleText && !bubbleText.innerHTML.trim()) {
    bubbleText.innerHTML = '(已中断)';
  }
};

// ── Helper: 流式生成中入队排队 ──
function _enqueueMessage(msg, images) {
  _messageQueue.push({ text: msg, images: [...images] });
  _pendingImages = [];
  updateImagePreview();
  renderQueueList();
  const qlen = _messageQueue.length;
  const sendBtn = $('send-btn');
  sendBtn.textContent = `⏳ 排队 ${qlen}`;
  sendBtn.className = 'btn btn-p warning';
  sendBtn.disabled = false;
  toast(`⏳ 消息已排队（队列中 ${qlen} 条）`, 'success');
}

// ── Helper: 创建流式消息容器和状态对象 ──
function _createStreamState() {
  const agentDiv = document.createElement('div');
  agentDiv.className = 'msg assistant';
  agentDiv.id = 'current-ai-msg';
  agentDiv.innerHTML = '<div class="msg-label">Tea Agent</div><div class="msg-bubble" id="ai-bubble"><div id="bubble-text"></div></div>';
  $('msgs').appendChild(agentDiv);
  scrollBottom();
  return {
    bubbleText: $('bubble-text'),
    fullText: '',
    thinkContainer: null,
    thinkSummary: null,
    thinkList: null,
    thinkContent: null,
    thinkCount: 0,
    toolCallContainer: null,
    toolCallList: null,
    toolCallSummary: null,
    toolCallBadge: null,
    toolCallCount: 0,
    toolDoneCount: 0,
    activeToolItem: null,
  };
}

// ── Helper: 流结束后清理并发送排队消息 ──
function _processQueueAfterStream() {
  if (_pendingUsage) {
    updateUsage(_pendingUsage);
    _pendingUsage = null;
  }
  // 清理 DOM ID，避免下一轮消息 ID 重复
  const oldMsg = $('current-ai-msg');
  if (oldMsg) {
    oldMsg.removeAttribute('id');
    const ob = oldMsg.querySelector('#ai-bubble');
    if (ob) ob.removeAttribute('id');
    const ot = oldMsg.querySelector('#bubble-text');
    if (ot) ot.removeAttribute('id');
  }
  const btn = $('send-btn');
  if (_messageQueue.length > 0) {
    const next = _messageQueue.shift();
    renderQueueList();
    const input = $('ci');
    input.value = next.text;
    input.style.height = 'auto';
    _pendingImages = next.images || [];
    updateImagePreview();
    const qlen = _messageQueue.length;
    btn.textContent = qlen > 0 ? `⏳ 排队 ${qlen}` : '⏳ 发送中...';
    btn.className = qlen > 0 ? 'btn btn-p warning' : 'btn btn-p';
    btn.disabled = false;
    sendMessage();
    return;
  }
  btn.textContent = '发送';
  btn.className = 'btn btn-p';
  btn.disabled = false;
  $('ci').focus();
  refreshTopics();
  refreshTaskPanel();
}

window.sendMessage = async function() {
  // 如果正在生成中 → 入队排队，不中断
  if (isStreaming) {
    const input = $('ci');
    const msg = input.value.trim();
    if (!msg && _pendingImages.length === 0) return;
    input.value = '';
    input.style.height = 'auto';
    _enqueueMessage(msg, _pendingImages);
    return;
  }

  // 如果后台轮询还在运行，停止它（用户发新消息了，不再需要轮询旧流）
  _stopBackgroundPoll();

  const input = $('ci');
  const msg = input.value.trim();
  if (!msg && _pendingImages.length === 0) return;
  input.value = '';

  // Show user message
  addMessage('user', msg || '(图片)', _pendingImages.length > 0 ? _pendingImages : null);
  renderJumpBar(); // 用户发出消息后立即更新跳转栏
  clearTitleDone(); // 新会话开始，移除旧(已完成)后缀
  addLoading();

  // Collect images
  const imagesToSend = [..._pendingImages];
  _pendingImages = [];
  updateImagePreview();

  // Create assistant message container and state
  const s = _createStreamState();
  _streamGeneration++;
  const myGen = _streamGeneration;
  isStreaming = true;
  _pendingUsage = null;

  // Hide old usage bar
  const oldUsageBar = $('usage-bar');
  if (oldUsageBar) oldUsageBar.style.display = 'none';

  // 立即在 topic 列表显示转圈圈（当前主题正在对话中）
  refreshTopics();

  abortController = new AbortController();

  // Update send button to interrupt
  const sendBtn = $('send-btn');
  sendBtn.textContent = '⏹ 中断';
  sendBtn.className = 'btn btn-p danger';
  sendBtn.disabled = false;

  try {
    const body = { message: msg, topic_id: currentTopicId };
    if (imagesToSend.length > 0) body.images = imagesToSend;
    // Include current config path if set
    const cfgSel = $('config-dropdown');
    if (cfgSel && cfgSel.value) body.config_path = cfgSel.value;

    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: abortController.signal,
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const slines = buf.split('\n');
      for (let i = 0; i < slines.length - 1; i++) {
        const line = slines[i].trim();
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          switch (data.type) {

            case 'token':
              removeLoading();
              s.fullText += data.text;
              s.bubbleText.innerHTML = esc(s.fullText);
              break;

            case 'think_start':
              if (!s.thinkContainer) {
                // 创建容器（类似 tool-call-container）
                s.thinkContainer = document.createElement('div');
                s.thinkContainer.className = 'think-container collapsed';
                s.bubbleText.parentNode.insertBefore(s.thinkContainer, s.bubbleText);
                // 折叠式摘要栏
                s.thinkSummary = document.createElement('div');
                s.thinkSummary.className = 'think-summary';
                s.thinkSummary.innerHTML = '<span class="think-summary-icon">🧠</span>'
                  + '<span class="think-summary-label">思考过程</span>'
                  + '<span class="think-summary-badge" id="think-badge">0</span>'
                  + '<span class="think-summary-arrow">▸</span>';
                s.thinkSummary.addEventListener('click', function() {
                  var list = s.thinkContainer.querySelector('.think-list');
                  if (list) {
                    var expanded = list.style.display !== 'none';
                    list.style.display = expanded ? 'none' : '';
                    s.thinkContainer.classList.toggle('collapsed', expanded);
                    s.thinkSummary.querySelector('.think-summary-arrow').textContent = expanded ? '▸' : '▾';
                  }
                });
                s.thinkContainer.appendChild(s.thinkSummary);
                // 列表容器
                s.thinkList = document.createElement('div');
                s.thinkList.className = 'think-list';
                s.thinkList.style.display = 'none'; // 默认折叠
                s.thinkContainer.appendChild(s.thinkList);
              }
              // 每次新的思考轮次创建独立条目
              s.thinkCount++;
              var badge = s.thinkContainer.querySelector('.think-summary-badge');
              if (badge) badge.textContent = s.thinkCount;
              var entry = document.createElement('details');
              entry.className = 'think-entry';
              entry.innerHTML = '<summary>思考 #' + s.thinkCount + '</summary><div class="think-content"></div>';
              s.thinkList.appendChild(entry);
              s.thinkContent = entry.querySelector('.think-content');
              break;

            case 'think':
              if (s.thinkContent) {
                s.thinkContent.textContent += data.text;
              }
              break;

            case 'think_done':
              // 更新最后一个 thinking 条目的 summary，显示前32字符预览
              if (s.thinkList) {
                var lastEntry = s.thinkList.querySelector('.think-entry:last-child');
                if (lastEntry) {
                  var summary = lastEntry.querySelector('summary');
                  var content = lastEntry.querySelector('.think-content');
                  if (summary) {
                    var preview = content ? content.textContent.trim().replace(/\s+/g, ' ').substring(0, 32) : '';
                    if (preview) preview = '：' + preview;
                    summary.textContent = '思考 #' + s.thinkCount + ' 完成' + preview;
                  }
                }
              }
              break;

            case 'tool_start': {
              removeLoading();
              if (!s.toolCallContainer) {
                s.toolCallContainer = document.createElement('div');
                s.toolCallContainer.className = 'tool-call-container collapsed';
                // 插入到 bubble-text 之前（使 AI 消息出现在最底部）
                s.bubbleText.parentNode.insertBefore(s.toolCallContainer, s.bubbleText);
                // 折叠式摘要栏：点击可展开/折叠整个工具调用列表
                s.toolCallSummary = document.createElement('div');
                s.toolCallSummary.className = 'tool-call-summary';
                s.toolCallSummary.innerHTML = '<span class="tool-call-summary-icon">🛠</span>'
                  + '<span class="tool-call-summary-label">工具调用</span>'
                  + '<span class="tool-call-summary-badge" id="tc-badge">0</span>'
                  + '<span class="tool-call-summary-arrow">▸</span>';
                s.toolCallSummary.addEventListener('click', function() {
                  const list = s.toolCallContainer.querySelector('.tool-call-list');
                  if (list) {
                    const expanded = list.style.display !== 'none';
                    list.style.display = expanded ? 'none' : '';
                    s.toolCallContainer.classList.toggle('collapsed', expanded);
                    s.toolCallSummary.querySelector('.tool-call-summary-arrow').textContent = expanded ? '▸' : '▾';
                  }
                });
                s.toolCallContainer.appendChild(s.toolCallSummary);
                s.toolCallList = document.createElement('div');
                s.toolCallList.className = 'tool-call-list';
                // 默认折叠：初始隐藏列表
                s.toolCallList.style.display = 'none';
                s.toolCallContainer.appendChild(s.toolCallList);
              }
              s.toolCallCount++;
              const badge = s.toolCallContainer.querySelector('.tool-call-summary-badge');
              if (badge) badge.textContent = s.toolCallCount;
              // 保持折叠状态，不展开列表
              const item = document.createElement('details');
              item.className = 'tool-call-item running';
              item.id = `tool-${s.toolCallCount}`;
              // details 默认不 open，即收缩状态（类似 think-entry）
              item.innerHTML = '<summary class="tool-call-header">'
                + '<span class="tool-call-icon">⚡</span>'
                + '<span class="tool-call-name">' + esc(data.name || '工具') + '</span>'
                + '<span class="tool-call-status status-running">运行中</span>'
                + '</summary>'
                + '<div class="tool-call-detail">'
                + '<div class="tool-call-section">'
                + '<div class="tool-call-section-label">参数</div>'
                + '<pre class="tool-call-args"></pre>'
                + '</div>'
                + '<div class="tool-call-section">'
                + '<div class="tool-call-section-label">结果</div>'
                + '<pre class="tool-call-result"></pre>'
                + '</div>'
                + '</div>';
              s.toolCallList.appendChild(item);
              s.activeToolItem = item;
              break;
            }

            case 'tool_args':
              if (s.activeToolItem) {
                const argsPre = s.activeToolItem.querySelector('.tool-call-args');
                if (argsPre) argsPre.textContent += data.args;
              }
              break;

            case 'tool_result':
              if (s.activeToolItem) {
                // 保持折叠，用户需点击 summary 手动展开查看详情
                // s.activeToolItem.open = true;
                const resPre = s.activeToolItem.querySelector('.tool-call-result');
                if (resPre) resPre.textContent += data.result;
              }
              break;

            case 'tool_done':
              s.toolDoneCount++;
              if (s.activeToolItem) {
                // 更新 item 容器状态类
                s.activeToolItem.classList.remove('running');
                s.activeToolItem.classList.add('done');
                // 更新状态标签
                const status = s.activeToolItem.querySelector('.tool-call-status');
                if (status) {
                  status.textContent = '✅ 完成';
                  status.className = 'tool-call-status status-done';
                }
                // 更新摘要中的完成计数
                const badge = s.toolCallContainer && s.toolCallContainer.querySelector('.tool-call-summary-badge');
                if (badge) {
                  badge.textContent = s.toolDoneCount + '/' + s.toolCallCount;
                }
              }
              s.activeToolItem = null;
              break;

            case 'status':
              if (data.text) {
                const oldStatus = document.getElementById('stream-status');
                if (!oldStatus) {
                  const statusDiv = document.createElement('div');
                  statusDiv.id = 'stream-status';
                  statusDiv.className = 'stream-status';
                  s.bubbleText.parentNode.appendChild(statusDiv);
                }
                const sd = $('stream-status');
                if (sd) sd.textContent = data.text;
              }
              break;

            case 'max_iter_confirm':
              removeLoading();
              showMaxIterConfirm(data.confirm_id, data.text);
              break;

            case 'question':
              removeLoading();
              showQuestionDialog(data.question_id, data.title, data.question, data.options, data.default);
              break;

            case 'done':
              removeLoading();
              // 记录 token 用量（延迟显示，等流结束后才更新 UI）
              if (data.usage) _pendingUsage = data.usage;
              // 更新 topic_id（首次消息后更新）
              if (data.topic_id && data.topic_id !== currentTopicId) {
                currentTopicId = data.topic_id;
                refreshTopics();
              }
              // 用 Markdown 重新渲染 AI 最终消息（流式 token 只是 esc 纯文本）
              if (data.ai_msg && s.bubbleText) {
                s.bubbleText.innerHTML = formatMarkdown(data.ai_msg);
                // 移除 tool/think 容器中的 id，避免下次流式清理时误删
                if (s.thinkContainer) s.thinkContainer.removeAttribute('id');
                if (s.toolCallContainer) s.toolCallContainer.removeAttribute('id');
              }
              markTitleDone();
              renderJumpBar(); // 新消息完成 -> 更新跳转栏
              break;

            case 'dag_viz': {
              let dagSection = $('tp-dag-section');
              if (!dagSection) break;
              dagSection.style.display = '';
              const snap = data.snapshot || {};
              const done = snap.done || 0;
              const total = snap.total || 0;
              const state = snap.state || 'running';
              // DAG SVG
              const iframe = $('dag-iframe');
              if (iframe && snap.svg) {
                const svgBlob = new Blob([snap.svg], { type: 'image/svg+xml' });
                iframe.src = URL.createObjectURL(svgBlob);
              }
              // 状态和进度条
              $('dag-state').textContent = state.toUpperCase();
              const dp = $('dag-progress');
              if (dp && total > 0) {
                dp.style.width = Math.round(done / total * 100) + '%';
                dp.textContent = done + ' / ' + total;
              }
              const lbTitle = $('dag-lightbox-title');
              if (lbTitle) {
                lbTitle.textContent = (snap.title || 'DAG') + ' · ' + state.toUpperCase() + ' · ' + done + '/' + total;
              }
              // 完成/失败/取消时停止轮询
              if (state === 'completed' || state === 'failed' || state === 'cancelled') {
                if (_dagStopPoll) _dagStopPoll();
              }
              break;
            }

            case 'error':
              removeLoading();
              s.bubbleText.innerHTML = '<span style="color:var(--red)">错误: ' + esc(data.error) + '</span>';
              break;
          }
          scrollBottom();
        } catch(e) { /* skip parse errors */ }
      }
      buf = slines[slines.length - 1];
    }
  } catch(e) {
    if (e.name === 'AbortError') {
      removeLoading();
      const bt = $('bubble-text');
      if (bt && !bt.innerHTML.trim()) bt.innerHTML = '(已中断)';
    } else {
      removeLoading();
      const bt = $('bubble-text');
      if (bt) bt.innerHTML = '<span style="color:var(--red)">网络错误: ' + esc(e.message) + '</span>';
    }
  } finally {
    if (myGen === _streamGeneration) {
      isStreaming = false;
      abortController = null;
      _processQueueAfterStream();
    }
    // else: 这是过期流（用户已切换主题），不做任何操作
  }
};

function updateUsage(usage) {
  if (!usage || !usage.total_tokens) return;
  var bar = $('usage-bar');
  if (!bar) return;
  bar.style.display = '';
  var modelHtml = ' | <span class="usage-model">主模型: ' + (usage.model || '?') + '</span>';
  var cheapHtml = '';
  if (usage.cheap_model) {
    cheapHtml = ' | <span class="usage-cheap">便宜模型: ' + usage.cheap_model + '</span>';
  }
  bar.innerHTML = '<span class="usage-tokens">📊 T:' + usage.total_tokens
    + '</span> <span class="usage-detail">(P:' + usage.prompt_tokens + '+C:' + usage.completion_tokens + ')</span>'
    + modelHtml
    + cheapHtml;
  bar.className = 'usage-bar';
}

// ══════════════════════════════════════════════════
//  TOPICS / SESSIONS
// ══════════════════════════════════════════════════

// ══════════════════════════════════════════════════
//  TOPICS / SESSIONS
// ══════════════════════════════════════════════════

async function refreshTopics() {
  try {
    const r = await fetch('/api/sessions');
    if (!r.ok) return;
    const d = await r.json();
    const topics = d.sessions || d.data;
    if (!topics) return;
    let html = '';
    // 当没有选中任何主题时（新对话），在列表顶部插入高亮的"新对话"虚拟条目
    if (!currentTopicId) {
      html += '<div class="topic-item active" data-topic-id="">'
        + '<span class="topic-item-title">🆕 新对话</span>'
        + '</div>';
    }
    html += topics.map(function(t) {
      const title = t.title || t.id.slice(0, 8);
      const cls = 'topic-item' + (t.id === currentTopicId ? ' active' : '');
      // ⭐ 判断 topic 是否有正在进行的后台处理
      //    增加客户端 isStreaming 检测：当前正在发的消息立即显示转圈圈
      const isCurrentlyStreaming = isStreaming && t.id === currentTopicId;
      const hasActivity = isCurrentlyStreaming || t.is_active || t.is_background;
      const spinnerHtml = hasActivity ? '<span class="topic-spinner"></span>' : '';
      return '<div class="' + cls + '" onclick="openTopic(\'' + t.id + '\',\'' + esc(title) + '\')">'
        + spinnerHtml
        + esc(title)
        + '<span class="topic-menu-wrap">'
        + '<button class="more-btn" onclick="event.stopPropagation();showTopicMenu(this,\'' + t.id + '\')">⋯</button>'
        + '<div class="topic-menu" id="topic-menu-' + t.id + '">'
        + '<a onclick="event.stopPropagation();renameTopic(\'' + t.id + '\')">✏️ 编辑标题</a>'
        + '<a class="danger" onclick="event.stopPropagation();deleteTopic(\'' + t.id + '\')">🗑 删除</a>'
        + '</div></span>'
        + '</div>';
    }).join('');
    $('topic-list').innerHTML = html;
  } catch(e) {}
}

window.openTopic = async function(id, title) {
  // 如果正在流式生成中且切换不同主题 → 不中断对话，仅分离 UI
  // 后台线程会继续完成对话并自动保存到数据库
  if (isStreaming && currentTopicId && currentTopicId !== id) {
    // ⭐ 中断旧 SSE fetch → 服务器收到 CancelledError → session 移入 _background_sessions
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    _streamGeneration++; // 标记旧流为过期
    isStreaming = false;
    removeLoading();
    _messageQueue = [];
    renderQueueList();
    const sendBtn = $('send-btn');
    sendBtn.textContent = '发送';
    sendBtn.className = 'btn btn-p primary';
    sendBtn.disabled = false;
  } else if (isStreaming) {
    // 同一个主题或当前无主题：正常中断
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    if (currentTopicId) {
      try {
        await fetch('/api/chat/abort', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ topic_id: currentTopicId }),
          signal: AbortSignal.timeout(3000),
        });
      } catch(e) { /* ignore */ }
    }
    isStreaming = false;
    removeLoading();
    _messageQueue = [];
    renderQueueList();
  }
  currentTopicId = id;
  setTitle(title || id.slice(0, 8));
  refreshTopics();
  // 清空旧的后台轮询
  _stopBackgroundPoll();
  try {
    const r = await fetch('/api/topic/' + id + '/conversations?limit=50');
    if (!r.ok) return;
    const d = await r.json();
    if (!d.conversations) return;
    $('msgs').innerHTML = '';
    _msgCounter = 0;  // 切换话题重置消息计数器
    _userNearBottom = true;  // 切换话题重置滚动状态
    d.conversations.forEach(function(c) {
      if (c.user_msg) addMessage('user', c.user_msg);
      if (c.ai_msg) addMessage('assistant', c.ai_msg);
    });
    // 加载旧话题 → 滚动到底部（显示最新消息）
    scrollBottom();
    renderJumpBar(); // 加载历史后更新跳转栏
    // ⭐ 检查 topic 是否在后台处理中，若是则启动轮询
    _checkBackgroundAndPoll(id);
  } catch(e) {}
};

/**
 * 检查 topic 是否有后台处理，如有则启动轮询等待完成
 */
async function _checkBackgroundAndPoll(topicId) {
  try {
    const r = await fetch('/api/topic/' + topicId + '/status');
    if (!r.ok) return;
    const status = await r.json();
    if (status.background || status.active) {
      _showBackgroundIndicator(topicId);
      _startBackgroundPoll(topicId);
    }
  } catch(e) {}
}

function _showBackgroundIndicator(topicId) {
  let banner = $('bg-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'bg-banner';
    banner.className = 'bg-processing-banner';
    banner.innerHTML = '<span class="bg-spinner"></span> ⏳ 后台正在处理中…';
    $('msgs').prepend(banner);
  }
}

function _removeBackgroundIndicator() {
  const banner = $('bg-banner');
  if (banner) banner.remove();
}

/**
 * 在后台处理期间，尝试实时渲染缓冲区中的 SSE 事件
 * 让用户看到 token 逐字输出，而不是只有"处理中"提示
 */
let _bufferSince = -1;
let _bufferEventCount = 0;
let _bufferStreamState = null; // 复用 _createStreamState 的结构

function _ensureBufferStreamState() {
  if (!_bufferStreamState) {
    _bufferStreamState = {
      bubbleText: null,
      fullText: '',
      thinkContainer: null,
      thinkSummary: null,
      thinkList: null,
      thinkContent: null,
      thinkCount: 0,
      toolCallContainer: null,
      toolCallList: null,
      toolCallSummary: null,
      toolCallBadge: null,
      toolCallCount: 0,
      toolDoneCount: 0,
      activeToolItem: null,
    };
  }
  return _bufferStreamState;
}

/** 渲染一个来自缓冲区的 SSE 事件到消息区 */
function _renderBufferEvent(event) {
  const s = _ensureBufferStreamState();
  switch (event.type) {

    case 'token':
      s.fullText += event.text;
      if (!s.bubbleText) {
        // 首次 token：创建 AI 消息容器
        const agentDiv = document.createElement('div');
        agentDiv.className = 'msg assistant';
        agentDiv.innerHTML = '<div class="msg-label">Tea Agent</div><div class="msg-bubble"><div class="bubble-text"></div></div>';
        $('msgs').appendChild(agentDiv);
        s.bubbleText = agentDiv.querySelector('.bubble-text');
        _removeBackgroundIndicator(); // 有实际内容了，隐藏"处理中"提示
      }
      s.bubbleText.innerHTML = esc(s.fullText);
      scrollBottom();
      break;

    case 'think_start':
      if (!s.thinkContainer) {
        s.thinkContainer = document.createElement('div');
        s.thinkContainer.className = 'think-container collapsed';
        // 找到最后一个 assistant 消息的 bubble 插入
        const lastBubble = $('msgs').querySelector('.msg.assistant:last-child .msg-bubble');
        if (lastBubble) {
          lastBubble.insertBefore(s.thinkContainer, lastBubble.querySelector('.bubble-text'));
        }
        s.thinkSummary = document.createElement('div');
        s.thinkSummary.className = 'think-summary';
        s.thinkSummary.innerHTML = '<span class="think-summary-icon">🧠</span>'
          + '<span class="think-summary-label">思考过程</span>'
          + '<span class="think-summary-badge" id="bg-think-badge">0</span>'
          + '<span class="think-summary-arrow">▸</span>';
        s.thinkSummary.addEventListener('click', function() {
          var list = s.thinkContainer.querySelector('.think-list');
          if (list) {
            var expanded = list.style.display !== 'none';
            list.style.display = expanded ? 'none' : '';
            s.thinkContainer.classList.toggle('collapsed', expanded);
            s.thinkSummary.querySelector('.think-summary-arrow').textContent = expanded ? '▸' : '▾';
          }
        });
        s.thinkContainer.appendChild(s.thinkSummary);
        s.thinkList = document.createElement('div');
        s.thinkList.className = 'think-list';
        s.thinkList.style.display = 'none';
        s.thinkContainer.appendChild(s.thinkList);
      }
      s.thinkCount++;
      var badge = s.thinkContainer.querySelector('.think-summary-badge');
      if (badge) badge.textContent = s.thinkCount;
      var entry = document.createElement('details');
      entry.className = 'think-entry';
      entry.innerHTML = '<summary>思考 #' + s.thinkCount + '</summary><div class="think-content"></div>';
      s.thinkList.appendChild(entry);
      s.thinkContent = entry.querySelector('.think-content');
      break;

    case 'think':
      if (s.thinkContent) {
        s.thinkContent.textContent += event.text;
      }
      break;

    case 'think_done':
      if (s.thinkList) {
        var lastEntry = s.thinkList.querySelector('.think-entry:last-child');
        if (lastEntry) {
          var summary = lastEntry.querySelector('summary');
          var content = lastEntry.querySelector('.think-content');
          if (summary) {
            var preview = content ? content.textContent.trim().replace(/\s+/g, ' ').substring(0, 32) : '';
            if (preview) preview = '：' + preview;
            summary.textContent = '思考 #' + s.thinkCount + ' 完成' + preview;
          }
        }
      }
      break;

    case 'tool_start': {
      if (!s.toolCallContainer) {
        s.toolCallContainer = document.createElement('div');
        s.toolCallContainer.className = 'tool-call-container collapsed';
        const lastBubble = $('msgs').querySelector('.msg.assistant:last-child .msg-bubble');
        if (lastBubble) {
          lastBubble.insertBefore(s.toolCallContainer, lastBubble.querySelector('.bubble-text'));
        }
        s.toolCallSummary = document.createElement('div');
        s.toolCallSummary.className = 'tool-call-summary';
        s.toolCallSummary.innerHTML = '<span class="tool-call-summary-icon">🛠</span>'
          + '<span class="tool-call-summary-label">工具调用</span>'
          + '<span class="tool-call-summary-badge" id="bg-tc-badge">0</span>'
          + '<span class="tool-call-summary-arrow">▸</span>';
        s.toolCallSummary.addEventListener('click', function() {
          var list = s.toolCallContainer.querySelector('.tool-call-list');
          if (list) {
            var expanded = list.style.display !== 'none';
            list.style.display = expanded ? 'none' : '';
            s.toolCallContainer.classList.toggle('collapsed', expanded);
            s.toolCallSummary.querySelector('.tool-call-summary-arrow').textContent = expanded ? '▸' : '▾';
          }
        });
        s.toolCallContainer.appendChild(s.toolCallSummary);
        s.toolCallList = document.createElement('div');
        s.toolCallList.className = 'tool-call-list';
        s.toolCallList.style.display = 'none';
        s.toolCallContainer.appendChild(s.toolCallList);
      }
      s.toolCallCount++;
      var badge = s.toolCallContainer.querySelector('.tool-call-summary-badge');
      if (badge) badge.textContent = s.toolCallCount;
      var item = document.createElement('details');
      item.className = 'tool-call-item running';
      item.innerHTML = '<summary class="tool-call-header">'
        + '<span class="tool-call-icon">⚡</span>'
        + '<span class="tool-call-name">' + esc(event.name || '工具') + '</span>'
        + '<span class="tool-call-status status-running">运行中</span>'
        + '</summary>'
        + '<div class="tool-call-detail">'
        + '<div class="tool-call-section"><div class="tool-call-section-label">参数</div><pre class="tool-call-args"></pre></div>'
        + '<div class="tool-call-section"><div class="tool-call-section-label">结果</div><pre class="tool-call-result"></pre></div>'
        + '</div>';
      s.toolCallList.appendChild(item);
      s.activeToolItem = item;
      break;
    }

    case 'tool_args':
      if (s.activeToolItem) {
        var argsPre = s.activeToolItem.querySelector('.tool-call-args');
        if (argsPre) argsPre.textContent += event.args;
      }
      break;

    case 'tool_result':
      if (s.activeToolItem) {
        var resPre = s.activeToolItem.querySelector('.tool-call-result');
        if (resPre) resPre.textContent += event.result;
      }
      break;

    case 'tool_done':
      s.toolDoneCount++;
      if (s.activeToolItem) {
        s.activeToolItem.classList.remove('running');
        s.activeToolItem.classList.add('done');
        var status = s.activeToolItem.querySelector('.tool-call-status');
        if (status) {
          status.textContent = '✅ 完成';
          status.className = 'tool-call-status status-done';
        }
        var badge = s.toolCallContainer && s.toolCallContainer.querySelector('.tool-call-summary-badge');
        if (badge) badge.textContent = s.toolDoneCount + '/' + s.toolCallCount;
      }
      s.activeToolItem = null;
      break;

    case 'status':
      if (event.text) {
        var oldStatus = document.getElementById('bg-stream-status');
        if (!oldStatus) {
          var statusDiv = document.createElement('div');
          statusDiv.id = 'bg-stream-status';
          statusDiv.className = 'stream-status';
          var lastBubble = $('msgs').querySelector('.msg.assistant:last-child .msg-bubble');
          if (lastBubble) {
            lastBubble.appendChild(statusDiv);
          }
        }
        var sd = $('bg-stream-status');
        if (sd) sd.textContent = event.text;
      }
      break;

    case 'done':
      // 后台流结束，用 Markdown 重新渲染最终消息
      if (event.ai_msg && s.bubbleText) {
        s.bubbleText.innerHTML = formatMarkdown(event.ai_msg);
      }
      break;

    case 'error':
      if (s.bubbleText) {
        s.bubbleText.innerHTML = '<span style="color:var(--red)">错误: ' + esc(event.error) + '</span>';
      }
      break;
  }
}

function _startBackgroundPoll(topicId) {
  _stopBackgroundPoll();
  _backgroundPollTopic = topicId;
  _bufferSince = -1;
  _bufferEventCount = 0;
  _bufferStreamState = null;

  _backgroundPollTimer = setInterval(async function() {
    try {
      // 1) 同时拉取 status（判断是否结束）和 stream-buffer（实时事件）
      const [statusResp, bufferResp] = await Promise.all([
        fetch('/api/topic/' + topicId + '/status'),
        fetch('/api/topic/' + topicId + '/stream-buffer?since=' + _bufferSince),
      ]);

      // 处理缓冲区事件
      if (bufferResp.ok) {
        const buf = await bufferResp.json();
        if (buf.events && buf.events.length > 0) {
          _bufferEventCount += buf.events.length;
          buf.events.forEach(function(entry) {
            _renderBufferEvent(entry.event);
          });
          _bufferSince = buf.next_index || 0;
        }

        // 流已完成 → 结束轮询，重新加载完整的最终会话
        if (buf.done) {
          _stopBackgroundPoll();
          _removeBackgroundIndicator();
          _reloadCurrentConversations();
          refreshTopics();
          return;
        }
      }

      // 也检查 status （兜底）
      if (statusResp.ok) {
        const status = await statusResp.json();
        if (!status.background && !status.active) {
          // 后台已结束但 buffer 没标记 done（可能没有 buffer 或 buffer 已过期）
          _stopBackgroundPoll();
          _removeBackgroundIndicator();
          _reloadCurrentConversations();
          refreshTopics();
          return;
        }
      }
    } catch(e) {
      _stopBackgroundPoll();
    }
  }, 1500); // 每 1.5 秒轮询一次（比之前 2 秒更密集，使实时性更好）
}

function _stopBackgroundPoll() {
  if (_backgroundPollTimer) {
    clearInterval(_backgroundPollTimer);
    _backgroundPollTimer = null;
  }
  _backgroundPollTopic = null;
  _removeBackgroundIndicator();
}

async function _reloadCurrentConversations() {
  if (!currentTopicId) return;
  // 重置缓冲区状态（避免与后续新流冲突）
  _bufferStreamState = null;
  _bufferSince = -1;
  _bufferEventCount = 0;
  try {
    const r = await fetch('/api/topic/' + currentTopicId + '/conversations?limit=50');
    if (!r.ok) return;
    const d = await r.json();
    if (!d.conversations) return;
    // 更新工具栏标题（后台处理期间可能 AI 已自动重命名）
    const newTitle = d.conversations.length > 0 ? (d.title || currentTopicId.slice(0, 8)) : '';
    if (newTitle) setTitle(newTitle);
    // 保留用户当前是否在底部
    const wasNearBottom = _isNearBottom();
    $('msgs').innerHTML = '';
    _msgCounter = 0;
    d.conversations.forEach(function(c) {
      if (c.user_msg) addMessage('user', c.user_msg);
      if (c.ai_msg) addMessage('assistant', c.ai_msg);
    });
    renderJumpBar(); // 后台 buffer 刷新后更新跳转栏
    if (wasNearBottom) scrollBottom();
  } catch(e) {}
}

window.newTopic = function() {
  // 如果正在流式生成中 → abort fetch 触发后台会话
  if (isStreaming) {
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    _streamGeneration++; // 标记旧流为过期
    isStreaming = false;
    removeLoading();
    _messageQueue = [];
    renderQueueList();
    const sendBtn = $('send-btn');
    sendBtn.textContent = '发送';
    sendBtn.className = 'btn btn-p primary';
    sendBtn.disabled = false;
  }
  currentTopicId = null;
  _userNearBottom = true;  // 新话题重置滚动状态
  _stopBackgroundPoll();   // 清除后台轮询
  setTitle('新对话');
  $('msgs').innerHTML = '';
  _msgCounter = 0; // 重置消息计数器
  // 隐藏跳转栏（新对话无历史）
  var jb = document.getElementById('jump-bar');
  if (jb) jb.style.display = 'none';
  // Restore welcome
  const welcome = document.createElement('div');
  welcome.className = 'welcome';
  welcome.innerHTML = '<h2>☕ Tea Agent GUI</h2><p>开始对话，或使用快捷键快速操作</p>'
    + '<div class="shortcuts">'
    + '<span class="shortcut-item"><kbd>Enter</kbd> 发送</span>'
    + '<span class="shortcut-item"><kbd>Shift+Enter</kbd> 换行</span>'
    + '<span class="shortcut-item"><kbd>Ctrl+N</kbd> 新对话</span>'
    + '<span class="shortcut-item"><kbd>Ctrl+K</kbd> 搜索</span>'
    + '<span class="shortcut-item"><kbd>Ctrl+Shift+M</kbd> 记忆</span>'
    + '<span class="shortcut-item"><kbd>Ctrl+J</kbd> 任务面板</span>'
    + '<span class="shortcut-item"><kbd>Escape</kbd> 中断/关闭</span>'
    + '</div>';
  $('msgs').appendChild(welcome);
  refreshTopics();
};

window.clearChat = function() {
  if (isStreaming) { toast('正在发送消息中...', 'error'); return; }
  $('msgs').innerHTML = '';
  newTopic();
};

window.deleteTopic = async function(id) {
  try {
    await fetch('/api/topic/' + encodeURIComponent(id), { method: 'DELETE' });
    if (currentTopicId === id) newTopic();
    else refreshTopics();
    toast('🗑 已删除', 'success');
  } catch(e) {
    toast('删除失败', 'error');
  }
};

// ── Topic Context Menu ──
window.showTopicMenu = function(btn, topicId) {
  const menuId = 'topic-menu-' + topicId;
  const menu = document.getElementById(menuId);
  if (!menu) return;
  const isOpen = menu.classList.contains('show');
  closeAllTopicMenus();
  if (!isOpen) {
    menu.classList.add('show');
    // Position menu using fixed coordinates relative to viewport
    const rect = btn.getBoundingClientRect();
    menu.style.left = rect.right + 'px';
    menu.style.top = rect.top + 'px';
    menu.style.transform = 'translate(-100%, 0)';
    // If not enough space below, flip up
    const spaceBelow = window.innerHeight - rect.top;
    if (spaceBelow < 160) {
      menu.style.top = rect.bottom + 'px';
      menu.style.transform = 'translate(-100%, -100%)';
    }
    // If off-screen left, align to left edge
    if (rect.right < 160) {
      menu.style.left = '8px';
      menu.style.transform = 'translate(0, 0)';
    }
  }
};

window.closeAllTopicMenus = function() {
  document.querySelectorAll('.topic-menu.show').forEach(function(m) {
    m.classList.remove('show');
  });
};

window.renameTopic = async function(topicId) {
  closeAllTopicMenus();
  // Get current title from the topic list
  const topicsEl = document.querySelectorAll('.topic-item');
  let currentTitle = '';
  for (const el of topicsEl) {
    if (el.getAttribute('onclick') && el.getAttribute('onclick').includes(topicId)) {
      // Extract title from the text content (first child text node before the menu)
      currentTitle = el.childNodes[0] ? el.childNodes[0].textContent.trim() : '';
      break;
    }
  }
  const newTitle = prompt('修改话题标题：', currentTitle);
  if (!newTitle || newTitle === currentTitle) return;
  try {
    const r = await fetch('/api/topic/' + encodeURIComponent(topicId), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle })
    });
    const d = await r.json();
    if (d.ok) {
      toast('✏️ 标题已更新', 'success');
      refreshTopics();
      // Update toolbar title if this is the current topic
      if (topicId === currentTopicId) {
        setTitle(newTitle);
      }
    } else {
      toast('修改失败: ' + (d.error || ''), 'error');
    }
  } catch(e) {
    toast('修改失败: ' + e.message, 'error');
  }
};

// ── Extend click handler to close topic menus ──
// (the existing document click handler already closes ss-menu, we add topic menu close)
document.addEventListener('click', function(e) {
  if (!e.target.closest('.topic-menu-wrap')) {
    closeAllTopicMenus();
  }
});

// ══════════════════════════════════════════════════
//  TASK PANEL (Plan + TODO) — 适配 #task-panel / tp-* 结构
// ══════════════════════════════════════════════════

window.closeDagView = function() {
  const section = $('tp-dag-section');
  if (section) section.style.display = 'none';
  // 清除缩略图
  const dagImg = $('tp-dag-img');
  if (dagImg) dagImg.src = '';
  // 隐藏缩略图区域
  const imgWrap = $('tp-dag-img-wrap');
  if (imgWrap) imgWrap.style.display = 'none';
  // 清除节点列表
  const nodes = $('tp-dag-nodes');
  if (nodes) nodes.innerHTML = '';
  // 重置状态栏
  const badge = $('dag-badge');
  const progress = $('dag-progress');
  const timer = $('dag-timer');
  if (badge) { badge.textContent = 'PENDING'; badge.className = 'dag-status-badge badge-pending'; }
  if (progress) progress.textContent = '0/0';
  if (timer) timer.textContent = '00:00';
  // 清除全局 viz_id
  window._dagVizId = null;
  // 停止轮询
  if (window._dagStopPoll) { window._dagStopPoll(); window._dagStopPoll = null; }
};

// ── DAG 灯箱（双击放大） ──
window.openDagLightbox = function() {
  const lb = $('dag-lightbox');
  const lbImg = $('dag-lightbox-img');
  const dagImg = $('tp-dag-img');
  if (!lb || !lbImg || !dagImg || !dagImg.src) return;
  lbImg.src = dagImg.src.replace(/&t=\d+/, '&t=' + Date.now());
  lb.classList.add('open');
  document.body.style.overflow = 'hidden';
};

window.closeDagLightbox = function() {
  const lb = $('dag-lightbox');
  if (lb) lb.classList.remove('open');
  document.body.style.overflow = '';
};

// 键盘 Esc 关闭灯箱
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    const lb = $('dag-lightbox');
    if (lb && lb.classList.contains('open')) {
      closeDagLightbox();
    }
  }
});

// DAG 节点列表渲染（轮询驱动）
window.renderDagNodeList = function(container, snap) {
  if (!container || !snap.nodes) return;
  let html = '';
  for (let i = 0; i < snap.nodes.length; i++) {
    const n = snap.nodes[i];
    const stateClass = n.state || 'pending';
    let icon = stateClass === 'completed' ? '\u2713' :
               stateClass === 'running' ? '\u25b6' :
               stateClass === 'failed' ? '\u2717' : '\u25cb';
    html += '<span class="dag-node-item">' +
      '<span class="dag-node-dot dot-' + stateClass + '"></span>' +
      '<span class="dag-node-label" title="' + esc(n.label) + ' [' + stateClass.toUpperCase() +
      (n.duration > 0 ? ' ' + n.duration.toFixed(1) + 's' : '') + ']">' +
      icon + ' ' + esc(n.label) +
      '</span></span>';
  }
  container.innerHTML = html;
};

window.toggleTaskPanel = function() {
  const panel = $('task-panel');
  const splitter = $('task-panel-splitter');
  if (!panel) return;
  _taskPanelOpen = !panel.classList.contains('open');
  if (_taskPanelOpen) {
    panel.classList.add('open');
    if (splitter) splitter.classList.add('visible');
    _taskPanelSuppressAutoOpen = false;  // 用户手动打开，取消抑制
    refreshTaskPanel();
  } else {
    panel.classList.remove('open');
    if (splitter) splitter.classList.remove('visible');
    _taskPanelSuppressAutoOpen = true;   // 用户手动关闭，抑制自动弹出
  }
};

window.refreshTaskPanel = async function() {
  if (!currentTopicId) {
    const planList = $('tp-plan-list');
    const todoList = $('tp-todo-list');
    if (planList) planList.innerHTML = '<div class="tp-empty">请先开始对话</div>';
    if (todoList) todoList.innerHTML = '<div class="tp-empty">请先开始对话</div>';
    const prog = $('tp-progress');
    if (prog) prog.textContent = '0/0';
    return;
  }
  try {
    const [planResp, todoResp] = await Promise.all([
      fetch('/api/topic/' + encodeURIComponent(currentTopicId) + '/plans?status=all'),
      fetch('/api/topic/' + encodeURIComponent(currentTopicId) + '/todos'),
    ]);

    // ── 渲染 Plan ──
    let plans = [];
    const planList = $('tp-plan-list');
    if (!planList) return;
    if (planResp.ok) {
      const planData = await planResp.json();
      plans = planData.data || [];
      // 分组：活跃 (running/paused/created) vs 已归档 (done/failed)
      const activePlans = [];
      const archivedPlans = [];
      for (const plan of plans) {
        const st = plan.status || '';
        if (st === 'done' || st === 'failed') {
          archivedPlans.push(plan);
        } else {
          activePlans.push(plan);
        }
      }
      if (activePlans.length === 0 && archivedPlans.length === 0) {
        planList.innerHTML = '<div class="tp-empty">(暂无计划)</div>';
      } else {
        const statusIconMap = {
          done: '✅', failed: '❌', running: '🔄',
          paused: '⏸️', created: '📋', pending: '⬜'
        };
        const renderPlanCard = function(plan) {
          const steps = plan.steps || [];
          const doneSteps = steps.filter(function(s) { return s.status === 'done'; }).length;
          const totalSteps = steps.length;
          const goalText = (plan.goal || '无目标').slice(0, 80);
          const statusIcon = statusIconMap[plan.status] || '📋';
          let card = '<div class="tp-plan-card';
          if (plan.status === 'failed') card += ' tp-plan-failed';
          card += '">';
          card += '<div class="tp-plan-card-header">';
          card += '<span>' + statusIcon + '</span>';
          card += '<span>' + esc(goalText) + '</span>';
          card += '<span class="tp-plan-card-progress">' + doneSteps + '/' + totalSteps + '</span>';
          card += '</div>';
          for (const step of steps) {
            const sStatus = step.status || 'pending';
            const iconMap = { done: '✅', failed: '❌', running: '▶️', pending: '⬜', skipped: '⏭️' };
            const sIcon = iconMap[sStatus] || '❓';
            const sDesc = (step.desc || '').slice(0, 100);
            const sCls = sStatus === 'done' ? 'done' : (sStatus === 'failed' ? 'failed' : '');
            card += '<div class="tp-step-item ' + sCls + '">';
            card += '<span class="step-icon">' + sIcon + '</span>';
            card += '<span class="step-desc">' + esc(sDesc) + '</span>';
            card += '</div>';
          }
          card += '</div>';
          return card;
        };

        let html = '';
        // 活跃计划
        if (activePlans.length > 0) {
          html += '<div class="tp-plan-active-section">';
          for (const plan of activePlans) {
            html += renderPlanCard(plan);
          }
          html += '</div>';
        }
        // 已归档（done/failed），默认折叠
        if (archivedPlans.length > 0) {
          html += '<div class="tp-plan-archive-group" id="tp-plan-archive-group">';
          html += '<div class="tp-plan-archive-hdr" onclick="toggleArchive()">';
          html += '<span class="tp-archive-arrow" id="tp-archive-arrow">▶</span> ';
          html += '<span>已归档 (' + archivedPlans.length + ')</span>';
          html += '</div>';
          html += '<div class="tp-plan-archive-body" id="tp-plan-archive-body" style="display:none">';
          for (const plan of archivedPlans) {
            html += renderPlanCard(plan);
          }
          html += '</div></div>';
        }
        planList.innerHTML = html;
      }
    } else {
      planList.innerHTML = '<div class="tp-empty">(加载失败)</div>';
    }

    // ── 渲染 TODO ──
    let items = [];
    const todoList = $('tp-todo-list');
    if (!todoList) return;
    if (todoResp.ok) {
      const todoData = await todoResp.json();
      items = todoData.items || [];
      const total = todoData.total || 0;
      const done = todoData.done || 0;
      const prog = $('tp-progress');
      if (prog) prog.textContent = done + '/' + total;

      if (items.length === 0) {
        todoList.innerHTML = '<div class="tp-empty">(暂无待办)</div>';
      } else {
        let html = '';
        for (const item of items) {
          const doneCls = item.done ? 'checked' : '';
          const descCls = item.done ? 'done' : '';
          html += '<div class="tp-todo-item">';
          html += '<div class="tp-todo-cb ' + doneCls + '" onclick="checkTodoItem(' + item.idx + ', ' + (!item.done) + ')">' + (item.done ? '✓' : '') + '</div>';
          html += '<span class="tp-todo-desc ' + descCls + '">' + esc(item.desc) + '</span>';
          html += '<span class="tp-todo-idx">#' + item.idx + '</span>';
          html += '</div>';
        }
        todoList.innerHTML = html;
      }
    } else {
      todoList.innerHTML = '<div class="tp-empty">(加载失败)</div>';
    }

    // ── 自动弹出：当有 TODO 或 Plan 或 DAG 内容时，自动打开任务面板 ──
    const hasContent = items.length > 0 || plans.length > 0 || (window._dagVizId != null);
    const panel = $('task-panel');
    const splitter = $('task-panel-splitter');
    if (hasContent && !_taskPanelOpen && !_taskPanelSuppressAutoOpen && !isStreaming) {
      _taskPanelOpen = true;
      if (panel) panel.classList.add('open');
      if (splitter) splitter.classList.add('visible');
    }

    // ── DAG 工作流轮询 ──
    await refreshDagSection();

  } catch(e) {
    // 静默失败
  }
};

// ══════════════════════════════════════════════════
//  DAG SECTION — 任务面板缩略图 + 自动刷新
// ══════════════════════════════════════════════════

window._dagPollTimer = null;
window._dagVizId = null;
window._dagStopPoll = null;

/** 从 /api/dags 获取活跃 DAG 并渲染到任务面板 */
window.refreshDagSection = async function() {
  const section = $('tp-dag-section');
  if (!section) return;

  try {
    const r = await fetch('/api/dags');
    if (!r.ok) return;
    const data = await r.json();
    const dags = data.dags || [];

    if (dags.length === 0) {
      // 没有活跃 DAG，隐藏区域
      closeDagView();
      return;
    }

    // 取第一个活跃 DAG
    const dag = dags[0];
    const vizId = dag.viz_id;

    // 如果 vizId 没变，只更新状态（避免闪烁）
    if (window._dagVizId === vizId) {
      // 已经在轮询中，跳过
      return;
    }

    // 新的 DAG — 初始化
    if (window._dagStopPoll) { window._dagStopPoll(); window._dagStopPoll = null; }
    window._dagVizId = vizId;

    // 显示 DAG 区域
    section.style.display = '';
    const imgWrap = $('tp-dag-img-wrap');
    if (imgWrap) imgWrap.style.display = '';

    // 初始状态
    const badge = $('dag-badge');
    const progress = $('dag-progress');
    const timer = $('dag-timer');
    if (badge) { badge.textContent = dag.state.toUpperCase(); badge.className = 'dag-status-badge badge-' + (dag.state || 'pending'); }
    if (progress) { const p = dag.progress || {}; progress.textContent = (p.completed || 0) + '/' + (p.total || 0); }
    if (timer) timer.textContent = '00:00';

    // 缩略图
    const dagImg = $('tp-dag-img');
    if (dagImg) {
      dagImg.src = '/dag/' + encodeURIComponent(vizId) + '/image?format=svg&t=' + Date.now();
      dagImg.ondblclick = function() { openDagInNewTab(vizId); };
    }

    // 启动轮询
    let startTime = Date.now();
    const poll = async function() {
      try {
        const resp = await fetch('/dag/' + encodeURIComponent(vizId) + '/status');
        if (!resp.ok) { stopPoll(); return; }
        const snap = await resp.json();
        const done = (snap.progress && snap.progress.completed) || 0;
        const total = (snap.progress && snap.progress.total) || 0;
        const state = snap.state || 'pending';

        if (badge) { badge.textContent = state.toUpperCase(); badge.className = 'dag-status-badge badge-' + state; }
        if (progress) progress.textContent = done + '/' + total;
        if (timer) {
          const elapsed = Math.floor((Date.now() - startTime) / 1000);
          timer.textContent = String(Math.floor(elapsed/60)).padStart(2,'0') + ':' + String(elapsed%60).padStart(2,'0');
        }
        // 更新节点列表
        renderDagNodeList($('tp-dag-nodes'), snap);
        // 刷新缩略图
        if (dagImg) dagImg.src = '/dag/' + encodeURIComponent(vizId) + '/image?format=svg&t=' + Date.now();
        // 更新灯箱
        const lbTitle = $('dag-lightbox-title');
        if (lbTitle) lbTitle.textContent = (snap.title || 'DAG') + ' · ' + state.toUpperCase() + ' · ' + done + '/' + total;

        if (state === 'completed' || state === 'failed' || state === 'cancelled') {
          stopPoll();
        }
      } catch(e) { /* retry */ }
    };
    const stopPoll = function() {
      if (window._dagPollTimer) { clearInterval(window._dagPollTimer); window._dagPollTimer = null; }
      window._dagStopPoll = null;
    };
    window._dagStopPoll = stopPoll;
    poll(); // 立即首次
    window._dagPollTimer = setInterval(poll, 2000); // 2秒轮询

  } catch(e) { /* ignore */ }
};

/** 双击缩略图 → 新标签页打开完整 DAG 页面 */
window.openDagInNewTab = function(vizId) {
  if (!vizId) return;
  window.open('/dag/' + encodeURIComponent(vizId), '_blank');
};

/** 展开/折叠已归档 Plan */
window.toggleArchive = function() {
  const body = $('tp-plan-archive-body');
  const arrow = $('tp-archive-arrow');
  if (!body || !arrow) return;
  if (body.style.display === 'none') {
    body.style.display = 'block';
    arrow.textContent = '▼';
  } else {
    body.style.display = 'none';
    arrow.textContent = '▶';
  }
};

/** 勾选/取消 TODO 项 */
window.checkTodoItem = async function(idx, done) {
  if (!currentTopicId) return;
  try {
    const r = await fetch('/api/topic/' + encodeURIComponent(currentTopicId) + '/todos/' + idx, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ done: done }),
    });
    if (r.ok) {
      await refreshTaskPanel();
    }
  } catch(e) { /* ignore */ }
};

window.startLeftResize = function(e) {
  e.preventDefault();
  const splitter = $('left-splitter');
  const sidebar = $('sidebar');
  splitter.classList.add('active');
  const startX = e.clientX;
  const startW = sidebar.offsetWidth;

  function onMove(ev) {
    const diff = ev.clientX - startX;
    const newW = Math.max(150, Math.min(400, startW + diff));
    sidebar.style.width = newW + 'px';
    // 更新CSS变量以保持一致
    document.documentElement.style.setProperty('--sidebar-w', newW + 'px');
  }
  function onUp() {
    splitter.classList.remove('active');
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  }
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
};

// ══════════════════════════════════════════════════
//  SEARCH
// ══════════════════════════════════════════════════

window.showSearchModal = function() {
  showModal('modal-search');
  $('search-q').value = '';
  $('search-results').innerHTML = '';
  setTimeout(function() { $('search-q').focus(); }, 100);
};

window.doSearch = async function() {
  const q = $('search-q').value.trim();
  if (!q) return;
  const el = $('search-results');
  el.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:8px 0">搜索中...</div>';
  try {
    const r = await fetch('/v1/search?q=' + encodeURIComponent(q) + '&limit=20');
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();
    const results = d.data || {};
    let h = '';
    if (results.conversations && results.conversations.length) {
      h += '<div style="font-size:13px;font-weight:600;margin:8px 0 4px;color:var(--primary)">💬 对话</div>';
      results.conversations.forEach(function(c) {
        h += '<div class="search-result-item">' + esc(c.user_msg || c.ai_msg || '').slice(0, 200) + '<div class="src">' + (c.stamp || '') + '</div></div>';
      });
    }
    if (results.memories && results.memories.length) {
      h += '<div style="font-size:13px;font-weight:600;margin:8px 0 4px;color:var(--green)">🧠 记忆</div>';
      results.memories.forEach(function(m) {
        h += '<div class="search-result-item">' + esc(m.content || '') + '<div class="src">' + esc(m.category || '') + '</div></div>';
      });
    }
    if (!h) h = '<div style="color:var(--text-muted);font-size:13px;padding:8px 0">没有结果</div>';
    el.innerHTML = h;
  } catch(e) {
    el.innerHTML = '<div style="color:var(--red);font-size:13px;padding:8px 0">Error: ' + esc(e.message) + '</div>';
  }
};

// ══════════════════════════════════════════════════
//  MEMORY
// ══════════════════════════════════════════════════

window.showMemoryModal = async function() {
  showModal('modal-memory');
  $('mem-input').value = '';
  await refreshMemoryList();
};

window.addMemory = async function() {
  const c = $('mem-input').value.trim();
  if (!c) return;
  try {
    const r = await fetch('/v1/memory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: c })
    });
    const d = await r.json();
    if (d.ok) {
      $('mem-input').value = '';
      await refreshMemoryList();
      toast('✓ 记忆已添加', 'success');
    } else {
      toast('✗ ' + (d.error || '添加失败'), 'error');
    }
  } catch(e) {
    toast('Error: ' + e.message, 'error');
  }
};

async function refreshMemoryList() {
  try {
    const r = await fetch('/v1/memory');
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();
    const el = $('mem-list');
    if (d.data && d.data.length) {
      el.innerHTML = d.data.map(function(m) {
        return '<div class="mem-item"><div class="tx">' + esc(m.content || '') + '<span class="cat">' + esc(m.category || '') + '</span></div>'
          + '<button class="btn btn-g btn-sm" onclick="deleteMemory(\'' + m.id + '\')">删除</button></div>';
      }).join('');
    } else {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:8px 0">暂无记忆</div>';
    }
  } catch(e) {
    $('mem-list').innerHTML = '<div style="color:var(--red);font-size:13px;padding:8px 0">加载失败: ' + esc(e.message) + '</div>';
  }
}

window.deleteMemory = async function(id) {
  try {
    const r = await fetch('/v1/memory/' + encodeURIComponent(id), { method: 'DELETE' });
    const d = await r.json();
    if (d.ok) {
      await refreshMemoryList();
      toast('🗑 已删除', 'success');
    }
  } catch(e) {
    toast('删除失败', 'error');
  }
};

// ══════════════════════════════════════════════════
//  CONFIG
// ══════════════════════════════════════════════════

window.showConfigModal = async function() {
  showModal('modal-config');
  $('cfg-status').style.display = 'none';
  await loadConfigForm();
};

async function loadConfigForm() {
  try {
    // Load current config
    const r1 = await fetch('/api/config');
    if (r1.ok) {
      const d = await r1.json();
      const cfg = d.data || d;
      $('cfg-model').value = cfg.model || '';
      $('cfg-url').value = cfg.api_url || '';
      $('cfg-key').value = '';
      $('cfg-temp').value = cfg.temperature != null ? cfg.temperature : '';
      $('cfg-max-tokens').value = cfg.max_tokens != null ? cfg.max_tokens : '';
      $('cfg-top-p').value = cfg.top_p != null ? cfg.top_p : '';
      $('cfg-max-ctx').value = cfg.max_context_tokens != null ? cfg.max_context_tokens : '';
      const opts = cfg.options || {};
      $('cfg-vision').checked = !!opts.supports_vision;
      $('cfg-reasoning').checked = opts.supports_reasoning !== false;
      // Cheap model
      if (cfg.cheap_model) {
        $('cfg-cheap-model').value = cfg.cheap_model.model || '';
        $('cfg-cheap-url').value = cfg.cheap_model.api_url || '';
        $('cfg-cheap-key').value = '';
      }
      // Runtime
      $('cfg-max-iter').value = cfg.max_iterations != null ? cfg.max_iterations : '';
      $('cfg-keep-turns').value = cfg.keep_turns != null ? cfg.keep_turns : '';
      $('cfg-thinking').checked = cfg.enable_thinking !== false;
    }
    // Load config file list
    const r2 = await fetch('/api/configs');
    if (r2.ok) {
      const d2 = await r2.json();
      const sel = $('cfg-select');
      const configs = d2.data || d2.configs || [];
      sel.innerHTML = '<option value="">-- 请选择 --</option>';
      const activePath = d2.active_config_path || '';
      configs.forEach(function(c) {
        const mainModel = c.main_model ? (c.main_model.model_name || '') : '';
        const cheapModel = c.cheap_model ? (c.cheap_model.model_name || '') : '';
        const selected = c.path === activePath ? ' selected' : '';

        const mainFormatted = _formatModelName(mainModel);
        const cheapFormatted = _formatModelName(cheapModel);

        let modelDisplay = mainFormatted || '?';
        if (cheapFormatted && cheapFormatted !== mainFormatted) {
          modelDisplay = mainFormatted + ' / ' + cheapFormatted;
        }

        const configName = (c.filename || '').replace(/\.(yaml|yml)$/i, '');
        const display = configName + ' — ' + modelDisplay;
        sel.innerHTML += '<option value="' + esc(c.path) + '"' + selected + '>' + esc(display) + '</option>';
      });
    }
  } catch(e) {
    showCfgStatus('加载配置失败: ' + e.message, 'error');
  }
}

function onConfigSelect(path) {
  if (!path) return;
  fetch('/api/configs').then(function(r) { return r.json(); }).then(function(d2) {
    const configs = d2.data || d2.configs || [];
    const cfg = configs.find(function(c) { return c.path === path; });
    if (cfg && cfg.main_model) {
      $('cfg-model').value = cfg.main_model.model_name || '';
      $('cfg-url').value = cfg.main_model.api_url || '';
      if (cfg.cheap_model) {
        $('cfg-cheap-model').value = cfg.cheap_model.model_name || '';
        $('cfg-cheap-url').value = cfg.cheap_model.api_url || '';
      }
    }
  }).catch(function(){});
}

window.applyConfig = async function() {
  const apiKey = $('cfg-key').value.trim();
  const apiUrl = $('cfg-url').value.trim();
  const modelName = $('cfg-model').value.trim();

  if (!apiUrl || !modelName) {
    showCfgStatus('请填写 API URL 和 模型名称', 'error');
    return;
  }

  if (isStreaming && !confirm('当前正在生成回复中，切换配置可能导致会话异常。\n确定要切换吗？')) return;

  function nv(id) { const v = $(id).value.trim(); return v ? Number(v) : null; }

  showCfgStatus('正在应用...', 'info');

  try {
    const body = {};
    if (apiKey) body.api_key = apiKey;
    body.api_url = apiUrl;
    body.model_name = modelName;
    body.temperature = nv('cfg-temp');
    body.max_tokens = nv('cfg-max-tokens');
    body.top_p = nv('cfg-top-p');
    body.max_context_tokens = nv('cfg-max-ctx');
    body.options = {
      supports_vision: $('cfg-vision').checked,
      supports_reasoning: $('cfg-reasoning').checked,
    };

    const cheapName = $('cfg-cheap-model').value.trim();
    const cheapUrl = $('cfg-cheap-url').value.trim();
    if (cheapName && cheapUrl) {
      const cheapKey = $('cfg-cheap-key').value.trim();
      if (cheapKey) body.cheap_api_key = cheapKey;
      body.cheap_api_url = cheapUrl;
      body.cheap_model_name = cheapName;
    }

    const r = await fetch('/api/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!d.ok) {
      showCfgStatus('失败: ' + (d.error || d.errors?.join(', ') || '未知错误'), 'error');
      return;
    }

    // Save runtime params
    const updates = {};
    const mi = nv('cfg-max-iter'); if (mi != null) updates.max_iterations = mi;
    const kt = nv('cfg-keep-turns'); if (kt != null) updates.keep_turns = kt;
    updates.enable_thinking = $('cfg-thinking').checked;

    if (Object.keys(updates).length > 0) {
      await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
    }

    showCfgStatus('✅ 已应用: ' + d.model, 'success');
    setTimeout(function() { closeModal('modal-config'); }, 1200);
  } catch(e) {
    showCfgStatus('失败: ' + e.message, 'error');
  }
};

function showCfgStatus(msg, type) {
  const el = $('cfg-status');
  if (!el) return;
  el.style.display = 'block';
  el.className = 'status-msg ' + (type || 'info');
  el.textContent = msg;
}

// ── New Config ──
window.showNewConfigModal = function() {
  closeModal('modal-config');
  showModal('modal-new-config');
  $('nc-status').style.display = 'none';
};

window.saveNewConfig = async function() {
  const filename = $('nc-filename').value.trim();
  const mainName = $('nc-main-name').value.trim();
  const mainUrl = $('nc-main-url').value.trim();
  const mainKey = $('nc-main-key').value.trim();

  if (!filename || !mainName || !mainUrl || !mainKey) {
    $('nc-status').style.display = 'block';
    $('nc-status').className = 'status-msg error';
    $('nc-status').textContent = '请填写完整信息';
    return;
  }

  $('nc-status').style.display = 'block';
  $('nc-status').className = 'status-msg info';
  $('nc-status').textContent = '保存中...';

  try {
    const body = { filename: filename, main_model_name: mainName, main_api_url: mainUrl, main_api_key: mainKey };
    const cheapName = $('nc-cheap-name').value.trim();
    const cheapUrl = $('nc-cheap-url').value.trim();
    const cheapKey = $('nc-cheap-key').value.trim();
    if (cheapName && cheapUrl) {
      body.cheap_model_name = cheapName;
      body.cheap_api_url = cheapUrl;
      if (cheapKey) body.cheap_api_key = cheapKey;
    }
    const r = await fetch('/api/config/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.ok) {
      $('nc-status').className = 'status-msg success';
      $('nc-status').textContent = '✓ 已保存: ' + d.filename;
      setTimeout(function() {
        closeModal('modal-new-config');
        closeModal('modal-config');
      }, 1200);
    } else {
      $('nc-status').className = 'status-msg error';
      $('nc-status').textContent = d.error || '保存失败';
    }
  } catch(e) {
    $('nc-status').className = 'status-msg error';
    $('nc-status').textContent = 'Error: ' + e.message;
  }
};

// ── Config Dropdown in Toolbar ──
function _formatModelName(modelName) {
  if (!modelName) return '';

  const specialMappings = {
    'gpt-4': 'GPT-4',
    'gpt-4-turbo': 'GPT-4 Turbo',
    'gpt-4o': 'GPT-4o',
    'gpt-4o-mini': 'GPT-4o Mini',
    'gpt-3.5-turbo': 'GPT-3.5 Turbo',
    'claude-3-opus': 'Claude 3 Opus',
    'claude-3-sonnet': 'Claude 3 Sonnet',
    'claude-3-haiku': 'Claude 3 Haiku',
    'claude-3.5-sonnet': 'Claude 3.5 Sonnet',
    'deepseek-chat': 'DeepSeek Chat',
    'deepseek-coder': 'DeepSeek Coder',
    'deepseek-r1': 'DeepSeek R1',
    'deepseek-v2': 'DeepSeek V2',
    'deepseek-v2.5': 'DeepSeek V2.5',
    'deepseek-v3': 'DeepSeek V3',
    'deepseek-v4': 'DeepSeek V4',
    'deepseek-v4-flash': 'DeepSeek V4 Flash',
    'deepseek-v4-pro': 'DeepSeek V4 Pro',
    'qwen-turbo': 'Qwen Turbo',
    'qwen-plus': 'Qwen Plus',
    'qwen-max': 'Qwen Max',
    'qwen-vl-plus': 'Qwen VL Plus',
    'qwen-vl-max': 'Qwen VL Max',
    'glm-4': 'GLM-4',
    'glm-3-turbo': 'GLM-3 Turbo',
    'gemini-1.5-pro': 'Gemini 1.5 Pro',
    'gemini-1.5-flash': 'Gemini 1.5 Flash',
    'gemini-2.0-flash': 'Gemini 2.0 Flash',
    'spark': 'Spark',
    'spark-max': 'Spark Max',
    'spark-lite': 'Spark Lite',
    'ernie-bot': 'Ernie Bot',
    'ernie-bot-turbo': 'Ernie Bot Turbo',
  };

  const lowerName = modelName.toLowerCase();
  if (specialMappings[lowerName]) {
    return specialMappings[lowerName];
  }

  // General conversion: replace hyphens and underscores with spaces, capitalize each word
  const words = modelName.replace(/[-_]/g, ' ').split(/\s+/);
  const formattedWords = words.map(function(word) {
    const lowerWord = word.toLowerCase();
    if (['gpt', 'api', 'ai', 'ml', 'llm', 'vl', 'r1', 'v2', 'v3', 'v4', 'v5'].includes(lowerWord)) {
      return word.toUpperCase();
    }
    if (/^\d+$/.test(word)) {
      return word;
    }
    return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
  });

  return formattedWords.join(' ');
}

async function refreshConfigDropdown() {
  try {
    const r = await fetch('/api/configs');
    if (!r.ok) return;
    const d = await r.json();
    const sel = $('config-dropdown');
    const configs = d.data || d.configs || [];
    const activePath = d.active_config_path || '';
    sel.innerHTML = '<option value="">⚡ 切换配置</option>';
    configs.forEach(function(c) {
      const mainModel = c.main_model ? (c.main_model.model_name || '') : '';
      const cheapModel = c.cheap_model ? (c.cheap_model.model_name || '') : '';
      const selected = c.path === activePath ? ' selected' : '';

      const mainFormatted = _formatModelName(mainModel);
      const cheapFormatted = _formatModelName(cheapModel);

      let modelDisplay = mainFormatted || '?';
      if (cheapFormatted && cheapFormatted !== mainFormatted) {
        modelDisplay = mainFormatted + ' / ' + cheapFormatted;
      }

      const configName = (c.filename || '').replace(/\.(yaml|yml)$/i, '');
      const display = configName + ' — ' + modelDisplay;
      sel.innerHTML += '<option value="' + esc(c.path) + '"' + selected + '>' + esc(display) + '</option>';
    });
  } catch(e) {}
}

window.switchConfig = async function(path) {
  if (!path) return;
  if (isStreaming && !confirm('当前正在生成回复中，切换配置可能导致会话异常。\n确定要切换吗？')) return;
  try {
    const r = await fetch('/api/model/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config_path: path }),
    });
    const d = await r.json();
    if (d.ok) {
      toast('✓ 已切换到配置', 'success');
      refreshConfigDropdown();
    } else {
      toast('✗ 切换失败', 'error');
    }
  } catch(e) {
    toast('Error: ' + e.message, 'error');
  }
};

// ══════════════════════════════════════════════════
//  EXPORT
// ══════════════════════════════════════════════════

window.showExportModal = function() {
  showModal('modal-export');
  $('export-result').innerHTML = '';
  // Reset to defaults
  const modeRadios = document.querySelectorAll('input[name="export-mode"]');
  if (modeRadios.length > 0) modeRadios[0].checked = true;
  const filterRadios = document.querySelectorAll('input[name="export-filter"]');
  if (filterRadios.length > 0) filterRadios[0].checked = true;
};

window.onExportModeChange = function() {
  $('export-result').innerHTML = '';
};

window.doExport = async function() {
  if (!currentTopicId) {
    $('export-result').innerHTML = '<div style="color:var(--red);font-size:13px">请先选择一个话题</div>';
    return;
  }
  const el = $('export-result');
  const modeEl = document.querySelector('input[name="export-mode"]:checked');
  const filterEl = document.querySelector('input[name="export-filter"]:checked');
  const mode = modeEl ? modeEl.value : 'latest';
  const filter = filterEl ? filterEl.value : 'final';
  el.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:8px 0">导出中...</div>';
  try {
    const url = '/v1/export/pdf/' + encodeURIComponent(currentTopicId)
      + '?mode=' + encodeURIComponent(mode)
      + '&filter=' + encodeURIComponent(filter);
    const r = await fetch(url, { method: 'GET' });
    const ct = r.headers.get('Content-Type') || '';
    if (ct.includes('application/pdf')) {
      // Download PDF directly
      const blob = await r.blob();
      let filename = 'export.pdf';
      const disp = r.headers.get('Content-Disposition') || '';
      const match = disp.match(/filename\*?=(?:UTF-8'')?([^;\s]+)/i);
      if (match) filename = decodeURIComponent(match[1].replace(/"/g, ''));
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
      el.innerHTML = '<div style="color:var(--green);font-size:13px">✅ 下载完成: ' + esc(filename) + '</div>';
    } else {
      // Error response (JSON)
      const d = await r.json();
      el.innerHTML = '<div style="color:var(--red);font-size:13px">' + esc(d.error || '导出失败') + '</div>';
    }
  } catch(e) {
    el.innerHTML = '<div style="color:var(--red);font-size:13px">Error: ' + esc(e.message) + '</div>';
  }
};

// ══════════════════════════════════════════════════
//  QUESTION DIALOG & MAX_ITER CONFIRM
// ══════════════════════════════════════════════════

function showQuestionDialog(qid, title, question, options, defaultVal) {
  // Simple implementation — uses the global window methods
  const answer = prompt((title || '问题') + ': ' + (question || ''));
  if (answer !== null) {
    fetch('/api/chat/question', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_id: qid, answer: answer })
    }).catch(function(){});
  } else {
    fetch('/api/chat/question', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_id: qid, answer: defaultVal || '' })
    }).catch(function(){});
  }
}

function showMaxIterConfirm(confirmId, text) {
  const cont = confirm((text || '已达到工具调用次数上限') + '\n\n继续执行吗？');
  fetch('/api/chat/continue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm_id: confirmId, continue: cont })
  }).catch(function(){});
}

// ══════════════════════════════════════════════════
//  BUTTON STYLES (re-export for HTML onclick)
// ══════════════════════════════════════════════════

// Ensure btn-g, btn-p, btn-sm classes exist in JS context
// (CSS already has them)

// ══════════════════════════════════════════════════
//  INIT
// ══════════════════════════════════════════════════

refreshTopics();
refreshConfigDropdown();
refreshTaskPanel();

// Auto-refresh topics every 30s
setInterval(refreshTopics, 30000);

// ══════════════════════════════════════════════════
//  FILE TREE NAVIGATION
//  ══════════════════════════════════════════════════

let _fileTreeOpen = false;
let _fileTreeCache = {};

window.toggleFileTree = function() {
  var panel = $('file-tree-panel');
  if (!panel) return;
  _fileTreeOpen = !_fileTreeOpen;
  panel.style.display = _fileTreeOpen ? '' : 'none';
  if (_fileTreeOpen && !_fileTreeCache['/']) {
    loadFileTree('');
  }
};

window.loadFileTree = async function(path) {
  var container = $('file-tree-content');
  if (!container) return;
  
  if (!path && _fileTreeCache['/']) {
    // 使用缓存
    renderFileTree(_fileTreeCache['/'], container);
    return;
  }
  
  container.innerHTML = '<div class="ft-loading">📂 加载中...</div>';
  
  try {
    var url = '/api/files';
    if (path) url += '?path=' + encodeURIComponent(path);
    var res = await fetch(url);
    var data = await res.json();
    if (!data.ok) {
      container.innerHTML = '<div class="ft-loading" style="color:var(--red)">❌ ' + esc(data.error) + '</div>';
      return;
    }
    // 缓存根目录
    if (!path) _fileTreeCache['/'] = data.items;
    renderFileTree(data.items, container, path);
  } catch(e) {
    container.innerHTML = '<div class="ft-loading" style="color:var(--red)">❌ ' + esc(e.message) + '</div>';
  }
};

function renderFileTree(items, container, parentPath) {
  if (!items || !items.length) {
    container.innerHTML = '<div class="ft-loading">(空目录)</div>';
    return;
  }
  var html = '<div class="ft-children">';
  items.forEach(function(item) {
    var isDir = item.type === 'dir';
    var icon = isDir ? '📁' : getFileIcon(item.ext || '');
    var sizeStr = item.size ? formatSize(item.size) : '';
    html += '<div class="ft-item ' + (isDir ? 'ft-dir' : 'ft-file') + '"'
      + ' onclick="' + (isDir ? 'loadFileTree(\'' + escAttr(item.path) + '\')' : 'openFile(\'' + escAttr(item.path) + '\')') + '"'
      + ' title="' + escAttr(item.name) + '">'
      + '<span class="ft-icon">' + icon + '</span>'
      + '<span class="ft-name">' + esc(item.name) + '</span>'
      + (sizeStr ? '<span class="ft-size">' + sizeStr + '</span>' : '')
      + '</div>';
  });
  html += '</div>';
  container.innerHTML = html;
}

function getFileIcon(ext) {
  var icons = {
    '.py': '🐍', '.js': '📜', '.ts': '📘', '.html': '🌐', '.css': '🎨',
    '.json': '📋', '.yaml': '⚙', '.yml': '⚙', '.toml': '⚙',
    '.md': '📝', '.txt': '📄', '.csv': '📊',
    '.sh': '💻', '.bat': '💻', '.ps1': '💻',
    '.c': '⚡', '.cpp': '⚡', '.h': '🔧', '.hpp': '🔧',
    '.java': '☕', '.rs': '🦀', '.go': '🔵', '.rb': '💎',
    '.sql': '🗄', '.db': '🗄', '.sqlite': '🗄',
    '.gitignore': '🔒', '.dockerignore': '🔒',
    '.env': '🔑', '.yaml': '⚙',
    '.xml': '📰', '.svg': '🎨',
  };
  return icons[ext] || '📄';
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + 'B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB';
  return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
}

window.openFile = async function(filePath) {
  try {
    var res = await fetch('/api/file?path=' + encodeURIComponent(filePath));
    var data = await res.json();
    if (!data.ok) {
      toast('❌ ' + (data.error || '读取失败'), 'error');
      return;
    }
    // 在消息区域显示文件内容
    var msgs = $('msgs');
    var div = document.createElement('div');
    div.className = 'file-view';
    div.innerHTML = '<div class="file-view-header">'
      + '<span>📄 ' + esc(filePath) + '</span>'
      + '<button class="tb-btn" onclick="closeFileView(this)" title="关闭">✕</button>'
      + '</div>'
      + '<pre class="file-view-content"><code>' + esc(data.content || '') + '</code></pre>';
    // 插入到消息区域顶部
    msgs.insertBefore(div, msgs.firstChild);
  } catch(e) {
    toast('❌ ' + e.message, 'error');
  }
};

window.closeFileView = function(btn) {
  var view = btn.closest('.file-view');
  if (view) view.remove();
};

// Expose helpers globally
window.showModal = showModal;
window.closeModal = closeModal;
window.toast = toast;

})();
