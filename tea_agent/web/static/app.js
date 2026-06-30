/**
 * Tea Agent Web 前端 — 主应用逻辑
 * 所有事件绑定统一在 DOMContentLoaded 中完成，避免竞态条件。
 * 所有 fetch 请求设置超时机制，防止请求挂起。
 */

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
const roundsPanel = document.getElementById('rounds-panel');
const roundsList = document.getElementById('rounds-list');
const roundsTopicTitle = document.getElementById('rounds-topic-title');
const uploadImageBtn = document.getElementById('upload-image-btn');
const imageInput = document.getElementById('image-input');
const imagePreviewContainer = document.getElementById('image-preview-container');
const imagePreviewList = document.getElementById('image-preview-list');

// ── Image Upload State ──
let pendingImages = [];

// ── Auto Resize ──
function setupAutoResize() {
    if (messageInput) {
        messageInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 150) + 'px';
        });
    }
}

// ── Image Upload Functions ──
function handleImageUpload(e) {
    const files = e.target.files;
    if (files.length > 0) {
        handleFileFiles(files);
    }
    // 重置 input 以允许再次选择相同文件
    e.target.value = '';
}

function handleFileFiles(files) {
    Array.from(files).forEach(file => {
        if (!file.type.startsWith('image/')) {
            return;
        }
        
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64 = e.target.result;
            pendingImages.push(base64);
            updateImagePreview();
        };
        reader.readAsDataURL(file);
    });
}

function handlePaste(e) {
    const items = e.clipboardData.items;
    for (let item of items) {
        if (item.type.startsWith('image/')) {
            e.preventDefault();
            const file = item.getAsFile();
            const reader = new FileReader();
            reader.onload = (event) => {
                const base64 = event.target.result;
                pendingImages.push(base64);
                updateImagePreview();
            };
            reader.readAsDataURL(file);
            break;
        }
    }
}

function updateImagePreview() {
    if (!imagePreviewContainer || !imagePreviewList) return;
    
    if (pendingImages.length === 0) {
        imagePreviewContainer.style.display = 'none';
        return;
    }
    
    imagePreviewContainer.style.display = 'block';
    imagePreviewList.innerHTML = '';
    
    pendingImages.forEach((img, index) => {
        const previewItem = document.createElement('div');
        previewItem.className = 'image-preview-item';
        previewItem.style.cssText = 'display: inline-block; position: relative; margin: 4px;';
        
        const imgEl = document.createElement('img');
        imgEl.src = img;
        imgEl.style.cssText = 'width: 60px; height: 60px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border);';
        
        const removeBtn = document.createElement('button');
        removeBtn.textContent = '×';
        removeBtn.style.cssText = 'position: absolute; top: -5px; right: -5px; background: var(--danger); color: white; border: none; border-radius: 50%; width: 18px; height: 18px; font-size: 12px; cursor: pointer; line-height: 1;';
        removeBtn.onclick = () => {
            pendingImages.splice(index, 1);
            updateImagePreview();
        };
        
        previewItem.appendChild(imgEl);
        previewItem.appendChild(removeBtn);
        imagePreviewList.appendChild(previewItem);
    });
}

// ── 带超时的 fetch 工具函数 ──
async function fetchWithTimeout(url, options = {}, timeout = 10000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    try {
        const res = await fetch(url, {
            ...options,
            signal: controller.signal,
        });
        return res;
    } finally {
        clearTimeout(timeoutId);
    }
}

// ── Initialize（DOM 完全加载后） ──
document.addEventListener('DOMContentLoaded', () => {
    // 绑定所有事件
    bindEvents();
    // 初始化
    loadConfig();
    loadHeaderConfigList(); // 加载头部配置下拉框
    setupAutoResize();
    messageInput.focus();
    
    // 图片上传按钮事件
    if (uploadImageBtn) {
        uploadImageBtn.addEventListener('click', () => imageInput.click());
    }
    
    // 图片输入变化事件
    if (imageInput) {
        imageInput.addEventListener('change', handleImageUpload);
    }
    
    // 粘贴图片支持
    messageInput.addEventListener('paste', handlePaste);
    
    // 拖拽上传支持
    messageInput.addEventListener('dragover', (e) => {
        e.preventDefault();
        messageInput.style.borderColor = 'var(--accent)';
    });
    
    messageInput.addEventListener('dragleave', () => {
        messageInput.style.borderColor = '';
    });
    
    messageInput.addEventListener('drop', (e) => {
        e.preventDefault();
        messageInput.style.borderColor = '';
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileFiles(files);
        }
    });
});

