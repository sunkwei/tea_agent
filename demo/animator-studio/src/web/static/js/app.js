// Animator Studio — 前端交互 (支持 LLM 模式)

const promptEl = document.getElementById('prompt');
const durationEl = document.getElementById('duration');
const ttsEl = document.getElementById('tts');
const recordEl = document.getElementById('record');
const generateBtn = document.getElementById('generateBtn');
const preview = document.getElementById('preview');
const previewIframe = document.getElementById('previewIframe');
const previewOverlay = document.getElementById('previewOverlay');
const statusEl = document.getElementById('status');
const downloadHtml = document.getElementById('downloadHtml');
const downloadMp4 = document.getElementById('downloadMp4');
const historyList = document.getElementById('historyList');
const fullscreenBtn = document.getElementById('fullscreenBtn');
const llmStatus = document.getElementById('llmStatus');
const dslPreview = document.getElementById('dslPreview');
const dslContent = document.getElementById('dslContent');
const toggleDslBtn = document.getElementById('toggleDslBtn');
const modeNormal = document.getElementById('modeNormal');
const modeLLM = document.getElementById('modeLLM');

let currentResult = null;
let isLLMMode = false;

// ── 模式切换 ──
modeNormal.addEventListener('click', () => {
  isLLMMode = false;
  modeNormal.classList.add('active');
  modeLLM.classList.remove('active');
  promptEl.placeholder = '关键词模式: 彩色粒子 快速 5秒';
});
modeLLM.addEventListener('click', () => {
  isLLMMode = true;
  modeLLM.classList.add('active');
  modeNormal.classList.remove('active');
  promptEl.placeholder = 'LLM 模式: 描述任何场景，AI 自动生成动画...';
});

// ── DSL 展开/折叠 ──
toggleDslBtn?.addEventListener('click', () => {
  const show = dslContent.classList.toggle('show');
  toggleDslBtn.textContent = show ? '折叠' : '展开';
});

// ── 生成动画 ──
generateBtn.addEventListener('click', async () => {
  const text = promptEl.value.trim();
  if (!text) { alert('请输入动画描述'); return; }

  generateBtn.disabled = true;
  generateBtn.textContent = '⏳ 生成中...';
  preview.style.display = 'block';
  previewOverlay.classList.remove('hidden');
  previewOverlay.querySelector('p').textContent = isLLMMode ? 'LLM 正在创作脚本...' : '生成中...';
  statusEl.textContent = isLLMMode ? '🤖 调用 LLM...' : '生成中...';
  dslPreview.style.display = 'none';

  if (isLLMMode) {
    llmStatus.style.display = 'flex';
  }

  try {
    let result;

    if (isLLMMode) {
      // LLM 模式
      const resp = await fetch('/api/llm-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          duration: parseFloat(durationEl.value) || 8,
          tts: ttsEl.checked,
        }),
      });
      const json = await resp.json();
      if (!json.ok) throw new Error(json.detail || 'LLM 生成失败');
      result = json.data;

      // 显示 DSL 预览
      if (result.dsl) {
        dslContent.textContent = JSON.stringify(result.dsl, null, 2);
        dslPreview.style.display = 'block';
        toggleDslBtn.textContent = '展开';
        dslContent.classList.remove('show');
      }
    } else {
      // 关键词模式
      const resp = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          duration: parseFloat(durationEl.value) || 5,
          tts: ttsEl.checked,
        }),
      });
      const json = await resp.json();
      if (!json.ok) throw new Error(json.detail || '生成失败');
      result = json.data;
    }

    currentResult = result;
    statusEl.textContent = '✅ 生成完成';
    previewOverlay.classList.add('hidden');
    llmStatus.style.display = 'none';

    // 加载预览
    const previewUrl = `/player/${result.id}`;
    previewIframe.src = previewUrl;
    downloadHtml.href = previewUrl;
    downloadHtml.download = 'animation.html';

    // 如果勾选了录制
    if (recordEl.checked) {
      statusEl.textContent = '🎬 录制中...';
      previewOverlay.classList.remove('hidden');
      previewOverlay.querySelector('p').textContent = '录制 MP4 中...';

      const filePath = result.html_path.replace(/\\/g, '/');
      const recResp = await fetch('/api/record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          html_path: filePath,
          duration: result.duration,
        }),
      });
      const recResult = await recResp.json();
      if (recResult.ok) {
        const videoPath = recResult.data.video_path.replace(/\\/g, '/');
        downloadMp4.style.display = 'inline-block';
        downloadMp4.href = 'file:///' + videoPath;
        downloadMp4.download = 'animation.mp4';
        statusEl.textContent = `✅ 录制完成 (${recResult.data.size_mb} MB)`;
      }
      previewOverlay.classList.add('hidden');
    }

    // 刷新历史
    loadHistory();
  } catch (err) {
    statusEl.textContent = '❌ ' + err.message;
    previewOverlay.querySelector('p').textContent = '生成失败';
    llmStatus.style.display = 'none';
  } finally {
    generateBtn.disabled = false;
    generateBtn.textContent = '▶ 生成动画';
  }
});

// ── 加载历史 ──
async function loadHistory() {
  try {
    const resp = await fetch('/api/animations');
    const result = await resp.json();
    if (!result.ok || !result.data.length) return;

    historyList.innerHTML = '';
    result.data.slice().reverse().forEach(item => {
      const div = document.createElement('div');
      div.className = 'history-item';
      const typeIcon = item.type === 'llm' ? '🤖' : item.type === 'story' ? '📱' : '🎯';
      div.innerHTML = `
        <div>
          <div class="text">${escapeHtml(item.text)}</div>
          <div class="meta">${typeIcon} ${item.type} · ${item.duration}s · ${item.created_at}</div>
        </div>
        <div class="actions">
          <a href="/player/${item.id}" class="btn" target="_blank">▶ 播放</a>
        </div>
      `;
      historyList.appendChild(div);
    });
  } catch (e) {
    // ignore
  }
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ── 全屏 ──
fullscreenBtn.addEventListener('click', () => {
  if (previewIframe.requestFullscreen) {
    previewIframe.requestFullscreen();
  }
});

// ── 初始加载历史 ──
loadHistory();

// ── 快捷键 ──
promptEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.ctrlKey) {
    generateBtn.click();
  }
});
