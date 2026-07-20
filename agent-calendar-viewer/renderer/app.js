/* ══════════════════════════════════════════════
   Agent 日历 · Zaker 风格前端逻辑（含配图+阅读视图）
   ══════════════════════════════════════════════ */

let allData = null;
let currentDate = null;
let isDark = localStorage.getItem('zaker-theme') === 'dark';
let loadedImages = {};        // 已加载的图片 URL 缓存
let imageLoadingQueue = new Set(); // 正在加载的 URL 去重
let fallbackIndex = 0;

// ── 字体缩放状态 ──
let readerFontScale = parseInt(localStorage.getItem('zaker-font-scale')) || 100;
// 字体缩放范围: 50% ~ 200%，步长 10%
const FONT_SCALE_MIN = 50;
const FONT_SCALE_MAX = 200;
const FONT_SCALE_STEP = 10;

// ── DOM 引用 ──
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// 主界面
const loadingEl = $('#loading');
const errorEl = $('#error');
const contentArea = $('#content-area');
const cardGrid = $('#card-grid');
const tabsScroll = $('#tabs-scroll');
const emptyEl = $('#empty');
// 新闻
const newsArea = $('#news-area');
const newsGrid = $('#news-grid');
const newsEmpty = $('#news-empty');
const btnRefreshNews = $('#btn-refresh-news');
const tabBar = document.querySelector('.tab-bar');
const footerInfo = $('#footer-info');
const btnRefresh = $('#btn-refresh');
const btnTheme = $('#btn-theme');
const errorTitle = $('#error-title');
const errorDesc = $('#error-desc');

// 阅读视图
const readerOverlay = $('#reader-overlay');
const readerBackBtn = $('#reader-back');
const readerTitle = $('#reader-title');
const readerLoading = $('#reader-loading');
const readerError = $('#reader-error');
const readerErrorText = $('#reader-error-text');
const readerContent = $('#reader-content');
const readerArticleTitle = $('#reader-article-title');
const readerSite = $('#reader-site');
const readerByline = $('#reader-byline');
const readerArticleBody = $('#reader-article-body');
const readerOpenBrowser = $('#reader-open-browser');
const readerFontDecrease = $('#reader-font-decrease');
const readerFontIncrease = $('#reader-font-increase');
const readerFontReset = $('#reader-font-reset');
const readerFontIndicator = $('#reader-font-indicator');

// ── 初始化 ──
document.addEventListener('DOMContentLoaded', () => {
    if (isDark) {
        document.documentElement.setAttribute('data-theme', 'dark');
        btnTheme.textContent = '☀️';
    }
    loadData();
    
    // 标签切换
    if (tabBar) {
        tabBar.addEventListener('click', (e) => {
            const tab = e.target.closest('.tab-item');
            if (!tab) return;
            document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.dataset.tab;
            if (target === 'calendar') {
                contentArea.style.display = 'block';
                newsArea.style.display = 'none';
            } else if (target === 'news') {
                contentArea.style.display = 'none';
                newsArea.style.display = 'block';
                loadNews();
            }
        });
    }

    // 刷新新闻
    btnRefreshNews.addEventListener('click', () => {
        btnRefreshNews.style.transform = 'rotate(360deg)';
        btnRefreshNews.style.transition = 'transform 0.6s';
        loadNews(true);
        setTimeout(() => { btnRefreshNews.style.transition = 'none'; btnRefreshNews.style.transform = ''; }, 600);
    });

    // 监听新闻推送
    if (window.electronAPI && window.electronAPI.onNewsFetched) {
        window.electronAPI.onNewsFetched((articles) => {
            if (articles && articles.length > 0) {
                renderNews(articles);
            }
        });
    }

    btnRefresh.addEventListener('click', () => {
        btnRefresh.style.transform = 'rotate(360deg)';
        btnRefresh.style.transition = 'transform 0.6s';
        loadData();
        setTimeout(() => { btnRefresh.style.transition = 'none'; btnRefresh.style.transform = ''; }, 600);
    });
    btnTheme.addEventListener('click', toggleTheme);

    // 阅读视图事件
    readerBackBtn.addEventListener('click', closeReader);
    readerOverlay.addEventListener('click', (e) => {
        if (e.target === readerOverlay || e.target.classList.contains('reader-backdrop')) {
            closeReader();
        }
    });
    readerOpenBrowser.addEventListener('click', () => {
        const url = readerOpenBrowser.dataset.url;
        if (url && window.electronAPI) window.electronAPI.openExternal(url);
    });

    // 键盘快捷键
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && readerOverlay.style.display !== 'none') closeReader();
    });

    // 字体缩放事件
    if (readerFontIncrease) {
        readerFontIncrease.addEventListener('click', () => changeReaderFontScale(FONT_SCALE_STEP));
    }
    if (readerFontDecrease) {
        readerFontDecrease.addEventListener('click', () => changeReaderFontScale(-FONT_SCALE_STEP));
    }
    if (readerFontReset) {
        readerFontReset.addEventListener('click', resetReaderFontScale);
    }

    // Ctrl+滚轮 字体缩放（在阅读视图打开时）
    document.addEventListener('wheel', (e) => {
        if (readerOverlay.style.display === 'none') return;
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        const delta = e.deltaY > 0 ? -FONT_SCALE_STEP : FONT_SCALE_STEP;
        changeReaderFontScale(delta);
    }, { passive: false });

    // 监听文件变更
    if (window.electronAPI) {
        window.electronAPI.onCalendarUpdated((data) => {
            allData = data;
            render();
        });
    }
});