// ── 统一事件绑定 ──
function bindEvents() {
    // 发送消息
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    sendBtn.addEventListener('click', sendMessage);

    // 历史会话面板
    const sessionsBtn = document.getElementById('sessions-btn');
    if (sessionsBtn) {
        sessionsBtn.addEventListener('click', async () => {
            sessionPanel.classList.add('open');
            overlay.classList.add('open');
            await loadSessions();
        });
    }

    const closeSessionsBtn = document.getElementById('close-sessions');
    if (closeSessionsBtn) {
        closeSessionsBtn.addEventListener('click', closeSessionPanel);
    }
    overlay.addEventListener('click', closeAllPanels);

    // 历史轮次面板
    const roundsBtn = document.getElementById('rounds-btn');
    if (roundsBtn) {
        roundsBtn.addEventListener('click', async () => {
            if (!currentTopicId) {
                // 如果没有当前主题，尝试从欢迎标题获取或提示
                roundsList.innerHTML = '<div class="status-msg">⚠ 请先开始对话或从历史会话中选择一个主题</div>';
                roundsPanel.classList.add('open');
                overlay.classList.add('open');
                return;
            }
            roundsPanel.classList.add('open');
            overlay.classList.add('open');
            await loadRounds(currentTopicId);
        });
    }

    // 所有面板的关闭按钮
    document.querySelectorAll('.close-panel-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const panelId = btn.dataset.panel;
            const panel = document.getElementById(panelId);
            if (panel) panel.classList.remove('open');
            overlay.classList.remove('open');
        });
    });

    // 新会话
    const newBtn = document.getElementById('new-btn');
    if (newBtn) {
        newBtn.addEventListener('click', () => {
            currentTopicId = '';
            chatContainer.innerHTML = '';
            welcome.style.display = 'flex';
            const welcomeSubtitle = welcome.querySelector('p');
            welcomeSubtitle.innerHTML = '自进化 AI 编程助手 · 60+ 内置工具 · 多 Agent 协作 · 长期记忆<br>在下方输入消息开始对话';
            messageInput.focus();
            usageTokens.textContent = '0';
            if (roundsTopicTitle) roundsTopicTitle.textContent = '';
            roundsList.innerHTML = '<div class="status-msg">请先开始对话或选择一个历史会话</div>';
            document.getElementById('usage-bar').style.display = 'none';
        });
    }

    // 停止生成
    const stopBtn = document.getElementById('stop-btn');
    if (stopBtn) {
        stopBtn.addEventListener('click', () => {
            if (abortController) {
                abortController.abort();
                finishStreaming();
            }
        });
    }

    // 模型设置
    const settingsBtn = document.getElementById('settings-btn');
    const settingsModal = document.getElementById('settings-modal');
    const closeSettings = document.getElementById('close-settings');
    const switchModelBtn = document.getElementById('switch-model-btn');
    const configSelect = document.getElementById('config-select');
    const addConfigBtn = document.getElementById('add-config-btn');

    if (settingsBtn) settingsBtn.addEventListener('click', () => openSettings(settingsModal));
    if (modelInfo) modelInfo.addEventListener('click', () => openSettings(settingsModal));
    if (closeSettings) closeSettings.addEventListener('click', () => closeSettingsModal(settingsModal));
    if (switchModelBtn) switchModelBtn.addEventListener('click', () => doSwitchModel(settingsModal));

    // 配置选择变化时自动填充字段
    if (configSelect) {
        configSelect.addEventListener('change', () => {
            const selected = configSelect.selectedOptions[0];
            if (selected && selected.dataset.mainModel) {
                const main = JSON.parse(selected.dataset.mainModel);
                const cheap = selected.dataset.cheapModel ? JSON.parse(selected.dataset.cheapModel) : null;
                document.getElementById('model-name').value = main.model_name || '';
                document.getElementById('api-url').value = main.api_url || '';
                document.getElementById('api-key').value = '';
                document.getElementById('api-key').placeholder = main.api_key_masked || 'sk-...';
                if (cheap) {
                    document.getElementById('cheap-model-name').value = cheap.model_name || '';
                    document.getElementById('cheap-api-url').value = cheap.api_url || '';
                    document.getElementById('cheap-api-key').value = '';
                    document.getElementById('cheap-api-key').placeholder = cheap.api_key_masked || 'sk-...';
                } else {
                    document.getElementById('cheap-model-name').value = '';
                    document.getElementById('cheap-api-url').value = '';
                    document.getElementById('cheap-api-key').value = '';
                    document.getElementById('cheap-api-key').placeholder = '不填则使用主模型的 Key';
                }
            }
        });
    }

    // 新增配置
    if (addConfigBtn) {
        addConfigBtn.addEventListener('click', () => {
            const newConfigModal = document.getElementById('new-config-modal');
            if (newConfigModal) {
                newConfigModal.style.display = 'flex';
                overlay.classList.add('open');
                document.getElementById('new-config-status').textContent = '';
                document.getElementById('new-config-status').className = 'form-status';
            }
        });
    }

    // 新增配置弹窗关闭
    const closeNewConfig = document.getElementById('close-new-config');
    if (closeNewConfig) {
        closeNewConfig.addEventListener('click', () => {
            document.getElementById('new-config-modal').style.display = 'none';
            overlay.classList.remove('open');
        });
    }

    // 保存新配置
    const saveNewConfigBtn = document.getElementById('save-new-config-btn');
    if (saveNewConfigBtn) {
        saveNewConfigBtn.addEventListener('click', () => doSaveNewConfig(settingsModal));
    }

    // 键盘快捷键
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            messageInput.focus();
        }
    });
}

