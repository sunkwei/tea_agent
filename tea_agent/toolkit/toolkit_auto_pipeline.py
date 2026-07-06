# @2026-07-02 gen by claude, 工具共生网络 — 自动编排多工具管线
"""
toolkit_auto_pipeline — 自动工具管线编排器（工具共生网络）

前所未有的元能力：不是单一工具，而是"工具编排工具"。
自动分析可用工具的输入/输出能力，动态构建最优执行管线，
实现「任务→工具链→执行→学习」的闭环。
"""

import logging
import re
import time

logger = logging.getLogger("toolkit.auto_pipeline")

# ── 工具能力注册表（模块级常量，builtin 下可访问） ──────

TASK_TEMPLATES = {
    "代码审查": {
        "description": "对代码进行全面审查",
        "pipeline": [{"tool": "toolkit_code_review", "params": {"filepath": "{filepath}", "level": "thorough"}, "parallel": False}],
        "inputs_needed": ["filepath"],
    },
    "批量格式化": {
        "description": "批量格式化目录下的所有 Python 文件",
        "pipeline": [{"tool": "toolkit_batch_process", "params": {"action": "format", "glob_pattern": "{glob}", "directory": "{dir}"}, "parallel": True}],
        "inputs_needed": ["glob", "dir"],
    },
    "修改并验证": {
        "description": "修改文件后运行测试验证",
        "pipeline": [
            {"tool": "toolkit_diff_edit", "params": {"file_path": "{filepath}", "old_text": "{old}", "new_text": "{new}"}, "parallel": False},
            {"tool": "toolkit_run_tests", "params": {"pattern": "{test_pattern}"}, "parallel": False},
        ],
        "inputs_needed": ["filepath", "old", "new"],
    },
    "全面项目分析": {
        "description": "构建知识库、分析架构、审查关键代码",
        "pipeline": [
            {"tool": "toolkit_explr", "params": {"action": "build", "directory": "{dir}"}, "parallel": False},
            {"tool": "toolkit_code_review", "params": {"directory": "{dir}", "level": "quick", "max_files": 10}, "parallel": False},
        ],
        "inputs_needed": ["dir"],
    },
}


def _match_score(task_lower, template_text):
    """计算任务与模板的匹配度"""
    kw = set(re.findall(r'[\w\u4e00-\u9fff]+', task_lower))
    tk = set(re.findall(r'[\w\u4e00-\u9fff]+', template_text))
    if not kw or not tk:
        return 0
    return len(kw & tk) / max(len(kw), 1)


def _build_dynamic_pipeline(task_lower):
    """动态编织管线（纯函数，无类依赖）"""
    pipeline = []
    needed = []

    has_analysis = any(k in task_lower for k in ["审查", "分析", "检查", "review", "analyze", "check"])
    has_edit = any(k in task_lower for k in ["修改", "编辑", "修复", "edit", "fix", "change", "update"])
    has_test = any(k in task_lower for k in ["测试", "验证", "test", "verify", "validate"])
    has_search = any(k in task_lower for k in ["搜索", "查找", "查询", "search", "find", "query"])
    has_format = any(k in task_lower for k in ["格式化", "format"])
    has_build = any(k in task_lower for k in ["构建", "打包", "build", "package"])
    has_batch = any(k in task_lower for k in ["批量", "所有", "全部", "batch", "all"])

    if has_search:
        pipeline.append({"tool": "toolkit_search", "params": {"query": "{query}"}, "parallel": False})
        needed.append("query")
    if has_analysis:
        if has_batch or "目录" in task_lower:
            pipeline.append({"tool": "toolkit_code_review", "params": {"directory": "{dir}", "level": "standard"}, "parallel": False})
            needed.append("dir")
        else:
            pipeline.append({"tool": "toolkit_code_review", "params": {"filepath": "{filepath}", "level": "standard"}, "parallel": False})
            needed.append("filepath")
    if has_format:
        pipeline.append({"tool": "toolkit_format_code", "params": {"path": "{filepath}"}, "parallel": True})
    if has_edit:
        pipeline.append({"tool": "toolkit_diff_edit", "params": {"file_path": "{filepath}", "old_text": "{old}", "new_text": "{new}"}, "parallel": False})
        if "filepath" not in needed:
            needed.append("filepath")
        needed.extend(["old", "new"])
    if has_test:
        pipeline.append({"tool": "toolkit_run_tests", "params": {"pattern": "{test_pattern}"}, "parallel": False})
        needed.append("test_pattern")
    if has_build:
        pipeline.append({"tool": "toolkit_build", "params": {"action": "package", "directory": "{dir}"}, "parallel": False})
        if "dir" not in needed:
            needed.append("dir")
    if not pipeline:
        pipeline.append({"tool": "toolkit_search", "params": {"query": "{query}"}, "parallel": False})
        needed.append("query")

    desc = " → ".join(p["tool"] for p in pipeline)
    return {"matched_template": None, "confidence": 0.5, "pipeline": pipeline,
            "inputs_needed": list(set(needed)), "description": f"自动编排: {desc}"}


def _call_tool_dynamic(tool_name, params):
    """动态调用工具函数（支持 builtin 注册的工具）"""
    try:
        # 策略1: 从当前全局查找
        import sys
        func = globals().get(tool_name)
        if func is not None:
            return func(**params)
        # 策略2: 从 tea_agent.toolkit 模块导入
        try:
            module = __import__(f"tea_agent.toolkit.{tool_name}", fromlist=[tool_name])
            func = getattr(module, tool_name, None)
            if func is not None:
                return func(**params)
        except Exception:
            pass
        # 策略3: 从 sys.modules 的 __main__ 查找（builtin 注册模式）
        main_mod = sys.modules.get("__main__")
        if main_mod:
            func = getattr(main_mod, tool_name, None)
            if func is not None:
                return func(**params)
        return {"ok": False, "error": f"工具不可用: {tool_name}"}
    except Exception as e:
        return {"ok": False, "error": f"{tool_name} 调用失败: {str(e)[:200]}"}


