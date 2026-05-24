"""
# @2026-05-27 gen by Tea Agent, 子Agent汇报工具

toolkit_sub_agent_report: 子Agent向主Agent汇报进度和结果的工具。
子Agent可以用此工具向主Agent发送中间结果或请求帮助。

toolkit_sub_agent_status: 查询所有子Agent状态的工具。
"""

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger("toolkit.sub_agent")

_sub_agent_reports: Dict[str, List[str]] = {}
_sub_agent_statuses: Dict[str, str] = {}


def toolkit_sub_agent_report(
    agent_name: str = "",
    report_type: str = "progress",
    message: str = "",
) -> str:
    """
    子Agent向主Agent汇报进度、中间结果或问题。

    Args:
        agent_name: 子Agent名称
        report_type: 报告类型: "progress"(进度), "result"(中间结果), "issue"(问题), "done"(完成)
        message: 报告内容

    Returns:
        确认信息
    """
    if not agent_name:
        return "❌ 必须提供 agent_name"
    
    if not message:
        return "❌ 必须提供 message"
    
    if agent_name not in _sub_agent_reports:
        _sub_agent_reports[agent_name] = []
    
    report_entry = f"[{report_type}] {message}"
    _sub_agent_reports[agent_name].append(report_entry)
    _sub_agent_statuses[agent_name] = report_type
    
    logger.info(f"子Agent报告 [{agent_name}][{report_type}]: {message[:100]}")
    
    return f"✅ 报告已记录 [{agent_name}][{report_type}]"


def toolkit_sub_agent_status(
    agent_name: str = "",
) -> str:
    """
    查询所有子Agent或指定子Agent的状态。

    Args:
        agent_name: 子Agent名称。为空时返回所有Agent状态。

    Returns:
        状态信息文本
    """
    if agent_name:
        if agent_name in _sub_agent_statuses:
            status = _sub_agent_statuses[agent_name]
            reports = _sub_agent_reports.get(agent_name, [])
            last_report = reports[-1] if reports else "无"
            return f"Agent '{agent_name}': 状态={status}, 最新报告={last_report[:200]}"
        else:
            return f"Agent '{agent_name}': 无记录"
    
    if not _sub_agent_statuses:
        return "当前无活跃的子Agent报告"
    
    lines = ["子Agent状态汇总:"]
    for name, status in _sub_agent_statuses.items():
        reports = _sub_agent_reports.get(name, [])
        last = reports[-1][:100] if reports else "无"
        lines.append(f"  - {name}: [{status}] {last}")
    
    return "\n".join(lines)


def clear_sub_agent_reports(agent_name: str = ""):
    """
    清除子Agent报告记录。

    Args:
        agent_name: 子Agent名称，为空则清除全部
    """
    if agent_name:
        _sub_agent_reports.pop(agent_name, None)
        _sub_agent_statuses.pop(agent_name, None)
    else:
        _sub_agent_reports.clear()
        _sub_agent_statuses.clear()



def meta_toolkit_sub_agent_report() -> dict:
    """
    toolkit_sub_agent_report 的元数据

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_sub_agent_report",
            "description": (
                "子Agent向主Agent汇报进度、中间结果或问题。"
                "子Agent应定期使用此工具汇报状态。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "子Agent名称"
                    },
                    "report_type": {
                        "type": "string",
                        "enum": ["progress", "result", "issue", "done"],
                        "description": "报告类型: progress=进度更新, result=中间结果, issue=遇到的问题, done=任务完成"
                    },
                    "message": {
                        "type": "string",
                        "description": "报告内容"
                    }
                },
                "required": ["agent_name", "report_type", "message"],
            },
        },
    }


def meta_toolkit_sub_agent_status() -> dict:
    """
    toolkit_sub_agent_status 的元数据

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_sub_agent_status",
            "description": "查询所有子Agent或指定子Agent的状态和最新报告",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "子Agent名称。为空则返回所有Agent状态。"
                    }
                },
                "required": [],
            },
        },
    }