// ── Config 加载（带超时） ──
async function loadConfig() {
    try {
        const res = await fetchWithTimeout('/api/config', {}, 8000);
        const data = await res.json();
        let text = `${data.model}`;
        if (data.cheap_model) {
            text += ` | cheap: ${data.cheap_model.model}`;
        }
        modelInfo.textContent = text;
        modelInfo.title = `主模型: ${data.model}\nAPI: ${data.api_url}\n便宜模型: ${data.cheap_model ? data.cheap_model.model + ' @ ' + data.cheap_model.api_url : '无'}`;
    } catch (e) {
        if (e.name === 'AbortError') {
            modelInfo.textContent = '⏳ 服务加载中...';
            // 3秒后重试一次
            setTimeout(() => {
                loadConfig();
            }, 3000);
        } else {
            modelInfo.textContent = '⚠ 连接失败';
            modelInfo.title = '点击重试';
            modelInfo.style.cursor = 'pointer';
            modelInfo.onclick = () => loadConfig();
        }
    }
}

// ── 头部配置下拉框加载 ──
async function loadHeaderConfigList() {
    const headerConfigSelect = document.getElementById('header-config-select');
    if (!headerConfigSelect) return;
    
    try {
        const res = await fetchWithTimeout('/api/configs', {}, 8000);
        const data = await res.json();
        const activeFilename = data.active_config_filename || '';
        
        headerConfigSelect.innerHTML = '<option value="">— 选择配置 —</option>';
        
        if (data.configs && data.configs.length > 0) {
            for (const cfg of data.configs) {
                const opt = document.createElement('option');
                opt.value = cfg.filename;
                let label = cfg.filename;
                if (cfg.main_model && cfg.main_model.model_name) {
                    label += ` [${cfg.main_model.model_name}]`;
                }
                if (cfg.error) {
                    label += ` ⚠`;
                }
                opt.textContent = label;
                opt.dataset.configPath = cfg.path || '';
                headerConfigSelect.appendChild(opt);
            }
            
            // 自动选中当前活跃配置
            if (activeFilename) {
                headerConfigSelect.value = activeFilename;
            }
        } else {
            headerConfigSelect.innerHTML = '<option value="">— 暂无配置 —</option>';
        }
        
        // 绑定切换事件
        headerConfigSelect.addEventListener('change', handleHeaderConfigSwitch);
        
    } catch (e) {
        console.error('加载配置列表失败:', e);
        headerConfigSelect.innerHTML = '<option value="">— 加载失败 —</option>';
    }
}

// ── 头部配置切换处理 ──
async function handleHeaderConfigSwitch(e) {
    const select = e.target;
    const filename = select.value;
    if (!filename) return;
    
    const configPath = select.selectedOptions[0]?.dataset.configPath;
    if (!configPath) {
        console.error('配置路径为空');
        return;
    }
    
    // 显示切换状态
    const originalText = modelInfo.textContent;
    modelInfo.textContent = '⏳ 切换中...';
    
    try {
        const res = await fetchWithTimeout('/api/model/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config_path: configPath }),
        }, 15000);
        
        const data = await res.json();
        if (data.ok) {
            // 刷新模型信息
            await loadConfig();
            // 更新设置模态框中的配置列表（如果打开）
            const configSelect = document.getElementById('config-select');
            if (configSelect) {
                await loadConfigList();
            }
        } else {
            modelInfo.textContent = originalText;
            alert(`切换失败: ${data.error || '未知错误'}`);
        }
    } catch (e) {
        modelInfo.textContent = originalText;
        console.error('配置切换失败:', e);
        alert(`切换失败: ${e.message}`);
    }
}

