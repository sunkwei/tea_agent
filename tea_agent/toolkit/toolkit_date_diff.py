## llm generated tool func, created Thu Apr 16 20:30:30 2026

def toolkit_date_diff(start_date: str, end_date: str = None) -> dict:
    """
    计算两个日期之间的天数差。
    
    参数:
        start_date: 开始日期，格式YYYY-MM-DD
        end_date: 结束日期，格式YYYY-MM-DD，不填则默认为今天
    
    返回:
        dict: 包含天数差和详细信息的字典
    """
    from datetime import datetime, date
    
    try:
        # 解析开始日期
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        
        # 解析结束日期（默认为今天）
        if end_date:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            end = date.today()
        
        # 计算天数差
        delta = end - start
        days = delta.days
        
        # 计算详细信息
        weeks = days // 7
        remaining_days = days % 7
        
        # 判断是过去还是未来
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
    return {"type": "function", "function": {"description": "计算两个日期之间的天数差。返回天数、周数等详细信息。", "name": "toolkit_date_diff", "parameters": {"properties": {"end_date": {"description": "结束日期，格式YYYY-MM-DD，不填则默认为今天", "type": "string"}, "start_date": {"description": "开始日期，格式YYYY-MM-DD", "type": "string"}}, "required": ["start_date"], "type": "object"}}}