def _resolve_params(params, context):
    """用上下文值填充参数中的 {placeholder}"""
    resolved = {}
    for k, v in params.items():
        if isinstance(v, str):
            for ctx_key, ctx_val in context.items():
                placeholder = "{" + ctx_key + "}"
                if placeholder in v:
                    v = v.replace(placeholder, str(ctx_val) if ctx_val is not None else "")
            resolved[k] = v
        else:
            resolved[k] = v
    return resolved


# ── 主入口 ──────────────────────────────────────────────

def toolkit_auto_pipeline(action="analyze", task="", inputs=None, pipeline=None):
    """
    自动工具管线编排器（工具共生网络）。
    自动分析任务需求，动态构建并执行工具链。

    Args:
        action: analyze=分析任务推荐管线, execute=执行管线, templates=查看模板列表
        task: 任务描述（如"审查代码"、"批量格式化后测试"）
        inputs: 输入参数字典，如 {"filepath": "main.py", "dir": "src/"}
        pipeline: 自定义管线（覆盖自动分析），格式同 TASK_TEMPLATES 的 pipeline

    Returns: {"ok": bool, "analysis": {...}, "execution": {...}, "log": [...]}
    """
    try:
        if action == "templates":
            return {"ok": True, "templates": {
                k: {"description": v["description"],
                    "pipeline": [p["tool"] for p in v["pipeline"]]}
                for k, v in TASK_TEMPLATES.items()
            }}

        if action == "analyze":
            if not task:
                return {"ok": False, "error": "analyze 需要 task 参数"}
            task_lower = task.lower()
            # 匹配模板
            best_match = None
            best_score = 0
            for tmpl_name, tmpl in TASK_TEMPLATES.items():
                score = _match_score(task_lower, tmpl_name + tmpl["description"])
                if score > best_score:
                    best_score = score
                    best_match = tmpl_name
            if best_match and best_score > 0.3:
                tmpl = TASK_TEMPLATES[best_match]
                analysis = {"matched_template": best_match, "confidence": best_score,
                           "pipeline": tmpl["pipeline"], "inputs_needed": tmpl["inputs_needed"],
                           "description": tmpl["description"]}
            else:
                analysis = _build_dynamic_pipeline(task_lower)
            return {"ok": True, "analysis": analysis, "action": "analyze"}

        if action == "execute":
            if not task and not pipeline:
                return {"ok": False, "error": "execute 需要 task 或 pipeline 参数"}
            inputs = inputs or {}

            # 确定管线
            if pipeline:
                pl = pipeline
            else:
                task_lower = task.lower()
                best_match = None
                best_score = 0
                for tmpl_name, tmpl in TASK_TEMPLATES.items():
                    score = _match_score(task_lower, tmpl_name + tmpl["description"])
                    if score > best_score:
                        best_score = score
                        best_match = tmpl_name
                pl = TASK_TEMPLATES[best_match]["pipeline"] if best_match and best_score > 0.3 else _build_dynamic_pipeline(task_lower)["pipeline"]

            if not pl:
                return {"ok": False, "error": f"无法为任务'{task}'构建管线"}

            # 执行管线
            start = time.time()
            exec_log = []
            context = dict(inputs)
            results = []

            for i, step in enumerate(pl):
                tool_name = step["tool"]
                params = _resolve_params(step["params"], context)
                parallel = step.get("parallel", False)
                step_start = time.time()

                result = _call_tool_dynamic(tool_name, params)
                elapsed = time.time() - step_start

                log_entry = {"step": i, "tool": tool_name, "params": params,
                            "elapsed": round(elapsed, 3), "ok": result.get("ok", False)}
                exec_log.append(log_entry)
                results.append({"tool": tool_name, "result": result, "elapsed": elapsed})

                if not result.get("ok", False) and not parallel:
                    return {"ok": False, "error": f"管线在步骤{i}({tool_name})失败: {result.get('error','')}",
                           "execution": {"results": results, "log": exec_log,
                                        "elapsed": round(time.time() - start, 3), "steps": len(pl)},
                           "action": "execute"}

                if isinstance(result, dict):
                    context.update(result)

            return {"ok": True, "execution": {"results": results, "log": exec_log,
                                              "elapsed": round(time.time() - start, 3), "steps": len(pl)},
                    "action": "execute"}

        return {"ok": False, "error": f"未知 action: {action}。支持: analyze, execute, templates"}

    except Exception as e:
        logger.exception(f"toolkit_auto_pipeline: {e}")
        return {"ok": False, "error": str(e)[:300]}


# ── Meta ────────────────────────────────────────────────

def meta_toolkit_auto_pipeline():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_auto_pipeline",
            "description": "【突破性创新】自动工具管线编排器（工具共生网络）。自动分析任务需求，动态构建最优工具执行链，实现「任务→工具链→执行→学习」闭环。不是单一工具，而是编排工具的元工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["analyze", "execute", "templates"],
                              "description": "analyze=分析任务推荐管线, execute=执行管线, templates=查看模板", "default": "analyze"},
                    "task": {"type": "string", "description": "任务描述，如'审查代码'、'批量格式化后测试'"},
                    "inputs": {"type": "object", "description": "输入参数字典，如 {'filepath': 'main.py', 'dir': 'src/'}"},
                    "pipeline": {"type": "array", "items": {"type": "object"},
                                "description": "自定义管线，格式: [{'tool': 'xxx', 'params': {...}, 'parallel': bool}]"},
                },
                "required": ["action"],
            },
        },
    }