// ── Send Message ──
async function sendMessage() {
    const text = messageInput.value.trim();
    const images = [...pendingImages]; // 复制当前图片列表
    if ((!text && images.length === 0) || isStreaming) return;

    messageInput.value = '';
    messageInput.style.height = 'auto';
    welcome.style.display = 'none';
    
    // 清空待发送图片
    pendingImages = [];
    updateImagePreview();

    // 添加用户消息（包含图片预览）
    addUserMessage(text, images);

    // 准备流式接收
    isStreaming = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '...';

    abortController = new AbortController();
    const stopBtn = document.getElementById('stop-btn');
    if (stopBtn) stopBtn.style.display = 'block';

    const assistantMsg = addAssistantMessage();
    const contentDiv = assistantMsg.querySelector('.message-bubble');
    contentDiv.classList.add('streaming-cursor');

    let currentThinkBlock = null;
    let currentToolBlock = null;
    let currentToolContent = '';

    try {
        const requestBody = {
            message: text || '[图片]',
            topic_id: currentTopicId,
        };
        
        // 如果有图片，添加到请求中
        if (images.length > 0) {
            requestBody.images = images;
        }

        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
            signal: abortController.signal,
        });

        if (!res.ok) {
            const errText = await res.text().catch(() => '');
            contentDiv.textContent = `服务器错误 (${res.status}): ${errText || '请求失败'}`;
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
            contentDiv.textContent = `连接错误: ${e.message}。请检查服务是否正常运行。`;
        }
    } finally {
        finishStreaming();
    }
}

