
import logging

logger = logging.getLogger("toolkit")

def toolkit_date_diff(start_date: str, end_date: str = None) -> dict:
    """
    计算两个日期之间的天数差。

    Args:
        start_date (str): Description.
        end_date (str): Description.

    Returns:
        dict: Description.
    """
    logger.info(f"toolkit_date_diff called: start_date={start_date!r}, end_date={end_date!r}")

    from datetime import datetime, date
    
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        
        if end_date:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            end = date.today()
        
        delta = end - start
        days = delta.days
        
        weeks = days // 7
        remaining_days = days % 7
        
        if days >= 0:
            direction = "过去"
        else:
            direction = "未来"
            days = abs(days)
            weeks = days // 7
            remaining_days = days % 7
        
        return {
            "start_date": start_date,
            "end_date": end.strftime("%Y-%m-%d"),
            "days": days,
            "weeks": weeks,
            "remaining_days": remaining_days,
            "direction": direction,
            "summary": f"从 {start_date} 到 {end.strftime('%Y-%m-%d')} 已经{direction}了 {days} 天（约 {weeks} 周 {remaining_days} 天）"
        }
    except Exception as e:
        return {"error": f"日期计算错误: {str(e)}"}

def meta_toolkit_date_diff() -> dict:
    """
    Meta toolkit date diff

    Returns:
        dict: Description.
    """
    return {"type": "function", "function": {"description": "计算两个日期之间的天数差。返回天数、周数等详细信息。", "name": "toolkit_date_diff", "parameters": {"properties": {"end_date": {"description": "结束日期，格式YYYY-MM-DD，不填则默认为今天", "type": "string"}, "start_date": {"description": "开始日期，格式YYYY-MM-DD", "type": "string"}}, "required": ["start_date"], "type": "object"}}}
