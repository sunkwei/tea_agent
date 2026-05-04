"""Skill: 通用工具 — 时间日期（始终激活）"""
SKILL_MANIFEST = {
    "name": "utility",
    "version": "1.0.0",
    "description": "通用工具：获取当前时间、计算日期差 — 默认激活",
    "tools": [
        "toolkit_gettime",
        "toolkit_date_diff",
    ],
    "activation": "auto",  # 虽然标记 auto，但初始化时默认激活
    "dependencies": [],
    "trigger_words": [
        "时间", "日期", "几号", "星期", "天数",
        "多少天", "今天", "明天", "昨天",
    ],
}
