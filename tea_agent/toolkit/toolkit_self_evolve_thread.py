# Self-Evolution Background Thread
# Replaces subconscious dream engine with practical self-maintenance tasks:
#   1. 工具使用率分析 → 优化建议 / 合并非正交工具
#   2. docs/TOOLS.md 自动同步
#   3. 技能 (skills) 整理
# version: 1.0.0

import logging

logger = logging.getLogger("toolkit")


def toolkit_self_evolve_thread(action: str):
    """自进化后台线程 — 定期评估工具、同步TOOLS.md、整理技能。

    Actions:
        start  — 启动 daemon 线程（每小时运行一次完整循环）
        stop   — 停止线程
        status — 查看运行状态
        run    — 立即强制执行一次循环（不等待定时）
    """
    logger.info(f"toolkit_self_evolve_thread called: action={action!r}")
    import os
    import json
    import time
    import sqlite3
    import threading
    import re
    import subprocess
    from datetime import datetime
    from collections import Counter

    # ── 路径 ──
    try:
        from tea_agent.config import get_config
        STATE_FILE = os.path.join(get_config().paths.data_dir_abs, "self_evolve_state.json")
    except Exception:
        STATE_FILE = os.path.expanduser("~/.tea_agent/self_evolve_state.json")
    DEFAULT_DB = "chat_history.db"
    CYCLE_INTERVAL = 3600       # 1 小时
    CHECK_INTERVAL = 30         # 状态检查间隔

    # ── 辅助 ──────────────────────────────

    def _is_tea_agent_cwd():
        cwd = os.getcwd()
        pyproj = os.path.join(cwd, "pyproject.toml")
        if os.path.exists(pyproj):
            try:
                with open(pyproj, "r") as f:
                    if 'name = "tea_agent"' in f.read() or "name = 'tea_agent'" in f.read():
                        return True
            except Exception:
                logger.exception("operation failed")

        if os.path.isdir(os.path.join(cwd, "tea_agent")):
            return True
        return False

    def _ensure_dir(p):
        os.makedirs(p, exist_ok=True)

    def _read_state():
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                logger.exception("operation failed")

        return {
            "running": False, "pid": os.getpid(), "started_at": None,
            "last_cycle_at": None, "cycles_completed": 0,
            "tool_analysis": {}, "readme_synced": False,
            "skills_organized": 0,
        }

    def _write_state(state):
        _ensure_dir(os.path.dirname(STATE_FILE))
        state["_updated"] = datetime.now().isoformat()
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def _get_db_path():
        if os.path.exists(DEFAULT_DB):
            return os.path.abspath(DEFAULT_DB)
        for c in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "chat_history.db"),
            os.path.expanduser(f"~/.tea_agent/{DEFAULT_DB}"),
        ]:
            if os.path.exists(c):
                return c
        return os.path.abspath(DEFAULT_DB)

    def _send_notification(title, msg, expire_ms=5000):
        try:
            if os.name == "nt":
                _ensure_dir(os.path.expanduser("~/.tea_agent/tmp"))
                ps = (
                    f'Add-Type -AssemblyName System.Windows.Forms\n'
                    f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n'
                    f'$tpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n'
                    f'$texts = @($tpl.GetElementsByTagName("text"))\n'
                    f'$null = $texts[0].AppendChild($tpl.CreateTextNode("{title}"))\n'
                    f'$null = $texts[1].AppendChild($tpl.CreateTextNode("{msg}"))\n'
                    f'$toast = [Windows.UI.Notifications.ToastNotification]::new($tpl)\n'
                    f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("TeaAgent.TeaAgent.TeaAgent").Show($toast)\n'
                )
                import tempfile
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False, encoding="utf-8")
                try:
                    tmp.write(ps)
                    tmp.close()
                    subprocess.run(
                        ["powershell", "-NoProfile", "-File", tmp.name],
                        capture_output=True, timeout=10,
                    )
                finally:
                    try:
                        os.unlink(tmp.name)
                    except Exception:
                        logger.exception("operation failed")

            else:
                subprocess.run(
                    ["notify-send", "--app-name=TeaAgent", title, msg],
                    capture_output=True, timeout=5,
                )
        except Exception:
            logger.exception("operation failed")


    # ═══════════════════════════════════════════
    # 任务 1：工具使用率分析
    # ═══════════════════════════════════════════

    def _analyze_tools(db_path):
        """从 chat_history 统计工具调用频率，生成优化建议。"""
        if not os.path.exists(db_path):
            return {"error": "数据库不存在"}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 从 ai_msg 中提取工具调用模式
        tool_counter = Counter()
        try:
            cur.execute(
                "SELECT ai_msg FROM conversations ORDER BY id DESC LIMIT 500"
            )
            for (ai_msg,) in cur.fetchall():
                if not ai_msg:
                    continue
                # 匹配 toolkit_XXX("action" 调用
                for m in re.finditer(r"toolkit_(\w+)", str(ai_msg)):
                    tool_counter[m.group(1)] += 1
        except Exception:
            logger.exception("operation failed")

        finally:
            conn.close()

        if not tool_counter:
            return {"total_calls": 0, "top_tools": [], "suggestions": []}

        total = sum(tool_counter.values())
        top = tool_counter.most_common(15)

        # ── 生成优化建议 ──
        suggestions = []

        # 1. 低频工具（使用 < 3 次）建议审视或合并
        low_use = [(t, c) for t, c in tool_counter.items() if c < 3]
        if low_use:
            low_list = ", ".join(f"{t}({c})" for t, c in low_use[:5])
            suggestions.append({
                "type": "low_usage",
                "msg": f"低频工具: {low_list}，建议审视是否需要或与其他工具合并",
            })

        # 2. 查找功能相似的工具组（名称前缀相同）
        prefix_groups = {}
        for t in tool_counter:
            # 按前缀分组: toolkit_file/toolkit_save_file/toolkit_write_b64 共用 file 操作
            parts = t.split("_")
            if len(parts) >= 2:
                prefix = "_".join(parts[:2])
                prefix_groups.setdefault(prefix, []).append(t)
        for prefix, tools in prefix_groups.items():
            if len(tools) >= 2:
                suggestions.append({
                    "type": "merge_candidate",
                    "msg": f"工具组 '{prefix}': {', '.join(tools)} 功能可能重叠，建议合并",
                })

        # 3. 高频工具 → 优化参数默认值
        if top and top[0][1] > total * 0.3:
            suggestions.append({
                "type": "hot_tool",
                "msg": f"高频工具 {top[0][0]} (占比 {top[0][1]/total:.0%})，建议优化其参数默认值以减少调用开销",
            })

        return {
            "total_calls": total,
            "unique_tools": len(tool_counter),
            "top_tools": [(t, c) for t, c in top],
            "suggestions": suggestions,
        }

    # ═══════════════════════════════════════════
    # 任务 2：README.md 自动同步
    # ═══════════════════════════════════════════

    def _sync_readme(tool_analysis):
        """自动生成/更新工具清单到 docs/TOOLS.md（不再覆盖 README.md）。"""
        cwd = os.getcwd()
        docs_dir = os.path.join(cwd, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        tools_md_path = os.path.join(docs_dir, "TOOLS.md")

        # 读取 pyproject.toml 获取项目元信息
        name = version = description = ""
        pyproj_path = os.path.join(cwd, "pyproject.toml")
        if os.path.exists(pyproj_path):
            try:
                with open(pyproj_path, "r") as f:
                    content = f.read()
                for m in re.finditer(r'name\s*=\s*"([^"]+)"', content):
                    name = m.group(1)
                for m in re.finditer(r'version\s*=\s*"([^"]+)"', content):
                    version = m.group(1)
                for m in re.finditer(r'description\s*=\s*"([^"]+)"', content):
                    description = m.group(1)
            except Exception:
                logger.exception("operation failed")


        # 收集工具列表
        toolkit_dir = os.path.join(cwd, "tea_agent", "toolkit")
        tools = []
        if os.path.isdir(toolkit_dir):
            for fname in sorted(os.listdir(toolkit_dir)):
                if fname.startswith("toolkit_") and fname.endswith(".py"):
                    tool_name = fname[8:-3]  # strip 'toolkit_' prefix and '.py'
                    if tool_name in ("self_evolve_thread",):
                        continue  # 不列出自身
                    # 提取第一行 docstring
                    fpath = os.path.join(toolkit_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            first_line = ""
                            for line in f:
                                stripped = line.strip()
                                if stripped.startswith("#") or not stripped:
                                    continue
                                if '"""' in stripped or "'''" in stripped:
                                    first_line = stripped.strip('"\'').strip()
                                elif first_line:
                                    break
                                elif stripped.startswith("def toolkit_"):
                                    first_line = stripped
                                if first_line:
                                    break
                        desc = first_line[:80] if first_line else ""
                    except Exception:
                        desc = ""
                    tools.append((tool_name, desc))

        # 使用统计
        top5 = tool_analysis.get("top_tools", [])[:5] if tool_analysis else []
        usage_lines = "\n".join(
            f"| `toolkit_{t}` | {c} 次 |" for t, c in top5
        ) if top5 else "| — | — |"

        readme = f"""# {name or 'Tea Agent'} {version and f'v{version}'}

{description or '智能编程助手 — 工具驱动、自我进化'}

## 📊 工具使用 TOP5

| 工具 | 调用次数 |
|------|---------|
{usage_lines}

## 🧰 所有工具 ({len(tools)} 个)

"""
        for tname, tdesc in tools:
            readme += f"- **`toolkit_{tname}`** — {tdesc}\n"

        readme += f"""
## ⚙️ 自进化引擎

后台每小时自动运行：
- 🔍 工具使用分析 & 优化建议
- 📝 docs/TOOLS.md 自动同步（本文件）
- 🎯 技能模式整理

> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

        try:
            with open(tools_md_path, "w", encoding="utf-8") as f:
                f.write(readme)
            return {"synced": True, "path": tools_md_path, "tools_count": len(tools)}
        except Exception as e:
            return {"synced": False, "error": str(e)}

    # ═══════════════════════════════════════════
    # 任务 3：技能 (Skills) 整理
    # ═══════════════════════════════════════════

    def _organize_skills():
        """调用 toolkit_dynamic_skill 整理技能。"""
        try:
            # 动态导入避免循环依赖
            import importlib.util
            toolkit_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), ""
            )
            skill_path = os.path.join(toolkit_dir, "toolkit_dynamic_skill.py")
            if not os.path.exists(skill_path):
                return {"skills": 0, "msg": "skill 模块未找到"}

            spec = importlib.util.spec_from_file_location(
                "_dynamic_skill", skill_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.toolkit_dynamic_skill("list")
            skills = result.get("skills", []) if isinstance(result, dict) else []
            count = len(skills)

            # 按类别分组
            by_category = Counter(
                s.get("category", "general") for s in skills
            )

            return {
                "skills": count,
                "by_category": dict(by_category),
                "top": [s.get("name", "?") for s in skills[:5]],
            }
        except Exception as e:
            return {"skills": 0, "error": str(e)}

    # ═══════════════════════════════════════════
    # 完整循环
    # ═══════════════════════════════════════════

    def _run_cycle(state):
        db_path = _get_db_path()

        # 1. 工具分析
        tool_analysis = _analyze_tools(db_path)
        state["tool_analysis"] = {
            "total_calls": tool_analysis.get("total_calls", 0),
            "unique_tools": tool_analysis.get("unique_tools", 0),
            "top_tools": tool_analysis.get("top_tools", [])[:5],
            "suggestions_count": len(tool_analysis.get("suggestions", [])),
        }

        # 2. README 同步
        readme_result = _sync_readme(tool_analysis)
        state["readme_synced"] = readme_result.get("synced", False)

        # 3. 技能整理
        skill_result = _organize_skills()
        state["skills_organized"] = skill_result.get("skills", 0)

        state["last_cycle_at"] = datetime.now().isoformat()
        state["cycles_completed"] = state.get("cycles_completed", 0) + 1
        _write_state(state)

        return {
            "tool_analysis": tool_analysis,
            "readme": readme_result,
            "skills": skill_result,
        }

    def _notify_cycle(result, state, first_run=False):
        ta = result.get("tool_analysis", {})
        n_tools = ta.get("unique_tools", 0)
        n_calls = ta.get("total_calls", 0)
        suggestions = ta.get("suggestions", [])
        n_sug = len(suggestions)
        rd = result.get("readme", {})
        sk = result.get("skills", {})

        prefix = "首轮" if first_run else f"第{state.get('cycles_completed',0)}轮"
        lines = [f"🔄 自进化 {prefix}完成"]
        if n_calls:
            lines.append(f"工具: {n_tools}种 / {n_calls}次调用")
        if n_sug:
            lines.append(f"优化建议: {n_sug}条")
            for s in suggestions[:3]:
                lines.append(f"  💡 {s.get('msg','')[:80]}")
        if rd.get("synced"):
            lines.append(f"README: 已同步 ({rd.get('tools_count',0)}个工具)")
        if sk.get("skills"):
            lines.append(f"技能: {sk.get('skills',0)}个")

        _send_notification("🔄 自进化引擎", "\n".join(lines), expire_ms=6000)

    # ═══════════════════════════════════════════
    # 后台循环
    # ═══════════════════════════════════════════

    def _self_evolve_loop():
        state = _read_state()
        _ensure_dir(os.path.dirname(STATE_FILE))
        state["running"] = True
        state["pid"] = os.getpid()
        state["started_at"] = datetime.now().isoformat()
        _write_state(state)
        _send_notification(
            "🔄 自进化引擎",
            "已启动！每小时：工具分析 · README同步 · 技能整理",
        )

        # 立即执行首轮
        try:
            result = _run_cycle(state)
            _notify_cycle(result, state, first_run=True)
        except Exception as e:
            state = _read_state()
            state["_last_error"] = str(e)[:200]
            _write_state(state)

        checks_per_cycle = CYCLE_INTERVAL // CHECK_INTERVAL
        while True:
            for _ in range(checks_per_cycle):
                time.sleep(CHECK_INTERVAL)
                state = _read_state()
                if not state.get("running") or state.get("pid") != os.getpid():
                    state["running"] = False
                    _write_state(state)
                    return
            state = _read_state()
            try:
                result = _run_cycle(state)
                _notify_cycle(result, state)
            except Exception as e:
                state = _read_state()
                state["_last_error"] = str(e)[:200]
                _write_state(state)

    # ═══════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════

    state = _read_state()

    if action == "start":
        if not _is_tea_agent_cwd():
            return {
                "status": "rejected",
                "reason": "当前目录非 tea_agent 项目",
                "cwd": os.getcwd(),
            }
        if state.get("running") and state.get("pid") == os.getpid():
            return {
                "status": "already_running",
                "started_at": state.get("started_at"),
                "cycles_completed": state.get("cycles_completed", 0),
            }
        if state.get("running") and state.get("pid") != os.getpid():
            state["running"] = False
            _write_state(state)
        t = threading.Thread(target=_self_evolve_loop, daemon=True)
        t.start()
        time.sleep(0.3)
        state = _read_state()
        return {
            "status": "started",
            "pid": os.getpid(),
            "started_at": state.get("started_at"),
            "cycle_interval": "1小时",
            "tasks": ["工具使用分析", "README同步", "技能整理"],
        }

    elif action == "stop":
        state["running"] = False
        state["stopped_at"] = datetime.now().isoformat()
        _write_state(state)
        return {
            "status": "stopped",
            "cycles_completed": state.get("cycles_completed", 0),
        }

    elif action == "status":
        running = state.get("running") and state.get("pid") == os.getpid()
        return {
            "running": running,
            "pid": state.get("pid"),
            "started_at": state.get("started_at"),
            "last_cycle_at": state.get("last_cycle_at"),
            "cycles_completed": state.get("cycles_completed", 0),
            "tool_analysis": state.get("tool_analysis", {}),
            "readme_synced": state.get("readme_synced", False),
            "skills_organized": state.get("skills_organized", 0),
        }

    elif action == "run":
        result = _run_cycle(state)
        state = _read_state()
        _notify_cycle(result, state)
        return result

    else:
        return {
            "error": f"未知 action: {action}",
            "supported": ["start", "stop", "status", "run"],
        }


def meta_toolkit_self_evolve_thread() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_self_evolve_thread",
            "description": "自进化后台线程 — 每小时自动运行：①工具使用率分析&优化建议 ②docs/TOOLS.md同步 ③技能模式整理。替代旧的潜意识引擎。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "stop", "status", "run"],
                        "description": "start=启动线程, stop=停止, status=查看状态, run=立即执行一轮",
                    },
                },
                "required": ["action"],
            },
        },
    }
