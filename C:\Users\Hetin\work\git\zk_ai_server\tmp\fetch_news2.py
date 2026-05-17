import urllib.request
import json

# 百度热搜 API - 更简单的版本
try:
    # Try multiple API endpoints
    apis = [
        "https://top.baidu.com/api/board?platform=wise&tab=realtime",
        "https://tieba.baidu.com/hottopic/api/rank",
    ]
    
    for api in apis:
        try:
            req = urllib.request.Request(api, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            resp = urllib.request.urlopen(req, timeout=8)
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            print(f"API: {api}")
            print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
            print("---")
        except Exception as e:
            print(f"Failed: {api}: {e}")
except Exception as e:
    print(f"Error: {e}")
