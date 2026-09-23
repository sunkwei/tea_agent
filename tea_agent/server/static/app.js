
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
let _bgPollFailures = 0;         // 连续轮询失败次数（server 重启窗口内容忍重试）

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
  _updateQueueButton();
  // 同步移除服务端排队项，避免工具循环仍注入已取消的消息
  if (removed.item_id && currentTopicId) {
    fetch('/api/queue/' + encodeURIComponent(currentTopicId) + '/' + encodeURIComponent(removed.item_id),
      { method: 'DELETE' }).catch(function(){});
  }
  toast('🗑 已取消: ' + (removed.text || '(图片)'), 'success');
};

// ── DOM Helpers ──
const $ = id => document.getElementById(id);
const esc = t => { if (!t) return ''; const d = document.createElement('div'); d.textContent = t; return d.innerHTML; };
const escAttr = t => String(t).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
// 🆕 内联 JS 字符串参数转义（用于 onclick="fn('...')" 场景，如主题标题、文件路径）
// 先做 JS 转义（\ ' ），再做 HTML 属性转义（" & < >）。
// 浏览器先解码 HTML 实体（&quot;→"）再执行 JS，顺序不能反。
const jsAttr = s => String(s)
  .replace(/\\/g, '\\\\')
  .replace(/'/g, "\\'")
  .replace(/"/g, '&quot;')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;');

// 🆕 解码 HTML 实体（在 esc() 前使用，防止双重转义）
// 多轮字符串替换，支持级联解码： &amp;lt; → &lt; → <
// 纯文本替换而非 DOM（避免 < 被浏览器当标签吃掉）
const decodeEntities = t => {
  if (!t) return '';
  let result = t;
  for (let i = 0; i < 5; i++) {
    const prev = result;
    result = result
      .replace(/&#39;/g, "'")
      .replace(/&#x27;/g, "'")
      .replace(/&quot;/g, '"')
      .replace(/&gt;/g, '>')
      .replace(/&lt;/g, '<')
      .replace(/&amp;/g, '&');
    if (result === prev) break;
  }
  return result;
};

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
  { name: '/export',     icon: '📄', desc: '导出 Markdown/PDF',       action: 'export' },
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
let _turnCounter = 0; // 对话轮次计数器（每条用户消息 = 1 轮）

function addMessage(role, content, images, convId) {
  const welcome = document.querySelector('.welcome');
  if (welcome) welcome.remove();

  const div = document.createElement('div');
  div.className = 'msg ' + (role === 'user' ? 'user' : 'assistant');
  div.dataset.msgIdx = _msgCounter++; // 给每条消息一个唯一递增索引
  // 后端会话 ID：分叉（#分叉）需要它作为边界点。仅历史加载时已知；
  // 刚发出的消息尚未落库，此时为空 —— 分叉以历史 tag 为锚点，属预期。
  if (convId !== undefined && convId !== null && convId !== '') {
    div.dataset.convId = String(convId);
  }

  // 轮次标记：每条用户消息视为一轮，插入明显的分隔条
  if (role === 'user') {
    _turnCounter++;
    const divider = document.createElement('div');
    divider.className = 'turn-divider';
    divider.innerHTML = '<span class="turn-badge">第 ' + _turnCounter + ' 轮</span>';
    $('msgs').appendChild(divider);
  }

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

/** 确保工具调用折叠容器存在（tool_parallel 事件使用，不依赖 tool_start 先到达） */
function _ensureToolCallContainer(s) {
  if (s.toolCallContainer) return s.toolCallContainer;
  s.toolCallContainer = document.createElement('div');
  s.toolCallContainer.className = 'tool-call-container collapsed';
  if (s.bubbleText && s.bubbleText.parentNode) {
    // 插入到 bubble-text 之前（使 AI 消息出现在最底部）
    s.bubbleText.parentNode.insertBefore(s.toolCallContainer, s.bubbleText);
  } else {
    const lastBubble = $('msgs').querySelector('.msg.assistant:last-child .msg-bubble');
    if (lastBubble) lastBubble.insertBefore(s.toolCallContainer, lastBubble.querySelector('.bubble-text'));
  }
  s.toolCallSummary = document.createElement('div');
  s.toolCallSummary.className = 'tool-call-summary';
  s.toolCallSummary.innerHTML = '<span class="tool-call-summary-icon">🛠</span>'
    + '<span class="tool-call-summary-label">工具调用</span>'
    + '<span class="tool-call-summary-badge">0</span>'
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
  s.toolCallList.style.display = 'none';
  s.toolCallContainer.appendChild(s.toolCallList);
  return s.toolCallContainer;
}

/** 渲染"并行工具批次"聚合条目（避免 [PARALLEL:...] 标记泄漏为聊天文本） */
function _renderToolParallel(s, namesStr) {
  removeLoading();
  _ensureToolCallContainer(s);
  if (!s.toolCallList) return;
  const names = (namesStr || '').split(',').map(function(n) { return n.trim(); }).filter(Boolean).join(', ');
  const item = document.createElement('details');
  item.className = 'tool-call-item parallel';
  item.innerHTML = '<summary class="tool-call-header">'
    + '<span class="tool-call-icon">⚡</span>'
    + '<span class="tool-call-name">并行执行: ' + esc(names || '多工具') + '</span>'
    + '<span class="tool-call-status status-done">并行</span>'
    + '</summary>';
  s.toolCallList.appendChild(item);
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
 * 选中的分叉点（历史 tag）：{convId, idx, snippet} | null
 * 由跳转栏点选，供输入框的 `#分叉` 前缀消费。
 */
let _forkAnchor = null;

/**
 * 渲染跳转栏：遍历 #msgs 中的 .msg.user，生成可点击的 chip
 * 每个 chip 显示用户消息的前 20 字摘要，点击滚动到对应消息；
 * 若该消息有后端会话 ID（历史消息），点击同时选为 `#分叉` 的分叉点。
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
    const convId = msg.dataset.convId || '';
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
    const isSel = (_forkAnchor && _forkAnchor.idx === idx) ? ' selected' : '';
    // 无 convId（本会话刚发、尚未回填）→ 只能跳转，不能作分叉点
    const action = convId
      ? 'onclick="selectJumpChip(' + idx + ',\'' + convId + '\')"'
      : 'onclick="jumpToMessage(' + idx + ')"';
    const tip = convId
      ? '点击跳转，并选为 #分叉 的分叉点'
      : (bubble ? bubble.textContent.trim().slice(0, 60) : '');
    html += '<span class="jump-chip' + isSel + '" ' + action
      + ' title="' + escAttr(tip) + '">'
      + esc(snippet) + '</span>';
  });
  if (_forkAnchor) {
    html += '<span class="jump-fork-hint">⑂ 已选分叉点 · 输入 #分叉 从此处分叉</span>';
  }
  bar.innerHTML = html;
}

/**
 * 点选跳转 chip：跳转到该消息，并把它设为 `#分叉` 的分叉点。
 * 再次点击同一个 chip → 取消选择。
 */
window.selectJumpChip = function selectJumpChip(idx, convId) {
  if (_forkAnchor && _forkAnchor.idx === idx) {
    _forkAnchor = null;
  } else {
    const el = document.querySelector('.msg[data-msg-idx="' + idx + '"]');
    const bubble = el ? el.querySelector('.msg-bubble') : null;
    _forkAnchor = {
      idx: idx,
      convId: convId,
      snippet: bubble
        ? bubble.textContent.replace(/\s+/g, ' ').trim().replace(/\(图片\)/g, '').slice(0, 30)
        : ''
    };
  }
  jumpToMessage(idx);
  renderJumpBar();
};

/**
 * 执行 `#分叉`：以选中的历史 tag 为分叉点，把该 tag **及其之前**的对话
 * 复制成新主题。新主题标题为 `#分叉: <描述>`，该前缀受后端保护，
 * 不会被自动摘要改写。
 *
 * @param {string} raw 输入框原文（形如 `#分叉 实验A` 或 `#分叉: 实验A`）
 */
async function _doForkTopic(raw) {
  const input = $('ci');
  if (!currentTopicId) {
    toast('请先打开一个话题再分叉', 'warning');
    return;
  }
  if (!_forkAnchor) {
    toast('请先在上方「📜 跳转」区点选一个历史 tag 作为分叉点', 'warning');
    return;
  }
  // 描述：`#分叉` 之后的文本（容忍 `:` / `：` 分隔）；缺省用分叉点消息摘要
  const desc = raw.replace(/^#分叉\s*[:：]?\s*/, '').trim();
  const label = desc || _forkAnchor.snippet || '分支';

  try {
    const r = await fetch('/api/topic/' + encodeURIComponent(currentTopicId) + '/fork', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boundary_conv_id: _forkAnchor.convId, title: label }),
    });
    const d = await r.json();
    if (!d.ok) {
      toast('❌ 分叉失败: ' + (d.error || '未知错误'), 'error');
      return;
    }
    input.value = '';
    input.style.height = 'auto';
    _forkAnchor = null;
    toast('⑂ 已分叉到新主题：' + (d.title || ''), 'success');
    await refreshTopics();
    if (d.target_topic_id) openTopic(d.target_topic_id, d.title || '');
  } catch (e) {
    toast('❌ 分叉请求失败: ' + e.message, 'error');
  }
}

/* ════════════════════════════════════════════════════════════
 * 轨迹视图 — 借鉴 DeepSeek Harness Trajectory
 * 从 session_events 重建 Agent 执行过程：用户输入 → 思考链 →
 * 工具调用(参数) → 工具结果 → AI 回复，彩色时间线展示。
 * ════════════════════════════════════════════════════════════ */
let _trajectoryOpen = false;

/** 切换轨迹面板显示 */
window.toggleTrajectory = function () {
  const panel = document.getElementById('trajectory-panel');
  if (!panel) return;
  _trajectoryOpen = !_trajectoryOpen;
  panel.style.display = _trajectoryOpen ? 'block' : 'none';
  if (_trajectoryOpen) loadTrajectory();
};

/** 加载当前 topic 的轨迹数据 */
async function loadTrajectory() {
  const panel = document.getElementById('trajectory-panel');
  if (!panel) return;
  if (!currentTopicId) {
    panel.innerHTML = '<div class="traj-empty">暂无会话，先发送一条消息吧</div>';
    return;
  }
  panel.innerHTML = '<div class="traj-loading">⏳ 加载轨迹…</div>';
  try {
    const r = await fetch('/api/topic/' + currentTopicId + '/trajectory');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    renderTrajectory(panel, d.timeline || []);
  } catch (e) {
    panel.innerHTML = '<div class="traj-error">⚠ 轨迹加载失败: ' + esc(e.message) + '</div>';
  }
}

/** 渲染彩色轨迹时间线 */
function renderTrajectory(panel, timeline) {
  if (!timeline.length) {
    panel.innerHTML = '<div class="traj-empty">暂无轨迹数据 —— 工具调用事件将在新会话中记录（旧会话仅有对话记录）</div>';
    return;
  }
  let html = '<div class="traj-header">🛤 执行轨迹'
    + '<span class="traj-count">' + timeline.length + ' 步</span>'
    + '<button class="traj-close" onclick="toggleTrajectory()" title="关闭">✕</button></div>';
  html += '<div class="traj-list">';
  timeline.forEach(function (item) {
    const t = item.type || '';
    let cls = 'traj-item traj-' + t;
    if (t === 'tool_result' && !item.success) cls += ' traj-fail';
    html += '<div class="' + cls + '">';
    if (t === 'user') {
      html += '<div class="traj-icon">👤</div><div class="traj-body">'
        + '<div class="traj-title">用户输入</div>'
        + '<div class="traj-content">' + esc(item.content) + '</div></div>';
    } else if (t === 'thinking') {
      html += '<div class="traj-icon">💭</div><div class="traj-body">'
        + '<div class="traj-title">思考</div>'
        + '<div class="traj-content traj-thinking-text">' + esc(item.content) + '</div></div>';
    } else if (t === 'tool_call') {
      html += '<div class="traj-icon">⚡</div><div class="traj-body">'
        + '<div class="traj-title">工具调用 · ' + esc(item.name) + '</div>'
        + '<details class="traj-details"><summary>参数</summary><pre>' + esc(item.args) + '</pre></details></div>';
    } else if (t === 'tool_result') {
      const ok = item.success ? '✅' : '❌';
      const dur = item.duration_ms ? ' · <span class="traj-dur">' + item.duration_ms + 'ms</span>' : '';
      html += '<div class="traj-icon">' + ok + '</div><div class="traj-body">'
        + '<div class="traj-title">' + esc(item.name) + (item.success ? ' 成功' : ' 失败') + dur + '</div>';
      if (item.error) html += '<div class="traj-content traj-error-text">' + esc(item.error) + '</div>';
      html += '<details class="traj-details"><summary>结果</summary><pre>' + esc(item.result || '') + '</pre></details></div>';
    } else if (t === 'assistant') {
      html += '<div class="traj-icon">🤖</div><div class="traj-body">'
        + '<div class="traj-title">AI 回复</div>'
        + '<div class="traj-content">' + esc(item.content) + '</div></div>';
    } else {
      html += '<div class="traj-icon">•</div><div class="traj-body"><div class="traj-content">' + esc(item.content || '') + '</div></div>';
    }
    html += '</div>';
  });
  html += '</div>';
  panel.innerHTML = html;
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
  // 🆕 先解码已有 HTML 实体（如 &lt;→<），再 esc() 防双重转义
  let html = esc(decodeEntities(text)).replace(/\r\n/g, '\n');

  // Protect code blocks — 内容已被 esc() 单次编码，不能再次 esc() 导致双重转义
  const codeBlocks = [];
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function(match, lang, code) {
    const idx = codeBlocks.length;
    const langLabel = lang ? '<span class="code-lang">' + esc(lang) + '</span>' : '';
    const trimmedCode = code.trimEnd();
    // 还原原始文本给复制按钮
    const originalCode = decodeEntities(trimmedCode);
    codeBlocks.push(
      '<div class="code-block-wrapper">'
      + '<div class="code-block-header">'
      + langLabel
      + '<button class="copy-btn" onclick="copyCode(this)" data-code="' + escAttr(originalCode) + '">📋 复制</button>'
      + '</div>'
      + '<pre><code class="lang-' + esc(lang) + '">' + trimmedCode + '</code></pre>'
      + '</div>'
    );
    return '\x00CODE' + idx + '\x00';
  });

  // 🆕 Inline code — 内容已被 esc() 编码一次，禁止再次 esc() 双重转义
  html = html.replace(/`([^`]+)`/g, function(match, code) {
    return '<code class="md-inline-code">' + code + '</code>';
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

  // Lists (unordered / ordered) — 逐行扫描，禁止 \s 跨行匹配
  //   旧写法 `^(\s*\d+\.\s+.+...)$` 里的 \s 会吞掉列表前的空行（标题/段落与列表之间
  //   按 Markdown 惯例有空行），匹配串因此以 '\n' 开头，split('\n') 后首元素为空串
  //   → 凭空多出一个空 <li>：两条数据渲染成「1. / 2. / 3.」，且 <ol> 自动编号整体后移，
  //   显示序号与源码序号错位（列表前的空行越多，幽灵条目越多）。
  const listBlocks = [];
  const LIST_MARKER = /^[ \t]*([-*+]|\d+\.)[ \t]+(\S.*)$/;
  const isOrderedMarker = m => m !== '-' && m !== '*' && m !== '+';
  const listLines = html.split('\n');
  const listOut = [];
  for (let i = 0; i < listLines.length; i++) {
    const first = LIST_MARKER.exec(listLines[i]);
    if (!first) { listOut.push(listLines[i]); continue; }
    const ordered = isOrderedMarker(first[1]);
    const items = [first[2]];
    const start = ordered ? parseInt(first[1], 10) : 1;
    let j = i + 1;
    while (j < listLines.length) {
      const next = LIST_MARKER.exec(listLines[j]);
      if (next) {
        if (isOrderedMarker(next[1]) !== ordered) break;   // 类型切换 → 另起一个列表
        items.push(next[2]);
        j++;
        continue;
      }
      // 松散列表：条目之间的空行不结束列表（旧实现把它变成一个空条目）
      if (listLines[j].trim() === '') {
        let k = j;
        while (k < listLines.length && listLines[k].trim() === '') k++;
        const after = k < listLines.length ? LIST_MARKER.exec(listLines[k]) : null;
        if (after && isOrderedMarker(after[1]) === ordered) { j = k; continue; }
      }
      break;
    }
    const tag = ordered ? 'ol' : 'ul';
    // 保留源起编号（如从 2. 开始）—— 否则 <ol> 一律从 1 重排，与原文序号对不上
    const startAttr = ordered && start > 1 ? ' start="' + start + '"' : '';
    const itemsHtml = items.map(function(t) {
      return '<li class="md-li">' + t + '</li>';
    }).join('');
    const idx = listBlocks.length;
    listBlocks.push('<' + tag + ' class="md-' + tag + '"' + startAttr + '>' + itemsHtml + '</' + tag + '>');
    listOut.push('\x00LIST' + idx + '\x00');
    i = j - 1;
  }
  html = listOut.join('\n');

  // Blockquotes（同样只吃空格/制表符：`\s` 会把引用行与下一行并成一条引用）
  html = html.replace(/^&gt;[ \t](.+)$/gm, '<blockquote class="md-blockquote">$1</blockquote>');
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
  html = html.replace(/\x00LIST(\d+)\x00/g, function(m, idx) { return listBlocks[idx] || ''; });
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
  // ⭐ 启动后台轮询，获取打断后的最终 AI 回复（后台线程继续运行至完成并写入 buffer）
  if (currentTopicId) {
    _startBackgroundPoll(currentTopicId);
  }
  const bubbleText = document.getElementById('bubble-text');
  if (bubbleText && !bubbleText.innerHTML.trim()) {
    bubbleText.innerHTML = '(已中断)';
  }
};

// ── Helper: 流式生成中入队排队 ──
function _enqueueMessage(msg, images) {
  const item = { text: msg, images: [...images], item_id: null };
  _messageQueue.push(item);
  _pendingImages = [];
  updateImagePreview();
  renderQueueList();
  _updateQueueButton();
  toast(`⏳ 消息已排队（队列中 ${_messageQueue.length} 条），将在下一轮工具处理时生效`, 'success');
  // 立即投递到服务端插话队列：工具循环在下一轮边界消费并注入
  _sendSteering(item);
}

// ── Helper: 发送按钮状态（排队数 / 中断 / 发送） ──
function _updateQueueButton() {
  const btn = $('send-btn');
  if (!btn) return;
  const qlen = _messageQueue.length;
  if (qlen > 0) {
    btn.textContent = `⏳ 排队 ${qlen}`;
    btn.className = 'btn btn-p warning';
  } else if (isStreaming) {
    btn.textContent = '⏹ 中断';
    btn.className = 'btn btn-p danger';
  } else {
    btn.textContent = '发送';
    btn.className = 'btn btn-p';
  }
  btn.disabled = false;
}

// ── Helper: 投递插话到服务端队列（steering） ──
function _sendSteering(item) {
  if (item.item_id || item._sending) return; // 已投递或投递中
  if (!currentTopicId) return; // 尚未拿到 topic_id（首次对话）：留在本地队列，流结束后按普通消息发送
  item._sending = true;
  const body = { topic_id: currentTopicId, message: item.text };
  if (item.images && item.images.length > 0) body.images = item.images;
  fetch('/api/chat/steering', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(function(r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function(data) {
    item._sending = false;
    if (data && data.ok) {
      item.item_id = data.item_id;
    } else {
      throw new Error((data && data.error) || 'steering failed');
    }
  }).catch(function() {
    item._sending = false;
    // 投递失败：留在本地队列，流结束后按普通消息重发（不阻塞用户）
    toast('⚠️ 插话投递失败，将排队到本次对话结束后发送', 'warning');
  });
}

// ── Helper: 处理插话生效事件（从本地队列移除 + 渲染到聊天区） ──
function _handleSteeringInjected(data) {
  const sid = data.item_id;
  let removed = false;
  if (sid) {
    for (let i = 0; i < _messageQueue.length; i++) {
      if (_messageQueue[i].item_id === sid) {
        const it = _messageQueue.splice(i, 1)[0];
        removed = true;
        if (it.text) addMessage('user', it.text, it.images && it.images.length > 0 ? it.images : null);
        break;
      }
    }
  }
  if (!removed && data.text) {
    // 来自其它标签页/客户端的插话：无本地项，直接渲染
    addMessage('user', data.text);
  }
  renderQueueList();
  _updateQueueButton();
  toast('⚡ 插话已生效，将在下一轮处理', 'success');
}

// ── 实时解码速率（回合进行中）──
// 服务端只能在一次流读完后才知道 completion_tokens，因此**生成过程中**的
// 速率只能由前端估算：按与后端 estimate_tokens 相同的启发式
// （中文 1.5 字/tok、其它 4 字符/tok）累计字符，除以「首 token → 当前」的窗口。
// 口径与实测值不同，因此：① 用 ⏱ 前缀 + 独立样式标记为估算；② 实测值一到就覆盖。
function _countCnChars(str) {
  let n = 0;
  for (const ch of str) {
    const c = ch.codePointAt(0);
    if ((c >= 0x4e00 && c <= 0x9fff) || (c >= 0x3400 && c <= 0x4dbf)) n++;
  }
  return n;
}

function _noteStreamChars(s, text) {
  if (!text) return;
  s.speedChars += text.length;
  s.speedCn += _countCnChars(text);
  const now = Date.now();
  if (!s.speedT0) s.speedT0 = now;   // 首 token 才起算：排队/prefill 不属于解码
  s.speedT1 = now;
}

function _updateLiveSpeed(s, force) {
  const el = $('speed-live');
  if (!el) return;
  const now = Date.now();
  if (!force) {
    if (now - _lastLiveSpeedRender < 250) return;   // 节流：每 token 刷 DOM 会拖慢流式
    _lastLiveSpeedRender = now;
  }
  const win = s.speedT0 ? (s.speedT1 - s.speedT0) / 1000 : 0;
  const toks = s.speedCn / 1.5 + (s.speedChars - s.speedCn) / 4.0;
  // 样本太少时速率毫无统计意义（首包抖动就能翻倍），宁可空着
  if (!s.speedT0 || win < 0.8 || toks < 12) {
    if (force) { el.style.display = 'none'; el.textContent = ''; }
    return;
  }
  const tps = toks / win;
  if (!isFinite(tps) || tps <= 0) return;
  el.textContent = '⏱ ~' + tps.toFixed(1) + ' tok/s';
  el.title = '实时估算：按字符启发式换算，与回合结束后的实测值（⚡）口径不同';
  el.style.display = '';
}

function _hideLiveSpeed() {
  const el = $('speed-live');
  if (el) { el.style.display = 'none'; el.textContent = ''; }
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
    // 实时速率估算计数（字符/中文字数/首末 token 时刻）
    speedChars: 0,
    speedCn: 0,
    speedT0: 0,
    speedT1: 0,
  };
}

// ── Helper: 流结束后清理并发送排队消息 ──
function _processQueueAfterStream() {
  _liveTpsStop();   // 流已结束：实时估算值失效，改用服务端实测值
  _liveTps.text = '';
  if (_pendingUsage) {
    updateUsage(_pendingUsage);
    _pendingUsage = null;
  } else if (_lastUsageData) {
    // 无最终 usage 载荷（如错误/中断）：至少把实时估算段从上一版渲染里去掉
    var bar = $('usage-bar');
    if (bar) {
      bar.innerHTML = _usageBarHtml(_lastUsageData, '');
      bar.className = 'usage-bar';
    }
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
    // 若该项曾投递到服务端插话队列但未被注入（流已结束），先删除服务端
    // 排队项，避免下轮对话的工具循环重复注入（内容随后经 /api/chat 重发）
    if (next.item_id && currentTopicId) {
      fetch('/api/queue/' + encodeURIComponent(currentTopicId) + '/' + encodeURIComponent(next.item_id),
        { method: 'DELETE' }).catch(function(){});
    }
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
  // ── #分叉：从选中的历史 tag 分叉出新主题（属控制命令，不发送消息）──
  const _forkRaw = $('ci').value.trim();
  if (_forkRaw.startsWith('#分叉')) {
    await _doForkTopic(_forkRaw);
    return;
  }

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
  _liveTpsReset();   // 重置实时解码速度采样（首增量到达后才开始计时）

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
              _noteStreamChars(s, data.text);
              _updateLiveSpeed(s);
              s.bubbleText.innerHTML = esc(decodeEntities(s.fullText));
              if (_liveTpsTick(data.text)) _paintLiveTps();
              break;

            case 'think_start':
              if (!s.thinkContainer) {
                // 创建容器（类似 tool-call-container）— 默认折叠，与工具调用一致
                s.thinkContainer = document.createElement('div');
                s.thinkContainer.className = 'think-container collapsed';
                s.bubbleText.parentNode.insertBefore(s.thinkContainer, s.bubbleText);
                // 摘要栏（默认折叠）
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
                // 列表容器（默认折叠，与工具调用一致）
                s.thinkList = document.createElement('div');
                s.thinkList.className = 'think-list';
                s.thinkList.style.display = 'none';
                s.thinkContainer.appendChild(s.thinkList);
              }
              // 每次新的思考轮次创建独立条目
              s.thinkCount++;
              var badge = s.thinkContainer.querySelector('.think-summary-badge');
              if (badge) badge.textContent = s.thinkCount;
              var entry = document.createElement('details');
              entry.className = 'think-entry';
              // 默认不 open：折叠状态，与工具调用条目一致
              entry.innerHTML = '<summary>思考 #' + s.thinkCount + '</summary><div class="think-content"></div>';
              s.thinkList.appendChild(entry);
              s.thinkContent = entry.querySelector('.think-content');
              break;

            case 'think':
              if (s.thinkContent) {
                s.thinkContent.textContent += data.text;
              }
              // 推理 token 同样计入解码速度（服务端口径为 completion_tokens 全体）
              if (_liveTpsTick(data.text)) _paintLiveTps();
              break;

            case 'think_done':
              // 更新 title 摘要，保持折叠状态不变（与工具调用一致）
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

            case 'tool_parallel': {
              _renderToolParallel(s, data.names);
              break;
            }

            case 'tool_start': {
              s.activeToolName = data.name;
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
              _throttledTaskRefresh();   // 工具完成 → 刷新任务面板 TODO
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

            case 'usage':
              // 实时 token 用量 / 命中率 / 上下文占用（每轮 LLM 调用后推送）
              if (data.usage && currentTopicId === (data.topic_id || currentTopicId)) {
                updateUsage(data.usage);
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
              _updateLiveSpeed(s, true);   // 收尾：按最终字符数定格一次
              _hideLiveSpeed();            // 实测值（⚡）随后接管，估算（⏱ ~）退场
              // 记录 token 用量（延迟显示，等流结束后才更新 UI）
              if (data.usage) _pendingUsage = data.usage;
              // 更新 topic_id（首次消息后更新）
              if (data.topic_id && data.topic_id !== currentTopicId) {
                currentTopicId = data.topic_id;
                refreshTopics();
              }
              // 用 Markdown 重新渲染 AI 最终消息（流式 token 只是 esc 纯文本）
              var finalMsg = data.ai_msg || s.fullText;
              if (finalMsg && s.bubbleText) {
                s.bubbleText.innerHTML = formatMarkdown(finalMsg);
                // 移除 tool/think 容器中的 id，避免下次流式清理时误删
                if (s.thinkContainer) s.thinkContainer.removeAttribute('id');
                if (s.toolCallContainer) s.toolCallContainer.removeAttribute('id');
              }
              markTitleDone();
              renderJumpBar(); // 新消息完成 -> 更新跳转栏
              _throttledTaskRefresh(); // 流结束 → 刷新任务面板 TODO
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

            case 'topic_ready':
              // 首次对话：尽早拿到 topic_id（用于投递插话 /api/chat/steering）
              if (data.topic_id && data.topic_id !== currentTopicId) {
                currentTopicId = data.topic_id;
                refreshTopics();
                // 之前因无 topic_id 未投递的本地排队项，现在补投
                _messageQueue.forEach(function(it) {
                  if (!it.item_id && !it._sending) _sendSteering(it);
                });
              }
              break;

            case 'steering_injected':
              _handleSteeringInjected(data);
              break;

            case 'queued':
              removeLoading();
              _hideLiveSpeed();
              isStreaming = false;
              // 恢复发送按钮
              var sb = document.getElementById('send-btn');
              if (sb) { sb.textContent = '发送'; sb.className = 'btn btn-p'; sb.disabled = false; }
              // 清理 DOM 避免残留
              var oldMsg = document.getElementById('current-ai-msg');
              if (oldMsg) { oldMsg.removeAttribute('id'); oldMsg.querySelector('.msg-bubble').removeAttribute('id'); }
              toast('⏳ 消息已入插话队列，将在当前对话的下一轮生效', 'success');
              // 启动后台轮询，等待队列处理完成
              if (data.topic_id) {
                _startBackgroundPoll(data.topic_id);
              }
              break;

            case 'error':
              removeLoading();
              _hideLiveSpeed();
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
      _hideLiveSpeed();
      const bt = $('bubble-text');
      if (bt && !bt.innerHTML.trim()) bt.innerHTML = '(已中断)';
      // ⭐ 安全网：后台线程仍在运行，启动轮询获取最终 AI 回复
      //    覆盖场景：Escape 打断、网络闪断、用户切换主题（当前流是未过期的）
      if (myGen === _streamGeneration && currentTopicId) {
        _checkBackgroundAndPoll(currentTopicId);
      }
    } else if (myGen === _streamGeneration && currentTopicId) {
      _hideLiveSpeed();
      // 非主动取消的流中断（网络闪断 / server 正在重启）→ 进入重连续读：
      // 由后台缓冲区补齐已产出内容；服务端重启后会把在途回合快照重建为缓冲区，
      // 因此「已产出的内容」不会丢失。
      removeLoading();
      _enterReconnectMode(currentTopicId);
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

/* 注：原 _fmtNum（千分位格式化）随 T:(P+C) 令牌明细一起移除 —— 明细已不再显示，
   保留会变成无引用的死代码。若将来重新展示原始 token 数，可一并恢复。 */

/**
 * 后端 usage 事件 → usage-bar 的 HTML 片段（纯函数，便于单独验证与复用）。
 *
 * 解码速度（tok/s）取自服务端实测值（decode_tps_text，口径 = 本轮输出 token /
 * 首增量→流结束）；服务端未提供时回退到前端本地实时估算（_liveTpsText），
 * 两者都可能是空串 —— 此时该段整体不渲染，而不是显示 0 tok/s。
 */
function _usageBarHtml(usage, liveTpsText) {
  // 展示顺序（2026-09-19 起）：tok/s → 主模型 Provider+model → 命中率 → 上下文用量。
  // 已移除：T:(P+C) 明细、便宜模型、便宜模型命中率 —— 令牌明细噪音大且可从
  // 上下文用量推知量级，便宜模型属内部调度细节、用户无需在状态栏盯。
  //
  // 主模型：Provider 与 model 名并排（如「DeepSeek · deepseek-v4-flash」）。
  // provider 缺失时只显示 model —— 显示错的提供商比不显示更糟。
  var modelHtml = '';
  if (usage.model || usage.model_provider) {
    var _prov = usage.model_provider || '';
    var _mdl = usage.model || '?';
    var _label = _prov ? (_prov + ' · ' + _mdl) : _mdl;
    var _mtitle = _prov ? ('主模型 — 提供商: ' + _prov + ' / 模型: ' + _mdl) : ('主模型: ' + _mdl);
    modelHtml = ' | <span class="usage-model" title="' + esc(_mtitle) + '">主模型: '
      + esc(_label) + '</span>';
  }
  // 缓存命中率：**只显示百分比**（hit/miss 明细挪进 tooltip，需要时悬停可看）
  var cacheHtml = '';
  var _cachePct = (usage.cache_hit_pct == null) ? null : usage.cache_hit_pct;
  if (_cachePct !== null) {
    var _cacheTitle = usage.cache_hit_detail
      ? ('前缀缓存命中率：' + usage.cache_hit_detail)
      : '前缀缓存命中率（命中 token / 总输入 token）';
    cacheHtml = ' | <span class="usage-cache" title="' + esc(_cacheTitle) + '">'
      + '命中率 ' + esc(String(_cachePct)) + '%</span>';
  }
  // 解码速度：服务端实测优先，其次前端实时估算
  var tpsHtml = '';
  var tpsText = usage.decode_tps_text || liveTpsText || '';
  if (tpsText) {
    var _tpsTitle = '解码速度：最近一次模型调用的输出 token / (首增量→流结束)，不含首 token 等待';
    if (usage.decode_estimated) _tpsTitle += '，供应商未返回 usage，数值为估算';
    if (usage.ttft_text) _tpsTitle += '；' + usage.ttft_text;
    var _estMark = usage.decode_estimated ? ' ≈' : '';
    tpsHtml = ' | <span class="usage-tps" title="' + esc(_tpsTitle) + '">'
      + esc(tpsText) + _estMark + '</span>';
  }
  // 当前上下文已用 xx%（后端预格式化 context_used 文案，供直接展示）
  var contextHtml = '';
  if (usage.context_used) {
    var _ctxPct = (usage.context_pct == null) ? '' : usage.context_pct;
    var _ctxCls = 'usage-context';
    if (_ctxPct !== '' && _ctxPct >= 80) _ctxCls += ' warn';
    if (_ctxPct !== '' && _ctxPct >= 95) _ctxCls += ' danger';
    contextHtml = ' | <span class="' + _ctxCls + '" title="' + esc(usage.context_used) + '">' + esc(usage.context_used) + '</span>';
  }
  return _stripLeadingSep(tpsHtml + modelHtml + cacheHtml + contextHtml);
}

/** 去掉首段残留的前导分隔符「 | 」（首段被省略时会剩下）。 */
function _stripLeadingSep(html) {
  return String(html || '').replace(/^\s*\|\s*/, '');
}

function updateUsage(usage) {
  if (!usage || (!usage.total_tokens && !usage.context_used)) return;
  var bar = $('usage-bar');
  if (!bar) return;
  _lastUsageData = usage;
  bar.style.display = '';
  // 流式过程中已显示实时估算值 → 保留它（服务端实测值在下一轮 usage/done 到达）
  bar.innerHTML = _usageBarHtml(usage, _liveTps.text);
  bar.className = 'usage-bar';
}

/* ══════════════════════════════════════════════════════
   实时解码速度（前端估算，仅用于流式过程中即时反馈）
   口径与服务端一致：输出 token / (首增量 → 现在)，排除首 token 等待。
   服务端在每轮 LLM 调用结束后用供应商 usage 计算实测值并下发，
   届时覆盖此估算 —— 估算仅填补「首轮尚未结束」这段空窗。
   ══════════════════════════════════════════════════════ */
var _lastUsageData = null;      // 最近一次服务端 usage 载荷（实时估算要复用它渲染其它字段）
var _liveTps = { active: false, firstTs: 0, cnChars: 0, otherChars: 0, text: '' };
var _liveTpsLastPaint = 0;

/** 与后端 session.history_builder.estimate_tokens 同口径的启发式 token 估算。 */
function _estTokensFromCounts(cnChars, otherChars) {
  return cnChars / 1.5 + otherChars / 4.0;
}

/** 统计文本的中文字符数（其余按非中文计）。 */
function _countCJK(text) {
  var m = String(text || '').match(/[\u4e00-\u9fff\u3400-\u4dbf]/g);
  return m ? m.length : 0;
}

function _liveTpsReset() {
  _liveTps = { active: true, firstTs: 0, cnChars: 0, otherChars: 0, text: '' };
  _liveTpsLastPaint = 0;
  // 上一回合的 usage 载荷作废：本轮在首个 usage 事件到达前应显示「生成中」，
  // 而不是拿上一回合的 T:/模型/tok/s 拼出新数字（归属错误的数比没有数更糟）。
  _lastUsageData = null;
}

function _liveTpsStop() {
  _liveTps.active = false;
  _liveTps.text = '';
}

/** 采样一个输出增量；返回 true 表示 usage-bar 需要重绘。 */
function _liveTpsTick(text) {
  if (!_liveTps.active) return false;
  var s = String(text || '');
  if (!s) return false;
  var now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
  if (!_liveTps.firstTs) _liveTps.firstTs = now;
  _liveTps.cnChars += _countCJK(s);
  _liveTps.otherChars += (s.length - _countCJK(s));
  var elapsed = (now - _liveTps.firstTs) / 1000;
  var tokens = _estTokensFromCounts(_liveTps.cnChars, _liveTps.otherChars);
  // 窗口过短 / 样本过少时除法噪声极大（首个增量与此刻几乎同时），
  // 与后端 MIN_DECODE_SECONDS 同策略：宁可不显示，也不显示抖动数字。
  if (elapsed < 0.5 || tokens < 8) return false;
  _liveTps.text = '⚡ ' + (tokens / elapsed).toFixed(1) + ' tok/s';
  if (now - _liveTpsLastPaint < 250) return false;   // 节流：token 事件可能每秒上百条
  _liveTpsLastPaint = now;
  return true;
}

/** 把实时估算值画进底部 usage-bar（尚无服务端 usage 时也能显示）。 */
function _paintLiveTps() {
  if (!_liveTps.text) return;
  var bar = $('usage-bar');
  if (!bar) return;
  bar.style.display = '';
  if (_lastUsageData) {
    bar.innerHTML = _usageBarHtml(_lastUsageData, _liveTps.text);
  } else {
    bar.innerHTML = '<span class="usage-live">⏳ 生成中</span>'
      + ' | <span class="usage-tps" title="解码速度（输出 token / 首增量→现在，不含首 token 等待），流结束后替换为服务端实测值">'
      + esc(_liveTps.text) + ' ≈</span>';
  }
  bar.className = 'usage-bar live';
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
      return '<div class="' + cls + '" onclick="openTopic(\'' + t.id + '\',\'' + jsAttr(title) + '\')">'
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
  setTitle(decodeEntities(title) || id.slice(0, 8));
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
    _turnCounter = 0; // 切换话题重置轮次计数器
    _forkAnchor = null; // 分叉点属于具体话题，切换即失效
    _userNearBottom = true;  // 切换话题重置滚动状态
    d.conversations.forEach(function(c) {
      // 传入会话 id：跳转栏据此把「历史 tag」映射为分叉边界点
      if (c.user_msg) addMessage('user', c.user_msg, null, c.id);
      if (c.ai_msg) addMessage('assistant', c.ai_msg, null, c.id);
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

function _showBackgroundIndicator(topicId, label) {
  let banner = $('bg-banner');
  const text = label || '后台正在处理中…';
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'bg-banner';
    banner.className = 'bg-processing-banner';
    banner.innerHTML = '<span class="bg-spinner"></span> ⏳ ' + esc(text);
    $('msgs').prepend(banner);
  } else {
    banner.innerHTML = '<span class="bg-spinner"></span> ⏳ ' + esc(text);
  }
}

/**
 * 进入「重连续读」模式：网络中断常见于 server 正在重启。
 *
 * 处理要点：
 *  1) 移除未完成的助手气泡 —— 续读由 _renderBufferEvent 统一重建，避免重复渲染；
 *  2) 改用后台缓冲区轮询（/api/topic/{id}/stream-buffer?since=N）补齐已产出内容；
 *     服务端重启后会把崩溃前的在途回合快照重建成缓冲区，所以内容不丢。
 */
function _enterReconnectMode(topicId) {
  const partial = $('current-ai-msg');
  if (partial) partial.remove();          // 去重：交给续读渲染
  _liveTpsStop();                         // 缓冲区是重放的，不能按重放节奏估算 tok/s
  _showBackgroundIndicator(topicId, '连接中断，正在重连并补齐内容…');
  _startBackgroundPoll(topicId);          // 内部重置 since / count / state
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
      speedChars: 0,
      speedCn: 0,
      speedT0: 0,
      speedT1: 0,
    };
  }
  return _bufferStreamState;
}

let _lastLiveSpeedRender = 0;   // 实时速率 DOM 刷新节流时间戳

/* 节流刷新任务面板：Agent 工具调用完成时更新 TODO 勾选状态（1s 内最多一次） */
let _lastTaskRefreshTs = 0;
function _throttledTaskRefresh() {
  const now = Date.now();
  if (now - _lastTaskRefreshTs < 1000) return;
  _lastTaskRefreshTs = now;
  refreshTaskPanel();
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
      s.bubbleText.innerHTML = esc(decodeEntities(s.fullText));
      if (_liveTpsTick(event.text)) _paintLiveTps();
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
      // 默认不 open：折叠状态，与工具调用条目一致
      entry.innerHTML = '<summary>思考 #' + s.thinkCount + '</summary><div class="think-content"></div>';
      s.thinkList.appendChild(entry);
      s.thinkContent = entry.querySelector('.think-content');
      break;

    case 'think':
      if (s.thinkContent) {
        s.thinkContent.textContent += event.text;
      }
      if (_liveTpsTick(event.text)) _paintLiveTps();
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

    case 'tool_parallel': {
      _renderToolParallel(s, event.names);
      break;
    }

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
      _throttledTaskRefresh();   // 工具完成 → 刷新任务面板 TODO
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

    case 'usage':
      // 续读/后台轮询路径：服务端实测 usage（含 decode_tps_text）同样刷新底部栏。
      // ⚠️ 此处**不做**实时估算：缓冲区是重放的，按重放节奏计时得到的是
      //    「回放速度」而非解码速度，展示出来就是编造数据。
      if (event.usage) updateUsage(event.usage);
      break;

    case 'steering_injected':
      // 后台轮询模式下收到插话生效事件：从本地排队列表移除并渲染
      if (event.item_id) {
        for (let i = 0; i < _messageQueue.length; i++) {
          if (_messageQueue[i].item_id === event.item_id) {
            _messageQueue.splice(i, 1);
            break;
          }
        }
        renderQueueList();
        _updateQueueButton();
      }
      if (event.text) addMessage('user', event.text);
      toast('⚡ 插话已生效，将在下一轮处理', 'success');
      break;

    case 'usage':
      // 后台/重连续读模式同样刷新用量条（含 tok/s），否则切回会话时数字缺失
      if (event.usage) updateUsage(event.usage);
      break;

    case 'done':
      // 后台流结束，用 Markdown 重新渲染最终消息
      var finalMsg = event.ai_msg || s.fullText;
      if (finalMsg && s.bubbleText) {
        s.bubbleText.innerHTML = formatMarkdown(finalMsg);
      }
      if (event.usage) updateUsage(event.usage);
      _throttledTaskRefresh(); // 流结束 → 刷新任务面板 TODO
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
  _liveTpsStop();        // 后台/续读模式不做实时估算（见 _renderBufferEvent 'usage'）
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
          // 如果缓冲区已经实时渲染了内容（包括 done 事件的 Markdown），
          // 则不需要从 DB 重载（避免重载清空已渲染的消息，而 DB 可能尚未保存）
          if (_bufferEventCount > 0 && _bufferStreamState && _bufferStreamState.bubbleText) {
            _bufferStreamState = null;
            _bufferSince = -1;
            _bufferEventCount = 0;
            refreshTopics();
          } else {
            _reloadCurrentConversations();
            refreshTopics();
          }
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
          if (_bufferEventCount > 0 && _bufferStreamState && _bufferStreamState.bubbleText) {
            _bufferStreamState = null;
            _bufferSince = -1;
            _bufferEventCount = 0;
            refreshTopics();
          } else {
            _reloadCurrentConversations();
            refreshTopics();
          }
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
    _turnCounter = 0; // 重载会话时重置轮次计数器
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
  _turnCounter = 0; // 重置轮次计数器
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
  await refreshModelSelects();
  await fillConfigForm();
};

// 当前配置的 options 快照（apply 时合并，避免整体替换丢键）
var _cfgCurOptions = {}, _cfgCurCheapOptions = {};

// 回填配置对话框：url/key/模型名只读展示（提交时忽略），参数可编辑
async function fillConfigForm() {
  try {
    var r = await fetch('/api/model');
    if (!r.ok) return;
    var d = await r.json();
    if (d.error) return;
    // ── 主模型 ──
    $('cfg-model').value = d.model || '';
    $('cfg-url').value = d.api_url || '';
    $('cfg-key').value = d.api_key_masked || '';   // 掩码回填（readonly，提交被忽略）
    if (d.temperature != null) $('cfg-temp').value = d.temperature;
    if (d.max_tokens != null) $('cfg-max-tokens').value = d.max_tokens;
    if (d.top_p != null) $('cfg-top-p').value = d.top_p;
    if (d.max_context_tokens != null) $('cfg-max-ctx').value = d.max_context_tokens;
    _cfgCurOptions = d.options || {};
    $('cfg-vision').checked = !!_cfgCurOptions.supports_vision;
    $('cfg-reasoning').checked = _cfgCurOptions.supports_reasoning !== false;
    _setEffort('cfg-effort', _cfgCurOptions.reasoning_effort);
    // ── 运行时 ──
    if (d.max_iterations != null) $('cfg-max-iter').value = d.max_iterations;
    if (d.keep_turns != null) $('cfg-keep-turns').value = d.keep_turns;
    $('cfg-thinking').checked = d.enable_thinking !== false;
    // ── 便宜模型 ──
    var cm = d.cheap_model || null;
    $('cfg-cheap-model').value = cm ? (cm.model || '') : '';
    $('cfg-cheap-url').value = cm ? (cm.api_url || '') : '';
    $('cfg-cheap-key').value = cm ? (cm.api_key_masked || '') : '';
    if (cm && cm.temperature != null) $('cfg-cheap-temp').value = cm.temperature;
    if (cm && cm.max_tokens != null) $('cfg-cheap-max-tokens').value = cm.max_tokens;
    if (cm && cm.top_p != null) $('cfg-cheap-top-p').value = cm.top_p;
    if (cm && cm.max_context_tokens != null) $('cfg-cheap-max-ctx').value = cm.max_context_tokens;
    _cfgCurCheapOptions = (cm && cm.options) || {};
    $('cfg-cheap-vision').checked = !!_cfgCurCheapOptions.supports_vision;
    $('cfg-cheap-reasoning').checked = _cfgCurCheapOptions.supports_reasoning !== false;
    _setEffort('cfg-cheap-effort', _cfgCurCheapOptions.reasoning_effort);
  } catch (e) { /* 回填失败不阻断对话框（placeholder 兜底） */ }
}

// reasoning_effort 兼容 str / list（provider.yaml 允许多值，取首项）
function _setEffort(id, eff) {
  var el = $(id);
  if (!el) return;
  if (Array.isArray(eff)) eff = eff[0];
  el.value = (typeof eff === 'string' && eff) ? eff : 'auto';
}

// ── 主/便宜模型下拉（provider / model 组合）──
function _shortModelLabel(label, maxLen) {
  // 超长 provider/model（如 local / ericli1018/Hermes3.6-35B-…）截断显示，
  // 避免 select 宽度被最长 option 撑爆；完整值仍在 option.value / title 中。
  maxLen = maxLen || 38;
  label = String(label || '');
  if (label.length <= maxLen) return label;
  var idx = label.indexOf(' / ');
  if (idx > 0 && idx < maxLen - 8) {
    var head = label.slice(0, idx + 3);
    var tail = label.slice(idx + 3);
    return head + tail.slice(0, maxLen - head.length - 1) + '…';
  }
  return label.slice(0, maxLen - 1) + '…';
}

async function refreshModelSelects() {
  var selIds = {
    main: ['main-model-select', 'cfg-main-select'],
    cheap: ['cheap-model-select', 'cfg-cheap-select'],
  };
  try {
    var r = await fetch('/api/model-options');
    if (!r.ok) return { any_valid: false, error: 'http ' + r.status };
    var d = await r.json();
    if (!d.ok) return { any_valid: false, error: d.error || 'load failed' };
    var options = d.options || [];
    Object.keys(selIds).forEach(function(role) {
      selIds[role].forEach(function(id) {
        var sel = $(id);
        if (!sel) return;
        var cur = (d[role] || {}).value || '';
        sel.innerHTML = '';
        var first = document.createElement('option');
        first.value = '';
        first.textContent = role === 'main' ? '— 主模型 —' : '— 便宜模型（可选）—';
        sel.appendChild(first);
        options.forEach(function(o) {
          var op = document.createElement('option');
          op.value = o.value;
          op.textContent = _shortModelLabel(o.label);
          op.title = o.label;
          if (o.value === cur) op.selected = true;
          sel.appendChild(op);
        });
      });
    });
    return { any_valid: !!(d.main && d.main.value), main: d.main, cheap: d.cheap };
  } catch(e) {
    return { any_valid: false, error: e.message };
  }
}

window.onModelSelect = async function(role, value) {
  if (!value) return;
  var m = value.split('::');
  if (m.length < 2) return;
  var provider = m[0], model = m[1];
  if (role === 'main' && isStreaming &&
      !confirm('当前正在生成回复中，切换主模型可能影响当前会话。继续？')) return;
  try {
    var r = await fetch('/api/model-select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: role, provider: provider, model: model }),
    });
    var d = await r.json();
    if (d.ok) {
      toast('✓ 已切换' + (role === 'main' ? '主模型' : '便宜模型') + ': ' + model, 'success');
      var inp = $(role === 'main' ? 'cfg-model' : 'cfg-cheap-model');
      if (inp) inp.value = model;
      refreshModelSelects();
    } else {
      toast('✗ 切换失败: ' + (d.error || '未知错误'), 'error');
      refreshModelSelects();
    }
  } catch(e) {
    toast('Error: ' + e.message, 'error');
  }
};

window.applyConfig = async function() {
  if (isStreaming && !confirm('当前正在生成回复中，切换配置可能导致会话异常。\n确定要切换吗？')) return;

  function nv(id) { const v = $(id).value.trim(); return v ? Number(v) : null; }

  showCfgStatus('正在应用...', 'info');

  try {
    // 语义：url / key / 模型名只读，不提交 —— 后端缺省兑底当前值；
    // 本对话框只提交「参数」（采样/窗口/能力），并写回 provider.yaml（后端完成）。
    const body = {};
    body.temperature = nv('cfg-temp');
    body.max_tokens = nv('cfg-max-tokens');
    body.top_p = nv('cfg-top-p');
    body.max_context_tokens = nv('cfg-max-ctx');
    body.options = Object.assign({}, _cfgCurOptions, {
      supports_vision: $('cfg-vision').checked,
      supports_reasoning: $('cfg-reasoning').checked,
      reasoning_effort: $('cfg-effort').value || 'auto',
    });
    // 便宜模型参数（后端对 cheap url/name 兑底当前值后应用）
    body.cheap_temperature = nv('cfg-cheap-temp');
    body.cheap_max_tokens = nv('cfg-cheap-max-tokens');
    body.cheap_top_p = nv('cfg-cheap-top-p');
    body.cheap_max_context_tokens = nv('cfg-cheap-max-ctx');
    body.cheap_options = Object.assign({}, _cfgCurCheapOptions, {
      supports_vision: $('cfg-cheap-vision').checked,
      supports_reasoning: $('cfg-cheap-reasoning').checked,
      reasoning_effort: $('cfg-cheap-effort').value || 'auto',
    });

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
      // 运行时参数（max_iterations/keep_turns/enable_thinking）走 PUT /api/config。
      // 必须检查响应：后端在长驻 Agent 未加载时返回 {"ok": false, errors:["Agent not loaded"]}，
      // 早期实现只 await 不看结果，界面仍报「✅ 已应用」—— 参数没落地却显示成功。
      const rc = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      let rd = {};
      try { rd = await rc.json(); } catch(e) { rd = {}; }
      if (!rc.ok || rd.ok === false) {
        const msg = (rd.errors && rd.errors.join(', ')) || rd.error || ('HTTP ' + rc.status);
        showCfgStatus('失败: 运行时参数未生效 — ' + msg, 'error');
        return;
      }
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
      $('nc-status').textContent = '✓ 已保存并切换: ' + d.filename;
      setTimeout(function() {
        closeModal('modal-new-config');
        closeModal('modal-config');
        refreshConfigDropdown();
        // 刷新页面提示，让用户知道可以开始对话了
        toast('☕ 配置完成！可以开始对话了', 'success', 4000);
      }, 1500);
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

// 保留向后兼容入口：委托 refreshModelSelects（主/便宜模型下拉）。
// 返回 {any_valid, main, cheap, error}；checkAndShowFirstRunModal 仅依赖 any_valid/error。
async function refreshConfigDropdown() {
  return await refreshModelSelects();
}

// 配置切换已由 onModelSelect（主/便宜模型下拉）统一处理；旧的"配置文件切换"已移除。

// ══════════════════════════════════════════════════
//  EXPORT
// ══════════════════════════════════════════════════

window.showExportModal = function() {
  showModal('modal-export');
  $('export-result').innerHTML = '';
  // Reset to defaults
  const fmtRadios = document.querySelectorAll('input[name="export-format"]');
  if (fmtRadios.length > 0) fmtRadios[0].checked = true;
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
  const fmtEl = document.querySelector('input[name="export-format"]:checked');
  const modeEl = document.querySelector('input[name="export-mode"]:checked');
  const filterEl = document.querySelector('input[name="export-filter"]:checked');
  const format = fmtEl ? fmtEl.value : 'md';
  const mode = modeEl ? modeEl.value : 'latest';
  const filter = filterEl ? filterEl.value : 'final';
  el.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:8px 0">导出中...</div>';
  try {
    const url = '/v1/export/' + format + '/' + encodeURIComponent(currentTopicId)
      + '?mode=' + encodeURIComponent(mode)
      + '&filter=' + encodeURIComponent(filter);
    const r = await fetch(url, { method: 'GET' });
    const ct = r.headers.get('Content-Type') || '';
    if (ct.includes('application/pdf') || ct.includes('text/markdown')) {
      // Download file directly
      const blob = await r.blob();
      let filename = format === 'pdf' ? 'export.pdf' : 'export.md';
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

var _maxIterConfirmId = null;

function showMaxIterConfirm(confirmId, text) {
  _maxIterConfirmId = confirmId;
  const t = $('mi-text');
  if (t) t.textContent = text || '已达到工具调用次数上限';
  const inp = $('mi-extra');
  if (inp) { inp.value = '10'; }
  showModal('modal-maxiter');
  if (inp) { inp.focus(); inp.select(); }
}

function maxIterDecision(cont) {
  const cid = _maxIterConfirmId;
  _maxIterConfirmId = null;
  closeModal('modal-maxiter');
  if (!cid) return;
  let extra = 10;
  if (cont) {
    const inp = $('mi-extra');
    const v = parseInt(inp && inp.value, 10);
    if (!isNaN(v)) extra = Math.max(1, Math.min(1000, v));
  }
  fetch('/api/chat/continue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm_id: cid, continue: !!cont, extra: extra })
  }).catch(function(){});
  if (cont) addLoading();  // 续命后流恢复，重新挂 loading；终止则等 done 事件清理
}

// ══════════════════════════════════════════════════
//  BUTTON STYLES (re-export for HTML onclick)
// ══════════════════════════════════════════════════
//  FIRST RUN — 无配置时自动弹出配置窗口
// ══════════════════════════════════════════════════

window.checkAndShowFirstRunModal = function(result) {
  // 由 refreshConfigDropdown().then() 调用
  // 检查是否已有有效配置，若无则弹出新增配置模态框
  // result: { configs, any_valid, count }
  var hasValidConfig = result && result.any_valid === true;
  // 如果 API 报错（网络问题），也不弹窗，避免误判
  if (result && result.error) return;
  if (hasValidConfig) return; // 已有有效配置，不打扰

  // 弹出自定义欢迎/配置模态框（区别于普通新增配置，有更友好的提示）
  toast('☕ 欢迎使用 Tea Agent！请先配置主模型', 'info');
  showNewConfigModal();
  // 修改模态框标题和说明
  setTimeout(function() {
    var titleEl = document.querySelector('#modal-new-config h3');
    if (titleEl) titleEl.textContent = '☕ 欢迎使用！请配置主模型';
    var statusEl = $('nc-status');
    if (statusEl) {
      statusEl.style.display = 'block';
      statusEl.className = 'status-msg info';
      statusEl.textContent = '首次使用，请填写主模型的 API 地址和密钥';
    }
    // 聚焦到第一个输入框
    var nameInput = $('nc-main-name');
    if (nameInput) nameInput.focus();
  }, 100);
};

// ══════════════════════════════════════════════════

// Ensure btn-g, btn-p, btn-sm classes exist in JS context
// (CSS already has them)

// ══════════════════════════════════════════════════
//  INIT
// ══════════════════════════════════════════════════

refreshTopics();
refreshConfigDropdown().then(function(result) {
  // 🔍 检测是否有有效配置，如无则自动弹出新增配置窗口
  // result: { configs, any_valid, count }
  checkAndShowFirstRunModal(result);
});
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

// ══════════════════════════════════════════════════
//  MODEL SWITCH (供应商 → 模型 两级切换，模型自带窗口/输出上限)
// ══════════════════════════════════════════════════

let mmProviders = [];
let mmSelectedProvider = '';
let mmSelectedModel = '';
let mmSelectedMeta = null;   // 选中模型的富元数据（context_window/max_output_tokens/...）
let mmCurrentModels = [];    // 当前供应商的模型列表（富条目）
let mmActiveModel = '';      // 当前配置生效的主模型 id
let mmActiveUrl = '';        // 当前配置生效的 api_url
let mmEditingProvider = null;  // null=新增模式；字符串=正在编辑的提供商名
let mmPanel = null;            // 统一模型配置面板数据（单一事实源 ~/.tea_agent/model_config.json）

function _mmStatus(msg, type) {
  const el = $('mm-status');
  if (!el) return;
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
  if (msg) {
    el.className = 'status-msg';
    if (type === 'error') el.style.color = '#e74c3c';
    else if (type === 'success') el.style.color = '#2ecc71';
    else el.style.color = '';
  }
}

function _fmtTokens(n) {
  if (!n || n <= 0) return '';
  if (n >= 1000000) return (n / 1000000).toFixed(n % 1000000 ? 1 : 0).replace(/\.0$/, '') + 'M';
  if (n >= 1000) return Math.round(n / 1000) + 'K';
  return String(n);
}

// 模型条目富信息 → 徽章串（上下文/输出/视觉/思考）
function _modelBadges(m) {
  const parts = [];
  const ctx = _fmtTokens(m && m.context_window);
  const out = _fmtTokens(m && m.max_output_tokens);
  if (ctx) parts.push('<span style="background:var(--bg2,#eee);border-radius:4px;padding:0 5px;font-size:10px;color:var(--text-dim,#888)">📏 ' + ctx + '</span>');
  if (out) parts.push('<span style="background:var(--bg2,#eee);border-radius:4px;padding:0 5px;font-size:10px;color:var(--text-dim,#888)">↗ ' + out + '</span>');
  if (m && m.supports_vision) parts.push('<span style="background:#8e44ad;color:#fff;border-radius:4px;padding:0 5px;font-size:10px">🖼 视觉</span>');
  if (m && m.supports_thinking) parts.push('<span style="background:#2980b9;color:#fff;border-radius:4px;padding:0 5px;font-size:10px">🧠 思考</span>');
  return parts.join('');
}

// 独立供应商/模型配置界面（provider.yaml 唯一事实源，与 configxxx.yaml 无关）
window.openProvidersPage = function() {
  window.open('/static/providers.html', '_blank', 'noopener');
};
window.showModelModal = async function() {  // 兼容旧入口：模型切换面板已删除 → 跳独立界面
  window.openProvidersPage();
};

// 面板数据源：GET /api/model-config（统一模型配置中心 model_config.json）
async function loadModelConfig() {
  try {
    const r = await fetch('/api/model-config');
    if (!r.ok) throw new Error((await r.json()).error || 'HTTP ' + r.status);
    mmPanel = await r.json();
  } catch (e) {
    _mmStatus('加载统一模型配置失败: ' + e.message, 'error');
    return;
  }
  mmProviders = (mmPanel.providers || []).map(p => ({
    name: p.name, source: p.source, api_url: p.api_url, default_model: p.default_model,
    models: (p.models || []).map(m => m.id),
    supports_thinking: p.supports_thinking, supports_vision: p.supports_vision,
    description: p.description, is_configured: p.is_configured,
    api_key_masked: p.api_key_masked || '',
  }));
  renderProviders();
  refreshCurrentModel();
  // 自动选中 main 角色绑定的提供商
  const bind = (mmPanel.roles || {}).main;
  let cur = bind ? mmProviders.find(p => p.name === bind.provider) : null;
  if (!cur) cur = mmProviders.find(p => p.is_configured);
  if (!cur && mmProviders.length) cur = mmProviders[0];
  if (cur) selectProvider(cur.name);
}

function refreshCurrentModel() {
  const el = $('mm-current-text');
  if (el) {
    const a = (mmPanel && mmPanel.active) || {};
    const parts = [];
    ['main', 'cheap', 'vision'].forEach(rl => {
      if (a[rl] && a[rl].model) parts.push(rl + ': ' + a[rl].model);
    });
    el.textContent = parts.length ? '当前: ' + parts.join(' | ') : '当前: 未配置';
  }
  const pe = $('mm-pending');
  if (pe) {
    const ps = mmPanel && mmPanel.pending_switch;
    if (ps && ps.model_name) {
      pe.style.display = 'block';
      pe.textContent = '⏳ 模型切换已排队：' + ps.model_name +
        ' — 本轮回复结束后自动生效并继续会话，无需重复点击';
    } else {
      pe.style.display = 'none';
    }
  }
}

async function loadProviders() { await loadModelConfig(); }  // 兼容旧调用点

function renderProviders() {
  const box = $('mm-providers');
  if (!box) return;
  const q = ($('mm-search')?.value || '').trim().toLowerCase();
  const list = mmProviders.filter(p => !q
    || p.name.toLowerCase().includes(q)
    || (p.description || '').toLowerCase().includes(q)
    || (p.catalog || []).some(m => String(m.id).toLowerCase().includes(q)));
  if (!list.length) {
    box.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-dim,#888);font-size:13px">无匹配供应商</div>';
    return;
  }
  box.innerHTML = list.map(p => {
    const active = p.name === mmSelectedProvider;
    const badges = [];
    if (p.source === 'config') badges.push('<span style="background:#16a085;color:#fff;border-radius:4px;padding:0 4px;font-size:10px" title="由 ~/.tea_agent/config_*.yaml 派生的真实配置 profile">profile</span>');
    else if (p.source === 'custom') badges.push('<span style="background:#f39c12;color:#fff;border-radius:4px;padding:0 4px;font-size:10px">自定义</span>');
    if (p.supports_vision) badges.push('<span style="background:#8e44ad;color:#fff;border-radius:4px;padding:0 4px;font-size:10px">视觉</span>');
    if (p.supports_thinking) badges.push('<span style="background:#2980b9;color:#fff;border-radius:4px;padding:0 4px;font-size:10px">思考</span>');
    const nModels = (p.catalog && p.catalog.length) ? p.catalog.length : (p.models || []).length;
    return '<div class="mm-provider" onclick="selectProvider(\'' + escAttr(p.name) + '\')" ' +
      'style="padding:8px 10px;margin-bottom:6px;border-radius:8px;cursor:pointer;border:1px solid ' +
      (active ? 'var(--primary,#4a90d9)' : 'var(--border,#ddd)') + ';' +
      (active ? 'background:rgba(74,144,217,0.1)' : '') + '">' +
      '<div style="display:flex;justify-content:space-between;align-items:center">' +
      '<b style="font-size:13px">' + esc(p.name) + '</b>' + badges.join('') +
      '</div>' +
      '<div style="font-size:11px;color:var(--text-dim,#888);margin-top:2px;word-break:break-all">' + esc(p.api_url) + (p.api_key_masked ? ' · ' + esc(p.api_key_masked) : '') + '</div>' +
      (p.is_configured ? '<div style="font-size:10px;color:#2ecc71;margin-top:2px">● 当前使用</div>' : '') +
      (p.source === 'custom'
        ? '<div style="margin-top:4px;display:flex;gap:6px">' +
          '<button class="btn" style="padding:1px 8px;font-size:11px;background:#f0ad4e;color:#fff" onclick="event.stopPropagation();showEditProviderForm(\'' + escAttr(p.name) + '\')">✏️ 编辑</button>' +
          '<button class="btn" style="padding:1px 8px;font-size:11px;background:#e74c3c;color:#fff" onclick="event.stopPropagation();deleteProvider(\'' + escAttr(p.name) + '\')">🗑 删除</button>' +
          '</div>'
        : '') +
      '</div>';
  }).join('');
}

async function selectProvider(name) {
  mmSelectedProvider = name;
  mmSelectedModel = '';
  mmSelectedMeta = null;
  const ms = $('mm-model-search');
  if (ms) ms.value = '';
  renderProviders();
  const p = mmProviders.find(x => x.name === name);
  // 回填能力/编辑/删除按钮
  const cap = $('mm-cap');
  if (cap) cap.textContent = p ? (p.description || '') + (p.supports_vision || p.supports_thinking ? ' | 能力: ' + [p.supports_vision && '视觉', p.supports_thinking && '思考'].filter(Boolean).join('+') : '') : '';
  const isCustom = !!(p && p.source === 'custom');
  const del = $('mm-del-btn');
  if (del) del.style.display = isCustom ? 'block' : 'none';
  const editBtn = $('mm-edit-btn');
  if (editBtn) editBtn.style.display = isCustom ? 'block' : 'none';
  mmSelectedModel = '';
  if ($('mm-cfg')) $('mm-cfg').style.display = 'none';
  renderModels();
  // 该提供商若绑定了 main 角色 → 自动选中正在使用的模型
  const bind = mmPanel && (mmPanel.roles || {}).main;
  if (bind && bind.provider === name && bind.model) selectModel(bind.model);
}

// 编辑自定义供应商（复用新增表单）
function showEditProviderForm(name) {
  const p = mmProviders.find(x => x.name === name);
  if (!p) return;
  mmEditingProvider = name;
  const form = $('mm-add-form');
  if (form) form.style.display = 'block';
  const title = $('mm-add-title');
  if (title) title.textContent = '✏️ 编辑自定义供应商: ' + name;
  const nameInput = $('mm-add-name');
  if (nameInput) nameInput.disabled = true;
  $('mm-add-name').value = name;
  $('mm-add-url').value = p.api_url || '';
  $('mm-add-default').value = p.default_model || '';
  $('mm-add-models').value = (p.catalog && p.catalog.length ? p.catalog : (p.models || [])).map(m => m && m.id !== undefined ? m.id : m).join(', ');
  $('mm-add-vision').checked = !!p.supports_vision;
  $('mm-add-thinking').checked = !!p.supports_thinking;
  $('mm-add-desc').value = p.description || '';
  const btn = $('mm-add-save');
  if (btn) btn.textContent = '💾 保存修改';
}

async function loadModels(name, refresh) {
  if (!name) return;
  const box = $('mm-models');
  const hint = $('mm-model-hint');
  const provider = mmProviders.find(p => p.name === name);
  if (box) box.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-dim,#888)">⏳ 加载模型…</div>';
  if (hint) hint.textContent = '';
  // 目录里已带富元数据时直接渲染（免请求），refresh 才走实时查询
  let models = [];
  let source = 'catalog';
  try {
    if (!refresh && provider && provider.catalog && provider.catalog.length) {
      models = provider.catalog;
      source = 'catalog';
    } else {
      const url = '/api/providers/' + encodeURIComponent(name) + '/models' + (refresh ? '?refresh=true' : '');
      const r = await fetch(url);
      if (!r.ok) throw new Error((await r.json()).error || 'HTTP ' + r.status);
      const d = await r.json();
      models = d.models || [];
      source = d.source || 'catalog';
      if (hint) {
        if (source === 'live') hint.textContent = '🟢 实时查询 (' + (d.endpoint || '') + ')';
        else if (source === 'cache') hint.textContent = '🕐 缓存（5 分钟有效）— 点「🔄 实时刷新」获取最新';
        else if (d.error_hint) hint.textContent = '⚠️ ' + d.error_hint;
        else if (d.needs_key) hint.textContent = '自定义供应商需填 key 后实时查询';
      }
    }
  } catch (e) {
    if (box) box.innerHTML = '<div style="padding:16px;text-align:center;color:#e74c3c">❌ ' + esc(e.message) + '</div>';
    return;
  }
  if (!models || !models.length) {
    if (box) box.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-dim,#888)">暂无模型 — 点击「🔄 实时刷新」或填 key 后查询</div>';
    return;
  }
  // 兜底：实时查询缺省 owned_by
  models = models.map(m => (typeof m === 'string') ? { id: m } : m);
  mmCurrentModels = models;
  renderModels();
  // 默认选中：当前生效模型（同供应商）> default_model
  const p = mmProviders.find(x => x.name === name);
  let preselect = '';
  if (p && p.is_configured && mmActiveModel && models.some(m => m.id === mmActiveModel)) {
    preselect = mmActiveModel;
  } else if (p && p.default_model && models.some(m => m.id === p.default_model)) {
    preselect = p.default_model;
  }
  if (preselect && !mmSelectedModel) selectModel(preselect);
}

function renderModels() {
  const box = $('mm-models');
  if (!box) return;
  const q = ($('mm-model-search')?.value || '').trim().toLowerCase();
  const list = mmCurrentModels.filter(m => !q || String(m.id || '').toLowerCase().includes(q));
  if (!list.length) {
    box.innerHTML = '<div style="padding:14px;text-align:center;color:var(--text-dim,#888)">无匹配模型</div>';
    return;
  }
  box.innerHTML = list.map(m => {
    const mid = m.id;
    const active = mid === mmSelectedModel;
    const meta = m && (m.context_window || m.max_output_tokens || m.supports_vision || m.supports_thinking)
      ? _modelBadges(m) : '';
    return '<div class="mm-model" onclick="selectModel(\'' + escAttr(mid) + '\')" ' +
      'style="padding:6px 10px;margin-bottom:4px;border-radius:6px;cursor:pointer;border:1px solid ' +
      (active ? 'var(--primary,#4a90d9)' : 'var(--border,#ddd)') + ';' +
      (active ? 'background:rgba(74,144,217,0.1)' : '') + ';font-size:12px;word-break:break-all">' +
      '<span style="font-weight:' + (active ? '600' : '400') + '">' + esc(mid) + '</span>' +
      (meta ? '<span style="margin-left:6px;display:inline-flex;gap:4px;flex-wrap:wrap">' + meta + '</span>' : '') +
      '</div>';
  }).join('');
}

function selectModel(id) {
  mmSelectedModel = id;
  // 高亮
  const box = $('mm-models');
  if (box) {
    box.querySelectorAll('.mm-model').forEach(el => {
      const on = (el.dataset && el.dataset.mid === id) || el.textContent.trim().startsWith(id);
      el.style.borderColor = on ? 'var(--primary,#4a90d9)' : 'var(--border,#ddd)';
      el.style.background = on ? 'rgba(74,144,217,0.1)' : '';
    });
  }
  openModelCfg(id);
}

// ── ② 模型列表：直接由统一配置渲染（零网络往返） ──
function _mmBadge(txt, color) {
  return '<span style="background:' + color + ';color:#fff;border-radius:4px;padding:0 4px;' +
    'font-size:10px;margin-left:4px">' + txt + '</span>';
}

function _mmFmtTok(n) {
  n = Number(n) || 0;
  if (n >= 1048576 && n % 1048576 === 0) return (n / 1048576) + 'M';
  if (n >= 1048576) return (n / 1048576).toFixed(1) + 'M';
  if (n >= 1024) return Math.round(n / 1024) + 'K';
  return String(n);
}

function renderModels() {
  const box = $('mm-models');
  const hint = $('mm-model-hint');
  if (!box) return;
  const p = mmPanel && (mmPanel.providers || []).find(x => x.name === mmSelectedProvider);
  const models = (p && p.models) || [];
  if (hint) hint.textContent = '📋 统一配置 ' + models.length + ' 个模型（model_config.json，点模型可编辑④配置）';
  if (!models.length) {
    box.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-dim,#888)">暂无模型 — 点「⇊ 同步入库」拉取在线列表</div>';
    return;
  }
  box.innerHTML = models.map(m => {
    const active = m.id === mmSelectedModel;
    const c = m.config || {};
    const badges = [];
    if (c.supports_thinking) badges.push(_mmBadge('思考', '#2980b9'));
    if (c.supports_vision) badges.push(_mmBadge('视觉', '#8e44ad'));
    if (m.is_default) badges.push(_mmBadge('★', '#f39c12'));
    return '<div class="mm-model" data-mid="' + escAttr(m.id) + '" onclick="selectModel(\'' + escAttr(m.id) + '\')" ' +
      'style="padding:7px 10px;margin-bottom:4px;border-radius:6px;cursor:pointer;border:1px solid ' +
      (active ? 'var(--primary,#4a90d9)' : 'var(--border,#ddd)') + ';' +
      (active ? 'background:rgba(74,144,217,0.1);' : '') + 'font-size:12px;word-break:break-all">' +
      '<div style="display:flex;justify-content:space-between;align-items:center">' +
      '<span>' + esc(m.id) + '</span><span style="white-space:nowrap">' + badges.join('') + '</span></div>' +
      '<div style="font-size:10px;color:var(--text-dim,#888);margin-top:2px">' +
      'ctx ' + _mmFmtTok(c.max_context_tokens) + ' · out ' + _mmFmtTok(c.max_output_tokens) +
      (c.note ? ' · ' + esc(c.note) : '') + '</div></div>';
  }).join('');
}

// ── ④ 逐模型配置编辑器 ──
function openModelCfg(id) {
  const sec = $('mm-cfg');
  if (!sec) return;
  const p = mmPanel && (mmPanel.providers || []).find(x => x.name === mmSelectedProvider);
  const m = ((p && p.models) || []).find(x => x.id === id);
  const c = (m && m.config) || {};
  sec.style.display = 'block';
  if ($('mm-cfg-name')) $('mm-cfg-name').textContent = mmSelectedProvider + ' / ' + id;
  if ($('mm-cfg-ctx')) $('mm-cfg-ctx').value = c.max_context_tokens || '';
  if ($('mm-cfg-out')) $('mm-cfg-out').value = c.max_output_tokens || '';
  if ($('mm-cfg-think')) $('mm-cfg-think').checked = !!c.supports_thinking;
  if ($('mm-cfg-vision')) $('mm-cfg-vision').checked = !!c.supports_vision;
  if ($('mm-cfg-tools')) $('mm-cfg-tools').checked = c.supports_tools !== false;
  if ($('mm-cfg-note')) $('mm-cfg-note').value = c.note || '';
}

async function saveModelConfig() {
  if (!mmSelectedProvider || !mmSelectedModel) { _mmStatus('请先选择模型', 'error'); return; }
  const config = {
    supports_thinking: $('mm-cfg-think').checked,
    supports_vision: $('mm-cfg-vision').checked,
    supports_tools: $('mm-cfg-tools').checked,
    note: ($('mm-cfg-note').value || '').trim(),
  };
  const ctx = parseInt($('mm-cfg-ctx').value, 10);
  const out = parseInt($('mm-cfg-out').value, 10);
  if (ctx > 0) config.max_context_tokens = ctx;
  if (out > 0) config.max_output_tokens = out;
  try {
    const r = await fetch('/api/model-config/model', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: mmSelectedProvider, model: mmSelectedModel, config: config }),
    });
    const d = await r.json();
    if (!r.ok || d.ok === false) throw new Error(d.error || 'HTTP ' + r.status);
    _mmStatus('✅ 已保存模型配置 → model_config.json', 'success');
    await loadModelConfig();
    selectModel(mmSelectedModel);
  } catch (e) {
    _mmStatus('保存模型配置失败: ' + e.message, 'error');
  }
}

async function delModelConfig() {
  if (!mmSelectedProvider || !mmSelectedModel) { _mmStatus('请先选择模型', 'error'); return; }
  if (!confirm('从统一配置移除 ' + mmSelectedProvider + ' / ' + mmSelectedModel + '？\n（内置注册表模型会在下次加载时自动补回）')) return;
  try {
    const url = '/api/model-config/model?provider=' + encodeURIComponent(mmSelectedProvider) +
                '&model=' + encodeURIComponent(mmSelectedModel);
    const r = await fetch(url, { method: 'DELETE' });
    const d = await r.json();
    if (!r.ok || d.ok === false) throw new Error(d.error || 'HTTP ' + r.status);
    mmSelectedModel = '';
    if ($('mm-cfg')) $('mm-cfg').style.display = 'none';
    _mmStatus('🗑 已删除配置条目', 'success');
    await loadModelConfig();
  } catch (e) {
    _mmStatus('删除失败: ' + e.message, 'error');
  }
}

async function syncModels() {
  if (!mmSelectedProvider) { _mmStatus('请先选择提供商', 'error'); return; }
  const payload = { provider: mmSelectedProvider };
  const key = ($('mm-key').value || '').trim();
  if (key) payload.api_key = key;
  _mmStatus('⇊ 同步在线模型入库中…');
  try {
    const r = await fetch('/api/model-config/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok || d.ok === false) throw new Error(d.error || 'HTTP ' + r.status);
    _mmStatus('✅ 同步入库完成：新增 ' + (d.added || []).length + ' 个 / 保留 ' +
      (d.kept || []).length + ' 个（来源: ' + d.query_source + '）', 'success');
    await loadModelConfig();
  } catch (e) {
    _mmStatus('同步入库失败: ' + e.message, 'error');
  }
}

function showAddProviderForm() {
  mmEditingProvider = null;
  const title = $('mm-add-title');
  if (title) title.textContent = '➕ 新增自定义供应商';
  const nameInput = $('mm-add-name');
  if (nameInput) nameInput.disabled = false;
  const btn = $('mm-add-save');
  if (btn) btn.textContent = '💾 保存新增';
  $('mm-add-form').style.display = 'block';
}
function hideAddProviderForm() {
  mmEditingProvider = null;
  const nameInput = $('mm-add-name');
  if (nameInput) nameInput.disabled = false;
  $('mm-add-form').style.display = 'none';
}

async function submitProvider() {
  const name = ($('mm-add-name').value || '').trim();
  const api_url = ($('mm-add-url').value || '').trim();
  const default_model = ($('mm-add-default').value || '').trim();
  if (!name || !api_url || !default_model) {
    _mmStatus('名称 / API URL / 默认模型 均为必填', 'error');
    return;
  }
  // 支持逗号分隔 id 或 JSON 富条目（如 [{"id":"gpt-4o","context_window":200000}]）
  const raw = ($('mm-add-models').value || '').trim();
  let models = [];
  try {
    if (raw.startsWith('[')) {
      const parsed = JSON.parse(raw);
      models = Array.isArray(parsed) ? parsed : [];
    } else {
      models = raw.split(',').map(s => s.trim()).filter(Boolean);
    }
  } catch (e) {
    _mmStatus('模型列表 JSON 解析失败: ' + e.message, 'error');
    return;
  }
  const payload = {
    name, api_url, default_model,
    models,
    supports_vision: $('mm-add-vision').checked,
    supports_thinking: $('mm-add-thinking').checked,
    description: ($('mm-add-desc').value || '').trim(),
  };
  try {
    const editing = mmEditingProvider;
    const url = editing ? '/api/providers/' + encodeURIComponent(editing) : '/api/providers';
    const r = await fetch(url, {
      method: editing ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    hideAddProviderForm();
    _mmStatus(editing ? '✅ 自定义供应商 ' + editing + ' 已更新' : '✅ 自定义供应商 ' + name + ' 已保存', 'success');
    // 清空表单
    ['mm-add-name', 'mm-add-url', 'mm-add-default', 'mm-add-models', 'mm-add-desc'].forEach(id => { $(id).value = ''; });
    $('mm-add-vision').checked = false;
    $('mm-add-thinking').checked = false;
    await loadProviders();
  } catch (e) {
    _mmStatus('保存失败: ' + e.message, 'error');
  }
}

async function applyProvider() {
  if (!mmSelectedProvider) { _mmStatus('请先选择供应商', 'error'); return; }
  if (!mmSelectedModel) { _mmStatus('请先选择模型', 'error'); return; }
  const payload = {
    provider: mmSelectedProvider,
    model: mmSelectedModel,
    role: role,
    api_key: ($('mm-key').value || '').trim(),
    continue_session: $('mm-continue') ? $('mm-continue').checked : true,
  };
  const meta = mmSelectedMeta || {};
  if (meta.max_output_tokens) payload.max_tokens = meta.max_output_tokens;
  if (meta.context_window) payload.max_context_tokens = meta.context_window;
  try {
    const r = await fetch('/api/model-config/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok || d.ok === false) throw new Error(d.error || 'HTTP ' + r.status);
    const sw = d.switch || {};
    const msgs = {
      applied: '✅ 已热切换 ' + d.model + '（逐模型配置自动注入），当前会话继续',
      pending_next_turn: '⏳ 当前回复进行中，本轮结束后自动切换为 ' + d.model + ' 并继续会话',
      next_message: '✅ 已应用 ' + d.model + '，下一条消息起以新模型继续当前会话',
      config_only: '✅ 已将 ' + d.model + ' 应用为 ' + role + ' 角色（下次会话生效）',
      error: '⚠️ 配置已落盘，但会话切换失败: ' + (sw.error || ''),
    };
    _mmStatus(msgs[sw.mode] || msgs.config_only, sw.mode === 'error' ? 'error' : 'success');
    $('mm-key').value = '';
    await loadModelConfig();
    // 刷新顶部模型下拉
    if (typeof refreshModelSelects === 'function') refreshModelSelects();
    toast('🎯 ' + d.model, 'success');
  } catch (e) {
    _mmStatus('应用失败: ' + e.message, 'error');
  }
}

async function testConnection() {
  const api_url = (mmProviders.find(p => p.name === mmSelectedProvider) || {}).api_url;
  const api_key = ($('mm-key').value || '').trim();
  if (!api_url || !api_key) {
    _mmStatus('测试连接需要 api_key（请填写 API Key）', 'error');
    return;
  }
  const btn = document.querySelector('#mm-current .btn-g');
  const old = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 测试中…'; }
  try {
    const r = await fetch('/api/model/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_url, api_key, model: mmSelectedModel || undefined }),
    });
    const d = await r.json();
    if (d.ok) {
      _mmStatus('✅ 连接正常 ' + d.latency_ms + 'ms' + (d.model_reported ? ' | 模型: ' + d.model_reported : ''), 'success');
    } else {
      _mmStatus('❌ 连接失败: ' + (d.error || '未知错误'), 'error');
    }
  } catch (e) {
    _mmStatus('❌ 测试异常: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

async function deleteProvider(name) {
  const target = name || mmSelectedProvider;
  if (!target) return;
  if (!confirm('确定删除自定义供应商 ' + target + ' 吗？')) return;
  try {
    const r = await fetch('/api/providers/' + encodeURIComponent(target), { method: 'DELETE' });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    _mmStatus('🗑 已删除 ' + target, 'success');
    if (mmSelectedProvider === target) { mmSelectedProvider = ''; mmSelectedModel = ''; }
    await loadProviders();
  } catch (e) {
    _mmStatus('删除失败: ' + e.message, 'error');
  }
}

// ── 导出到 window（HTML 内联 onclick/oninput 需要全局可见） ──
// 注：IIFE 内 function/let 声明不在全局作用域；不导出则
// onclick="renderProviders()" 等全部 ReferenceError，控件失效。
window._mmStatus = _mmStatus;
window.refreshCurrentModel = refreshCurrentModel;
window.loadProviders = loadProviders;
window.renderProviders = renderProviders;
window.selectProvider = selectProvider;
window.loadModels = loadModels;
window.renderModels = renderModels;
window.selectModel = selectModel;
window.showEditProviderForm = showEditProviderForm;
window.showAddProviderForm = showAddProviderForm;
window.hideAddProviderForm = hideAddProviderForm;
window.submitProvider = submitProvider;
window.applyProvider = applyProvider;
window.testConnection = testConnection;
window.deleteProvider = deleteProvider;
window.loadModelConfig = loadModelConfig;
window.renderModels = renderModels;
window.saveModelConfig = saveModelConfig;
window.delModelConfig = delModelConfig;
window.syncModels = syncModels;
// 变量用 getter 导出（let 重新赋值不改变 window 属性引用，getter 保证实时读取）
Object.defineProperty(window, 'mmSelectedProvider', { get: () => mmSelectedProvider });
Object.defineProperty(window, 'mmSelectedModel', { get: () => mmSelectedModel });

})();
