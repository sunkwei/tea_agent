/**
 * Tea Agent Web App - matching GUI layout & behavior
 * Features: SSE streaming, topic management, model switch, search, memory, tasks, export
 */
(function() {
'use strict';

// -- State --
let currentTopicId = '';
let isStreaming = false;
let activeTheme = localStorage.getItem('tea-theme') || 'dark';
let abortController = null;     // AbortController 实例，用于中断请求
let _pendingUsage = null;       // 暂存 token 用量，流结束后才显示

// -- DOM helpers --
const $ = (id) => document.getElementById(id);
const esc = (t) => { if (!t) return ''; const d = document.createElement('div'); d.textContent = t; return d.innerHTML; };
const show = (id) => { $(id).style.display = 'flex'; };
const hide = (id) => { $(id).style.display = 'none'; };

// -- Toast --
function toast(msg, type) {
    let el = $('toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'toast';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.className = 'show ' + (type || '');
    setTimeout(() => el.classList.remove('show'), 2500);
}

// -- Theme --
window.toggleTheme = function() {
    activeTheme = activeTheme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('tea-theme', activeTheme);
    applyTheme();
};
function applyTheme() {
    const t = activeTheme === 'dark'
        ? { '--bg': '#0d1117', '--surface': '#161b22', '--surface2': '#21262d', '--text': '#c9d1d9', '--text-dim': '#8b949e', '--border': '#30363d' }
        : { '--bg': '#ffffff', '--surface': '#f6f8fa', '--surface2': '#e8eaed', '--text': '#1f2328', '--text-dim': '#656d76', '--border': '#d1d5da' };
    const root = document.documentElement;
    for (const [k, v] of Object.entries(t)) root.style.setProperty(k, v);
    if ($('theme-btn')) $('theme-btn').textContent = activeTheme === 'dark' ? '\u2600' : '\uD83C\uDF19';
}
applyTheme();

// -- Messages --
function addMessage(role, content, images) {
    let w = document.querySelector('.welcome');
    if (w) w.style.display = 'none';
    const div = document.createElement('div');
    div.className = 'msg ' + (role === 'user' ? 'user' : 'agent');

    let html = '<div class="msg-label">' + (role === 'user' ? '\u4f60' : 'Tea Agent') + '</div>';
    html += '<div class="msg-bubble">';
    // 显示图片
    if (images && images.length > 0) {
        html += '<div class="msg-images" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px;">';
        images.forEach(function(img) {
            html += '<img src="' + esc(img) + '" style="max-height:150px;max-width:250px;border-radius:6px;border:1px solid var(--border);cursor:pointer;" onclick="window.openImageOverlay(this.src)">';
        });
        html += '</div>';
    }
    html += formatMarkdown(content || '');
    html += '</div>';
    div.innerHTML = html;

    // 点击图片查看大图
    div.querySelectorAll('.msg-images img').forEach(function(img) {
        img.addEventListener('click', function() { window.openImageOverlay(this.src); });
    });

    $('messages').appendChild(div);
    scrollBottom();
    return div.querySelector('.msg-bubble');
}

// 图片大图查看
window.openImageOverlay = function(src) {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;z-index:9999;cursor:pointer;';
    overlay.innerHTML = '<img src="' + esc(src) + '" style="max-width:90vw;max-height:90vh;border-radius:8px;">';
    overlay.addEventListener('click', function() { overlay.remove(); });
    document.body.appendChild(overlay);
};

// ── 智能滚动：用户向上翻看时不自动跳转 ──
let _userNearBottom = true;  // 用户是否在聊天底部附近

function _isNearBottom() {
    const m = $('messages');
    if (!m) return true;
    // 距离底部 80px 以内视为"在底部"
    return m.scrollHeight - m.scrollTop - m.clientHeight < 80;
}

function scrollBottom() {
    if (!_userNearBottom) return;  // 用户在看历史，不强制跳转
    const m = $('messages');
    if (!m) return;
    // 直接同步滚动，避免 setTimeout 延迟导致肉眼可见的跳动
    m.scrollTop = m.scrollHeight;
}

function addLoading() {
    let w = document.querySelector('.welcome');
    if (w) w.style.display = 'none';
    const div = document.createElement('div');
    div.className = 'loading';
    div.id = 'loading-indicator';
    div.innerHTML = '<div class="spinner"></div><span>\u6b63\u5728\u601d\u8003...</span>';
    $('messages').appendChild(div);
    scrollBottom();
}
function removeLoading() {
    const el = $('loading-indicator');
    if (el) el.remove();
}

// -- SSE Chat --
// 中断当前对话（模拟 ESC 行为）
window.interruptChat = async function() {
    // 1. Abort the HTTP request
    if (abortController) {
        abortController.abort();
        abortController = null;
    }
    // 2. Signal the backend to stop processing
    if (currentTopicId) {
        try {
            await fetch('/api/chat/abort', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ topic_id: currentTopicId }),
                signal: AbortSignal.timeout(3000),  // 最多等3秒
            });
        } catch (e) { /* ignore timeout errors */ }
    }
    // 3. Update loading indicator if still visible
    removeLoading();
    const bubbleText = document.getElementById('bubble-text');
    if (bubbleText && !bubbleText.innerHTML.trim()) {
        bubbleText.innerHTML = '(\u5df2\u4e2d\u65ad)';
    }
    // Note: isStreaming will be set to false in sendMessage's finally block
};

