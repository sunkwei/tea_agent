## llm generated tool func, created Thu Jul 16 22:00:23 2026
# version: 1.0.0

"""
toolkit_categorize_tools — 工具分类与精简模式管理。

借鉴 opencode/codex 的最小化工具集理念，将 75+ 工具按场景类别组织。
支持 list（列出分类）、recommend（按任务推荐工具）、compact（返回精简工具列表）。

用法:
    toolkit_categorize_tools(action="list")          # 列出所有分类
    toolkit_categorize_tools(action="recommend", task="修改代码")  # 推荐工具
    toolkit_categorize_tools(action="compact")       # 返回精简列表
"""

import json
import logging

logger = logging.getLogger("toolkit")

# ── 工具分类表 ──

TOOL_CATEGORIES = {
    "📁 文件操作": [
        "toolkit_file", "toolkit_save_file", "toolkit_explr",
    ],
    "✏️ 代码编辑": [
        "toolkit_edit", "toolkit_diff_edit", "toolkit_diff",
        "toolkit_self_evolve", "toolkit_clean_comments",
        "toolkit_format_code", "toolkit_auto_fix", "toolkit_comment",
    ],
    "🔍 搜索": [
        "toolkit_search", "toolkit_lsp", "toolkit_query_chat_history",
    ],
    "📸 截图与OCR": [
        "toolkit_screenshot", "toolkit_ocr", "toolkit_screen_read",
    ],
    "💻 系统操作": [
        "toolkit_exec", "toolkit_config", "toolkit_os_info",
        "toolkit_sudo_gui", "toolkit_input", "toolkit_clipboard",
    ],
    "📦 包管理": [
        "toolkit_pkg", "toolkit_build", "toolkit_read_pyproject",
    ],
    "🧪 测试": [
        "toolkit_run_tests", "toolkit_test_gui",
    ],
    "🧠 记忆与知识": [
        "toolkit_memory", "toolkit_kb", "toolkit_reflection",
        "toolkit_proactive",
    ],
    "🤖 多Agent协作": [
        "toolkit_parallel_subtasks", "toolkit_subagent",
        "toolkit_subagent_msg", "toolkit_auto_pipeline",
    ],
    "📋 计划与任务": [
        "toolkit_plan", "toolkit_todo", "toolkit_scheduler",
        "toolkit_task_resume",
    ],
    "🔗 Git版本控制": [
        "toolkit_git_commit", "toolkit_git_push_all_remotes",
        "toolkit_git_branch_manager",
    ],
    "🌐 Web与网络": [
        "toolkit_browser_tab", "toolkit_js_fetch", "toolkit_mcp",
    ],
    "🧬 自进化": [
        "toolkit_self_evolve", "toolkit_self_evolve_thread",
        "toolkit_prompt_evolve", "toolkit_evolution_exp",
        "toolkit_experience_solidify",
    ],
    "🛠️ 实用工具": [
        "toolkit_gettime", "toolkit_weather_my", "toolkit_lunar",
        "toolkit_date_diff", "toolkit_ip_location_my",
    ],
    "📤 导出与分享": [
        "toolkit_dump_topic", "toolkit_export_last_pdf",
        "toolkit_notify",
    ],
    "🔌 MCP集成": [
        "toolkit_mcp",
    ],
}

# 任务→工具推荐映射
TASK_TO_TOOLS = {
    "修改代码": ["toolkit_edit", "toolkit_diff_edit", "toolkit_diff", "toolkit_self_evolve", "toolkit_search", "toolkit_lsp"],
    "审查代码": ["toolkit_code_review", "toolkit_lsp", "toolkit_explr", "toolkit_search"],
    "测试": ["toolkit_run_tests", "toolkit_test_gui", "toolkit_build"],
    "调试": ["toolkit_exec", "toolkit_file", "toolkit_search", "toolkit_lsp"],
    "搜索信息": ["toolkit_search", "toolkit_js_fetch", "toolkit_query_chat_history"],
    "文件操作": ["toolkit_file", "toolkit_save_file", "toolkit_explr", "toolkit_edit"],
    "Git操作": ["toolkit_git_commit", "toolkit_git_push_all_remotes", "toolkit_git_branch_manager"],
    "包管理": ["toolkit_pkg", "toolkit_build", "toolkit_read_pyproject"],
    "截图": ["toolkit_screenshot", "toolkit_ocr", "toolkit_screen_read"],
    "多Agent": ["toolkit_parallel_subtasks", "toolkit_subagent", "toolkit_auto_pipeline"],
    "规划任务": ["toolkit_plan", "toolkit_todo", "toolkit_task_resume"],
    "记忆管理": ["toolkit_memory", "toolkit_kb"],
}


def toolkit_categorize_tools(action: str = "list", task: str = "") -> str:
    """获取按类别分组的工具列表或按任务推荐工具。

    Args:
        action: list=列出分类, recommend=按任务推荐, compact=精简列表
        task: [recommend] 任务描述，如'修改代码'、'审查代码'

    Returns:
        JSON 格式的分类/推荐结果
    """
    if action == "list":
        categories = []
        total = set()
        for cat_name, tools in TOOL_CATEGORIES.items():
            categories.append({"category": cat_name, "tools": tools})
            total.update(tools)
        return json.dumps({
            "ok": True,
            "categories": categories,
            "total_tools": len(total),
            "category_count": len(categories),
        }, ensure_ascii=False)

    elif action == "recommend":
        if not task:
            return json.dumps({"ok": False, "error": "recommend 需要 task 参数"}, ensure_ascii=False)
        # 匹配任务关键词
        matched = []
        for task_key, tools in TASK_TO_TOOLS.items():
            if any(kw in task for kw in task_key) or any(kw in task_key for kw in task):
                matched.append({"task": task_key, "recommended_tools": tools})
        if not matched:
            # 没匹配到，返回所有工具（按分类）
            return toolkit_categorize_tools(action="list")
        return json.dumps({"ok": True, "recommendations": matched}, ensure_ascii=False)

    elif action == "compact":
        # 精简模式：每个分类只取前2-3个核心工具
        compact = {}
        for cat_name, tools in TOOL_CATEGORIES.items():
            compact[cat_name] = tools[:3]
        all_tools = set()
        for tools in compact.values():
            all_tools.update(tools)
        return json.dumps({
            "ok": True,
            "compact_tools": compact,
            "total": len(all_tools),
            "note": "精简模式 — 每个分类仅列出核心工具，完整列表使用 list",
        }, ensure_ascii=False)

    return json.dumps({"ok": False, "error": f"未知 action: {action}"}, ensure_ascii=False)


def meta_toolkit_categorize_tools() -> dict:
    return {"type": "function", "function": {"name": "toolkit_categorize_tools", "description": "工具分类组织 — 将 75+ 工具按场景类别分组管理。支持 list(列出分类)、recommend(按任务推荐工具)、compact(精简列表)。借鉴 opencode/codex 的最小化工具集理念，降低选择成本。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "recommend", "compact"], "description": "list=列出分类, recommend=按任务推荐, compact=精简列表"}, "task": {"type": "string", "description": "[recommend] 任务描述"}}, "required": ["action"]}}}