// ── 加载数据 ──
async function loadData() {
    showLoading(true);
    try {
        let data;
        if (window.electronAPI) {
            data = await window.electronAPI.readCalendar();
        } else {
            data = { error: '仅支持 Electron 环境' };
        }

        if (data.error) {
            showError('文件读取失败', data.error + '\n路径: ' + (data.path || ''));
            return;
        }
        allData = data;
        render();
    } catch (err) {
        showError('加载失败', err.message);
    }
}

// ── 渲染 ──
function render() {
    showLoading(false);
    errorEl.style.display = 'none';
    contentArea.style.display = 'block';

    if (!allData || !allData.dates || allData.dates.length === 0) {
        emptyEl.style.display = 'flex';
        cardGrid.innerHTML = '';
        footerInfo.textContent = '共 0 篇文章';
        return;
    }
    emptyEl.style.display = 'none';

    renderTabs();
    
    if (!currentDate || !allData.dates.includes(currentDate)) {
        currentDate = allData.dates[0];
    }
    
    renderCards(currentDate);
    updateFooter();
}

// ── 日期标签 ──
function renderTabs() {
    tabsScroll.innerHTML = '';
    allData.dates.forEach((date) => {
        const btn = document.createElement('button');
        btn.className = 'tab-btn' + (date === currentDate ? ' active' : '');
        const d = new Date(date);
        const weekDays = ['日', '一', '二', '三', '四', '五', '六'];
        const label = `${date.replace('2026-', '')} 周${weekDays[d.getDay()]}`;
        btn.textContent = label;
        btn.dataset.date = date;
        btn.addEventListener('click', () => {
            currentDate = date;
            renderCards(date);
            $$('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            btn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        });
        tabsScroll.appendChild(btn);
    });
}

// ── 渲染卡片 ──
function renderCards(date) {
    const articles = allData.grouped[date];
    if (!articles || articles.length === 0) {
        cardGrid.innerHTML = '<div class="empty" style="display:flex"><div class="empty-icon">📭</div><p>该日期暂无文章</p></div>';
        return;
    }

    cardGrid.innerHTML = '';
    articles.forEach((article, idx) => {
        const card = document.createElement('div');
        card.className = 'card';
        card.dataset.index = idx;

        const preview = truncate(article.summary || '暂无摘要', 120);
        const fallbackClass = 'fallback-' + ((idx + fallbackIndex) % 10);

        card.innerHTML = `
            <div class="card-image-wrap" data-url="${escapeAttr(article.url)}">
                <div class="shimmer"></div>
                <div class="fallback-bg ${fallbackClass}"></div>
            </div>
            <span class="card-domain">${escapeHtml(article.domain)}</span>
            <span class="card-number">#${article.date} · ${idx + 1}</span>
            <div class="card-title">${escapeHtml(article.title)}</div>
            <div class="card-summary">${escapeHtml(preview)}</div>
            <span class="card-expand-btn">展开全文 ›</span>
        `;

        // 加载配图
        loadCardImage(card, article.url);

        // 点击卡片 → 打开阅读视图
        card.addEventListener('click', (e) => {
            if (e.target.closest('.card-expand-btn')) return;
            if (e.target.closest('.card-image-wrap')) return;
            openReader(article);
        });

        // 点击图片区也打开阅读视图
        const imgWrap = card.querySelector('.card-image-wrap');
        imgWrap.addEventListener('click', (e) => {
            e.stopPropagation();
            openReader(article);
        });

        // 展开/折叠
        const expandBtn = card.querySelector('.card-expand-btn');
        expandBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (card.classList.contains('expanded')) {
                card.classList.remove('expanded');
                card.querySelector('.card-summary').textContent = preview;
                expandBtn.textContent = '展开全文 ›';
            } else {
                card.classList.add('expanded');
                card.querySelector('.card-summary').textContent = article.summary || '暂无摘要';
                expandBtn.textContent = '收起 ▲';
            }
        });

        // 右键复制链接
        card.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            if (article.url) {
                navigator.clipboard.writeText(article.url).then(() => showToast('链接已复制'));
            }
        });

        cardGrid.appendChild(card);
    });

    // 卡片入场动画（错开）
    requestAnimationFrame(() => {
        $$('.card').forEach((c, i) => {
            c.style.opacity = '0';
            c.style.transform = 'translateY(20px)';
            c.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            setTimeout(() => {
                c.style.opacity = '1';
                c.style.transform = 'translateY(0)';
            }, i * 60);
        });
    });
}

