/**
 * @2026-05-16 gen by tea_agent, TeaAgent Android 前端主逻辑
 *
 * 对标桌面版 HtmlFrame + session_pipeline:
 * - 流式对话 + thinking/tool_call 区分显示
 * - Token 统计
 * - 历史压缩 (Level 1/2/3)
 * - 三模型配置
 * - 主题切换
 * - 移动端滑动手势（左边缘右滑呼出侧边栏）
 * - 内置元工具：toolkit_save / toolkit_reload
 */
(function() {
    'use strict';
    var $ = function(s) { return document.querySelector(s); };

    // DOM
    var chatMsgs = $('#chat-messages'), userInput = $('#user-input'),
        btnSend = $('#btn-send'), btnStop = $('#btn-stop'),
        optTools = $('#opt-tools'), optThinking = $('#opt-thinking'),
        statusEl = $('#status'), tokenStats = $('#token-stats'),
        topicList = $('#topic-list'), topicTitle = $('#current-topic-title'),
        sidebar = $('#sidebar');

    // 状态
    var isStreaming = false, currentTopicId = '', currentMsgEl = null,
        currentContentEl = null, currentTextBuf = '', pendingToolCalls = [];

    // 手势状态
    var touchStartX = 0, touchStartY = 0, touchMoved = false;
    var SWIPE_THRESHOLD = 60;
    var EDGE_WIDTH = 32;

    // 是否小屏模式
    var isMobile = window.matchMedia('(max-width: 600px)').matches;

    // ============ 初始化 ============
    function init() {
        initSwipeBackdrop();
        // 受保护工具(toolkit_save/reload)已由 Kotlin 侧 ToolManager.init() 管理
        loadTopics();
        loadConfigToUI();
        applyTheme();

        if (!currentTopicId) {
            var topics = TeaBridge.topicList();
            if (topics.length > 0) {
                selectTopic(topics[0].id);
            } else {
                newTopic();
            }
        }

        if (isMobile) {
            sidebar.classList.add('hidden');
        }

        btnSend.addEventListener('click', sendMsg);
        btnStop.addEventListener('click', stopGen);
        userInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
        });
        userInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
        });

        $('#btn-new-topic').addEventListener('click', newTopic);
        $('#btn-toggle-sidebar').addEventListener('click', toggleSidebar);
        $('#btn-settings-sidebar').addEventListener('click', openSettings);
        $('#btn-scroll-bottom').addEventListener('click', scrollBottom);
        $('#chat-container').addEventListener('scroll', function() {
            var atBot = this.scrollHeight - this.scrollTop - this.clientHeight < 100;
            $('#btn-scroll-bottom').style.display = atBot ? 'none' : 'block';
        });

        $('#btn-save-config').addEventListener('click', saveConfig);
        $('#btn-close-settings').addEventListener('click', function() {
            $('#settings-overlay').style.display = 'none';
        });
        $('#btn-close-tool-detail').addEventListener('click', function() {
            $('#tool-detail-overlay').style.display = 'none';
        });

        document.querySelectorAll('.tab-bar .tab').forEach(function(t) {
            t.addEventListener('click', function() {
                document.querySelectorAll('.tab-bar .tab').forEach(function(x){x.classList.remove('active');});
                document.querySelectorAll('.tab-content').forEach(function(x){x.classList.remove('active');});
                this.classList.add('active');
                $('#tab-' + this.dataset.tab).classList.add('active');
            });
        });

        if (isMobile) {
            document.addEventListener('touchstart', onTouchStart, {passive: true});
            document.addEventListener('touchmove', onTouchMove, {passive: false});
            document.addEventListener('touchend', onTouchEnd, {passive: true});
        }

        window.matchMedia('(max-width: 600px)').addEventListener('change', function(e) {
            isMobile = e.matches;
            if (isMobile) {
                sidebar.classList.add('hidden');
            } else {
                sidebar.classList.remove('hidden');
                hideBackdrop();
            }
        });

        TeaBridge.on('token', onToken);
        TeaBridge.on('thinking', onThinking);
        TeaBridge.on('tool_call', onToolCall);
        TeaBridge.on('done', onDone);
        TeaBridge.on('error', onError);
    }

    // ============ 内置元工具注册 ============

    // ============ 遮罩层 & 手势元素 ============
    function initSwipeBackdrop() {
        var backdrop = document.createElement('div');
        backdrop.id = 'sidebar-backdrop';
        backdrop.addEventListener('click', function() { hideSidebar(); });
        document.body.appendChild(backdrop);

        var hint = document.createElement('div');
        hint.id = 'swipe-hint';
        document.body.appendChild(hint);
    }

    function showSidebar() {
        sidebar.classList.remove('hidden');
        $('#sidebar-backdrop').classList.add('show');
        $('#swipe-hint').classList.remove('show');
    }

    function hideSidebar() {
        sidebar.classList.add('hidden');
        hideBackdrop();
    }

    function hideBackdrop() { $('#sidebar-backdrop').classList.remove('show'); }

    function toggleSidebar() {
        if (isMobile) {
            sidebar.classList.contains('hidden') ? showSidebar() : hideSidebar();
        } else {
            sidebar.classList.toggle('hidden');
        }
    }

    // ============ 滑动手势 ============
    function onTouchStart(e) {
        if (e.touches.length !== 1) return;
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        touchMoved = false;
        if (!sidebar.classList.contains('hidden')) return;
        if (touchStartX <= EDGE_WIDTH) $('#swipe-hint').classList.add('show');
    }

    function onTouchMove(e) {
        if (e.touches.length !== 1) return;
        var dx = e.touches[0].clientX - touchStartX;
        var dy = e.touches[0].clientY - touchStartY;
        if (Math.abs(dx) < Math.abs(dy)) return;
        touchMoved = true;
        if (sidebar.classList.contains('hidden')) {
            if (touchStartX <= EDGE_WIDTH && dx > 10) e.preventDefault();
            return;
        }
        if (dx < -10) e.preventDefault();
    }

    function onTouchEnd(e) {
        $('#swipe-hint').classList.remove('show');
        var dx = (e.changedTouches[0] ? e.changedTouches[0].clientX : touchStartX) - touchStartX;
        if (sidebar.classList.contains('hidden')) {
            if (touchStartX <= EDGE_WIDTH && dx > SWIPE_THRESHOLD) showSidebar();
        } else {
            if (dx < -SWIPE_THRESHOLD) hideSidebar();
        }
    }

    // ============ 主题 ============
    function newTopic() {
        var title = '新对话 ' + new Date().toLocaleTimeString();
        var id = TeaBridge.topicNew(title);
        selectTopic(id);
        loadTopics();
    }

    function selectTopic(id) {
        currentTopicId = id;
        chatMsgs.innerHTML = '';
        var msgs = TeaBridge.topicMessages(id);
        msgs.forEach(function(m) { renderHistoryMsg(m); });
        scrollBottom();

        var topics = TeaBridge.topicList();
        var t = topics.find(function(x){return x.id===id;});
        if (t) topicTitle.textContent = t.title;

        updateTokenStats();
        renderTopicList();

        if (isMobile) hideSidebar();
    }

    function loadTopics() { renderTopicList(); }

    function renderTopicList() {
        var topics = TeaBridge.topicList();
        topicList.innerHTML = topics.map(function(t) {
            var cls = t.id === currentTopicId ? 'topic-item active' : 'topic-item';
            return '<div class="' + cls + '" data-id="' + t.id + '">' +
                '<span class="topic-title">' + escHtml(t.title) + '</span>' +
                '<div class="topic-actions">' +
                '<button class="topic-menu-btn" data-id="' + t.id + '">⋯</button>' +
                '<div class="topic-dropdown" data-id="' + t.id + '">' +
                '<div class="dropdown-item" data-action="rename">✏️ 重命名</div>' +
                '<div class="dropdown-item" data-action="delete">🗑️ 删除</div>' +
                '</div></div></div>';
        }).join('');

        // 点击主题标题 → 选择主题
        topicList.querySelectorAll('.topic-item').forEach(function(el) {
            el.addEventListener('click', function(e) {
                // 如果点击的是按钮或下拉菜单内部，不触发选择
                if (e.target.closest('.topic-actions')) return;
                selectTopic(this.dataset.id);
            });
        });

        // 点击 "⋯" 按钮 → 切换下拉菜单
        topicList.querySelectorAll('.topic-menu-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var id = this.dataset.id;
                // 关闭其他所有下拉
                document.querySelectorAll('.topic-dropdown.open').forEach(function(d) {
                    if (d.dataset.id !== id) d.classList.remove('open');
                });
                var dd = this.nextElementSibling;
                dd.classList.toggle('open');
            });
        });

        // 下拉菜单项点击
        topicList.querySelectorAll('.dropdown-item').forEach(function(item) {
            item.addEventListener('click', function(e) {
                e.stopPropagation();
                var action = this.dataset.action;
                var id = this.closest('.topic-dropdown').dataset.id;
                // 关闭下拉
                this.closest('.topic-dropdown').classList.remove('open');

                if (action === 'rename') {
                    var topic = topics.find(function(t){ return t.id === id; });
                    var oldTitle = topic ? topic.title : '';
                    var newTitle = prompt('请输入新标题：', oldTitle);
                    if (newTitle && newTitle.trim() && newTitle !== oldTitle) {
                        // 加 ※ 前缀表示手动标记主题（保持主题，不被自动摘要覆盖）
                        var finalTitle = newTitle.trim();
                        if (!finalTitle.startsWith('※')) finalTitle = '※' + finalTitle;
                        TeaBridge.topicRename(id, finalTitle);
                        if (id === currentTopicId) {
                            topicTitle.textContent = finalTitle;
                        }
                        loadTopics();
                    }
                } else if (action === 'delete') {
                    if (confirm('确定删除此对话？')) {
                        TeaBridge.topicDelete(id);
                        if (id === currentTopicId) {
                            currentTopicId = '';
                            chatMsgs.innerHTML = '';
                            topicTitle.textContent = '新对话';
                        }
                        loadTopics();
                    }
                }
            });
        });

        // 点击页面空白处关闭所有下拉菜单
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.topic-actions')) {
                document.querySelectorAll('.topic-dropdown.open').forEach(function(d) {
                    d.classList.remove('open');
                });
            }
        });
    }

    function updateTokenStats() {
        if (!currentTopicId) { tokenStats.textContent = '🪙 0'; return; }
        var s = TeaBridge.topicTokenStats(currentTopicId);
        tokenStats.textContent = '🪙 ' + (s.total_tokens || 0);
        tokenStats.title = 'Prompt: ' + (s.prompt_tokens||0) + ' | Completion: ' + (s.completion_tokens||0);
    }

    // ============ 渲染历史 ============
    function renderHistoryMsg(m) {
        switch (m.role) {
            case 'user':
                addMsg('user', escHtml(m.content || ''));
                break;
            case 'assistant':
                var el = addMsg('assistant', '');
                var contentEl = el.querySelector('.msg-content');
                renderMd(contentEl, m.content || '');
                if (m.tool_calls) {
                    try {
                        var tcs = JSON.parse(m.tool_calls);
                        tcs.forEach(function(tc) {
                            var fn = tc.function || tc;
                            appendToolBlock(el, contentEl, fn.name, fn.arguments || '{}', '(已完成)');
                        });
                    } catch(e) {}
                }
                if (m.token_count > 0) {
                    appendTokenBar(el, m.token_count, m.prompt_tokens, m.completion_tokens);
                }
                break;
            case 'tool':
                break;
            case 'system':
                addMsg('system', m.content || '');
                break;
        }
    }

    // ============ 消息发送 ============
    function sendMsg() {
        if (isStreaming || !currentTopicId) return;
        var text = userInput.value.trim();
        if (!text) return;
        addMsg('user', escHtml(text));
        userInput.value = ''; userInput.style.height = 'auto';

        currentTextBuf = '';
        pendingToolCalls = [];
        currentMsgEl = addMsg('assistant', '');
        currentContentEl = currentMsgEl.querySelector('.msg-content');

        setStreaming(true);
        TeaBridge.chatSend(text, currentTopicId);
    }

    function stopGen() { TeaBridge.chatStop(); }

    // ============ SSE 回调 ============
    function onToken(data) {
        if (!currentContentEl) return;
        currentTextBuf += data.text || '';
        renderMd(currentContentEl, currentTextBuf);
        scrollBottom();
    }

    function onThinking(data) {
        if (!currentMsgEl) return;
        var text = data.text || '';
        if (!text.trim()) return;
        var block = currentMsgEl.querySelector('.msg-thinking');
        if (!block) {
            block = document.createElement('div');
            block.className = 'msg-thinking';
            block.innerHTML = '<div class="thinking-header" onclick="this.nextElementSibling.classList.toggle(\'open\')">🧠 思考过程 ▼</div><div class="thinking-body open"></div>';
            currentMsgEl.insertBefore(block, currentContentEl);
        }
        block.querySelector('.thinking-body').textContent += text;
        scrollBottom();
    }

    function onToolCall(data) {
        if (!currentMsgEl) return;
        try {
            var tc = typeof data === 'string' ? JSON.parse(data) : data;
            if (tc.result !== undefined) {
                var blocks = currentMsgEl.querySelectorAll('.msg-tool');
                var last = blocks[blocks.length - 1];
                if (last) {
                    var pre = last.querySelector('.tool-result');
                    if (pre) pre.textContent = typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2);
                }
                pendingToolCalls.push(tc);
            } else {
                appendToolBlock(currentMsgEl, currentContentEl, tc.name, tc.args || '{}', '(执行中...)');
            }
        } catch(e) { console.error(e); }
        scrollBottom();
    }

    function onDone(data) {
        setStreaming(false);
        if (currentContentEl && currentTextBuf) {
            renderMd(currentContentEl, currentTextBuf);
        }
        if (data.total_tokens > 0 && currentMsgEl) {
            appendTokenBar(currentMsgEl, data.total_tokens, data.prompt_tokens, data.completion_tokens);
        }
        if (!currentTextBuf.trim() && pendingToolCalls.length === 0 && currentMsgEl) {
            currentMsgEl.remove();
        }
        currentMsgEl = null; currentContentEl = null; currentTextBuf = '';
        updateTokenStats();
    }

    function onError(data) {
        setStreaming(false);
        if (currentContentEl) {
            currentContentEl.innerHTML += '<p style="color:var(--bad)">❌ ' + escHtml(data.message || '错误') + '</p>';
        }
    }

    // ============ UI 构建 ============
    function addMsg(type, html) {
        var div = document.createElement('div');
        var clsMap = { user: 'msg-user', assistant: 'msg-assistant', system: 'msg-system', thinking: 'msg-thinking', tool: 'msg-tool' };
        div.className = 'msg ' + (clsMap[type] || '');
        div.innerHTML = '<div class="msg-content">' + html + '</div>';
        chatMsgs.appendChild(div);
        return div;
    }

    function appendToolBlock(parentEl, beforeEl, name, args, result) {
        var block = document.createElement('div');
        block.className = 'msg msg-tool';
        var argsStr = typeof args === 'string' ? args : JSON.stringify(args, null, 2);
        var resultStr = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
        var paramLines = '';
        try {
            var a = typeof args === 'string' ? JSON.parse(args) : args;
            paramLines = Object.keys(a).map(function(k) {
                var v = a[k];
                return '  ' + k + ': ' + (typeof v === 'string' ? "'" + v + "'" : JSON.stringify(v));
            }).join(',\n');
        } catch(e) { paramLines = argsStr; }
        block.innerHTML =
            '<div class="tool-header" onclick="var b=this.nextElementSibling;b.classList.toggle(\'open\')">🔧 ' + escHtml(name) + ' ▼</div>' +
            '<div class="tool-body">' +
            '<div style="color:var(--text3);">参数:</div><pre>' + escHtml(paramLines||'(无)') + '</pre>' +
            '<div style="color:var(--text3);">结果:</div><pre class="tool-result">' + escHtml(resultStr) + '</pre>' +
            '</div>';
        parentEl.insertBefore(block, beforeEl);
    }

    function appendTokenBar(el, total, prompt, comp) {
        var bar = document.createElement('div');
        bar.className = 'token-bar';
        bar.innerHTML = '<span>🪙 ' + total + '</span><span>📥 ' + (prompt||0) + '</span><span>📤 ' + (comp||0) + '</span>';
        el.appendChild(bar);
    }

    function renderMd(el, text) {
        if (typeof marked !== 'undefined' && marked.parse) {
            try { el.innerHTML = marked.parse(text); } catch(e) { el.textContent = text; }
        } else {
            el.textContent = text;
        }
    }

    // ============ 状态 ============
    function setStreaming(active) {
        isStreaming = active;
        btnSend.style.display = active ? 'none' : 'flex';
        btnStop.style.display = active ? 'flex' : 'none';
        userInput.disabled = active;
        statusEl.textContent = active ? '● 生成中...' : '● 就绪';
        statusEl.className = active ? 'status-streaming' : 'status-idle';
        if (!active) pendingToolCalls = [];
    }

    function scrollBottom() {
        var c = $('#chat-container');
        c.scrollTop = c.scrollHeight;
    }

    // ============ 设置 ============
    function openSettings() {
        loadConfigToUI();
        $('#settings-overlay').style.display = 'flex';
        if (isMobile) hideSidebar();
    }

    function loadConfigToUI() {
        var cfg = TeaBridge.configGet();
        var m = cfg.main_model || {};
        $('#cfg-main-url').value = m.api_url || '';
        $('#cfg-main-key').value = m.api_key || '';
        $('#cfg-main-model').value = m.model_name || '';
        $('#cfg-main-max-tokens').value = m.max_tokens || 4096;

        var c = cfg.cheap_model || {};
        $('#cfg-cheap-url').value = c.api_url || '';
        $('#cfg-cheap-key').value = c.api_key || '';
        $('#cfg-cheap-model').value = c.model_name || '';

        var e = cfg.embedding_model || {};
        $('#cfg-emb-url').value = e.api_url || '';
        $('#cfg-emb-key').value = e.api_key || '';
        $('#cfg-emb-model').value = e.model_name || '';

        $('#cfg-keep-turns').value = cfg.keep_turns || 5;
        $('#cfg-max-iter').value = cfg.max_iterations || 30;
        $('#cfg-theme').value = cfg.theme || 'dark';
    }

    function saveConfig() {
        TeaBridge.configSet({
            main_model: {
                api_url: $('#cfg-main-url').value.trim(),
                api_key: $('#cfg-main-key').value.trim(),
                model_name: $('#cfg-main-model').value.trim(),
                max_tokens: parseInt($('#cfg-main-max-tokens').value) || 4096
            },
            cheap_model: {
                api_url: $('#cfg-cheap-url').value.trim(),
                api_key: $('#cfg-cheap-key').value.trim(),
                model_name: $('#cfg-cheap-model').value.trim()
            },
            embedding_model: {
                api_url: $('#cfg-emb-url').value.trim(),
                api_key: $('#cfg-emb-key').value.trim(),
                model_name: $('#cfg-emb-model').value.trim()
            },
            keep_turns: parseInt($('#cfg-keep-turns').value) || 5,
            max_iterations: parseInt($('#cfg-max-iter').value) || 30,
            theme: $('#cfg-theme').value
        });
        $('#settings-overlay').style.display = 'none';
        applyTheme();
    }

    function applyTheme() {
        var cfg = TeaBridge.configGet();
        var theme = cfg.theme || 'dark';
        document.body.className = 'theme-' + theme;
    }

    // ============ 工具 ============
    function escHtml(t) {
        var d = document.createElement('div');
        d.textContent = t || '';
        return d.innerHTML;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else { init(); }
})();
