import logging

logger = logging.getLogger("toolkit")

"""toolkit_lunar — 公历/农历互转，含天干地支、生肖、节气"""

# ============================================================
# 农历数据表 1900-2100 (经典编码)
# 编码格式 (与 lunar.js / zhdate 一致):
#   bits 0-3:   闰月 (0=无闰月, 1-12=闰几月)
#   bits 4-15:  12个月的日数标志 (bit4=正月, bit15=腊月; 1=30天, 0=29天)
#   bit 16:     闰月天数 (1=30天, 0=29天)
# 每月天数: 29 + ((info >> (4+i)) & 1), i=0..11
# ============================================================
_LUNAR_INFO = [
    0x04bd8,0x04ae0,0x0a570,0x054d5,0x0d260,0x0d950,0x16554,0x056a0,0x09ad0,0x055d2,
    0x04ae0,0x0a5b6,0x0a4d0,0x0d250,0x1d255,0x0b540,0x0d6a0,0x0ada2,0x095b0,0x14977,
    0x04970,0x0a4b0,0x0b4b5,0x06a50,0x06d40,0x1ab54,0x02b60,0x09570,0x052f2,0x04970,
    0x06566,0x0d4a0,0x0ea50,0x06e95,0x05ad0,0x02b60,0x186e3,0x092e0,0x1c8d7,0x0c950,
    0x0d4a0,0x1d8a6,0x0b550,0x056a0,0x1a5b4,0x025d0,0x092d0,0x0d2b2,0x0a950,0x0b557,
    0x06ca0,0x0b550,0x15355,0x04da0,0x0a5b0,0x14573,0x052b0,0x0a9a8,0x0e950,0x06aa0,
    0x0aea6,0x0ab50,0x04b60,0x0aae4,0x0a570,0x05260,0x0f263,0x0d950,0x05b57,0x056a0,
    0x096d0,0x04dd5,0x04ad0,0x0a4d0,0x0d4d4,0x0d250,0x0d558,0x0b540,0x0b6a0,0x195a6,
    0x095b0,0x049b0,0x0a974,0x0a4b0,0x0b27a,0x06a50,0x06d40,0x0af46,0x0ab60,0x09570,
    0x04af5,0x04970,0x064b0,0x074a3,0x0ea50,0x06b58,0x055c0,0x0ab60,0x096d5,0x092e0,
    0x0c960,0x0d954,0x0d4a0,0x0da50,0x07552,0x056a0,0x0abb7,0x025d0,0x092d0,0x0cab5,
    0x0a950,0x0b4a0,0x0baa4,0x0ad50,0x055d9,0x04ba0,0x0a5b0,0x15176,0x052b0,0x0a930,
    0x07954,0x06aa0,0x0ad50,0x05b52,0x04b60,0x0a6e6,0x0a4e0,0x0d260,0x0ea65,0x0d530,
    0x05aa0,0x076a3,0x096d0,0x04afb,0x04ad0,0x0a4d0,0x1d0b6,0x0d250,0x0d520,0x0dd45,
    0x0b5a0,0x056d0,0x055b2,0x049b0,0x0a577,0x0a4b0,0x0aa50,0x1b255,0x06d20,0x0ada0,
    0x14b63,0x09370,0x049f8,0x04970,0x064b0,0x168a6,0x0ea50,0x06b20,0x1a6c4,0x0aae0,
    0x0a2e0,0x0d2e3,0x0c960,0x0d557,0x0d4a0,0x0da50,0x05d55,0x056a0,0x0a6d0,0x055d4,
    0x052d0,0x0a9b8,0x0a950,0x0b4a0,0x0b6a6,0x0ad50,0x055a0,0x0aba4,0x0a5b0,0x052b0,
    0x0b273,0x06930,0x07337,0x06aa0,0x0ad50,0x14b55,0x04b60,0x0a570,0x054e4,0x0d160,
    0x0e968,0x0d520,0x0daa0,0x16aa6,0x056d0,0x04ae0,0x0a9d4,0x0a4d0,0x0d150,0x0f252,
    0x0d520,
]

_LEAP_MONTH_MASK = 0xf          # bits 0-3
_MONTH_BIT_BASE = 4             # month bits start at bit 4
_LEAP_DAYS_BIT = 16             # leap month: 1=30d, 0=29d
_BASE_YEAR = 1900
_BASE_MONTH_DAYS = 29 * 12      # 348

# 天干地支 / 生肖 / 农历月日名称
_TIANGAN = "甲乙丙丁戊己庚辛壬癸"
_DIZHI = "子丑寅卯辰巳午未申酉戌亥"
_SHENGXIAO = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
_LUNAR_MONTHS = "正二三四五六七八九十冬腊"
_LUNAR_DAYS = {
    1:"初一",2:"初二",3:"初三",4:"初四",5:"初五",6:"初六",7:"初七",8:"初八",9:"初九",10:"初十",
    11:"十一",12:"十二",13:"十三",14:"十四",15:"十五",16:"十六",17:"十七",18:"十八",19:"十九",20:"二十",
    21:"廿一",22:"廿二",23:"廿三",24:"廿四",25:"廿五",26:"廿六",27:"廿七",28:"廿八",29:"廿九",30:"三十",
}

