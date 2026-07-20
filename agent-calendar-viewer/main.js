const { app, BrowserWindow, ipcMain, shell, net } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { fetchAndExtract } = require('./reader-view');
const { fetchNews } = require('./news-fetcher');

// ── 配置 ──
const MD_PATH = path.join(os.homedir(), 'Documents', 'agent日历.md');
const IMG_CACHE_PATH = path.join(os.homedir(), 'Documents', 'agent日历-images.json');
const CONTENT_CACHE_PATH = path.join(os.homedir(), 'Documents', 'agent日历-content.json');

let mainWindow = null;
let watcher = null;
let imageCache = {};
let textContentCache = {};

// ── 图片缓存 ──
function loadImageCache() {
    try {
        if (fs.existsSync(IMG_CACHE_PATH)) {
            imageCache = JSON.parse(fs.readFileSync(IMG_CACHE_PATH, 'utf-8'));
        }
    } catch { imageCache = {}; }
}

function saveImageCache() {
    try {
        fs.writeFileSync(IMG_CACHE_PATH, JSON.stringify(imageCache, null, 2), 'utf-8');
    } catch {}
}

// ── 正文缓存 ──
function loadContentCache() {
    try {
        if (fs.existsSync(CONTENT_CACHE_PATH)) {
            textContentCache = JSON.parse(fs.readFileSync(CONTENT_CACHE_PATH, 'utf-8'));
        }
    } catch { textContentCache = {}; }
}

function saveContentCache() {
    try {
        fs.writeFileSync(CONTENT_CACHE_PATH, JSON.stringify(textContentCache, null, 2), 'utf-8');
    } catch {}
}

// ── 抓取 OG 图片 ──
async function fetchOgImage(articleUrl) {
    // 检查缓存
    if (imageCache[articleUrl] !== undefined) {
        return imageCache[articleUrl];
    }

    try {
        const ogUrl = await tryFetchOgImage(articleUrl);
        imageCache[articleUrl] = ogUrl || null;
        saveImageCache();
        return imageCache[articleUrl];
    } catch {
        imageCache[articleUrl] = null;
        saveImageCache();
        return null;
    }
}

function tryFetchOgImage(url) {
    return new Promise((resolve, reject) => {
        const parsed = new URL(url);
        const request = net.request({
            method: 'GET',
            url: url,
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
            }
        });

        let chunks = [];
        let timeout = setTimeout(() => {
            request.abort();
            reject(new Error('Timeout'));
        }, 8000);

        request.on('response', (response) => {
            // 只处理 HTML 响应
            const contentType = response.headers['content-type'] || '';
            if (!contentType.includes('text/html') && !contentType.includes('text/plain')) {
                clearTimeout(timeout);
                request.abort();
                resolve(null);
                return;
            }

            let bodyLen = 0;
            response.on('data', (chunk) => {
                chunks.push(chunk);
                bodyLen += chunk.length;
                // 只需前 100KB 就够解析 meta 标签
                if (bodyLen > 102400) {
                    request.abort();
                }
            });

            response.on('end', () => {
                clearTimeout(timeout);
                try {
                    const html = Buffer.concat(chunks).toString('utf-8');
                    const ogImage = extractOgImage(html, url);
                    resolve(ogImage);
                } catch {
                    resolve(null);
                }
            });

            response.on('error', () => {
                clearTimeout(timeout);
                resolve(null);
            });
        });

        request.on('error', (err) => {
            clearTimeout(timeout);
            resolve(null);
        });

        request.end();
    });
}