// ── 加载卡片配图 ──
function loadCardImage(card, articleUrl) {
    const wrap = card.querySelector('.card-image-wrap');
    if (!wrap) return;

    // 检查缓存
    if (loadedImages[articleUrl]) {
        showCardImage(wrap, loadedImages[articleUrl]);
        return;
    }

    // 正在加载中
    if (imageLoadingQueue.has(articleUrl)) return;
    imageLoadingQueue.add(articleUrl);

    if (window.electronAPI && window.electronAPI.fetchOgImage) {
        window.electronAPI.fetchOgImage(articleUrl).then((imgUrl) => {
            imageLoadingQueue.delete(articleUrl);
            if (imgUrl) {
                loadedImages[articleUrl] = imgUrl;
                // 检查这个 wrap 是否还在 DOM 中
                if (document.body.contains(wrap)) {
                    showCardImage(wrap, imgUrl);
                }
            }
        }).catch(() => {
            imageLoadingQueue.delete(articleUrl);
        });
    }
}

function showCardImage(wrap, imgUrl) {
    // 移除 shimmer
    const shimmer = wrap.querySelector('.shimmer');
    if (shimmer) shimmer.remove();
    const fallback = wrap.querySelector('.fallback-bg');
    if (fallback) fallback.remove();

    const img = new Image();
    img.onload = () => {
        wrap.innerHTML = '';
        wrap.appendChild(img);
    };
    img.onerror = () => {
        // 图片加载失败，保留 fallback
    };
    img.src = imgUrl;
    img.alt = '';
    img.style.width = '100%';
    img.style.height = '100%';
    img.style.objectFit = 'cover';
}

// ── 阅读视图 ──
let currentReaderUrl = '';