# 节气名
_JIEQI_NAMES = [
    "小寒","大寒","立春","雨水","惊蛰","春分","清明","谷雨",
    "立夏","小满","芒种","夏至","小暑","大暑","立秋","处暑",
    "白露","秋分","寒露","霜降","立冬","小雪","大雪","冬至",
]

def _solar_days_in_year(y):
    """Internal: solar days in year.
    
    Args:
        y: Description.
    """
    return 366 if (y % 400 == 0 or (y % 4 == 0 and y % 100 != 0)) else 365

def _solar_days_in_month(y, m):
    """Internal: solar days in month.
    
    Args:
        y: Description.
        m: Description.
    """
    if m == 2:
        return 29 if (y % 400 == 0 or (y % 4 == 0 and y % 100 != 0)) else 28
    return 31 if m in (1,3,5,7,8,10,12) else 30

def _offset_from_base(y, m, d):
    """从 1900-01-31 起的天数偏移 (农历基准日 = 1900 年春节)"""
    days = 0
    for yr in range(_BASE_YEAR, y):
        days += _solar_days_in_year(yr)
    for mo in range(1, m):
        days += _solar_days_in_month(y, mo)
    return days + d - 31

def _lunar_year_info(idx):
    """Internal: lunar year info.
    
    Args:
        idx: Description.
    """
    return _LUNAR_INFO[idx]

def _leap_month(info):
    """Internal: leap month.
    
    Args:
        info: Description.
    """
    return info & _LEAP_MONTH_MASK

def _leap_days(info):
    """Internal: leap days.
    
    Args:
        info: Description.
    """
    return 30 if (info & (1 << _LEAP_DAYS_BIT)) else 29

def _month_days(info, mi):
    """农历月天数, mi=0..11 对应正月~腊月"""
    return 30 if (info & (1 << (_MONTH_BIT_BASE + mi))) else 29

def _lunar_year_total_days(info):
    """农历年总天数"""
    days = _BASE_MONTH_DAYS
    for i in range(12):
        if info & (1 << (_MONTH_BIT_BASE + i)):
            days += 1
    if _leap_month(info):
        days += _leap_days(info)
    return days

def _solar_to_lunar(y, m, d):
    """公历 → 农历 核心算法"""
    offset = _offset_from_base(y, m, d)

    # 找农历年
    idx = 0
    cumulative = 0
    for i in range(len(_LUNAR_INFO)):
        yd = _lunar_year_total_days(_LUNAR_INFO[i])
        if cumulative + yd > offset:
            idx = i
            break
        cumulative += yd
    else:
        idx = len(_LUNAR_INFO) - 1

    lunar_year = _BASE_YEAR + idx
    info = _LUNAR_INFO[idx]
    leap = _leap_month(info)
    remaining = offset - cumulative

    # 在该农历年内定位月日
    is_leap = False
    lm = 0
    ld = 0

    for mi in range(12):
        md = _month_days(info, mi)
        if remaining < md:
            lm = mi + 1
            ld = remaining + 1
            break
        remaining -= md

        # 闰月
        if leap and mi + 1 == leap:
            leap_d = _leap_days(info)
            if remaining < leap_d:
                lm = mi + 1
                ld = remaining + 1
                is_leap = True
                break
            remaining -= leap_d
    else:
        lm = 12
        ld = remaining + 1

    # 天干地支纪年 (农历年起算: 以立春为界，简化用正月初一)
    tg_idx = (lunar_year - 4) % 10
    dz_idx = (lunar_year - 4) % 12
    tgdz = _TIANGAN[tg_idx] + _DIZHI[dz_idx]
    zodiac = _SHENGXIAO[dz_idx]

    return (lunar_year, lm, ld, is_leap, tgdz, zodiac)

# ============================================================
# 公开 API
# ============================================================

