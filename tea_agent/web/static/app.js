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
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        messageInput.focus();
    }
});

// ── Model Settings ──
const settingsModal = document.getElementById('settings-modal');
const closeSettings = document.getElementById('close-settings');
const settingsBtn = document.getElementById('settings-btn');
const switchModelBtn = document.getElementById('switch-model-btn');
const switchConfigBtn = document.getElementById('switch-config-btn');
const providerSelect = document.getElementById('provider-select');
const modelNameInput = document.getElementById('model-name');
const apiUrlInput = document.getElementById('api-url');
const apiKeyInput = document.getElementById('api-key');
const switchStatus = document.getElementById('model-switch-status');

function openSettings() {
    settingsModal.style.display = 'flex';
    overlay.classList.add('open');
    switchStatus.textContent = '';
    switchStatus.className = 'form-status';
    loadCurrentModel();
    loadProviders();
}

function closeSettings() {
    settingsModal.style.display = 'none';
    overlay.classList.remove('open');
}

async function loadCurrentModel() {
    try {
        const res = await fetch('/api/model');
        const data = await res.json();
        modelNameInput.value = data.model || '';
        apiUrlInput.value = data.api_url || '';
        apiKeyInput.value = '';
        apiKeyInput.placeholder = data.api_key_masked || 'sk-...';
    } catch (e) {
        switchStatus.textContent = '无法加载当前模型信息';
        switchStatus.className = 'form-status error';
    }
}

async function loadProviders() {
    try {
        const res = await fetch('/api/model/providers');
        const data = await res.json();
        providerSelect.innerHTML = '<option value="">— 手动输入 —</option>';
        for (const [name, info] of Object.entries(data.providers)) {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = `${name} (${info.model})`;
            providerSelect.appendChild(opt);
        }
    } catch (e) {
        console.warn('加载提供商预设失败');
    }
}

providerSelect.addEventListener('change', () => {
    const name = providerSelect.value;
    if (!name) return;
    fetch('/api/model/providers')
        .then(r => r.json())
        .then(data => {
            const info = data.providers[name];
            if (info) {
                modelNameInput.value = info.model;
                apiUrlInput.value = info.url;
            }
        });
});

async function doSwitchModel() {
    const apiKey = apiKeyInput.value.trim() || undefined;
    const apiUrl = apiUrlInput.value.trim();
    const modelName = modelNameInput.value.trim();

    if (!apiUrl || !modelName) {
        switchStatus.textContent = '请填写 API URL 和模型名称';
        switchStatus.className = 'form-status error';
        return;
    }

    switchStatus.textContent = '⏳ 正在切换模型...';
    switchStatus.className = 'form-status loading';
    switchModelBtn.disabled = true;

    try {
        const res = await fetch('/api/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: apiKey, api_url: apiUrl, model_name: modelName }),
        });
        const data = await res.json();
        if (data.ok) {
            switchStatus.textContent = `✅ 已切换到 ${data.model} @ ${data.api_url}`;
            switchStatus.className = 'form-status success';
            modelInfo.textContent = data.model;
            apiKeyInput.value = '';
            apiKeyInput.placeholder = data.api_key_masked || 'sk-...';
        } else {
            switchStatus.textContent = `❌ 切换失败: ${data.error || data.errors?.join(', ')}`;
            switchStatus.className = 'form-status error';
        }
    } catch (e) {
        switchStatus.textContent = `❌ 网络错误: ${e.message}`;
        switchStatus.className = 'form-status error';
    } finally {
        switchModelBtn.disabled = false;
    }
}

async function doSwitchConfig() {
    const configPath = prompt('请输入配置文件路径:');
    if (!configPath) return;

    switchStatus.textContent = '⏳ 正在从配置文件加载...';
    switchStatus.className = 'form-status loading';

    try {
        const res = await fetch('/api/model/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config_path: configPath }),
        });
        const data = await res.json();
        if (data.ok) {
            switchStatus.textContent = `✅ 已从配置文件加载: ${configPath}`;
            switchStatus.className = 'form-status success';
            await loadCurrentModel();
            const mi = await (await fetch('/api/model')).json();
            modelInfo.textContent = mi.model;
        } else {
            switchStatus.textContent = `❌ 加载失败: ${data.error}`;
            switchStatus.className = 'form-status error';
        }
    } catch (e) {
        switchStatus.textContent = `❌ 错误: ${e.message}`;
        switchStatus.className = 'form-status error';
    }
}

settingsBtn.addEventListener('click', openSettings);
modelInfo.addEventListener('click', openSettings);
closeSettings.addEventListener('click', closeSettings);
switchModelBtn.addEventListener('click', doSwitchModel);
switchConfigBtn.addEventListener('click', doSwitchConfig);