function openReader(article) {
    currentReaderUrl = article.url;
    readerOverlay.style.display = 'flex';
    readerLoading.style.display = 'flex';
    readerError.style.display = 'none';
    readerContent.style.display = 'none';
    readerTitle.textContent = '正在加载...';
    readerOpenBrowser.dataset.url = article.url;

    // 先显示标题和摘要
    readerArticleTitle.textContent = article.title || '加载中...';
    readerSite.textContent = article.domain || '';
    readerByline.textContent = '';

    if (window.electronAPI && window.electronAPI.fetchArticleContent) {
        window.electronAPI.fetchArticleContent(article.url).then((result) => {
            readerLoading.style.display = 'none';
            if (result.success) {
                readerContent.style.display = 'block';
                readerArticleTitle.textContent = result.title || article.title;
                readerTitle.textContent = result.title || article.title;
                readerSite.textContent = result.siteName || article.domain || '';
                readerByline.textContent = result.byline ? '作者: ' + result.byline : '';
                
                // 注入清理后的 HTML 内容
                readerArticleBody.innerHTML = result.content || '<p>无法提取正文内容</p>';
                
                // 应用用户保存的字体缩放
                applyReaderFontScale();
                
                if (result.fallback) {
                    const note = document.createElement('div');
                    note.style.cssText = 'background:var(--accent-glow);padding:12px 16px;border-radius:8px;font-size:13px;color:var(--text-secondary);margin-bottom:20px;border:1px solid var(--border);';
                    note.textContent = '⚠️ 内容提取受限，显示为纯文本版本';
                    readerArticleBody.insertBefore(note, readerArticleBody.firstChild);
                }
            } else {
                readerError.style.display = 'flex';
                readerErrorText.textContent = result.error || '无法加载文章内容';
                readerTitle.textContent = article.title || '加载失败';
            }
        }).catch((err) => {
            readerLoading.style.display = 'none';
            readerError.style.display = 'flex';
            readerErrorText.textContent = err.message || '网络请求失败';
            readerTitle.textContent = article.title || '加载失败';
        });
    } else {
        readerLoading.style.display = 'none';
        readerContent.style.display = 'block';
        readerArticleBody.innerHTML = `<p>无法在非 Electron 环境中加载文章。</p><p><a href="${escapeAttr(article.url)}" target="_blank">点击在浏览器中打开</a></p>`;
        // 应用用户保存的字体缩放
        applyReaderFontScale();
    }
}

function closeReader() {
    readerOverlay.style.display = 'none';
    readerContent.style.display = 'none';
    readerLoading.style.display = 'none';
    readerError.style.display = 'none';
    currentReaderUrl = '';
}

// ── 字体缩放功能 ──

/**
 * 应用当前字体缩放到阅读正文
 */
function applyReaderFontScale() {
    if (!readerArticleBody) return;
    const baseSize = 17; // px
    const scaledSize = Math.round(baseSize * readerFontScale / 100);
    readerArticleBody.style.fontSize = scaledSize + 'px';
    // 更新指示器
    if (readerFontIndicator) {
        readerFontIndicator.textContent = readerFontScale + '%';
    }
}

/**
 * 改变字体缩放
 * @param {number} delta - 变化量（正数放大，负数缩小）
 */
function changeReaderFontScale(delta) {
    const newScale = Math.max(FONT_SCALE_MIN, Math.min(FONT_SCALE_MAX, readerFontScale + delta));
    if (newScale === readerFontScale) return;
    readerFontScale = newScale;
    localStorage.setItem('zaker-font-scale', String(readerFontScale));
    applyReaderFontScale();
}

/**
 * 重置字体缩放到 100%
 */
function resetReaderFontScale() {
    readerFontScale = 100;
    localStorage.setItem('zaker-font-scale', '100');
    applyReaderFontScale();
}

// ── 更新底部 ──
function updateFooter() {
    if (!allData) return;
    const total = allData.entries ? allData.entries.length : 0;
    const dates = allData.dates ? allData.dates.length : 0;
    footerInfo.textContent = `共 ${total} 篇文章 · ${dates} 个日期`;
}

// ── 主题切换 ──
function toggleTheme() {
    isDark = !isDark;
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
    btnTheme.textContent = isDark ? '☀️' : '🌙';
    localStorage.setItem('zaker-theme', isDark ? 'dark' : 'light');
}

// ── 工具函数 ──
function showLoading(show) {
    loadingEl.style.display = show ? 'flex' : 'none';
    if (show) { contentArea.style.display = 'none'; errorEl.style.display = 'none'; }
}

function showError(title, desc) {
    loadingEl.style.display = 'none';
    contentArea.style.display = 'none';
    errorEl.style.display = 'flex';
    errorTitle.textContent = title;
    errorDesc.textContent = desc;
}

