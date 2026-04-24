# llm generated tool func, created Wed Apr 15 13:08:10 2026

def toolkit_gettime() -> dict:
    import datetime
    now = datetime.datetime.now()
    return {
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "date_str": now.strftime("%Y-%m-%d"),
        "datetime_str": now.strftime("%Y-%m-%d %H:%M:%S")
    }


def meta_toolkit_gettime() -> dict:
    return {"type": "function", "function": {"name": "toolkit_gettime", "description": "获取当前的日期和时间，返回包含年月日等信息的字典", "parameters": {"type": "object", "properties": {}, "required": []}}}
