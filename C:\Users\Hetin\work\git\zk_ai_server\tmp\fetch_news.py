import urllib.request
import re
import json

# Try multiple sources
results = []

# 1. Try Baidu hot search API
try:
    url = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    cards = data.get("data", {}).get("cards", [])
    for card in cards:
        for item in card.get("content", []):
            title = item.get("word") or item.get("query")
            hot_score = item.get("hotScore", "")
            desc = item.get("desc", "")
            if title:
                results.append(f"{title}  {desc}  {hot_score}")
    print("=== 百度热搜 ===")
    for i, r in enumerate(results[:15], 1):
        print(f"{i}. {r}")
except Exception as e:
    print(f"[百度] 失败: {e}")

# 2. Try Tencent news
if not results:
    try:
        url = "https://i.news.qq.com/trpc.qqnews_web.kv_srv.kv_srv_http_proxy/list?sub_srv_id=topnews&size=15"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        newslist = data.get("data", {}).get("list", [])
        print("=== 腾讯新闻 ===")
        for i, item in enumerate(newslist[:15], 1):
            print(f"{i}. {item.get('title', '')}")
    except Exception as e:
        print(f"[腾讯] 也失败: {e}")