function extractOgImage(html, baseUrl) {
    // 方法1: og:image
    let match = html.match(/<meta\s+[^>]*property=["']og:image["'][^>]*content=["']([^"']+)["'][^>]*\/?>/i);
    if (!match) {
        // 属性顺序可能不同
        match = html.match(/<meta\s+[^>]*content=["']([^"']+)["'][^>]*property=["']og:image["'][^>]*\/?>/i);
    }
    if (match) {
        const imgUrl = match[1].trim();
        // 处理相对路径
        if (imgUrl.startsWith('//')) return 'https:' + imgUrl;
        if (imgUrl.startsWith('/')) {
            const u = new URL(baseUrl);
            return u.origin + imgUrl;
        }
        if (imgUrl.startsWith('http')) return imgUrl;
        return null;
    }

    // 方法2: twitter:image
    match = html.match(/<meta\s+[^>]*name=["']twitter:image["'][^>]*content=["']([^"']+)["'][^>]*\/?>/i);
    if (!match) {
        match = html.match(/<meta\s+[^>]*content=["']([^"']+)["'][^>]*name=["']twitter:image["'][^>]*\/?>/i);
    }
    if (match) {
        const imgUrl = match[1].trim();
        if (imgUrl.startsWith('//')) return 'https:' + imgUrl;
        if (imgUrl.startsWith('/')) {
            const u = new URL(baseUrl);
            return u.origin + imgUrl;
        }
        if (imgUrl.startsWith('http')) return imgUrl;
    }

    // 方法3: 第一张图片
    match = html.match(/<img[^>]+src=["']([^"']+)["'][^>]*\/?>/i);
    if (match) {
        const imgUrl = match[1].trim();
        if (imgUrl.startsWith('//')) return 'https:' + imgUrl;
        if (imgUrl.startsWith('/')) {
            const u = new URL(baseUrl);
            return u.origin + imgUrl;
        }
        if (imgUrl.startsWith('http')) return imgUrl;
    }

    return null;
}

// ── Markdown 解析器 ──
function parseAgentCalendar(mdText) {
    const entries = [];
    const dateRegex = /^##\s*📅\s*(\d{4}-\d{2}-\d{2})/m;
    const lines = mdText.split('\n');

    let currentDate = null;
    let currentArticle = null;

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const dateMatch = line.match(dateRegex);
        if (dateMatch) {
            currentDate = dateMatch[1];
            continue;
        }
        const articleMatch = line.match(/^\d+\.\s*\[(.+?)\]\((.+?)\)/);
        if (articleMatch && currentDate) {
            if (currentArticle) entries.push(currentArticle);
            currentArticle = {
                date: currentDate,
                title: articleMatch[1],
                url: articleMatch[2],
                summary: '',
                domain: extractDomain(articleMatch[2])
            };
            continue;
        }
        if (line.trimStart().startsWith('> ') && currentArticle) {
            const summaryLine = line.trimStart().substring(2).trim();
            if (summaryLine && !summaryLine.startsWith('（摘要')) {
                currentArticle.summary += (currentArticle.summary ? '\n' : '') + summaryLine;
            }
            continue;
        }
    }
    if (currentArticle) entries.push(currentArticle);

    const grouped = {};
    for (const entry of entries) {
        if (!grouped[entry.date]) grouped[entry.date] = [];
        grouped[entry.date].push(entry);
    }

    return {
        entries,
        dates: Object.keys(grouped).sort().reverse(),
        grouped
    };
}

function extractDomain(url) {
    try { const u = new URL(url); return u.hostname.replace('www.', ''); }
    catch { return url; }
}

// ── 读取文件 ──
function readCalendar() {
    try {
        if (!fs.existsSync(MD_PATH)) return { error: '文件不存在', path: MD_PATH };
        const mdText = fs.readFileSync(MD_PATH, 'utf-8');
        const data = parseAgentCalendar(mdText);
        data.filePath = MD_PATH;
        return data;
    } catch (err) {
        return { error: err.message, path: MD_PATH };
    }
}

// ── 文件监听 ──
function startWatching() {
    try {
        if (watcher) watcher.close();
        if (!fs.existsSync(MD_PATH)) return;
        watcher = fs.watch(MD_PATH, (eventType) => {
            if (eventType === 'change' && mainWindow) {
                const data = readCalendar();
                mainWindow.webContents.send('calendar-updated', data);
            }
        });
    } catch (e) { console.warn('文件监听启动失败:', e.message); }
}

// ── IPC 处理 ──
ipcMain.handle('read-calendar', () => readCalendar());
ipcMain.handle('open-external', (_, url) => {
    if (url) shell.openExternal(url);
});
ipcMain.handle('fetch-article-content', async (_, url) => {
    if (!url) return { success: false, error: 'No URL provided' };
    // 命中缓存直接返回，避免重新加载
    if (textContentCache[url] !== undefined) {
        return textContentCache[url];
    }
    try {
        const result = await fetchAndExtract(url);
        if (result && result.success) {
            textContentCache[url] = result;
            saveContentCache();
        }
        return result;
    } catch (err) {
        return { success: false, error: err.message, url };
    }
});
ipcMain.handle('fetch-og-image', async (_, url) => {
    return await fetchOgImage(url);
});
ipcMain.handle('get-cached-og-images', () => {
    return imageCache;
});

// ── 新闻 ──
ipcMain.handle('fetch-news', async (_, forceRefresh) => {
    try {
        return await fetchNews(forceRefresh);
    } catch (err) {
        return { success: false, error: err.message };
    }
});

// ── 窗口创建 ──
function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1300,
        height: 850,
        minWidth: 800,
        minHeight: 600,
        title: 'Agent 日历',
        icon: path.join(__dirname, 'icon.png'),
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false
        },
        backgroundColor: '#f5f5f5',
        show: false
    });

    mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        startWatching();
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
        if (watcher) { watcher.close(); watcher = null; }
    });
}

// ── 启动 ──
loadImageCache();
loadContentCache();
app.whenReady().then(() => {
    createWindow();
    // 启动后自动抓取新闻并发送给渲染进程
    fetchNews(false).then(result => {
        if (mainWindow && result.success) {
            mainWindow.webContents.send('news-fetched', result.articles);
        }
    }).catch(() => {});
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});
app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
