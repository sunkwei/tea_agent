## llm generated tool func, created Thu May 14 08:57:17 2026
# version: 1.0.0

import urllib.request
import json


def toolkit_ip_location_my():
    """
    先通过 KVS 服务获取本机公网IP（与 toolkit_get_public_ip_my 相同），
    再用 ip-api.com 查询该IP的地理位置。
    返回 city, region, country, lat, lon 等字段。
    """
    ip = None

    # 获取公网IP — 与 toolkit_get_public_ip_my 相同的 KVS 服务
    try:
        req = urllib.request.Request(
            "http://120.26.89.217:9994/kvs?name=qd_public_ip",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ip = resp.read().decode("utf-8").strip()
    except Exception:
        # 回退：用公共IP服务
        try:
            req = urllib.request.Request(
                "https://api.ipify.org?format=json",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                ip = json.loads(resp.read().decode("utf-8"))["ip"]
        except Exception as e:
            return {"success": False, "error": f"无法获取公网IP: {e}"}

    if not ip:
        return {"success": False, "error": "无法获取公网IP"}

    # 用指定 IP 查询 ip-api.com
    url = (
        f"http://ip-api.com/json/{ip}"
        "?fields=status,message,country,countryCode,region,regionName,"
        "city,zip,lat,lon,timezone,isp,query"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("status") == "fail":
            return {"success": False, "error": data.get("message", "Unknown error")}

        return {
            "success": True,
            "ip": data["query"],
            "city": data["city"],
            "region": data["regionName"],
            "country": data["country"],
            "lat": data["lat"],
            "lon": data["lon"],
            "timezone": data["timezone"],
            "isp": data["isp"],
            "location_str": f"{data['city']}, {data['regionName']}, {data['country']}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def meta_toolkit_ip_location_my() -> dict:
    return {"type": "function", "function": {"name": "toolkit_ip_location_my", "description": "根据公网IP查询当前地理位置（城市、区域、国家等）。内部调用'我的公网IP'的KVS服务获取IP，再用ip-api.com查询位置。", "parameters": {"type": "object", "properties": {}, "required": []}}}
