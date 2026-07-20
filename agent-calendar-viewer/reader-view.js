/* ====================================================
   Reader View -- 文章内容提取与清理模块
   使用 Electron BrowserWindow + executeJavaScript
   真实浏览器加载 -> 绕过反爬 -> 提取正文
   ==================================================== */

const { BrowserWindow } = require('electron');

const FETCH_TIMEOUT = 20000;

// -- 页面内提取脚本（在目标页面的浏览器上下文中执行） --
const EXTRACT_SCRIPT = `
    (function() {
        try {
            // 1. 清理噪声元素
            var removals = [
                'iframe', 'nav', 'header', 'footer',
                '.advertisement', '.ad', '.ads', '.adsbygoogle',
                '#sidebar', '.sidebar', '.aside',
                '.comment', '#comments', '.comment-area',
                '.share-bar', '.share-box',
                '.related-articles', '.recommend',
                '.breadcrumb', '.pagination',
                '.mask', '.popup', '.modal',
                '.subscribe', '.qrcode', '.download',
                'script', 'style', 'noscript', 'svg'
            ];
            for (var r = 0; r < removals.length; r++) {
                try {
                    var els = document.querySelectorAll(removals[r]);
                    for (var i = 0; i < els.length; i++) {
                        if (els[i] && els[i].remove) els[i].remove();
                    }
                } catch(e) {}
            }
    
            // 2. 获取标题
            var title = '';
            var h1 = document.querySelector('h1');
            if (h1) title = h1.textContent.trim();
            if (!title || title.length < 4) {
                var ogTitle = document.querySelector('meta[property="og:title"]');
                if (ogTitle) title = ogTitle.getAttribute('content') || '';
            }
            if (!title || title.length < 4) {
                title = document.title || '';
            }
            if (title.indexOf(' - ') > 0) title = title.split(' - ')[0].trim();
            if (title.indexOf(' | ') > 0) title = title.split(' | ')[0].trim();
    
            // 3. 查找正文容器
            var contentEl = null;
            var selectors = [
                'article',
                '[role="main"]',
                '.post-content', '.article-content',
                '.entry-content', '.content-body',
                '.post-body', '.article-body',
                '.Post-RichText', '.RichText',
                '#content', '.content',
                '#main-content', '.main-content',
                '.post', '.article',
                '.rich-text', '.article-detail',
                '.ContentItem', '.ArticleItem',
                '.detail-content', '.news-content',
                '.article-main', '#read-content',
                '.zh-article', '#zh-article'
            ];
            for (var i = 0; i < selectors.length; i++) {
                var el = document.querySelector(selectors[i]);
                if (el && el.textContent.trim().length > 200) {
                    contentEl = el;
                    break;
                }
            }
    
            if (!contentEl) {
                var all = document.querySelectorAll('body, .main, .container, .page, .layout, section, #app, #root');
                var best = null;
                var bestScore = 0;
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    var pCount = el.querySelectorAll('p').length;
                    var textLen = el.textContent.trim().length;
                    var score = pCount * 10 + Math.min(textLen / 100, 50);
                    if (score > bestScore) {
                        bestScore = score;
                        best = el;
                    }
                }
                contentEl = best;
            }
    
            if (!contentEl || contentEl.textContent.trim().length < 100) {
                var bodyText = document.body ? document.body.textContent.replace(/\s+/g, ' ').trim() : '';
                if (bodyText.length > 50) {
                    return JSON.stringify({
                        success: true,
                        title: title || '\u539f\u6587',
                        content: '<p>' + bodyText.substring(0, 10000) + '</p>',
                        siteName: (location && location.hostname) || '',
                        byline: '',
                        fallback: true
                    });
                }
                return JSON.stringify({ success: false, error: '\u672a\u627e\u5230\u6b63\u6587\u5185\u5bb9' });
            }
    
            // 4. 清理小图标
            var imgs = contentEl.querySelectorAll('img');
            for (var i = 0; i < imgs.length; i++) {
                var img = imgs[i];
                var w = parseInt(img.getAttribute('width') || '');
                var h = parseInt(img.getAttribute('height') || '');
                if ((w > 0 && w < 40) || (h > 0 && h < 40)) {
                    if (img.parentNode) img.parentNode.removeChild(img);
                    continue;
                }
                if (!img.getAttribute('alt')) img.setAttribute('alt', '\u63d2\u56fe');
                var src = img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('data-original') || '';
                if (src && !img.getAttribute('src')) img.setAttribute('src', src);
            }
    
            // 5. 清理空标签
            var allEls = contentEl.querySelectorAll('*');
            for (var i = allEls.length - 1; i >= 0; i--) {
                var el = allEls[i];
                if (el.textContent.trim() === '' && el.tagName !== 'IMG' && el.tagName !== 'BR' && el.tagName !== 'HR' && el.querySelectorAll('img,iframe').length === 0) {
                    if (el.parentNode) el.parentNode.removeChild(el);
                }
            }
    
            // 6. 返回
            var contentHtml = contentEl.innerHTML;
            var textContent = contentEl.textContent.replace(/\s+/g, ' ').trim();
            var siteName = (location && location.hostname.replace('www.', '')) || '';
    
            var byline = '';
            var authorEl = document.querySelector('.author-name, .author, [rel="author"], meta[name="author"]');
            if (authorEl) byline = authorEl.getAttribute('content') || authorEl.textContent.trim();
            var timeEl = document.querySelector('time, .time, .date, .publish-date, meta[property="article:published_time"]');
            if (timeEl) {
                var timeText = timeEl.getAttribute('datetime') || timeEl.getAttribute('content') || timeEl.textContent.trim();
                if (timeText) byline = (byline ? byline + ' \u00b7 ' : '') + timeText.substring(0, 10);
            }
    
            return JSON.stringify({
                success: true,
                title: title || siteName,
                content: contentHtml,
                textContent: textContent,
                siteName: siteName,
                byline: byline
            });
        } catch(err) {
            return JSON.stringify({ success: false, error: err.message });
        }
    })();

`;

