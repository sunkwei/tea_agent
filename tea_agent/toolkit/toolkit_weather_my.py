# version: 1.0.1

import json
import urllib.request
from datetime import datetime, timedelta, timezone

# WMO 天气码中文映射
_WMO = {
    0: "晴", 1: "晴", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "中毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "小阵雨", 81: "中阵雨", 82: "大阵雨",
    95: "雷暴", 96: "雷暴+小冰雹", 99: "雷暴+大冰雹",
}


def toolkit_weather_my(forecast_days=7):
    """
    获取当前所在地的天气预报。
    1. 通过 KVS 获取公网IP → ip-api 定位 → 经纬度+时区
    2. 用 Open-Meteo 免费 API 获取天气
    返回含当前时间（定位时区）和预报。
    """
    now_utc = datetime.now(timezone.utc)

    # --- 第一步：获取位置 ---
    ip = None
    try:
        req = urllib.request.Request(
            "http://120.26.89.217:9994/kvs?name=qd_public_ip",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ip = resp.read().decode("utf-8").strip()
    except Exception:
        pass

    if not ip:
        return {"success": False, "error": "无法获取公网IP"}

    geo_url = (
        f"http://ip-api.com/json/{ip}"
        "?fields=status,message,city,regionName,country,lat,lon,timezone"
    )
    try:
        req = urllib.request.Request(geo_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            geo = json.loads(resp.read().decode("utf-8"))
        if geo.get("status") == "fail":
            return {"success": False, "error": geo.get("message", "定位失败")}
    except Exception as e:
        return {"success": False, "error": f"定位失败: {e}"}

    lat, lon = geo["lat"], geo["lon"]
    tz_name = geo.get("timezone", "Asia/Shanghai")
    location = f"{geo['city']}, {geo['regionName']}, {geo['country']}"

    # 计算定位时区的当前时间
    tz_offsets = {
        "Asia/Shanghai": 8, "Asia/Tokyo": 9, "Asia/Seoul": 9,
        "Asia/Kolkata": 5.5, "Asia/Bangkok": 7, "Asia/Dubai": 4,
        "Europe/London": 0, "Europe/Paris": 1, "Europe/Berlin": 1,
        "Europe/Moscow": 3, "America/New_York": -5, "America/Chicago": -6,
        "America/Denver": -7, "America/Los_Angeles": -8,
        "Pacific/Auckland": 12, "Australia/Sydney": 10,
    }
    offset_hours = tz_offsets.get(tz_name, 8)
    now_local = now_utc + timedelta(hours=offset_hours)

    # --- 第二步：获取天气 ---
    days = max(1, min(forecast_days or 7, 7))
    weather_url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        f"wind_speed_10m_max,precipitation_sum"
        f"&timezone={tz_name}"
        f"&forecast_days={days}"
    )

    try:
        req = urllib.request.Request(weather_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            w = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "error": f"天气API请求失败: {e}"}

    daily = w.get("daily", {})
    if not daily:
        return {"success": False, "error": "天气数据为空"}

    forecast = []
    for i, date in enumerate(daily.get("time", [])):
        forecast.append({
            "date": date,
            "weather": _WMO.get(daily["weather_code"][i], str(daily["weather_code"][i])),
            "temp_max": daily["temperature_2m_max"][i],
            "temp_min": daily["temperature_2m_min"][i],
            "wind_max": daily["wind_speed_10m_max"][i],
            "rain": daily.get("precipitation_sum", [0] * len(daily["time"]))[i],
        })

    return {
        "success": True,
        "ip": ip,
        "location": location,
        "lat": lat,
        "lon": lon,
        "timezone": tz_name,
        "now": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now_local.weekday()],
        "forecast_days": days,
        "forecast": forecast,
    }


def meta_toolkit_weather_my() -> dict:
    return {"type": "function", "function": {"name": "toolkit_weather_my", "description": "查询当前所在地的天气。先通过IP定位获取经纬度，再用Open-Meteo免费API获取7天天气预报。返回含当前时间、时区、每日预报。", "parameters": {"type": "object", "properties": {"forecast_days": {"type": "integer", "description": "预报天数，1-7，默认7"}}, "required": []}}}
