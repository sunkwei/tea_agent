#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2025-01-20 gen by Claude, news_CSI300
新华网新闻 + 沪深300指数定时抓取

功能:
  - 9:00 从新华网(时政/国际/财经)各抓取<=20条新闻 -> SQLite
  - 9:00-15:00 每10分钟从新浪抓沪深300指数 -> SQLite
  - 启动时根据当前时间自动判断行为

依赖: pip install requests beautifulsoup4
"""
import re, time, sqlite3, logging
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DB_PATH = Path(__file__).parent / "news_csi300.db"
LOG_PATH = Path(__file__).parent / "news_CSI300.log"

CHANNELS = {
    "时政": "https://www.news.cn/politics/",
    "国际": "https://www.news.cn/world/",
    "财经": "https://www.news.cn/fortune/index.htm",
}
SINA_INDEX_URL = "https://hq.sinajs.cn/list=sh000300"
MAX_NEWS_PER_CHANNEL = 20
INDEX_INTERVAL_MIN = 10
NEWS_H, NEWS_M = 9, 0
IDX_START_H, IDX_START_M = 9, 0
IDX_END_H, IDX_END_M = 15, 0
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
SINA_HEADERS = {**HEADERS, "Referer": "https://finance.sina.com.cn/"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        channel TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT DEFAULT '',
        url TEXT DEFAULT '',
        rank INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(date, channel, url)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS index_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        price REAL,
        change_amt REAL,
        change_pct REAL,
        volume REAL,
        amount REAL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(date, time)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_date ON news(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_news_channel ON news(channel)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_index_date ON index_data(date)")
    conn.commit()
    conn.close()
    logger.info(f"DB ready: {DB_PATH}")

def save_news(date_str, channel, items):
    if not items:
        return 0
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    saved = 0
    for item in items:
        try:
            c.execute("INSERT OR IGNORE INTO news (date,channel,title,summary,url,rank) VALUES (?,?,?,?,?,?)",
                (date_str, channel, item.get("title",""), item.get("summary",""), item.get("url",""), item.get("rank",0)))
            if c.rowcount > 0:
                saved += 1
        except Exception as e:
            logger.error(f"save news err: {e}")
    conn.commit()
    conn.close()
    logger.info(f"[{channel}] saved {saved}/{len(items)}")
    return saved

def save_index(date_str, time_str, data):
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO index_data (date,time,price,change_amt,change_pct,volume,amount) VALUES (?,?,?,?,?,?,?)",
            (date_str, time_str, data.get("price"), data.get("change_amt"), data.get("change_pct"), data.get("volume"), data.get("amount")))
        if c.rowcount > 0:
            logger.info(f"index saved: {date_str} {time_str} price={data.get('price')}")
    except Exception as e:
        logger.error(f"save index err: {e}")
    finally:
        conn.commit()
        conn.close()

def news_fetched_today(date_str):
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM news WHERE date=?", (date_str,))
    n = c.fetchone()[0]
    conn.close()
    return n > 0

def fetch_xinhua_channel(channel, url, max_items=20):
    logger.info(f"fetching [{channel}]: {url}")
    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code != 200:
            logger.error(f"[{channel}] HTTP {resp.status_code}")
            return items
        soup = BeautifulSoup(resp.text, "html.parser")
        candidates = []
        for selector in ["ul.newsList li", "div.news-list li", "div.newsList li", "ul.list li", "div.listWrap li", "div.content ul li"]:
            try:
                lis = soup.select(selector)
                if lis:
                    for li in lis:
                        a_tag = li.find("a", href=True)
                        if a_tag and a_tag.get_text(strip=True):
                            title = a_tag.get_text(strip=True)
                            href = a_tag["href"]
                            if not href.startswith("http"):
                                href = "https://www.news.cn" + href
                            summary_el = li.find(["p", "span"], class_=re.compile(r"des|summary|abstract|intro", re.I))
                            summary = summary_el.get_text(strip=True) if summary_el else title
                            candidates.append({"title": title, "summary": summary, "url": href})
                    break
            except Exception:
                continue
        if not candidates:
            for a_tag in soup.find_all("a", href=True):
                title = a_tag.get_text(strip=True)
                href = a_tag["href"]
                if len(title) >= 8 and "新闻" not in title and "更多" not in title:
                    if re.search(r"(news\.cn|xinhuanet\.com)", href) or href.startswith("/"):
                        if not href.startswith("http"):
                            href = "https://www.news.cn" + href
                        candidates.append({"title": title, "summary": title, "url": href})
        seen = set()
        for item in candidates:
            key = item["url"]
            if key not in seen:
                seen.add(key)
                items.append(item)
            if len(items) >= max_items:
                break
        for i, item in enumerate(items):
            item["rank"] = i + 1
        logger.info(f"[{channel}] got {len(items)} items")
    except Exception as e:
        logger.error(f"[{channel}] fetch error: {e}")
    return items

def fetch_index():
    logger.info("fetching CSI300 index...")
    try:
        resp = requests.get(SINA_INDEX_URL, headers=SINA_HEADERS, timeout=10)
        resp.encoding = "gbk"
        text = resp.text
        m = re.search(r'"([^"]*)"', text)
        if not m:
            logger.error("index parse fail: no quoted data")
            return None
        parts = m.group(1).split(",")
        if len(parts) < 6:
            logger.error(f"index parse fail: only {len(parts)} fields")
            return None
        # Sina CSI300 format: [0]名称 [1]昨收 [2]今开 [3]当前价 [4]最高 [5]最低 ...
        prev_close = float(parts[1]) if parts[1] else None
        cur_price  = float(parts[3]) if parts[3] else None
        data = {
            "price": cur_price,
            "change_amt": round(cur_price - prev_close, 4) if cur_price and prev_close else None,
            "change_pct": round((cur_price - prev_close) / prev_close * 100, 4) if cur_price and prev_close else None,
            "volume": float(parts[8]) if len(parts) > 8 and parts[8] else None,
            "amount": float(parts[9]) if len(parts) > 9 and parts[9] else None,
        }
        logger.info(f"CSI300: price={data['price']}, chg={data['change_pct']}%")
        return data
    except Exception as e:
        logger.error(f"fetch index error: {e}")
        return None

def fetch_all_news():
    today = datetime.now().strftime("%Y-%m-%d")
    if news_fetched_today(today):
        logger.info(f"news already fetched for {today}, skip")
        return
    logger.info(f"=== start fetching news for {today} ===")
    total = 0
    for channel, url in CHANNELS.items():
        items = fetch_xinhua_channel(channel, url, MAX_NEWS_PER_CHANNEL)
        if items:
            n = save_news(today, channel, items)
            total += n
        time.sleep(2)
    logger.info(f"=== news fetch done: {total} total ===")

def next_aligned_minute(interval=INDEX_INTERVAL_MIN):
    now = datetime.now()
    mins = now.minute // interval * interval + interval
    if mins >= 60:
        target = now.replace(hour=now.hour+1, minute=0, second=0, microsecond=0)
    else:
        target = now.replace(minute=mins, second=0, microsecond=0)
    return target

def is_index_time():
    now = datetime.now()
    start = now.replace(hour=IDX_START_H, minute=IDX_START_M, second=0, microsecond=0)
    end = now.replace(hour=IDX_END_H, minute=IDX_END_M, second=0, microsecond=0)
    return start <= now <= end

def run_index_loop():
    logger.info("index loop started (9:00-15:00, every 10min)")
    while True:
        now = datetime.now()
        if now.hour > IDX_END_H or (now.hour == IDX_END_H and now.minute >= IDX_END_M):
            logger.info("index time ended (>=15:00)")
            break
        data = fetch_index()
        if data:
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M")
            save_index(date_str, time_str, data)
        target = next_aligned_minute(INDEX_INTERVAL_MIN)
        wait_sec = (target - datetime.now()).total_seconds()
        if wait_sec > 0:
            logger.info(f"next index fetch at {target.strftime('%H:%M')}, sleeping {wait_sec:.0f}s")
            time.sleep(wait_sec)
        else:
            time.sleep(30)

def main():
    logger.info("=" * 50)
    logger.info("news_CSI300 starting...")
    logger.info("=" * 50)
    init_db()
    now = datetime.now()
    today_9am = now.replace(hour=NEWS_H, minute=NEWS_M, second=0, microsecond=0)
    today_3pm = now.replace(hour=IDX_END_H, minute=IDX_END_M, second=0, microsecond=0)
    logger.info(f"current time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if now < today_9am:
        wait_sec = (today_9am - now).total_seconds()
        logger.info(f"before 9:00, sleeping {wait_sec:.0f}s until 9:00...")
        time.sleep(wait_sec)
        fetch_all_news()
        run_index_loop()
    elif today_9am <= now <= today_3pm:
        logger.info("in trading window (9:00-15:00)")
        fetch_all_news()
        run_index_loop()
    else:
        logger.info("after 15:00, news only")
        fetch_all_news()
    logger.info("news_CSI300 finished.")

if __name__ == "__main__":
    main()