function truncate(str, len) {
    if (!str) return '';
    if (str.length <= len) return str;
    return str.substring(0, len) + '...';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(text) {
    if (!text) return '';
    return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Toast ──
function showToast(msg) {
    let toast = document.querySelector('.toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.className = 'toast';
        Object.assign(toast.style, {
            position: 'fixed',
            bottom: '60px',
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'var(--bg-card)',
            color: 'var(--text-primary)',
            padding: '10px 24px',
            borderRadius: '20px',
            fontSize: '14px',
            boxShadow: 'var(--shadow-md)',
            border: '1px solid var(--border)',
            zIndex: '9999',
            transition: 'opacity 0.3s, transform 0.3s',
            opacity: '0',
            transform: 'translateX(-50%) translateY(10px)',
            fontFamily: 'var(--font-sans)',
        });
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.style.opacity = '1';
    toast.style.transform = 'translateX(-50%) translateY(0)';
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(-50%) translateY(10px)';
    }, 2000);
}

// ════════════════════════════════════════════════
// 新闻模块
// ════════════════════════════════════════════════

let newsArticles = [];
let isNewsLoading = false;

async function loadNews(forceRefresh) {
    if (isNewsLoading) return;
    isNewsLoading = true;

    newsEmpty.style.display = 'none';
    newsEmpty.innerHTML = '<div class="empty-icon">📡</div><p>正在抓取...</p>';

    try {
        let articles;
        if (window.electronAPI && window.electronAPI.fetchNews) {
            const result = await window.electronAPI.fetchNews(!!forceRefresh);
            if (result.success) {
                articles = result.articles;
            } else {
                throw new Error(result.error || '抓取失败');
            }
        } else {
            // 离线 fallback
            articles = getDemoNews();
        }

        if (articles && articles.length > 0) {
            newsArticles = articles;
            renderNews(articles);
        } else {
            newsGrid.innerHTML = '';
            newsEmpty.style.display = 'flex';
            newsEmpty.innerHTML = '<div class="empty-icon">📡</div><p>暂无新闻，请稍后再试</p>';
        }
    } catch (err) {
        newsGrid.innerHTML = '';
        newsEmpty.style.display = 'flex';
        newsEmpty.innerHTML = '<div class="empty-icon">⚠️</div><p>' + escapeHtml(err.message) + '</p>';
    } finally {
        isNewsLoading = false;
    }
}

function renderNews(articles) {
    newsGrid.innerHTML = '';
    newsEmpty.style.display = 'none';

    articles.forEach((article) => {
        const card = document.createElement('div');
        card.className = 'news-card';

        const timeStr = article.date ? formatNewsDate(article.date) : '';
        const summary = article.summary || '';

        card.innerHTML = `
            <div class="news-card-source">${escapeHtml(article.source || '')}</div>
            <div class="news-card-title">${escapeHtml(article.title)}</div>
            <div class="news-card-summary">${escapeHtml(summary)}</div>
            <div class="news-card-time">${timeStr}</div>
        `;

        card.addEventListener('click', () => {
            openReader({
                url: article.link || article.url,
                title: article.title,
                domain: article.source || '',
                summary: summary,
            });
        });

        newsGrid.appendChild(card);
    });
}

function formatNewsDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '';
    const now = new Date();
    const diff = now - d;
    if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前';
    if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前';
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

function getDemoNews() {
    const demos = [
        { source: '科技', title: 'DeepSeek 发布新一代推理模型', summary: 'DeepSeek 最新推出的推理模型在多项基准测试中取得突破性进展，引发业界广泛关注。', date: new Date().toISOString(), link: 'https://www.deepseek.com' },
        { source: '科技', title: 'Linux 内核 6.12 发布，带来多项重要更新', summary: 'Linus Torvalds 宣布 Linux 内核 6.12 正式发布，包含新硬件支持、性能优化和安全改进。', date: new Date().toISOString(), link: 'https://kernel.org' },
        { source: 'AI', title: 'Claude 3.5 Sonnet 性能大幅提升', summary: 'Anthropic 发布了 Claude 3.5 Sonnet 的更新版本，在编程和推理任务上表现显著提升。', date: new Date().toISOString(), link: 'https://anthropic.com' },
        { source: '开发', title: 'TypeScript 5.8 正式发布', summary: '微软发布了 TypeScript 5.8，带来了更好的类型推断和新的语言特性。', date: new Date().toISOString(), link: 'https://devblogs.microsoft.com/typescript' },
        { source: '开源', title: 'React 19 进入稳定阶段', summary: 'React 19 经过多个 RC 版本后趋于稳定，带来了 Actions、新 Hooks 等重大更新。', date: new Date().toISOString(), link: 'https://react.dev' },
    ];
    return demos;
}