def toolkit_lunar(date_str: str = "", action: str = "solar_to_lunar") -> str:
    """公历 ↔ 农历转换工具。零外部依赖，覆盖 1900-2100 年。

    Args:
        date_str: 日期 'YYYY-MM-DD'，不填默认今天
        action:
            - 'solar_to_lunar': 公历→农历 (默认)
            - 'lunar_to_solar': 农历→公历 ('YYYY-MM-DD,L', L=1闰月,0非闰)
            - 'today': 今日农历 + 节气

    Returns:
        JSON: {solar_date, lunar_date, lunar_year/month/day, is_leap_month, tiangan_dizhi, zodiac, nearest_jieqi...}
    """
    logger.info(f"toolkit_lunar called: date_str={date_str!r}, action={action!r}")

    import json, datetime

    if action in ("solar_to_lunar", "today"):
        if not date_str:
            now = datetime.date.today()
            y, m, d = now.year, now.month, now.day
        else:
            try:
                parts = date_str.strip().split("-")
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            except (ValueError, IndexError):
                return json.dumps({"error": f"日期格式错误: {date_str}，应为 YYYY-MM-DD"}, ensure_ascii=False)

        if y < 1900 or y > 2100:
            return json.dumps({"error": f"年份超出 (1900-2100): {y}"}, ensure_ascii=False)
        try:
            datetime.date(y, m, d)
        except ValueError:
            return json.dumps({"error": f"无效日期: {date_str}"}, ensure_ascii=False)

        ly, lm, ld, is_leap, tgdz, zodiac = _solar_to_lunar(y, m, d)

        month_name = ("闰" if is_leap else "") + _LUNAR_MONTHS[lm - 1] + "月"
        day_name = _LUNAR_DAYS.get(ld, str(ld))

        result = {
            "solar_date": f"{y}-{m:02d}-{d:02d}",
            "lunar_date": f"{tgdz}年 {month_name}{day_name}",
            "lunar_year": ly,
            "lunar_month": lm,
            "lunar_day": ld,
            "is_leap_month": is_leap,
            "tiangan_dizhi": tgdz,
            "zodiac": zodiac,
        }

        if action == "today":
            # 简化版节气
            terms = _solar_terms(y)
            for idx, (tm, td) in enumerate(terms):
                tdate = datetime.date(y, tm, td)
                diff = (datetime.date(y, m, d) - tdate).days
                if 0 <= diff < 16:
                    result["nearest_jieqi"] = _JIEQI_NAMES[idx]
                    result["jieqi_date"] = f"{y}-{tm:02d}-{td:02d}"
                    break
                elif -16 < diff < 0:
                    ji = (idx - 1) % 24 if idx > 0 else 23
                    result["nearest_jieqi"] = _JIEQI_NAMES[ji]
                    prev = terms[ji] if idx > 0 else terms[23]
                    result["jieqi_date"] = f"{y}-{prev[0]:02d}-{prev[1]:02d}"
                    break

        return json.dumps(result, ensure_ascii=False, indent=2)

    elif action == "lunar_to_solar":
        if not date_str:
            return json.dumps({"error": "lunar_to_solar 需要 date_str, 格式 'YYYY-MM-DD,L' (L=1闰月)"}, ensure_ascii=False)
        try:
            parts = date_str.strip().split(",")
            ymd = parts[0].split("-")
            ly, lm, ld = int(ymd[0]), int(ymd[1]), int(ymd[2])
            want_leap = len(parts) > 1 and parts[1].strip() == "1"
        except (ValueError, IndexError):
            return json.dumps({"error": f"格式: 'YYYY-MM-DD,L'"}, ensure_ascii=False)

        found = None
        for sy in range(ly - 1, ly + 2):
            for sm in range(1, 13):
                for sd in range(1, 32):
                    try:
                        datetime.date(sy, sm, sd)
                    except ValueError:
                        continue
                    rly, rlm, rld, rleap, _, _ = _solar_to_lunar(sy, sm, sd)
                    if rly == ly and rlm == lm and rld == ld and rleap == want_leap:
                        found = (sy, sm, sd)
                        break
                if found:
                    break
            if found:
                break

        if found:
            return json.dumps({"solar_date": f"{found[0]}-{found[1]:02d}-{found[2]:02d}"}, ensure_ascii=False, indent=2)
        return json.dumps({"error": "未找到对应公历日期"}, ensure_ascii=False)

    return json.dumps({"error": f"未知 action: {action}"}, ensure_ascii=False)

def _solar_terms(y):
    """简化节气计算 (1900-01-06 小寒起，每 15.2184 天一个节气)"""
    base_days = 5  # 1900-01-06 → Jan 1 + 5
    total_days = 0
    for yr in range(1900, y):
        total_days += _solar_days_in_year(yr)
    total_days += base_days

    terms = []
    for i in range(24):
        d_offset = int(total_days + i * 15.2184 + 0.5)
        d = d_offset
        for yr in range(1900, y):
            d -= _solar_days_in_year(yr)
        mth = 1
        while d >= _solar_days_in_month(y, mth):
            d -= _solar_days_in_month(y, mth)
            mth += 1
        terms.append((mth, d + 1))
    return terms

def meta_toolkit_lunar() -> dict:
    """Meta toolkit lunar."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_lunar",
            "description": "公历农历转换工具。输入公历日期返回农历（天干地支、生肖）。也支持农历→公历反查。零外部依赖，覆盖 1900-2100 年。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_str": {
                        "type": "string",
                        "description": "日期 YYYY-MM-DD，不填默认今天。农历→公历时: 'YYYY-MM-DD,L'"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["solar_to_lunar", "lunar_to_solar", "today"],
                        "description": "solar_to_lunar=公历→农历, lunar_to_solar=农历→公历, today=今日+节气"
                    }
                },
                "required": []
            }
        }
    }