window.sendMessage = async function() {
    // 如果正在对话中，点击发送按钮=中断
    if (isStreaming) {
        await interruptChat();
        return;
    }
    const input = $('chat-input');
    const msg = input.value.trim();
    if (!msg && pendingImages.length === 0) return;
    input.value = '';

    // 构建用户消息显示（含图片预览）
    addMessage('user', msg || '(图片)', pendingImages.length > 0 ? pendingImages : null);
    addLoading();

    // 收集图片数据并清空
    const imagesToSend = [...pendingImages];
    pendingImages = [];
    updateImagePreview();

    const agentDiv = document.createElement('div');
    agentDiv.className = 'msg agent';
    agentDiv.id = 'current-ai-msg';
    agentDiv.innerHTML = '<div class="msg-label">Tea Agent</div><div class="msg-bubble" id="ai-bubble"><div id="bubble-text"></div></div>';
    $('messages').appendChild(agentDiv);
    const bubble = $('ai-bubble');
    const bubbleText = $('bubble-text');
    let thinkBlock = null, thinkContent = null;
    let fullText = '';
    // Tool call state tracking
    let toolCallContainer = null;  // <details> wrapper
    let toolCallList = null;       // tool item list inside details
    let toolCallSummary = null;    // <summary> element
    let toolCallBadge = null;      // count badge
    let toolCallCount = 0;
    let toolDoneCount = 0;
    let activeToolItem = null;     // currently running tool DOM element

    isStreaming = true;
    _pendingUsage = null;
    abortController = new AbortController();
    // 切换发送按钮为「中断」样式
    const sendBtn = $('send-btn');
    sendBtn.textContent = '\u23f9 \u4e2d\u65ad';
    sendBtn.className = 'btn btn-danger';
    sendBtn.disabled = false;

    try {
        const body = { message: msg, topic_id: currentTopicId };
        if (imagesToSend.length > 0) body.images = imagesToSend;
        // 如果当前有选中的配置路径，附带发送（不同 Web 实例可用不同配置）
        if (_configCurrentPath) body.config_path = _configCurrentPath;
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
            const lines = buf.split('\n');
            for (let i = 0; i < lines.length - 1; i++) {
                const line = lines[i].trim();
                if (!line.startsWith('data: ')) continue;
                try {
                    const data = JSON.parse(line.slice(6));
                    switch (data.type) {
                        case 'token':
                            removeLoading();
                            fullText += data.text;
                            bubbleText.innerHTML = formatMarkdown(fullText);
                            break;
                        case 'think_start':
                            removeLoading();
                            thinkBlock = document.createElement('details');
                            thinkBlock.className = 'think-block';
                            thinkBlock.innerHTML = '<summary>\uD83D\uDCAD \u601d\u8003\u4e2d...</summary>';
                            thinkContent = document.createElement('div');
                            thinkContent.className = 'think-content';
                            thinkBlock.appendChild(thinkContent);
                            bubble.insertBefore(thinkBlock, bubbleText);
                            break;
                        case 'think':
                            if (thinkContent) thinkContent.textContent += data.text;
                            break;
                        case 'think_done':
                            if (thinkBlock) {
                                const summary = thinkBlock.querySelector('summary');
                                if (summary) summary.textContent = '\uD83D\uDCAD \u601d\u8003\u5b8c\u6210 (' + (thinkContent ? thinkContent.textContent.length : 0) + ' \u5b57)';
                            }
                            thinkBlock = null; thinkContent = null;
                            break;
                        case 'tool_start':
                            removeLoading();
                            toolCallCount++;
                            // Create collapsible container on first tool call
                            if (!toolCallContainer) {
                                toolCallContainer = document.createElement('details');
                                toolCallContainer.className = 'tool-call-container';
                                toolCallContainer.open = true;
                                toolCallSummary = document.createElement('summary');
                                toolCallSummary.className = 'tool-call-summary';
                                toolCallSummary.innerHTML = '<span class="icon">🔧</span><span class="label">工具调用中...</span><span class="badge">0/' + toolCallCount + '</span>';
                                toolCallBadge = toolCallSummary.querySelector('.badge');
                                toolCallContainer.appendChild(toolCallSummary);
                                toolCallList = document.createElement('div');
                                toolCallContainer.appendChild(toolCallList);
                                bubble.insertBefore(toolCallContainer, bubbleText);
                            }
                            // Create tool item with spinner
                            const item = document.createElement('div');
                            item.className = 'tool-call-item running';
                            item.innerHTML = '<span class="status-icon"><span class="tool-spinner"></span></span><span class="tool-name"><code>' + esc(data.name) + '</code></span>';
                            toolCallList.appendChild(item);
                            activeToolItem = item;
                            // Update badge
                            if (toolCallBadge) toolCallBadge.textContent = toolDoneCount + '/' + toolCallCount;
                            scrollBottom();
                            break;
                        case 'tool_done':
                            // Mark running tool as done
                            if (activeToolItem) {
                                activeToolItem.classList.remove('running');
                                activeToolItem.classList.add('done');
                                const icon = activeToolItem.querySelector('.status-icon');
                                if (icon) icon.innerHTML = '✅';
                                toolDoneCount++;
                                if (toolCallBadge) toolCallBadge.textContent = toolDoneCount + '/' + toolCallCount;
                            }
                            activeToolItem = null;
                            // If all tools done, finalize container
                            if (toolDoneCount >= toolCallCount && toolCallContainer) {
                                toolCallContainer.classList.add('done');
                                toolCallContainer.open = false;
                                const label = toolCallSummary.querySelector('.label');
                                if (label) label.textContent = '工具调用完成';
                                const icon = toolCallSummary.querySelector('.icon');
                                if (icon) icon.textContent = '✅';
                            }
                            break;
                        case 'tool_args':
                            // Parse "key: value, key: value" and show each param
                            if (activeToolItem && data.args) {
                                const paramsDiv = document.createElement('div');
                                paramsDiv.className = 'tool-params';
                                const pairs = String(data.args).split(', ');
                                for (const pair of pairs) {
                                    const colon = pair.indexOf(': ');
                                    const row = document.createElement('div');
                                    row.className = 'tool-param-row';
                                    if (colon > 0) {
                                        const key = pair.slice(0, colon);
                                        let val = pair.slice(colon + 2);
                                        if (val.length > 120) val = val.slice(0, 120) + '…';
                                        row.innerHTML = '<span class="param-key">' + esc(key) + '</span><span class="param-val"><code>' + esc(val) + '</code></span>';
                                    } else {
                                        let val = pair;
                                        if (val.length > 120) val = val.slice(0, 120) + '…';
                                        row.innerHTML = '<span class="param-val"><code>' + esc(val) + '</code></span>';
                                    }
                                    paramsDiv.appendChild(row);
                                }
                                activeToolItem.appendChild(paramsDiv);
                            }
                            break;
                        case 'tool_result':
                            // Show return value under the tool item
                            if (activeToolItem && data.result) {
                                let val = String(data.result);
                                if (val.length > 120) val = val.slice(0, 120) + '…';
                                const resDiv = document.createElement('div');
                                resDiv.className = 'tool-result';
                                resDiv.innerHTML = '<span class="result-label">↳</span><span class="result-val"><code>' + esc(val) + '</code></span>';
                                activeToolItem.appendChild(resDiv);
                            }
                            break;
                        case 'status':
                            removeLoading();
                            const st = document.createElement('div');
                            st.className = 'status-msg info';
                            st.textContent = data.text;
                            st.style.fontSize = '12px';
                            st.style.margin = '4px 0';
                            bubble.insertBefore(st, bubbleText);
                            setTimeout(() => st.remove(), 3000);
                            break;
                        case 'max_iter_confirm':
                            // 工具轮达到上限，弹窗询问用户是否继续
                            removeLoading();
                            showMaxIterConfirm(data.confirm_id, data.text);
                            break;
                        case 'done':
                            removeLoading();
                            // Finalize tool container if still open
                            if (toolCallContainer && !toolCallContainer.classList.contains('done')) {
                                toolCallContainer.classList.add('done');
                                toolCallContainer.open = false;
                                const label = toolCallSummary.querySelector('.label');
                                if (label) label.textContent = '工具调用完成';
                                const iconEl = toolCallSummary.querySelector('.icon');
                                if (iconEl) iconEl.textContent = '✅';
                            }
                            if (!fullText && data.ai_msg) {
                                bubbleText.innerHTML = formatMarkdown(data.ai_msg);
                            } else if (!fullText) {
                                bubbleText.innerHTML = '(\u65e0\u54cd\u5e94)';
                            }
                            // 暂存 usage，等流结束后在 finally 中显示（避免用户误以为对话已结束）
                            if (data.usage) _pendingUsage = data.usage;
                            // 保存 topic_id 以便后续消息关联到同一主题
                            if (data.topic_id) {
                                currentTopicId = data.topic_id;
                                // 更新工具栏标题（新主题时用简短id显示）
                                const titleEl = document.getElementById('topic-title');
                                if (titleEl && titleEl.textContent === '新对话') {
                                    titleEl.textContent = 'Web Session';
                                }
                            }
                            break;
                        case 'error':
                            removeLoading();
                            bubbleText.innerHTML = '<span style="color:var(--red)">\u9519\u8bef: ' + esc(data.error) + '</span>';
                            break;
                    }
                    scrollBottom();
                } catch (e) { /* skip */ }
            }
            buf = lines[lines.length - 1];
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            // 用户主动中断，不显示错误
            removeLoading();
            if (!bubbleText.innerHTML.trim()) {
                bubbleText.innerHTML = '(\u5df2\u4e2d\u65ad)';
            }
        } else {
            removeLoading();
            bubbleText.innerHTML = '<span style="color:var(--red)">\u7f51\u7edc\u9519\u8bef: ' + esc(e.message) + '</span>';
        }
    } finally {
        isStreaming = false;
        abortController = null;
        // 恢复发送按钮
        const sendBtn = $('send-btn');
        sendBtn.textContent = '\u53d1\u9001';
        sendBtn.className = 'btn btn-primary';
        sendBtn.disabled = false;
        // 流结束后才显示 token 用量，避免用户误以为对话还在进行中
        if (_pendingUsage) {
            updateUsage(_pendingUsage);
            _pendingUsage = null;
        }
        $('chat-input').focus();
        // Clean up ids to prevent DOM id collision on next message
        const old = $('current-ai-msg');
        if (old) {
            old.removeAttribute('id');
            const oldBubble = old.querySelector('#ai-bubble');
            if (oldBubble) oldBubble.removeAttribute('id');
            const oldText = old.querySelector('#bubble-text');
            if (oldText) oldText.removeAttribute('id');
        }
        refreshTopics();
    }
};

