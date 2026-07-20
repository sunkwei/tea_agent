/* ════════════════════════════════════════════════
   News Fetcher — 多源 RSS/Atom 新闻抓取模块
   使用 cheerio 解析 XML，支持 RSS 2.0 和 Atom 格式
   ════════════════════════════════════════════════ */

const { net } = require('electron');
const cheerio = require('cheerio');
const fs = require('fs');
const path = require('path');

const CACHE_PATH = path.join(require('os').homedir(), 'Documents', 'agent日历-news.json');
const CACHE_TTL = 30 * 60 * 1000; // 30 分钟缓存有效期
const MAX_NEWS = 15;

// ── 新闻源配置 ──
// 每个源最多取 n 条，合并后截取 MAX_NEWS 条
const NEWS_SOURCES = [
    {
        name: 'V2EX',
        url: 'https://www.v2ex.com/feed',
        lang: 'zh',
        format: 'atom',    // Atom: <entry><title><link><summary><published>
        max: 5,
    },
    {
        name: '36氪',
        url: 'https://36kr.com/feed',
        lang: 'zh',
        format: 'rss',     // RSS 2.0: <item><title><link><description><pubDate>
        max: 5,
    },
    {
        name: '阮一峰',
        url: 'https://feeds.feedburner.com/ruanyifeng',
        lang: 'zh',
        format: 'atom',
        max: 3,
    },
    {
        name: 'Hacker News',
        url: 'https://hnrss.org/frontpage?count=5',
        lang: 'en',
        format: 'rss',
        max: 5,
    },
    {
        name: '博客园',
        url: 'https://feed.cnblogs.com/blog/category/1/rss',
        lang: 'zh',
        format: 'rss',
        max: 3,
    },
];

// ── 工具函数 ──

function parseDate(str) {
    if (!str) return new Date(0);
    const d = new Date(str);
    return isNaN(d.getTime()) ? new Date(0) : d;
}

function stripHtml(str) {
    if (!str) return '';
    return str.replace(/<[^>]*>/g, '').replace(/&[^;]+;/g, ' ').replace(/\s+/g, ' ').trim();
}

function truncate(str, maxLen) {
    return str.length > maxLen ? str.substring(0, maxLen) + '…' : str;
}

// ── 解析 Atom 条目 ──
function parseAtomEntry($, entry) {
    const getText = (sel) => $(entry).find(sel).first().text().trim();

    const title = getText('title');
    // Atom link: <link href="..." rel="alternate"/>
    let link = '';
    $(entry).find('link').each((i, el) => {
        const rel = $(el).attr('rel') || 'alternate';
        if (rel === 'alternate' || !link) {
            link = $(el).attr('href') || '';
        }
    });
    const summary = stripHtml(getText('summary') || getText('content'));
    const dateStr = getText('published') || getText('updated');
    const date = parseDate(dateStr);

    return { title, link, summary: truncate(summary, 300), date, source: '' };
}

// ── 解析 RSS 2.0 条目 ──
function parseRssItem($, item) {
    const getText = (sel) => $(item).find(sel).first().text().trim();

    const title = getText('title');
    const link = getText('link');
    const summary = stripHtml(getText('description'));
    const dateStr = getText('pubDate');
    const date = parseDate(dateStr);

    return { title, link, summary: truncate(summary, 300), date, source: '' };
}

// ── 抓取单个源 ──
function fetchSource(source) {
    return new Promise((resolve) => {
        const articles = [];
        const req = net.request({
            method: 'GET',
            url: source.url,
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/xml,text/xml,*/*',
            }
        });

        let chunks = [];
        let timer = setTimeout(() => {
            req.destroy();
            resolve([]);
        }, 15000);

        req.on('response', (res) => {
            if (res.statusCode !== 200) {
                clearTimeout(timer);
                req.destroy();
                resolve([]);
                return;
            }
            res.on('data', d => chunks.push(d));
            res.on('end', () => {
                clearTimeout(timer);
                try {
                    const xml = Buffer.concat(chunks).toString('utf-8');
                    const $ = cheerio.load(xml, { xmlMode: true });
                    const sourceName = source.name;

                    if (source.format === 'atom') {
                        $('entry').each((i, el) => {
                            if (i >= source.max) return false;
                            const item = parseAtomEntry($, el);
                            item.source = sourceName;
                            if (item.title && item.link) articles.push(item);
                        });
                    } else {
                        $('item').each((i, el) => {
                            if (i >= source.max) return false;
                            const item = parseRssItem($, el);
                            item.source = sourceName;
                            if (item.title && item.link) articles.push(item);
                        });
                    }
                } catch (e) {
                    // 解析失败跳过
                }
                resolve(articles);
            });
        });
        req.on('error', () => {
            clearTimeout(timer);
            resolve([]);
        });
        req.end();
    });
}

// ── 加载缓存 ──
function loadCache() {
    try {
        if (fs.existsSync(CACHE_PATH)) {
            const data = JSON.parse(fs.readFileSync(CACHE_PATH, 'utf-8'));
            const age = Date.now() - (data.fetched_at || 0);
            if (age < CACHE_TTL && data.articles && data.articles.length > 0) {
                return data.articles;
            }
        }
    } catch {}
    return null;
}

// ── 保存缓存 ──
function saveCache(articles) {
    try {
        fs.writeFileSync(CACHE_PATH, JSON.stringify({
            fetched_at: Date.now(),
            articles: articles,
        }, null, 2), 'utf-8');
    } catch {}
}

// ── 公开 API ──
async function fetchNews(forceRefresh = false) {
    // 检查缓存
    if (!forceRefresh) {
        const cached = loadCache();
        if (cached) return { success: true, articles: cached, cached: true };
    }

    // 并行抓取所有源
    const results = await Promise.all(NEWS_SOURCES.map(src => fetchSource(src)));

    // 合并、去重、排序
    const seen = new Set();
    const all = [];
    for (const articles of results) {
        for (const item of articles) {
            const key = item.title.toLowerCase().trim();
            if (!seen.has(key) && item.link) {
                seen.add(key);
                all.push(item);
            }
        }
    }

    // 按日期降序排列
    all.sort((a, b) => b.date - a.date);

    // 截取前 MAX_NEWS 条
    const top = all.slice(0, MAX_NEWS);

    if (top.length > 0) {
        saveCache(top);
    }

    return {
        success: true,
        articles: top,
        total_fetched: results.reduce((s, a) => s + a.length, 0),
        cached: false,
    };
}

module.exports = { fetchNews, NEWS_SOURCES };
