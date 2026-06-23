let isStreaming = false;
let currentTopicId = '';
let abortController = null;

// ── DOM References ──
const chatContainer = document.getElementById('chat-container');
const inputArea = document.getElementById('input-area');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const welcome = document.getElementById('welcome');
const usageBar = document.getElementById('usage-bar');
const usageTokens = document.getElementById('usage-tokens');
const modelInfo = document.getElementById('model-info');
const sessionPanel = document.getElementById('session-panel');
const overlay = document.getElementById('overlay');

// ── Initialize ──
document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    setupAutoResize();
    messageInput.focus();
});

// ── Message Input ──
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

sendBtn.addEventListener('click', sendMessage);

function setupAutoResize() {
    messageInput.addEventListener('input', () => {
        messageInput.style.height = 'auto';
        messageInput.style.height = Math.min(messageInput.scrollHeight, 160) + 'px';
    });
}

// ── Config ──
async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();
        modelInfo.textContent = `${data.model}`;
    } catch (e) {
        modelInfo.textContent = '无法连接服务器';
    }
}

// ── Send Message ──
async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text || isStreaming) return;

    messageInput.value = '';
    messageInput.style.height = 'auto';
    welcome.style.display = 'none';

    // 添加用户消息
    addUserMessage(text);

    // 准备流式接收
    isStreaming = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '...';

    abortController = new AbortController();
    document.getElementById('stop-btn').style.display = 'block';

    const assistantMsg = addAssistantMessage();
    const contentDiv = assistantMsg.querySelector('.message-bubble');
    contentDiv.classList.add('streaming-cursor');

    let currentThinkBlock = null;
    let currentToolBlock = null;
    let currentToolContent = '';

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                topic_id: currentTopicId,
            }),
            signal: abortController.signal,
        });

        if (!res.ok) {
            contentDiv.textContent = `服务器错误: ${res.status}`;
            finishStreaming();
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.slice(6));
                        handleSSEEvent(event, contentDiv, assistantMsg);
                    } catch (e) {
                        console.warn('SSE parse error:', e, line);
                    }
                }
            }
        }

        // 处理剩余 buffer
        if (buffer.startsWith('data: ')) {
            try {
                const event = JSON.parse(buffer.slice(6));
                handleSSEEvent(event, contentDiv, assistantMsg);
            } catch (e) {}
        }
    } catch (e) {
        if (e.name !== 'AbortError') {
            contentDiv.textContent = `连接错误: ${e.message}`;
        }
    } finally {
        finishStreaming();
    }
}

function finishStreaming() {
    isStreaming = false;
    sendBtn.disabled = false;
    sendBtn.innerHTML = '发送';
    document.getElementById('stop-btn').style.display = 'none';
    abortController = null;

    // 移除所有流式光标
    document.querySelectorAll('.streaming-cursor').forEach(el => {
        el.classList.remove('streaming-cursor');
    });

    messageInput.focus();
}

function handleSSEEvent(event, contentDiv, assistantMsg) {
    switch (event.type) {
        case 'think_start': {
            const block = createThinkBlock();
            assistantMsg.insertBefore(block, contentDiv);
            currentThinkBlock = block;
            break;
        }
        case 'think_done': {
            if (currentThinkBlock) {
                currentThinkBlock.querySelector('.think-content').classList.add('open');
                currentThinkBlock = null;
            }
            break;
        }
        case 'think': {
            if (currentThinkBlock) {
                const tc = currentThinkBlock.querySelector('.think-content');
                tc.textContent += event.text;
                scrollToBottom();
            }
            break;
        }
        case 'tool_start': {
            const block = createToolBlock(event.name);
            assistantMsg.insertBefore(block, contentDiv);
            currentToolBlock = block;
            break;
        }
        case 'tool_done': {
            if (currentToolBlock) {
                currentToolBlock.querySelector('.tool-result').classList.add('open');
                currentToolBlock = null;
            }
            scrollToBottom();
            break;
        }
        case 'token': {
            if (currentToolBlock) {
                const tr = currentToolBlock.querySelector('.tool-result');
                tr.textContent += event.text;
                tr.classList.add('open');
            } else {
                contentDiv.textContent += event.text;
                contentDiv.innerHTML = renderMarkdown(contentDiv.textContent);
                scrollToBottom();
            }
            break;
        }
        case 'status': {
            addStatusMessage(event.text);
            break;
        }
        case 'done': {
            contentDiv.classList.remove('streaming-cursor');
            if (event.usage) {
                updateUsage(event.usage);
            }
            if (event.ai_msg) {
                const displayed = contentDiv.textContent.replace(/\s/g, '');
                const full = event.ai_msg.replace(/\s/g, '');
                if (full.length > displayed.length + 10) {
                    contentDiv.innerHTML = renderMarkdown(event.ai_msg);
                }
            }
            break;
        }
        case 'error': {
            contentDiv.textContent = `错误: ${event.error}`;
            contentDiv.style.color = 'var(--red)';
            break;
        }
    }
    scrollToBottom();
}