function finishStreaming() {
    isStreaming = false;
    sendBtn.disabled = false;
    sendBtn.innerHTML = '发送';
    const stopBtn = document.getElementById('stop-btn');
    if (stopBtn) stopBtn.style.display = 'none';
    abortController = null;

    // 移除所有流式光标
    document.querySelectorAll('.streaming-cursor').forEach(el => {
        el.classList.remove('streaming-cursor');
    });

    messageInput.focus();

    // 如果有当前主题，自动刷新轮次数据（不打开面板）
    autoLoadRounds();
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
                // 移除旋转图标
                const spinner = currentToolBlock.querySelector('.tool-spinner');
                if (spinner) spinner.remove();
                // 添加完成标记
                const header = currentToolBlock.querySelector('.tool-header');
                const doneMark = document.createElement('span');
                doneMark.textContent = '✅';
                doneMark.style.marginLeft = 'auto';
                doneMark.style.fontSize = '14px';
                header.appendChild(doneMark);
                currentToolBlock = null;
            }
            scrollToBottom();
            break;
        }
        case 'token': {
            if (currentToolBlock) {
                const paramsDiv = currentToolBlock.querySelector('.tool-params');
                if (paramsDiv) {
                    paramsDiv.textContent += event.text;
                }
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
function addUserMessage(text, images = []) {
    const div = document.createElement('div');
    div.className = 'message user';
    
    let contentHtml = '';
    
    // 添加图片预览
    if (images.length > 0) {
        const imagesHtml = images.map(img => 
            `<img src="${img}" style="max-width: 200px; max-height: 200px; border-radius: 4px; margin: 4px; border: 1px solid var(--border);">`
        ).join('');
        contentHtml += `<div style="margin-bottom: 8px;">${imagesHtml}</div>`;
    }
    
    // 添加文本内容
    if (text) {
        contentHtml += `<div class="message-bubble">${escapeHtml(text)}</div>`;
    } else if (images.length > 0) {
        contentHtml += `<div class="message-bubble" style="color: var(--text-muted);">[图片]</div>`;
    }
    
    div.innerHTML = `
        <div class="message-label">你</div>
        ${contentHtml}
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
            调用工具: <span class="tool-name">${escapeHtml(name)}</span>
            <span class="tool-spinner"></span>
        </div>
        <div class="tool-params" style="display:block;"></div>
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
function closeSessionPanel() {
    sessionPanel.classList.remove('open');
    overlay.classList.remove('open');
}

async function loadSessions() {
    const list = document.getElementById('session-list');
    list.innerHTML = '<div class="status-msg">⏳ 加载中...</div>';
    try {
        const res = await fetchWithTimeout('/api/sessions', {}, 8000);
        const data = await res.json();
        list.innerHTML = '';
        if (!data.sessions || data.sessions.length === 0) {
            list.innerHTML = '<div class="status-msg">暂无历史会话</div>';
            return;
        }
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
                const welcomeTitle = welcome.querySelector('h2');
                welcomeTitle.textContent = s.title;
                // 加载历史轮次信息到 welcome 区域
                const welcomeSubtitle = welcome.querySelector('p');
                if (welcomeSubtitle) {
                    welcomeSubtitle.innerHTML = `📜 主题: ${escapeHtml(s.title)}<br>` +
                        `<span style="font-size:12px; color:var(--text-muted);">${s.updated} · ${(s.total_tokens || 0).toLocaleString()} tokens</span><br>` +
                        `<button class="btn-secondary" style="margin-top:12px; padding:6px 16px; font-size:13px;" onclick="openRounds()">🔄 查看本轮次对话</button>`;
                }
            });
            list.appendChild(item);
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            list.innerHTML = '<div class="status-msg" style="color:var(--orange)">⏳ 加载超时，请重试</div>';
        } else {
            list.innerHTML = `<div class="status-msg" style="color:var(--red)">❌ 加载失败: ${e.message}</div>`;
        }
    }
}

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

// ── Model Settings Modal ──
function openSettings(settingsModal) {
    if (!settingsModal) return;
    settingsModal.style.display = 'flex';
    overlay.classList.add('open');
    const switchStatus = document.getElementById('model-switch-status');
    if (switchStatus) {
        switchStatus.textContent = '';
        switchStatus.className = 'form-status';
    }
    loadCurrentModel();
    loadConfigList();
}

function closeSettingsModal(settingsModal) {
    if (!settingsModal) return;
    settingsModal.style.display = 'none';
    overlay.classList.remove('open');
    // 同时关闭新增配置弹窗
    const newConfigModal = document.getElementById('new-config-modal');
    if (newConfigModal) newConfigModal.style.display = 'none';
}

async function loadCurrentModel() {
    const modelNameInput = document.getElementById('model-name');
    const apiUrlInput = document.getElementById('api-url');
    const apiKeyInput = document.getElementById('api-key');
    const cheapModelNameInput = document.getElementById('cheap-model-name');
    const cheapApiUrlInput = document.getElementById('cheap-api-url');
    const cheapApiKeyInput = document.getElementById('cheap-api-key');
    const switchStatus = document.getElementById('model-switch-status');
    try {
        const res = await fetchWithTimeout('/api/model', {}, 8000);
        const data = await res.json();
        if (modelNameInput) modelNameInput.value = data.model || '';
        if (apiUrlInput) apiUrlInput.value = data.api_url || '';
        if (apiKeyInput) {
            apiKeyInput.value = '';
            apiKeyInput.placeholder = data.api_key_masked || 'sk-...';
        }
        // 便宜模型
        const cheap = data.cheap_model;
        if (cheap && cheapModelNameInput) {
            cheapModelNameInput.value = cheap.model || '';
            cheapApiUrlInput.value = cheap.api_url || '';
            cheapApiKeyInput.value = '';
            cheapApiKeyInput.placeholder = cheap.api_key_masked || '不填则使用主模型的 Key';
        }
    } catch (e) {
        if (switchStatus) {
            switchStatus.textContent = '⚠ 无法加载当前模型信息';
            switchStatus.className = 'form-status error';
        }
    }
}

async function loadConfigList() {
    const configSelect = document.getElementById('config-select');
    if (!configSelect) return;
    configSelect.innerHTML = '<option value="">⏳ 加载中...</option>';
    try {
        const res = await fetchWithTimeout('/api/configs', {}, 8000);
        const data = await res.json();
        const activeFilename = data.active_config_filename || '';
        configSelect.innerHTML = '<option value="">— 选择配置文件 —</option>';
        if (data.configs && data.configs.length > 0) {
            for (const cfg of data.configs) {
                const opt = document.createElement('option');
                opt.value = cfg.filename;
                let label = cfg.filename;
                if (cfg.main_model && cfg.main_model.model_name) {
                    label += `  [main: ${cfg.main_model.model_name}`;
                    if (cfg.cheap_model && cfg.cheap_model.model_name) {
                        label += ` | cheap: ${cfg.cheap_model.model_name}`;
                    }
                    label += ']';
                }
                if (cfg.error) {
                    label += ` ⚠ ${cfg.error}`;
                }
                opt.textContent = label;
                if (cfg.main_model) {
                    opt.dataset.mainModel = JSON.stringify(cfg.main_model);
                }
                if (cfg.cheap_model) {
                    opt.dataset.cheapModel = JSON.stringify(cfg.cheap_model);
                }
                opt.dataset.configPath = cfg.path || '';
                configSelect.appendChild(opt);
            }
            // 自动选中当前活跃配置
            if (activeFilename) {
                configSelect.value = activeFilename;
            }
        } else {
            configSelect.innerHTML = '<option value="">— 暂无配置文件，请新增 —</option>';
        }
    } catch (e) {
        configSelect.innerHTML = '<option value="">— 加载失败，请重试 —</option>';
    }
}

async function doSwitchModel(settingsModal) {
    const apiKeyInput = document.getElementById('api-key');
    const apiUrlInput = document.getElementById('api-url');
    const modelNameInput = document.getElementById('model-name');
    const cheapApiKeyInput = document.getElementById('cheap-api-key');
    const cheapApiUrlInput = document.getElementById('cheap-api-url');
    const cheapModelNameInput = document.getElementById('cheap-model-name');
    const switchStatus = document.getElementById('model-switch-status');

    const apiKey = apiKeyInput ? apiKeyInput.value.trim() : '';
    const apiUrl = apiUrlInput ? apiUrlInput.value.trim() : '';
    const modelName = modelNameInput ? modelNameInput.value.trim() : '';
    const cheapApiKey = cheapApiKeyInput ? cheapApiKeyInput.value.trim() : '';
    const cheapApiUrl = cheapApiUrlInput ? cheapApiUrlInput.value.trim() : '';
    const cheapModelName = cheapModelNameInput ? cheapModelNameInput.value.trim() : '';

    // 如果 apiKey 为空，尝试从占位符获取 masked key（但实际需要真实 key）
    // 如果占位符有 masked key，说明已有配置，使用当前配置的 key
    let finalApiKey = apiKey;
    if (!finalApiKey && apiKeyInput && apiKeyInput.placeholder && apiKeyInput.placeholder !== 'sk-...') {
        // 用户没有输入新 key，提示
        if (switchStatus) {
            switchStatus.textContent = '请输入 API Key（或留空保持当前 Key，但需先填入值）';
            switchStatus.className = 'form-status error';
        }
        return;
    }

    if (!finalApiKey && apiKeyInput && apiKeyInput.placeholder && apiKeyInput.placeholder.startsWith('sk-')) {
        // 有占位符 key，尝试自动使用
        // 但无法从占位符获取完整 key，需要用户输入
        if (switchStatus) {
            switchStatus.textContent = '如需保留当前 API Key，请从配置文件选择（下拉框选择即可自动填充字段）。或手动填入 Key。';
            switchStatus.className = 'form-status error';
        }
        return;
    }

    const errors = [];
    if (!finalApiKey) errors.push('API Key 不能为空');
    if (!apiUrl) errors.push('API URL 不能为空');
    if (!modelName) errors.push('模型名称不能为空');
    if (errors.length) {
        if (switchStatus) {
            switchStatus.textContent = errors.join('；');
            switchStatus.className = 'form-status error';
        }
        return;
    }

    // 便宜模型：如果填了名或url，必须两者都填
    if ((cheapModelName || cheapApiUrl) && (!cheapModelName || !cheapApiUrl)) {
        if (switchStatus) {
            switchStatus.textContent = '便宜模型需同时填写名称和 URL';
            switchStatus.className = 'form-status error';
        }
        return;
    }

    if (switchStatus) {
        switchStatus.textContent = '⏳ 正在切换模型...';
        switchStatus.className = 'form-status loading';
    }
    const switchModelBtn = document.getElementById('switch-model-btn');
    if (switchModelBtn) switchModelBtn.disabled = true;

    try {
        const body = {
            api_key: finalApiKey,
            api_url: apiUrl,
            model_name: modelName,
        };
        if (cheapModelName && cheapApiUrl) {
            body.cheap_api_key = cheapApiKey || finalApiKey;
            body.cheap_api_url = cheapApiUrl;
            body.cheap_model_name = cheapModelName;
        }

        const res = await fetchWithTimeout('/api/model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }, 30000);

        const data = await res.json();
        if (data.ok) {
            if (switchStatus) {
                let msg = `✅ 已切换到 ${data.model}`;
                if (data.cheap_model) {
                    msg += ` | cheap: ${data.cheap_model.model}`;
                }
                switchStatus.textContent = msg;
                switchStatus.className = 'form-status success';
            }
            // 更新 header 显示
            let headerText = data.model;
            if (data.cheap_model) {
                headerText += ` | cheap: ${data.cheap_model.model}`;
            }
            modelInfo.textContent = headerText;
            if (apiKeyInput) {
                apiKeyInput.value = '';
                apiKeyInput.placeholder = data.api_key_masked || 'sk-...';
            }
            // 关闭弹窗
            setTimeout(() => closeSettingsModal(settingsModal), 1500);
        } else {
            if (switchStatus) {
                switchStatus.textContent = `❌ 切换失败: ${data.error || (data.errors ? data.errors.join(', ') : '未知错误')}`;
                switchStatus.className = 'form-status error';
            }
        }
    } catch (e) {
        if (switchStatus) {
            if (e.name === 'AbortError') {
                switchStatus.textContent = '⏳ 切换超时（30s），服务可能仍在处理中，请检查模型配置';
            } else {
                switchStatus.textContent = `❌ 网络错误: ${e.message}`;
            }
            switchStatus.className = 'form-status error';
        }
    } finally {
        if (switchModelBtn) switchModelBtn.disabled = false;
    }
}

// ── New Config ──
async function doSaveNewConfig(settingsModal) {
    const filenameInput = document.getElementById('new-config-filename');
    const mainNameInput = document.getElementById('new-main-name');
    const mainUrlInput = document.getElementById('new-main-url');
    const mainKeyInput = document.getElementById('new-main-key');
    const cheapNameInput = document.getElementById('new-cheap-name');
    const cheapUrlInput = document.getElementById('new-cheap-url');
    const cheapKeyInput = document.getElementById('new-cheap-key');
    const statusEl = document.getElementById('new-config-status');

    const filename = filenameInput ? filenameInput.value.trim() : '';
    const mainName = mainNameInput ? mainNameInput.value.trim() : '';
    const mainUrl = mainUrlInput ? mainUrlInput.value.trim() : '';
    const mainKey = mainKeyInput ? mainKeyInput.value.trim() : '';
    const cheapName = cheapNameInput ? cheapNameInput.value.trim() : '';
    const cheapUrl = cheapUrlInput ? cheapUrlInput.value.trim() : '';
    const cheapKey = cheapKeyInput ? cheapKeyInput.value.trim() : '';

    const errors = [];
    if (!filename) errors.push('文件名不能为空');
    if (!mainName) errors.push('主模型名称不能为空');
    if (!mainUrl) errors.push('主模型 API URL 不能为空');
    if (!mainKey) errors.push('主模型 API Key 不能为空');
    if (errors.length) {
        statusEl.textContent = errors.join('；');
        statusEl.className = 'form-status error';
        return;
    }

    statusEl.textContent = '⏳ 正在保存并应用...';
    statusEl.className = 'form-status loading';
    const saveBtn = document.getElementById('save-new-config-btn');
    if (saveBtn) saveBtn.disabled = true;

    try {
        const res = await fetchWithTimeout('/api/config/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: filename,
                main_model_name: mainName,
                main_api_url: mainUrl,
                main_api_key: mainKey,
                cheap_model_name: cheapName,
                cheap_api_url: cheapUrl,
                cheap_api_key: cheapKey || mainKey,
            }),
        }, 30000);

        const data = await res.json();
        if (data.ok) {
            statusEl.textContent = `✅ 已创建并应用配置: ${data.filename}`;
            statusEl.className = 'form-status success';
            // 更新 header
            modelInfo.textContent = mainName;
            // 关闭新增配置弹窗
            setTimeout(() => {
                document.getElementById('new-config-modal').style.display = 'none';
                // 刷新设置弹窗的配置列表
                loadConfigList();
                loadCurrentModel();
            }, 1000);
        } else {
            statusEl.textContent = `❌ 创建失败: ${data.error || (data.errors ? data.errors.join(', ') : '未知错误')}`;
            statusEl.className = 'form-status error';
        }
    } catch (e) {
        statusEl.textContent = `❌ 错误: ${e.message}`;
        statusEl.className = 'form-status error';
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

// ── Rounds Panel (历史轮次) ──

// 打开轮次面板（供 onclick 调用）
window.openRounds = function() {
    if (!currentTopicId) return;
    roundsPanel.classList.add('open');
    overlay.classList.add('open');
    loadRounds(currentTopicId);
};

// 关闭所有侧面板
function closeAllPanels() {
    sessionPanel.classList.remove('open');
    if (roundsPanel) roundsPanel.classList.remove('open');
    overlay.classList.remove('open');
}

// 加载指定主题的历史轮次
async function loadRounds(topicId) {
    if (!topicId) {
        roundsList.innerHTML = '<div class="status-msg">⚠ 未选择主题</div>';
        return;
    }

    roundsList.innerHTML = '<div class="status-msg">⏳ 加载历史轮次...</div>';

    try {
        // 先获取主题信息
        const topicRes = await fetchWithTimeout(`/api/topic/${topicId}`, {}, 8000);
        const topicData = await topicRes.json();
        if (topicData.topic && roundsTopicTitle) {
            roundsTopicTitle.textContent = `— ${escapeHtml(topicData.topic.title)}`;
        }

        const res = await fetchWithTimeout(`/api/topic/${topicId}/conversations?limit=0`, {}, 15000);
        const data = await res.json();
        roundsList.innerHTML = '';

        if (!data.conversations || data.conversations.length === 0) {
            roundsList.innerHTML = '<div class="status-msg">📭 该主题暂无对话记录</div>';
            return;
        }

        // 从后往前遍历（最新的在最上面）
        const convs = data.conversations.reverse();
        for (let i = 0; i < convs.length; i++) {
            const c = convs[i];
            const item = renderRoundItem(c, i + 1, convs.length);
            roundsList.appendChild(item);
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            roundsList.innerHTML = '<div class="status-msg" style="color:var(--orange)">⏳ 加载超时，请重试</div>';
        } else {
            roundsList.innerHTML = `<div class="status-msg" style="color:var(--red)">❌ 加载失败: ${e.message}</div>`;
        }
    }
}

// 渲染单个历史轮次条目
function renderRoundItem(conv, index, total) {
    const item = document.createElement('div');
    item.className = 'round-item';

    // 解析用户消息
    let userText = conv.user_msg || '';
    try {
        const parsed = JSON.parse(userText);
        if (typeof parsed === 'object' && parsed.text) {
            userText = parsed.text;
        } else if (typeof parsed === 'string') {
            userText = parsed;
        }
    } catch (e) {
        // 不是 JSON，保持原样
    }

    const aiText = conv.ai_msg || '';
    const stamp = conv.stamp ? conv.stamp.slice(0, 19) : '';
    const aiPreview = aiText.length > 100 ? aiText.slice(0, 100) + '...' : aiText;
    const userPreview = userText.length > 80 ? userText.slice(0, 80) + '...' : userText;

    item.innerHTML = `
        <div class="round-stamp">
            <span>#${total - index + 1} · ${escapeHtml(stamp)}</span>
            <span class="round-index">轮次 ${total - index + 1}/${total}</span>
        </div>
        <div class="round-msg">
            <div class="round-label user-label">Q</div>
            <div class="round-text" title="${escapeHtml(userText)}">${escapeHtml(userPreview)}</div>
        </div>
        <div class="round-msg">
            <div class="round-label ai-label">A</div>
            <div class="round-text" title="${escapeHtml(aiText)}">${escapeHtml(aiPreview)}</div>
        </div>
        <div class="round-text-full">${renderMarkdown(aiText)}</div>
        <div class="round-expand" onclick="event.stopPropagation(); toggleRoundFull(this)">▼ 展开完整对话</div>
    `;

    // 点击条目：将对话加载到聊天区域
    item.addEventListener('click', () => restoreRound(conv, userText, aiText));

    return item;
}

// 展开/收起完整 AI 回答
window.toggleRoundFull = function(el) {
    const fullDiv = el.parentElement.querySelector('.round-text-full');
    if (fullDiv) {
        fullDiv.classList.toggle('open');
        el.textContent = fullDiv.classList.contains('open') ? '▲ 收起' : '▼ 展开完整对话';
    }
};

// 将历史轮次恢复到聊天区域
function restoreRound(conv, userText, aiText) {
    // 关闭侧面板
    closeAllPanels();

    // 清除当前聊天
    chatContainer.innerHTML = '';
    welcome.style.display = 'none';

    // 添加用户消息
    addUserMessage(userText || conv.user_msg || '');

    // 添加 AI 回复
    const assistantMsg = addAssistantMessage();
    const contentDiv = assistantMsg.querySelector('.message-bubble');
    if (aiText) {
        contentDiv.innerHTML = renderMarkdown(aiText);
    } else {
        contentDiv.textContent = '(空回复)';
    }
}

// 自动加载当前主题的轮次（对话结束后调用）
function autoLoadRounds() {
    if (currentTopicId) {
        // 不自动打开面板，只记录
        console.log(`当前主题 ${currentTopicId} 有新轮次`);
    }
}
