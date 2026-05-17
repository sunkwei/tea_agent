import urllib.request
import json

try:
    url = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    
    cards = data.get("data", {}).get("cards", [])
    idx = 0
    for card in cards:
        content = card.get("content", [])
        if isinstance(content, list):
            for item in content:
                # item can be a dict with 'word' or a nested structure
                if isinstance(item, dict):
                    word = item.get("word", "")
                    desc = item.get("desc", "")
                    hot = item.get("hotScore", "")
                    if word:
                        idx += 1
                        tag = ""
                        if item.get("isTop"):
                            tag = "[置顶]"
                        print(f"{idx}. {word} {tag} {desc[:30] if desc else ''}")
                    # check nested content
                    nested = item.get("content", [])
                    if isinstance(nested, list):
                        for n in nested:
                            if isinstance(n, dict) and n.get("word"):
                                idx += 1
                                tag = ""
                                if n.get("isTop"):
                                    tag = "[置顶]"
                                hot_tag = n.get("hotTag", "")
                                print(f"{idx}. {n['word']} {tag} 🔥{hot_tag}" if hot_tag else f"{idx}. {n['word']} {tag}")
                elif isinstance(item, str):
                    idx += 1
                    print(f"{idx}. {item}")
except Exception as e:
    print(f"Error: {e}")
