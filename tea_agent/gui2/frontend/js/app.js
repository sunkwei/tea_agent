// Tea Agent GUI2 - Modern SPA Frontend

const API = {
    base: '/api',
    async request(path, opts = {}) {
        const res = await fetch(this.base + path, {
            headers: { 'Content-Type': 'application/json' },
            ...opts,
        });
        if (!res.ok) throw new Error(res.status);
        return await res.json();
    },
    async health() {
        try { const d = await this.request('/health'); return d.status === 'ok'; }
        catch { return false; }
    },
    async listTopics() {
        return await this.request('/v1/sessions');
    },
    async sendMessage(topicId, content) {
        const params = {
            messages: [{ role: 'user', content }],
            stream: true,
        };
        if (topicId) params.topic_id = topicId;
        return fetch(this.base + '/v1/chat/completions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
        });
    },
};

// DOM Helpers
const $el = (id) => document.getElementById(id);

function addMsg(role, text, streaming = false) {
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    if (streaming) div.classList.add('streaming');
    div.innerHTML = `
        <div class="msg-label">${role === 'user' ? '\u7528\u6237' : 'Tea Agent'}</div>
        <div class="msg-bubble">${text}</div>`;
    const msgs = $el('chat-messages');
    msgs.appendChild(div);
    setTimeout(() => { msgs.scrollTop = msgs.scrollHeight; }, 50);
    return div;
}

function removeWelcome() {
    document.querySelector('.welcome')?.remove();
}

// Streaming
let isStreaming = false;

async function streamConversation(topicId, content) {
    if (isStreaming) return;
    isStreaming = true;
    const btn = $el('btn-send');
    btn.disabled = true;
    btn.textContent = '\u6b63\u5728\u53d1\u9001...';

    removeWelcome();
    addMsg('user', content);
    const aiMsg = addMsg('ai', '', true);
    const aiBubble = aiMsg.querySelector('.msg-bubble');

    try {
        const res = await API.sendMessage(topicId, content);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            for (let i = 0; i < lines.length - 1; i++) {
                const l = lines[i].trim();
                if (l.startsWith('data: ')) {
                    try {
                        const d = JSON.parse(l.slice(6));
                        if (d.choices?.[0]?.delta?.content) {
                            aiBubble.innerHTML += d.choices[0].delta.content;
                        }
                    } catch (e) { /* partial data */ }
                }
            }
            buffer = lines[lines.length - 1];
        }
    } catch (e) {
        aiBubble.innerHTML = `<span style="color:#ff5555">Error: ${e.message}</span>`;
    } finally {
        isStreaming = false;
        aiMsg.classList.remove('streaming');
        btn.disabled = false;
        btn.textContent = '\u53d1\u9001';
    }
}

// Topic Management
let currentTopicId = null;

async function refreshTopics() {
    try {
        const data = await API.listTopics();
        const list = $el('topic-list');
        if (data?.data) {
            list.innerHTML = data.data.map(t => `
                <div class="topic-item${t.id === currentTopicId ? ' active' : ''}"
                     data-topic="${t.id}">
                    ${t.summary || t.id || '\u65b0\u5bf9\u8bdd'}
                </div>
            `).join('');
        }
    } catch (e) {
        // API unavailable
    }
}

// Event Setup
function setupInput() {
    const input = $el('chat-input');
    const btn = $el('btn-send');

    input.addEventListener('input', () => {
        btn.disabled = !input.value.trim() || isStreaming;
    });

    input.addEventListener('keydown', (e) => {
        if ((e.key === 'Enter' && !e.shiftKey) || (e.ctrlKey && e.key === 'Enter')) {
            e.preventDefault();
            if (!btn.disabled) handleSend();
        }
    });

    btn.addEventListener('click', handleSend);
}

async function handleSend() {
    const input = $el('chat-input');
    const msg = input.value.trim();
    if (!msg) return;

    input.value = '';
    $el('btn-send').disabled = true;

    await streamConversation(currentTopicId, msg);
    await refreshTopics();
}

function setupTopicList() {
    $el('topic-list').addEventListener('click', (e) => {
        const item = e.target.closest('.topic-item');
        if (item) {
            const id = item.getAttribute('data-topic');
            if (id && id !== currentTopicId) {
                currentTopicId = id;
                const title = item.textContent.trim();
                $el('topic-title').textContent = title;
                refreshTopics();
            }
        }
    });

    $el('btn-new-topic').addEventListener('click', () => {
        currentTopicId = null;
        $el('topic-title').textContent = '\u65b0\u5bf9\u8bdd';
        $el('chat-messages').innerHTML = '';
        refreshTopics();
    });

    $el('btn-clear').addEventListener('click', () => {
        $el('chat-messages').innerHTML = '';
    });
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    setupInput();
    setupTopicList();
    refreshTopics();

    API.health().then(connected => {
        if (connected) console.log('Connected');
        else console.warn('API unavailable');
    });
});