// -- 使用隐藏浏览器窗口加载页面并提取正文 --
async function fetchAndExtract(url) {
    return new Promise((resolve) => {
        const win = new BrowserWindow({
            width: 1366,
            height: 768,
            show: false,
            webPreferences: {
                images: false,
                javascript: true,
                webSecurity: true,
                contextIsolation: false,
                nodeIntegration: false
            }
        });

        let settled = false;
        const timer = setTimeout(() => {
            if (!settled) {
                settled = true;
                try { win.close(); } catch {}
                resolve({ success: false, error: '\u9875\u9762\u52a0\u8f7d\u8d85\u65f6', url });
            }
        }, FETCH_TIMEOUT);

        function finish(result) {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            try { win.close(); } catch {}
            resolve(result);
        }

        win.webContents.on('did-finish-load', async () => {
            try {
                const currentUrl = win.webContents.getURL();
                if (currentUrl.startsWith('chrome-error://')) {
                    finish({ success: false, error: '\u65e0\u6cd5\u8bbf\u95ee\u8be5\u9875\u9762', url });
                    return;
                }

                // 等待 JS 渲染
                await new Promise(r => setTimeout(r, 2000));

                const json = await win.webContents.executeJavaScript(EXTRACT_SCRIPT);
                let result;
                try {
                    result = JSON.parse(json);
                    result.url = currentUrl || url;
                } catch {
                    result = { success: false, error: '\u63d0\u53d6\u811a\u672c\u6267\u884c\u5931\u8d25', url: currentUrl || url };
                }
                finish(result);
            } catch (err) {
                finish({ success: false, error: err.message, url });
            }
        });

        win.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
            finish({ success: false, error: errorDescription || '\u9875\u9762\u52a0\u8f7d\u5931\u8d25', url });
        });

        win.loadURL(url);
    });
}

module.exports = { fetchAndExtract };