function updateUsage(usage) {
    if (!usage.total_tokens) return;
    let bar = $('usage-bar');
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'usage-bar';
        bar.style.cssText = 'padding:4px 16px;font-size:12px;color:var(--text-dim);text-align:right;border-top:1px solid var(--border)';
        const main = $('main');
        main.insertBefore(bar, $('input-row'));
    }
    bar.textContent = '\uD83D\uDCCA \u672c\u6b21: ' + usage.total_tokens + ' tokens (prompt: ' + usage.prompt_tokens + ', completion: ' + usage.completion_tokens + ')';
}

// -- Markdown --
function formatMarkdown(text) {
    if (!text) return '';
    let html = esc(text).replace(/\r\n/g, '\n');
    // Protect code blocks from newline conversion
    const codeBlocks = [];
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function(match, lang, code) {
        const idx = codeBlocks.length;
        codeBlocks.push('<pre><code>' + code.trimEnd() + '</code></pre>');
        return '\x00CODE' + idx + '\x00';
    });
    // Inline code
    const inlineCodes = [];
    html = html.replace(/`([^`]+)`/g, function(match, code) {
        const idx = inlineCodes.length;
        inlineCodes.push('<code>' + code + '</code>');
        return '\x00ICODE' + idx + '\x00';
    });
    // Headers (protect from <br> conversion)
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
    // Tables (protect from <br> conversion)
    const tableBlocks = [];
    html = html.replace(/^\|(.+)\|[ \t]*[\r\n]+\|[\-:|\s]+\|[ \t]*[\r\n]+((?:^\|.+\|[ \t]*[\r\n]?)+)/gm, function(match, headerRow, bodyRows) {
        let h = headerRow.split('|').map(function(c, i) { return '<th>' + c.trim() + '</th>'; }).join('');
        let rows = bodyRows.trim().split('\n').map(function(line) {
            let cells = line.replace(/^\||\|$/g, '').split('|').map(function(c) { return '<td>' + c.trim() + '</td>'; }).join('');
            return '<tr>' + cells + '</tr>';
        }).join('');
        const idx = tableBlocks.length;
        tableBlocks.push('<table class="md-table"><thead><tr>' + h + '</tr></thead><tbody>' + rows + '</tbody></table>');
        return '\x00TABLE' + idx + '\x00';
    });
    // Convert newlines to <br> (outside code blocks and tables)
    html = html.replace(/\n/g, '<br>');
    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    // Restore inline codes
    html = html.replace(/\x00ICODE(\d+)\x00/g, function(m, idx) { return inlineCodes[idx] || ''; });
    // Restore tables
    html = html.replace(/\x00TABLE(\d+)\x00/g, function(m, idx) { return tableBlocks[idx] || ''; });
    // Restore code blocks
    html = html.replace(/\x00CODE(\d+)\x00/g, function(m, idx) { return codeBlocks[idx] || ''; });
    return html;
}

// -- Topics --
function escHtml(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/'/g,'&#39;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function refreshTopics() {
    try {
        const r = await fetch('/api/sessions');
        if (!r.ok) return;
        const d = await r.json();
        const list = $('topic-list');
        const sessions = d.sessions || d.data || [];
        list.innerHTML = sessions.map(t => {
            const title = t.title || (t.id || '').slice(0, 8);
            const cls = 'topic-item' + (t.id === currentTopicId ? ' active' : '');
            const safeId = escHtml(t.id);
            const safeTitle = escHtml(title);
            return '<div class="' + cls + '" data-topic-id="' + safeId + '">'
                + '<span class="topic-item-title">' + safeTitle + '</span>'
                + '<button class="topic-actions-btn">⋯</button>'
                + '<div class="topic-actions-menu" data-topic-id="' + safeId + '">'
                + '<button class="topic-actions-menu-item" data-action="rename">✏️ 改名</button>'
                + '<button class="topic-actions-menu-item danger" data-action="delete">🗑️ 删除</button>'
                + '</div>'
                + '</div>';
        }).join('');
    } catch (e) { /* ignore */ }
}

// Event delegation for topic list — handles click on title, "⋯" button, menu items
document.getElementById('topic-list').addEventListener('click', function(e) {
    const item = e.target.closest('.topic-item');
    if (!item) return;
    const id = item.dataset.topicId;

    // "⋯" button clicked — toggle menu
    if (e.target.closest('.topic-actions-btn')) {
        e.stopPropagation();
        // Close all other menus
        document.querySelectorAll('.topic-actions-menu.show').forEach(m => {
            if (m.closest('.topic-item') !== item) m.classList.remove('show');
        });
        const menu = item.querySelector('.topic-actions-menu');
        menu.classList.toggle('show');
        return;
    }

    // Menu item clicked
    const menuItem = e.target.closest('.topic-actions-menu-item');
    if (menuItem) {
        e.stopPropagation();
        const action = menuItem.dataset.action;
        const menu = menuItem.closest('.topic-actions-menu');
        menu.classList.remove('show');
        if (action === 'rename') renameTopic(id);
        else if (action === 'delete') deleteTopic(id);
        return;
    }

    // Title clicked — open topic
    if (e.target.closest('.topic-item-title')) {
        // Get original title text from the item
        const titleSpan = item.querySelector('.topic-item-title');
        const title = titleSpan.textContent;
        openTopic(id, title);
    }
});

// Close topic menus when clicking outside any topic item
document.addEventListener('click', function(e) {
    if (!e.target.closest('.topic-item')) {
        document.querySelectorAll('.topic-actions-menu.show').forEach(m => m.classList.remove('show'));
    }
});

async function renameTopic(id) {
    const newTitle = prompt('请输入新主题名称:');
    if (!newTitle || !newTitle.trim()) return;
    try {
        const r = await fetch('/api/topic/' + id, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: newTitle.trim()})
        });
        if (!r.ok) {
            toast('重命名失败: HTTP ' + r.status);
            return;
        }
        toast('✅ 已重命名');
        refreshTopics();
        if (id === currentTopicId) {
            $('topic-title').textContent = newTitle.trim();
        }
    } catch (e) {
        toast('重命名失败: ' + e.message);
    }
}

async function deleteTopic(id) {
    if (!confirm('确定要删除此主题及其所有对话吗？此操作不可撤销。')) return;
    try {
        const r = await fetch('/api/topic/' + id, { method: 'DELETE' });
        if (!r.ok) {
            toast('删除失败: HTTP ' + r.status);
            return;
        }
        toast('🗑️ 已删除');
        if (id === currentTopicId) {
            currentTopicId = '';
            $('topic-title').textContent = '欢迎使用 Tea Agent';
            $('messages').innerHTML = '<div class="welcome"><div class="welcome-icon">☕</div><h2>Tea Agent</h2><p>自进化 AI 编程助手 · 60+ 内置工具 · 多 Agent 协作 · 长期记忆<br>在下方输入消息开始对话</p></div>';
        }
        refreshTopics();
    } catch (e) {
        toast('删除失败: ' + e.message);
    }
}

window.openTopic = async function(id, title) {
    currentTopicId = id;
    $('topic-title').textContent = title || id.slice(0, 8);
    refreshTopics();
    try {
        const r = await fetch('/api/topic/' + id + '/conversations?limit=50');
        if (!r.ok) return;
        const d = await r.json();
        $('messages').innerHTML = '';
        (d.conversations || []).forEach(c => {
            addMessage('user', c.user_msg || '');
            addMessage('agent', c.ai_msg || '');
        });
    } catch (e) { /* ignore */ }
};

window.newTopic = function() {
    currentTopicId = '';
    $('topic-title').textContent = '\u65b0\u5bf9\u8bdd';
    $('messages').innerHTML = '<div class="welcome"><div class="welcome-icon">\u2615</div><h2>Tea Agent</h2><p>\u81ea\u8fdb\u5316 AI \u7f16\u7a0b\u52a9\u624b \u00b7 60+ \u5185\u7f6e\u5de5\u5177 \u00b7 \u591a Agent \u534f\u4f5c \u00b7 \u957f\u671f\u8bb0\u5fc6<br>\u5728\u4e0b\u65b9\u8f93\u5165\u6d88\u606f\u5f00\u59cb\u5bf9\u8bdd</p></div>';
    refreshTopics();
    $('chat-input').focus();
};

window.clearChat = function() {
    if (isStreaming) { toast('\u6b63\u5728\u53d1\u9001\u6d88\u606f\uff0c\u8bf7\u7a0d\u5019...', 'error'); return; }
    $('messages').innerHTML = '<div class="welcome"><div class="welcome-icon">\u2615</div><h2>Tea Agent</h2><p>\u81ea\u8fdb\u5316 AI \u7f16\u7a0b\u52a9\u624b \u00b7 60+ \u5185\u7f6e\u5de5\u5177 \u00b7 \u591a Agent \u534f\u4f5c \u00b7 \u957f\u671f\u8bb0\u5fc6<br>\u5728\u4e0b\u65b9\u8f93\u5165\u6d88\u606f\u5f00\u59cb\u5bf9\u8bdd</p></div>';
};

window.handleInputKey = function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!isStreaming) sendMessage();
    }
};


// -- Search --
window.showSearch = function() { show('modal-search'); $('search-query').value = ''; $('search-results').innerHTML = ''; setTimeout(() => $('search-query').focus(), 100); };
window.doSearch = async function() {
    const q = $('search-query').value.trim();
    if (!q) return;
    const el = $('search-results');
    el.innerHTML = '<div class="status-msg info">\u641c\u7d22\u4e2d...</div>';
    try {
        const r = await fetch('/v1/search?q=' + encodeURIComponent(q) + '&limit=20');
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        let h = '';
        if (d.conversations && d.conversations.length) {
            h += '<div style="font-size:13px;font-weight:600;margin:8px 0 4px">\u5bf9\u8bdd\u7ed3\u679c</div>';
            d.conversations.forEach(c => h += '<div class="search-item"><div class="st">' + esc(c.user_msg || c.ai_msg || '') + '</div><div class="sp">' + esc(c.stamp || '') + '</div></div>');
        }
        if (d.memories && d.memories.length) {
            h += '<div style="font-size:13px;font-weight:600;margin:8px 0 4px">\u8bb0\u5fc6\u7ed3\u679c</div>';
            d.memories.forEach(m => h += '<div class="search-item"><div class="st">' + esc(m.content || '') + '</div><div class="sp">' + esc(m.category || '') + '</div></div>');
        }
        if (!h) h = '<div style="color:var(--text-dim);font-size:13px">\u6ca1\u6709\u7ed3\u679c</div>';
        el.innerHTML = h;
    } catch (e) { el.innerHTML = '<div class="status-msg error">Error: ' + e.message + '</div>'; }
};

// -- Memory --
window.showMemory = async function() { show('modal-memory'); $('memory-input').value = ''; await refreshMemory(); };
async function refreshMemory() {
    try {
        const r = await fetch('/v1/memory');
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        const el = $('memory-list');
        const items = d.data || [];
        if (items.length) {
            el.innerHTML = items.map(m => '<div class="memory-item"><div class="text">' + esc(m.content || '') + '<span class="meta">' + esc(m.category || '') + '</span></div><button class="btn btn-ghost btn-sm" onclick="deleteMemory(\'' + m.id + '\')">\u5220\u9664</button></div>').join('');
        } else { el.innerHTML = '<div style="color:var(--text-dim);font-size:13px">\u6682\u65e0\u8bb0\u5fc6</div>'; }
    } catch (e) {}
}
window.addMemory = async function() {
    const c = $('memory-input').value.trim();
    if (!c) return;
    try {
        await fetch('/v1/memory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: c }) });
        $('memory-input').value = '';
        await refreshMemory();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
};
window.deleteMemory = async function(id) {
    try { await fetch('/v1/memory/' + encodeURIComponent(id), { method: 'DELETE' }); await refreshMemory(); } catch (e) {}
};

// -- Tasks --
window.showScheduler = async function() { show('modal-scheduler'); $('task-name').value = ''; $('task-command').value = ''; $('task-schedule').value = ''; await refreshTasks(); };
async function refreshTasks() {
    try {
        const r = await fetch('/v1/tasks');
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        const el = $('task-list');
        const items = d.data || [];
        if (items.length) {
            el.innerHTML = items.map(t => '<div class="task-item"><div class="text">' + esc(t.name || '') + '<span class="meta">' + esc(t.schedule || '') + '</span></div><button class="btn btn-ghost btn-sm" onclick="deleteTask(\'' + t.id + '\')">\u5220\u9664</button></div>').join('');
        } else { el.innerHTML = '<div style="color:var(--text-dim);font-size:13px">\u6682\u65e0\u4efb\u52a1</div>'; }
    } catch (e) {}
}
window.addTask = async function() {
    const name = $('task-name').value.trim();
    const cmd = $('task-command').value.trim();
    const sched = $('task-schedule').value.trim();
    if (!name || !cmd) { toast('\u8bf7\u586b\u5199\u4efb\u52a1\u540d\u79f0\u548c\u547d\u4ee4', 'error'); return; }
    try {
        await fetch('/v1/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, command: cmd, schedule: sched || 'once' }) });
        $('task-name').value = ''; $('task-command').value = ''; $('task-schedule').value = '';
        await refreshTasks();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
};
window.deleteTask = async function(id) {
    try { await fetch('/v1/tasks/' + encodeURIComponent(id), { method: 'DELETE' }); await refreshTasks(); } catch (e) {}
};

// -- Export --
window.showExport = function() { show('modal-export'); $('export-result').innerHTML = ''; };
window.doExport = async function() {
    if (!currentTopicId) { $('export-result').innerHTML = '<div class="status-msg error">\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u8bdd\u9898</div>'; return; }
    const el = $('export-result');
    el.innerHTML = '<div class="status-msg info">\u5bfc\u51fa\u4e2d...</div>';
    try {
        const r = await fetch('/v1/export/pdf', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic_id: currentTopicId }) });
        const d = await r.json();
        if (d.success) el.innerHTML = '<div class="status-msg success">\u2713 \u5df2\u5bfc\u51fa: ' + esc(d.path || '') + '</div>';
        else el.innerHTML = '<div class="status-msg error">' + esc(d.error || '\u5931\u8d25') + '</div>';
    } catch (e) { el.innerHTML = '<div class="status-msg error">Error: ' + e.message + '</div>'; }
};

// -- Settings --
window.showSettings = async function() {
    show('modal-settings');
    $('settings-status').innerHTML = '';
    try {
        // Load current config
        const r1 = await fetch('/api/config');
        if (r1.ok) {
            const cfg = await r1.json();
            $('model-name').value = cfg.model || '';
            $('api-url').value = cfg.api_url || '';
            $('api-key').value = '';
            $('main-temperature').value = cfg.temperature != null ? cfg.temperature : '';
            $('main-max-tokens').value = cfg.max_tokens != null ? cfg.max_tokens : '';
            $('main-top-p').value = cfg.top_p != null ? cfg.top_p : '';
            $('main-max-context').value = cfg.max_context_tokens != null ? cfg.max_context_tokens : '';
            const mainOpts = cfg.options || {};
            $('main-supports-vision').checked = !!mainOpts.supports_vision;
            $('main-supports-reasoning').checked = mainOpts.supports_reasoning !== false;
            // Runtime params
            $('rt-max-iterations').value = cfg.max_iterations != null ? cfg.max_iterations : '';
            $('rt-keep-turns').value = cfg.keep_turns != null ? cfg.keep_turns : '';
            $('rt-max-history').value = cfg.max_history != null ? cfg.max_history : '';
            $('rt-max-tool-output').value = cfg.max_tool_output != null ? cfg.max_tool_output : '';
            $('rt-extra-iters').value = cfg.extra_iterations_on_continue != null ? cfg.extra_iterations_on_continue : '';
            $('rt-mem-extract').value = cfg.memory_extraction_threshold != null ? cfg.memory_extraction_threshold : '';
            $('rt-mem-dedup').value = cfg.memory_dedup_threshold != null ? cfg.memory_dedup_threshold : '';
            $('rt-chat-page').value = cfg.chat_page_size != null ? cfg.chat_page_size : '';
            $('rt-enable-thinking').checked = cfg.enable_thinking !== false;
            if (cfg.cheap_model) {
                $('cheap-model-name').value = cfg.cheap_model.model || '';
                $('cheap-api-url').value = cfg.cheap_model.api_url || '';
                $('cheap-api-key').value = '';
                $('cheap-temperature').value = cfg.cheap_model.temperature != null ? cfg.cheap_model.temperature : '';
                $('cheap-max-tokens').value = cfg.cheap_model.max_tokens != null ? cfg.cheap_model.max_tokens : '';
                $('cheap-top-p').value = cfg.cheap_model.top_p != null ? cfg.cheap_model.top_p : '';
                $('cheap-max-context').value = cfg.cheap_model.max_context_tokens != null ? cfg.cheap_model.max_context_tokens : '';
                const cheapOpts = cfg.cheap_model.options || {};
                $('cheap-supports-vision').checked = !!cheapOpts.supports_vision;
                $('cheap-supports-reasoning').checked = cheapOpts.supports_reasoning !== false;
            }
        }
        // Load config file list
        const r2 = await fetch('/api/configs');
        if (r2.ok) {
            const d = await r2.json();
            const sel = $('config-select');
            sel.innerHTML = '<option value="">-- \u8bf7\u9009\u62e9\u6216\u65b0\u589e --</option>';
            (d.configs || []).forEach(c => {
                const model = c.main_model ? c.main_model.model_name : '';
                sel.innerHTML += '<option value="' + c.path + '">' + esc(c.filename) + ' (' + esc(model) + ')</option>';
            });
            sel.onchange = async function() {
                const path = this.value;
                if (!path) return;
                // Find matching config
                const cfg = (d.configs || []).find(c => c.path === path);
                if (cfg && cfg.main_model) {
                    $('model-name').value = cfg.main_model.model_name || '';
                    $('api-url').value = cfg.main_model.api_url || '';
                    if (cfg.cheap_model && cfg.cheap_model.model_name) {
                        $('cheap-model-name').value = cfg.cheap_model.model_name || '';
                        $('cheap-api-url').value = cfg.cheap_model.api_url || '';
                    }
                }
            };
        }
    } catch (e) { /* ignore */ }
};

window.applyConfig = async function() {
    const apiKey = $('api-key').value.trim();
    const apiUrl = $('api-url').value.trim();
    const modelName = $('model-name').value.trim();
    const cheapKey = $('cheap-api-key').value.trim();
    const cheapUrl = $('cheap-api-url').value.trim();
    const cheapModel = $('cheap-model-name').value.trim();

    if (!apiUrl || !modelName) {
        $('settings-status').innerHTML = '<div class="status-msg error">\u8bf7\u586b\u5199\u5b8c\u6574\u4e3b\u6a21\u578b\u4fe1\u606f</div>';
        return;
    }

    // Collect extra model parameters
    function numVal(id) {
        const v = $(id).value.trim();
        return v ? Number(v) : null;
    }
    const temperature = numVal('main-temperature');
    const max_tokens = numVal('main-max-tokens');
    const top_p = numVal('main-top-p');
    const max_context_tokens = numVal('main-max-context');
    const options = {
        supports_vision: $('main-supports-vision').checked,
        supports_reasoning: $('main-supports-reasoning').checked,
    };

    $('settings-status').innerHTML = '<div class="status-msg info">\u5e94\u7528\u4e2d...</div>';
    try {
        const body = {};
        if (apiKey) body.api_key = apiKey;
        body.api_url = apiUrl;
        body.model_name = modelName;
        if (temperature != null) body.temperature = temperature;
        if (max_tokens != null) body.max_tokens = max_tokens;
        if (top_p != null) body.top_p = top_p;
        if (max_context_tokens != null) body.max_context_tokens = max_context_tokens;
        body.options = options;
        if (cheapModel && cheapUrl) {
            if (cheapKey) body.cheap_api_key = cheapKey;
            body.cheap_api_url = cheapUrl;
            body.cheap_model_name = cheapModel;
            body.cheap_temperature = numVal('cheap-temperature');
            body.cheap_max_tokens = numVal('cheap-max-tokens');
            body.cheap_top_p = numVal('cheap-top-p');
            body.cheap_max_context_tokens = numVal('cheap-max-context');
            body.cheap_options = {
                supports_vision: $('cheap-supports-vision').checked,
                supports_reasoning: $('cheap-supports-reasoning').checked,
            };
        }
        const r = await fetch('/api/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (d.ok) {
            $('settings-status').innerHTML = '<div class="status-msg success">\u2713 \u5df2\u5e94\u7528: ' + esc(d.model) + '</div>';
            // Also save runtime params
            saveRuntimeParams();
            checkVisionSupport();
            setTimeout(() => hide('modal-settings'), 1500);
        } else {
            $('settings-status').innerHTML = '<div class="status-msg error">' + esc(d.error || '\u5931\u8d25') + '</div>';
        }
    } catch (e) {
        $('settings-status').innerHTML = '<div class="status-msg error">' + esc(e.message) + '</div>';
    }
};

// Save runtime params to server
async function saveRuntimeParams() {
    function numVal(id) {
        const v = $(id).value.trim();
        return v ? Number(v) : null;
    }
    const updates = {};
    const n = numVal('rt-max-iterations');
    if (n != null) updates.max_iterations = n;
    const k = numVal('rt-keep-turns');
    if (k != null) updates.keep_turns = k;
    const h = numVal('rt-max-history');
    if (h != null) updates.max_history = h;
    const t = numVal('rt-max-tool-output');
    if (t != null) updates.max_tool_output = t;
    const e = numVal('rt-extra-iters');
    if (e != null) updates.extra_iterations_on_continue = e;
    const m = numVal('rt-mem-extract');
    if (m != null) updates.memory_extraction_threshold = m;
    const d = numVal('rt-mem-dedup');
    if (d != null) updates.memory_dedup_threshold = d;
    const p = numVal('rt-chat-page');
    if (p != null) updates.chat_page_size = p;
    updates.enable_thinking = $('rt-enable-thinking').checked;
    if (Object.keys(updates).length === 0) return;
    try {
        const r = await fetch('/api/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates),
        });
        const r2 = await r.json();
        if (r2.ok) {
            console.log('Runtime params updated:', r2.updated);
        }
    } catch (e) { /* ignore */ }
}

// -- New Config --
window.showNewConfig = function() {
    show('modal-new-config');
    $('new-config-status').innerHTML = '';
};
window.saveNewConfig = async function() {
    const filename = $('new-config-filename').value.trim();
    const mainName = $('new-main-name').value.trim();
    const mainUrl = $('new-main-url').value.trim();
    const mainKey = $('new-main-key').value.trim();
    const cheapName = $('new-cheap-name').value.trim();
    const cheapUrl = $('new-cheap-url').value.trim();
    const cheapKey = $('new-cheap-key').value.trim();

    if (!filename || !mainName || !mainUrl || !mainKey) {
        $('new-config-status').innerHTML = '<div class="status-msg error">\u8bf7\u586b\u5199\u5b8c\u6574\u4fe1\u606f</div>';
        return;
    }

    $('new-config-status').innerHTML = '<div class="status-msg info">\u4fdd\u5b58\u4e2d...</div>';
    try {
        const body = { filename, main_model_name: mainName, main_api_url: mainUrl, main_api_key: mainKey };
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
            $('new-config-status').innerHTML = '<div class="status-msg success">\u2713 \u914d\u7f6e\u5df2\u4fdd\u5b58\u5e76\u5e94\u7528: ' + esc(d.filename) + '</div>';
            setTimeout(() => { hide('modal-new-config'); hide('modal-settings'); }, 1500);
        } else {
            $('new-config-status').innerHTML = '<div class="status-msg error">' + esc(d.error || '\u5931\u8d25') + '</div>';
        }
    } catch (e) {
        $('new-config-status').innerHTML = '<div class="status-msg error">' + esc(e.message) + '</div>';
    }
};



// -- Image Upload --
let pendingImages = []; // 存储待发送的图片 base64 数据

window.triggerImageUpload = function() {
    $('image-input').click();
};

window.handleImageSelect = function(event) {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (!file.type.startsWith('image/')) continue;

        const reader = new FileReader();
        reader.onload = function(e) {
            pendingImages.push(e.target.result); // base64 data URL
            updateImagePreview();
        };
        reader.readAsDataURL(file);
    }
    // 重置 input 以便可以再次选择同一文件
    event.target.value = '';
};

window.clearImages = function() {
    pendingImages = [];
    updateImagePreview();
};

function updateImagePreview() {
    const container = $('image-preview-container');
    const row = $('image-preview-row');
    if (!container || !row) return;

    if (pendingImages.length === 0) {
        row.style.display = 'none';
        container.innerHTML = '';
        return;
    }

    row.style.display = 'flex';
    container.innerHTML = '';
    pendingImages.forEach(function(img, idx) {
        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'position:relative;display:inline-block;';
        wrapper.innerHTML = '<img src="' + esc(img) + '" style="max-height:80px;max-width:120px;border-radius:6px;border:1px solid var(--border);cursor:pointer;" title="点击查看大图">' +
            '<button onclick="removeImage(' + idx + ')" style="position:absolute;top:-6px;right:-6px;background:var(--red);color:#fff;border:none;border-radius:50%;width:18px;height:18px;font-size:12px;cursor:pointer;line-height:1;">×</button>';
        // 点击查看大图
        wrapper.querySelector('img').addEventListener('click', function() {
            const overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;z-index:9999;cursor:pointer;';
            overlay.innerHTML = '<img src="' + esc(img) + '" style="max-width:90vw;max-height:90vh;border-radius:8px;">';
            overlay.addEventListener('click', function() { overlay.remove(); });
            document.body.appendChild(overlay);
        });
        container.appendChild(wrapper);
    });
}

window.removeImage = function(idx) {
    pendingImages.splice(idx, 1);
    updateImagePreview();
};

// -- Config Upload --
// 创建一个隐藏的 file input 用于上传配置文件
let _configUploadInput = null;
function _ensureConfigUploadInput() {
    if (!_configUploadInput) {
        _configUploadInput = document.createElement('input');
        _configUploadInput.type = 'file';
        _configUploadInput.accept = '.yaml,.yml';
        _configUploadInput.style.display = 'none';
        document.body.appendChild(_configUploadInput);
        _configUploadInput.addEventListener('change', async function(e) {
            const file = e.target.files && e.target.files[0];
            if (!file) return;
            await _doUploadConfig(file);
            // 重置 input 以便可以再次选择同一文件
            _configUploadInput.value = '';
        });
    }
    return _configUploadInput;
}

window.uploadConfigFile = function() {
    _ensureConfigUploadInput().click();
};

async function _doUploadConfig(file) {
    const formData = new FormData();
    formData.append('file', file);

    toast('正在上传配置...', 'info');
    try {
        const r = await fetch('/api/config/upload', {
            method: 'POST',
            body: formData,
        });
        const d = await r.json();
        if (d.ok) {
            toast('✓ 配置已上传: ' + d.filename, 'success');
            // 刷新配置组合框和配置状态
            await loadConfigSwitcher();
            checkConfigStatus();
        } else {
            toast('✗ 上传失败: ' + (d.error || '未知错误'), 'error');
        }
    } catch (e) {
        toast('✗ 上传失败: ' + e.message, 'error');
    }
}

// -- Config Status Check --
async function checkConfigStatus() {
    const warningEl = document.getElementById('config-warning');
    if (!warningEl) return;
    try {
        const r = await fetch('/api/configs');
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        // 检查是否有有效配置
        const anyValid = d.any_valid === true;
        const hasActive = !!(d.active_config_path);
        if (!anyValid && !hasActive) {
            warningEl.style.display = 'block';
        } else {
            warningEl.style.display = 'none';
        }
    } catch (e) {
        // 出错时隐藏警告，避免占位
        warningEl.style.display = 'none';
    }
}

// -- Config Switcher --
let _configCurrentPath = '';

async function loadConfigSwitcher() {
    const sel = $('cs-select');
    if (!sel) return;
    sel.disabled = true;
    sel.innerHTML = '<option value="">加载中...</option>';
    try {
        const r = await fetch('/api/configs');
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        const configs = d.configs || [];
        // 使用服务器返回的活跃配置路径设置默认选中项
        if (d.active_config_path) {
            _configCurrentPath = d.active_config_path.replace(/\\/g, '/');
        }
        let html = '<option value="">未选择</option>';
        let found = false;
        configs.forEach(function(c) {
            const model = c.main_model ? c.main_model.model_name : '';
            const norm = c.path.replace(/\\/g, '/');
            const selAttr = (norm === _configCurrentPath) ? ' selected' : '';
            if (norm === _configCurrentPath) found = true;
            html += '<option value="' + esc(c.path) + '"' + selAttr + '>' + esc(c.filename) + ' — ' + esc(model) + '</option>';
        });
        sel.innerHTML = html;
        sel.disabled = false;
        if (!found) _configCurrentPath = '';
    } catch (e) {
        sel.innerHTML = '<option value="">❌ 加载失败</option>';
        sel.disabled = true;
    }
    // 加载完成后检查配置状态
    checkConfigStatus();
}

window.switchConfig = async function(path) {
    if (!path) return;
    const sel = $('cs-select');
    if (sel) sel.disabled = true;
    try {
        const r = await fetch('/api/model/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config_path: path }),
        });
        const d = await r.json();
        if (d.ok) {
            _configCurrentPath = path.replace(/\\/g, '/');
            toast('✓ 已切换到: ' + (path.split('/').pop() || path.split('\\').pop()), 'success');
            checkVisionSupport();
        } else {
            toast('✗ 切换失败: ' + (d.error || '未知错误'), 'error');
        }
    } catch (e) {
        toast('✗ 切换失败: ' + e.message, 'error');
    }
    await loadConfigSwitcher();
    checkConfigStatus();
};


// -- Splitter drag logic --
function initSplitter(splitterId, targetId, direction) {
    const splitter = $(splitterId);
    const target = $(targetId);
    if (!splitter || !target) return;

    let startPos = 0;
    let startSize = 0;

    function onMove(e) {
        const delta = (direction === 'h' ? e.clientX : e.clientY) - startPos;
        // 若 target 在 splitter 之后（DOM 中），反转方向：拖向下时 target 缩小
        const isReversed = splitter.compareDocumentPosition(target) & Node.DOCUMENT_POSITION_FOLLOWING;
        const effectiveDelta = isReversed ? -delta : delta;
        const minSize = direction === 'h' ? 100 : 60;
        const newSize = Math.max(minSize, startSize + effectiveDelta);
        if (direction === 'h') {
            target.style.width = newSize + 'px';
            target.style.flex = 'none';
        } else {
            target.style.flex = 'none';
            target.style.height = newSize + 'px';
        }
    }

    function onUp() {
        splitter.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
    }

    splitter.addEventListener('mousedown', function(e) {
        e.preventDefault();
        startPos = direction === 'h' ? e.clientX : e.clientY;
        startSize = direction === 'h' ? target.offsetWidth : target.offsetHeight;
        splitter.classList.add('active');
        document.body.style.cursor = direction === 'h' ? 'col-resize' : 'row-resize';
        document.body.style.userSelect = 'none';
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
}

// -- Max Iter 确认弹窗 --
window.showMaxIterConfirm = function(confirmId, text) {
    const match = text.match(/已执行(\d+)轮/);
    const info = match ? match[0] : '达到上限';

    let existing = document.querySelector('.max-iter-overlay');
    if (existing) return;

    const overlay = document.createElement('div');
    overlay.className = 'max-iter-overlay';

    const box = document.createElement('div');
    box.className = 'mi-box';
    box.innerHTML = '<div class="mi-icon">🔧</div>' +
        '<div class="mi-title">工具调用轮次已达上限</div>' +
        '<div class="mi-desc">已执行 <strong>' + info + '</strong>，是否继续执行？</div>' +
        '<div class="mi-actions">' +
        '<button id="max-iter-stop" class="btn btn-ghost">终止</button>' +
        '<button id="max-iter-continue" class="btn btn-primary">继续</button>' +
        '</div>';

    overlay.appendChild(box);
    document.body.appendChild(overlay);

    document.getElementById('max-iter-stop').addEventListener('click', async function() {
        try {
            await fetch('/api/chat/continue', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirm_id: confirmId, continue: false }),
            });
        } catch (e) { /* ignore */ }
        overlay.remove();
    });

    document.getElementById('max-iter-continue').addEventListener('click', async function() {
        try {
            await fetch('/api/chat/continue', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirm_id: confirmId, continue: true }),
            });
        } catch (e) { /* ignore */ }
        overlay.remove();
    });
};

// ================================================================
//  Screenshot Region Capture (full-screen overlay + drag select)
// ================================================================

let _screenshotOverlay = null;

/** 服务端截图 — 无需浏览器 WebRTC 权限 */
async function checkVisionSupport() {
    const btn = document.getElementById('screenshot-btn');
    if (btn) {
        btn.style.display = '';
        btn.title = '服务端截图\n点击后从服务器截取屏幕，然后在截图上拖拽选区域或点击「截取全屏」';
    }
}

window.startScreenshot = async function() {
    if (_screenshotOverlay) return;

    toast('正在从服务器截取屏幕...', 'info');

    // 1. 调服务端 API 获取全屏截图 base64
    let fullImageData;
    try {
        const resp = await fetch('/api/screenshot/full');
        const data = await resp.json();
        if (!data.ok) throw new Error(data.error || '服务端截图失败');
        const b64 = data.image_base64;  // "data:image/png;base64,xxxxx"
        if (!b64 || b64.length < 100) throw new Error('截图数据无效');
        fullImageData = b64;
    } catch (err) {
        toast('截图失败: ' + err.message, 'error');
        return;
    }

    // 2. 创建 overlay（全屏暗色遮罩 + 图片居中缩放显示）
    var overlay = document.createElement('div');
    overlay.id = 'screenshot-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.88);z-index:10000;cursor:crosshair;display:flex;align-items:center;justify-content:center;';
    document.body.appendChild(overlay);
    _screenshotOverlay = overlay;

    var img = document.createElement('img');
    img.src = fullImageData;
    img.draggable = false;
    img.style.cssText = 'display:block;max-width:95vw;max-height:90vh;width:auto;height:auto;user-select:none;-webkit-user-drag:none;pointer-events:none;';
    overlay.appendChild(img);

    // 等待图片加载
    await new Promise(function(r) { img.onload = r; img.onerror = r; });

    // 确保布局稳定：等待两帧以保证 getBoundingClientRect 返回正确值
    await new Promise(function(r) { requestAnimationFrame(function() { requestAnimationFrame(r); }); });

    // 检查布局是否有效，若无效则强制布局
    var _checkRect = img.getBoundingClientRect();
    if (_checkRect.width < 1 || _checkRect.height < 1) {
        // 强制重排：临时修改样式触发 reflow
        img.style.display = 'inline-block';
        void img.offsetHeight; // force reflow
        img.style.display = 'block';
        await new Promise(function(r) { requestAnimationFrame(function() { requestAnimationFrame(r); }); });
    }
    console.log('[screenshot] img rect:', JSON.stringify(img.getBoundingClientRect()), 'natural:', img.naturalWidth, 'x', img.naturalHeight);

    // 3. 橡皮筋选区框
    var sel = document.createElement('div');
    sel.style.cssText = 'position:fixed;border:2px dashed #00aaff;background:rgba(0,170,255,0.18);display:none;pointer-events:none;z-index:10001;';
    overlay.appendChild(sel);

    // 工具条（固定在 overlay 底部）
    var toolbar = document.createElement('div');
    toolbar.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);display:flex;gap:12px;align-items:center;z-index:10002;pointer-events:auto;';
    toolbar.innerHTML = '' +
        '<span style="color:#aaa;font-size:13px;background:rgba(0,0,0,0.6);padding:6px 14px;border-radius:16px;">' +
        '🖱️ 拖拽选区域 · 点击=全图</span>' +
        '<button id="screenshot-capture-all" style="background:#1a73e8;color:white;border:none;padding:8px 18px;border-radius:8px;cursor:pointer;font-size:14px;">📷 截取全屏</button>' +
        '<button id="screenshot-cancel" style="background:rgba(255,255,255,0.15);color:#ddd;border:1px solid rgba(255,255,255,0.3);padding:8px 18px;border-radius:8px;cursor:pointer;font-size:14px;">✕ 取消</button>';
    overlay.appendChild(toolbar);

    // 辅助函数：获取图片在视口中的实际渲染矩形
    function imgRenderRect() {
        var r = img.getBoundingClientRect();
        return { left: r.left, top: r.top, width: r.width, height: r.height };
    }

    // 辅助函数：视口坐标 → 图片原始像素坐标
    function clientToImage(cx, cy) {
        var r = imgRenderRect();
        // 零宽保护：若布局未完成，用视口尺寸作为兜底
        var w = r.width > 0 ? r.width : window.innerWidth;
        var h = r.height > 0 ? r.height : window.innerHeight;
        var left = isFinite(r.left) ? r.left : 0;
        var top = isFinite(r.top) ? r.top : 0;
        // 在图片渲染区域内的比例
        var rx = (cx - left) / w;
        var ry = (cy - top) / h;
        // 钳制到 [0,1]
        rx = Math.max(0, Math.min(1, rx));
        ry = Math.max(0, Math.min(1, ry));
        var imgW = img.naturalWidth || screen.width || 1920;
        var imgH = img.naturalHeight || screen.height || 1080;
        return {
            x: Math.round(rx * imgW),
            y: Math.round(ry * imgH)
        };
    }

    // 截取并添加图片（公共函数）
    function doCrop(cropX, cropY, cropW, cropH) {
        toast('正在裁剪...', 'info');
        try {
            var canvas = document.createElement('canvas');
            canvas.width = cropW;
            canvas.height = cropH;
            var ctx = canvas.getContext('2d');
            ctx.drawImage(img, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH);
            pendingImages.push(canvas.toDataURL('image/png'));
            updateImagePreview();
            cleanupOverlay();
            toast('✓ 截图已添加', 'success');
        } catch (err) {
            toast('裁剪失败: ' + err.message, 'error');
        }
    }

    // 清理 overlay
    function cleanupOverlay() {
        document.removeEventListener('keydown', onKey);
        if (_screenshotOverlay && _screenshotOverlay.parentNode) {
            _screenshotOverlay.parentNode.removeChild(_screenshotOverlay);
        }
        _screenshotOverlay = null;
    }

    // 截取全屏
    function captureFull() {
        cleanupOverlay();
        doCrop(0, 0, img.naturalWidth, img.naturalHeight);
    }

    // 按钮事件
    document.getElementById('screenshot-capture-all').addEventListener('click', captureFull);
    document.getElementById('screenshot-cancel').addEventListener('click', function() {
        cleanupOverlay();
        toast('截图已取消', 'info');
    });

    var dragging = false;
    var clickOnly = false;
    var sx = 0, sy = 0;

    // ----- 鼠标事件 -----
    overlay.addEventListener('mousedown', function(e) {
        // 排除工具条按钮点击
        if (e.target.closest('#screenshot-cancel') || e.target.closest('#screenshot-capture-all')) return;
        dragging = true;
        clickOnly = true;
        sx = e.clientX;
        sy = e.clientY;
        sel.style.left = e.clientX + 'px';
        sel.style.top = e.clientY + 'px';
        sel.style.width = '0px';
        sel.style.height = '0px';
        sel.style.display = 'block';
    });

    overlay.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        // 有移动 → 不是纯点击
        clickOnly = false;
        var x = Math.min(sx, e.clientX);
        var y = Math.min(sy, e.clientY);
        var w = Math.abs(e.clientX - sx);
        var h = Math.abs(e.clientY - sy);
        sel.style.left = x + 'px';
        sel.style.top = y + 'px';
        sel.style.width = w + 'px';
        sel.style.height = h + 'px';
    });

    overlay.addEventListener('mouseup', function(e) {
        if (!dragging) return;
        dragging = false;

        // 情形 A：纯点击（无移动）→ 截取全屏
        if (clickOnly) {
            captureFull();
            return;
        }

        // 情形 B：拖拽选区
        _screenshotOverlay = null;
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);

        var vw = Math.abs(e.clientX - sx);
        var vh = Math.abs(e.clientY - sy);
        if (vw < 12 || vh < 12) {
            toast('选区太小，点击=全屏截图，拖拽=选区截图', 'error');
            return;
        }

        // 视口坐标 → 图片像素坐标
        var p1 = clientToImage(sx, sy);
        var p2 = clientToImage(e.clientX, e.clientY);

        var cropX = Math.max(0, Math.min(p1.x, p2.x));
        var cropY = Math.max(0, Math.min(p1.y, p2.y));
        var cropW = Math.abs(p2.x - p1.x);
        var cropH = Math.abs(p2.y - p1.y);

        // 若比例映射结果异常小，直接按视口比例估算（备用方案）
        if (cropW < 8 || cropH < 8) {
            var _r = imgRenderRect();
            var _scaleX = (_r.width > 0) ? (img.naturalWidth / _r.width) : 1;
            var _scaleY = (_r.height > 0) ? (img.naturalHeight / _r.height) : 1;
            var _altW = Math.round(vw * _scaleX);
            var _altH = Math.round(vh * _scaleY);
            if (_altW >= 8 && _altH >= 8) {
                console.log('[screenshot] fallback: clientToImage gave', cropW, 'x', cropH, '→ using', _altW, 'x', _altH);
                cropW = _altW;
                cropH = _altH;
                // 重新估算起始点
                var pMinX = Math.min(sx, e.clientX);
                var pMinY = Math.min(sy, e.clientY);
                cropX = Math.round((pMinX - _r.left) / _r.width * img.naturalWidth);
                cropY = Math.round((pMinY - _r.top) / _r.height * img.naturalHeight);
                cropX = Math.max(0, Math.min(img.naturalWidth - cropW, cropX));
                cropY = Math.max(0, Math.min(img.naturalHeight - cropH, cropY));
            } else {
                toast('选区太小，请重试', 'error');
                return;
            }
        }

        doCrop(cropX, cropY, cropW, cropH);
    });

    // ----- 触屏事件（移动端支持） -----
    var touchStart = null;

    overlay.addEventListener('touchstart', function(e) {
        if (e.target.closest('#screenshot-cancel') || e.target.closest('#screenshot-capture-all')) return;
        var t = e.touches[0];
        touchStart = { x: t.clientX, y: t.clientY };
        sx = t.clientX;
        sy = t.clientY;
        clickOnly = true;
        sel.style.left = t.clientX + 'px';
        sel.style.top = t.clientY + 'px';
        sel.style.width = '0px';
        sel.style.height = '0px';
        sel.style.display = 'block';
    }, { passive: true });

    overlay.addEventListener('touchmove', function(e) {
        if (!touchStart) return;
        clickOnly = false;
        var t = e.touches[0];
        var x = Math.min(sx, t.clientX);
        var y = Math.min(sy, t.clientY);
        var w = Math.abs(t.clientX - sx);
        var h = Math.abs(t.clientY - sy);
        sel.style.left = x + 'px';
        sel.style.top = y + 'px';
        sel.style.width = w + 'px';
        sel.style.height = h + 'px';
    }, { passive: true });

    overlay.addEventListener('touchend', function(e) {
        if (!touchStart) return;
        var endX = sx, endY = sy;
        // 如果是拖拽，取最后移动位置
        if (e.changedTouches && e.changedTouches.length > 0) {
            endX = e.changedTouches[0].clientX;
            endY = e.changedTouches[0].clientY;
        }
        touchStart = null;

        if (clickOnly) {
            captureFull();
            return;
        }

        cleanupOverlay();

        var vw = Math.abs(endX - sx);
        var vh = Math.abs(endY - sy);
        if (vw < 12 || vh < 12) return;

        var p1 = clientToImage(sx, sy);
        var p2 = clientToImage(endX, endY);
        var cropX = Math.max(0, Math.min(p1.x, p2.x));
        var cropY = Math.max(0, Math.min(p1.y, p2.y));
        var cropW = Math.abs(p2.x - p1.x);
        var cropH = Math.abs(p2.y - p1.y);
        if (cropW < 8 || cropH < 8) return;

        doCrop(cropX, cropY, cropW, cropH);
    }, { passive: true });

    // ESC 取消
    function onKey(e) {
        if (e.key === 'Escape') {
            cleanupOverlay();
            toast('截图已取消', 'info');
        }
    }
    document.addEventListener('keydown', onKey);
}




// ── 监听用户在 messages 区域的手动滚动 ──
function _initScrollTracking() {
    const m = $('messages');
    if (!m) return;
    m.addEventListener('scroll', function() {
        _userNearBottom = _isNearBottom();
    }, { passive: true });
}

// -- Init --
async function initApp() {
    await refreshTopics();
    await loadConfigSwitcher();
    checkVisionSupport();
    checkConfigStatus();
    _initScrollTracking();
    // 自动选中最近的主题，避免空 topic_id 导致刷新后创建多余的 "Web Session"
    const list = document.getElementById('topic-list');
    if (list) {
        const first = list.querySelector('.topic-item');
        if (first && !currentTopicId) {
            first.click();
        }
    }
    $('chat-input').focus();
}
initApp();
// Init splitters after DOM ready
initSplitter('sidebar-splitter', 'sidebar', 'h');
initSplitter('vsplitter', 'input-row', 'v');
})();