// ── UI Builders ──
function addUserMessage(text) {
    const div = document.createElement('div');
    div.className = 'message user';
    div.innerHTML = `
        <div class="message-label">你</div>
        <div class="message-bubble">${escapeHtml(text)}</div>
    `;
    chatContainer.appendChild(div);
    scrollToBottom();
}

function addAssistantMessage() {
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `
        <div class="message-label">Tea Agent</div>
        <div class="message-bubble"></div>
    `;
    chatContainer.appendChild(div);
    scrollToBottom();
    return div;
}

function createThinkBlock() {
    const div = document.createElement('div');
    div.className = 'think-block';
    div.innerHTML = `
        <div class="think-header" onclick="toggleThink(this)">
            <span>💭</span> 思考中...
        </div>
        <div class="think-content"></div>
    `;
    return div;
}

function createToolBlock(name) {
    const div = document.createElement('div');
    div.className = 'tool-block';
    div.innerHTML = `
        <div class="tool-header">
            <span class="tool-icon">🔧</span>
            调用工具: <code>${escapeHtml(name)}</code>
        </div>
        <div class="tool-result"></div>
    `;
    return div;
}

function addStatusMessage(text) {
    const div = document.createElement('div');
    div.className = 'status-msg';
    div.textContent = text;
    chatContainer.appendChild(div);
}

function updateUsage(usage) {
    const total = usage.total_tokens || 0;
    if (total > 0) {
        usageTokens.textContent = total.toLocaleString();
        document.getElementById('usage-bar').style.display = 'flex';
    }
}

// ── Toggle Think ──
window.toggleThink = function(header) {
    const content = header.parentElement.querySelector('.think-content');
    content.classList.toggle('open');
    const icon = header.querySelector('span');
    icon.textContent = content.classList.contains('open') ? '💡' : '💭';
};

// ── Scroll ──
function scrollToBottom() {
    requestAnimationFrame(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    });
}

// ── Session Panel ──
document.getElementById('sessions-btn').addEventListener('click', async () => {
    sessionPanel.classList.add('open');
    overlay.classList.add('open');
    await loadSessions();
});

document.getElementById('close-sessions').addEventListener('click', closeSessionPanel);
overlay.addEventListener('click', closeSessionPanel);

function closeSessionPanel() {
    sessionPanel.classList.remove('open');
    overlay.classList.remove('open');
}

async function loadSessions() {
    const list = document.getElementById('session-list');
    list.innerHTML = '<div class="status-msg">加载中...</div>';
    try {
        const res = await fetch('/api/sessions');
        const data = await res.json();
        list.innerHTML = '';
        for (const s of data.sessions) {
            const item = document.createElement('div');
            item.className = 'session-item';
            item.innerHTML = `
                <div class="sess-title">${escapeHtml(s.title)}</div>
                <div class="sess-meta">${s.updated} · ${(s.total_tokens || 0).toLocaleString()} tokens</div>
            `;
            item.addEventListener('click', () => {
                currentTopicId = s.id;
                closeSessionPanel();
                // Reload conversation
                chatContainer.innerHTML = '';
                welcome.style.display = 'block';
                welcome.querySelector('h2').textContent = s.title;
            });
            list.appendChild(item);
        }
    } catch (e) {
        list.innerHTML = '<div class="status-msg">加载失败</div>';
    }
}

// ── New Topic ──
document.getElementById('new-btn').addEventListener('click', () => {
    currentTopicId = '';
    chatContainer.innerHTML = '';
    welcome.style.display = 'flex';
    messageInput.focus();
    usageTokens.textContent = '0';
});

// ── Stop Generation ──
document.getElementById('stop-btn').addEventListener('click', () => {
    if (abortController) {
        abortController.abort();
        finishStreaming();
    }
});

// ── Markdown Renderer ──
function renderMarkdown(text) {
    if (!text) return '';

    // Escape HTML first
    let html = escapeHtml(text);

    // Code blocks (```lang ... ```)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        const langClass = lang ? ` class="language-${lang}"` : '';
        return `<pre><button class="copy-btn" onclick="copyCode(this)">复制</button><code${langClass}>${escapeHtml(code.trim())}</code></pre>`;
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');

    return html;
}

// ── Copy Code ──
window.copyCode = function(btn) {
    const code = btn.parentElement.querySelector('code').textContent;
    navigator.clipboard.writeText(code).then(() => {
        btn.textContent = '已复制';
        setTimeout(() => { btn.textContent = '复制'; }, 2000);
    });
};

// ── Escape HTML ──
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── Keyboard shortcut ──
document.addEventListener('keydown', (e) => {
    // Ctrl+K: focus input
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        messageInput.focus();
    }
});
