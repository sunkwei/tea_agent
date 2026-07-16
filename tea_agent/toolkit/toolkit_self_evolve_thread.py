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
    import json
    import os
    import re
    import sqlite3
    import subprocess
    import threading
    import time
    from collections import Counter
    from datetime import datetime

    # ── 路径 ──
    try:
        from tea_agent.config import get_config
        STATE_FILE = os.path.join(get_config().paths.data_dir_abs, "self_evolve_state.json")  # noqa: N806
    except Exception:
        STATE_FILE = os.path.expanduser("~/.tea_agent/self_evolve_state.json")  # noqa: N806
    DEFAULT_DB = "chat_history.db"  # noqa: N806
    CYCLE_INTERVAL = 3600       # 1 小时  # noqa: N806
    CHECK_INTERVAL = 30         # 状态检查间隔  # noqa: N806

    # ── 辅助 ──────────────────────────────

    def _is_tea_agent_cwd():
        cwd = os.getcwd()
        pyproj = os.path.join(cwd, "pyproject.toml")
        if os.path.exists(pyproj):
            try:
                with open(pyproj) as f:
                    if 'name = "tea_agent"' in f.read() or "name = 'tea_agent'" in f.read():
                        return True
            except Exception:
                logger.exception("operation failed")

        return bool(os.path.isdir(os.path.join(cwd, "tea_agent")))

    def _ensure_dir(p):
        os.makedirs(p, exist_ok=True)

    def _read_state():
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
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

    def _send_notification(title, msg, expire_ms=6000):
        """发送桌面系统通知。

        优先使用 toolkit_notify（跨平台、更稳健），
        失败时 fallback 到直接 PowerShell/notify-send。
        """
        try:
            # 优先调用 toolkit_notify（注册的工具函数）
            # 通过直接 import 函数实现，避免依赖 toolkit 调用链
            from tea_agent.toolkit.toolkit_notify import toolkit_notify
            toolkit_notify(
                title=title,
                message=msg,
                urgency="normal",
                duration=expire_ms,
            )
            return  # 成功，直接返回
        except Exception:
            logger.debug("toolkit_notify 不可用，使用 fallback 通知")

        # ── Fallback：PowerShell Toast (Windows) ──
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
            logger.exception("通知发送失败")


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
                with open(pyproj_path) as f:
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
                        with open(fpath, encoding="utf-8", errors="ignore") as f:
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
    # 任务 3：技能 (Skills) 整理 + 晋升
    # ═══════════════════════════════════════════

    def _organize_skills():
        """整理技能 + 自动晋升高置信度结晶技能到 SKILL.md。"""
        result = {"skills": 0, "promoted": 0, "skipped": 0}

        # ── 3a. 统计已有 SKILL.md 技能数 ──
        try:
            skill_md_dir = os.path.expanduser("~/.tea_agent/skills")
            if os.path.isdir(skill_md_dir):
                skill_count = 0
                for entry in os.listdir(skill_md_dir):
                    entry_path = os.path.join(skill_md_dir, entry)
                    if os.path.isdir(entry_path):
                        for fname in ("SKILL.md", "BRIEF.md"):
                            if os.path.isfile(os.path.join(entry_path, fname)):
                                skill_count += 1
                                break
                result["skills"] = skill_count
        except Exception:
            pass

        # ── 3b. 晋升：JSON 结晶技能 → SKILL.md ──
        try:
            import yaml
            skills_dir = os.path.expanduser("~/.tea_agent/skills")
            if not os.path.isdir(skills_dir):
                return result

            for fname in os.listdir(skills_dir):
                if not fname.endswith(".json") or fname == "skill_index.json":
                    continue
                fpath = os.path.join(skills_dir, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    result["skipped"] += 1
                    continue

                # 晋升条件：成功次数 >= 3 且置信度 >= 0.75
                success_count = data.get("success_count", 0)
                fail_count = data.get("fail_count", 0)
                total = success_count + fail_count
                confidence = success_count / total if total > 0 else 0.0

                if success_count < 3 or confidence < 0.75:
                    result["skipped"] += 1
                    continue

                name = data.get("name", "").strip()
                if not name:
                    name = data.get("example_task", fname[:30])
                # 清理名称，作为目录名
                safe_name = re.sub(r'[^\w\u4e00-\u9fff\s-]', '', name)[:40].strip()
                if not safe_name:
                    safe_name = f"skill_{hash(fname) % 10000:04d}"

                # 检查是否已被晋升
                skill_dir = os.path.join(skills_dir, safe_name)
                skill_md = os.path.join(skill_dir, "SKILL.md")
                if os.path.exists(skill_md):
                    result["skipped"] += 1
                    continue

                # 构建 YAML front matter
                desc = data.get("description", "") or data.get("example_task", "")[:100]
                tags = data.get("tags", [])
                category = data.get("category", "general")
                steps = data.get("steps", [])
                tools = data.get("tools", [])
                tools_str = "\n".join(f"- `{t}`" for t in tools[:8]) if tools else ""
                steps_str = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps[:10])) if steps else ""

                # 构建内容
                content_lines = [
                    "---",
                    f"name: {safe_name}",
                    f"description: {desc}",
                    f"category: {category}",
                    f"tags: {yaml.dump(tags, default_flow_style=True).strip()}",
                    f"version: {data.get('version', '1.0.0')}",
                    f"success_count: {success_count}",
                    f"confidence: {confidence:.2f}",
                    "---",
                ]
                content_lines.append("")
                content_lines.append(f"# {safe_name}")
                content_lines.append("")
                if desc:
                    content_lines.append(desc)
                    content_lines.append("")

                if steps_str:
                    content_lines.append("## 步骤")
                    content_lines.append(steps_str)
                    content_lines.append("")

                if tools_str:
                    content_lines.append("## 使用的工具")
                    content_lines.append(tools_str)
                    content_lines.append("")

                if data.get("success_conditions"):
                    content_lines.append("## 成功条件")
                    for sc in data["success_conditions"][:5]:
                        content_lines.append(f"- {sc}")
                    content_lines.append("")

                content_lines.append(f"> 自动晋升自 {fname}")

                # 写入 SKILL.md
                os.makedirs(skill_dir, exist_ok=True)
                with open(skill_md, "w", encoding="utf-8") as f:
                    f.write("\n".join(content_lines))

                result["promoted"] += 1
                logger.info(f"🏆 技能晋升: {safe_name} (置信度={confidence:.2f}, 成功{success_count}次)")

        except Exception as e:
            logger.warning(f"技能晋升过程出错: {e}")
            result["error"] = str(e)[:100]

        return result

    # ═══════════════════════════════════════════
    # 任务 4：跨主题记忆提取
    # ═══════════════════════════════════════════

    def _acquire_extract_lock(lock_path, ttl_minutes=30):
        """进程间互斥锁（文件锁）：防止多个 Agent 进程同时提取记忆。

        使用带有 O_CREAT|O_EXCL 标志的临时锁文件实现原子性。
        Windows/macOS/Linux 均适用。

        Args:
            lock_path: 锁文件路径
            ttl_minutes: 锁的超时时间，超时后自动视为过期

        Returns:
            True 表示获得锁，False 表示其他进程正在提取
        """
        try:
            # 检查过期锁
            if os.path.exists(lock_path):
                try:
                    mtime = os.path.getmtime(lock_path)
                    age = time.time() - mtime
                    if age > ttl_minutes * 60:
                        os.unlink(lock_path)
                        logger.debug(f"过期锁已清理: {lock_path} ({age:.0f}s old)")
                except OSError:
                    pass

            # 原子创建锁文件
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w') as f:
                f.write(f"pid={os.getpid()}\n")
                f.write(f"time={time.time()}\n")
            return True
        except (OSError, FileExistsError):
            # 锁已被其他进程持有
            return False

    def _release_extract_lock(lock_path):
        """释放提取锁"""
        try:
            if os.path.exists(lock_path):
                os.unlink(lock_path)
        except OSError:
            pass

    def _extract_memories_from_all_topics(db_path):
        """扫描所有主题中未摘要的对话，用 LLM 提取记忆并写入。

        策略：
        - 进程间互斥锁（30分钟TTL），防止 GUI/Server 同时提取
        - 按主题最后活动时间降序处理（最新优先）
        - 每个主题最多处理 20 条未摘要对话
        - 每次循环最多处理 5 个主题（防止资源耗尽）
        - 用便宜模型提取，非关键对话跳过

        Returns:
            dict: {status, topics_scanned, memories_extracted, errors}
        """
        if not os.path.exists(db_path):
            return {"status": "no_db", "topics_scanned": 0, "memories_extracted": 0}

        # ── 进程间互斥锁 ──
        lock_path = os.path.join(
            os.path.dirname(STATE_FILE),
            ".memory_extract.lock",
        )
        if not _acquire_extract_lock(lock_path, ttl_minutes=30):
            return {
                "status": "locked",
                "topics_scanned": 0,
                "memories_extracted": 0,
                "msg": "另一进程正在提取记忆，跳过本轮",
            }

        try:
            from tea_agent.config import get_config
            from tea_agent.memory import MemoryManager
            from tea_agent.store._core import Storage
        except ImportError as e:
            return {"status": f"import_error: {e}", "topics_scanned": 0, "memories_extracted": 0}

        result = {"topics_scanned": 0, "memories_extracted": 0, "errors": 0, "skipped": 0}

        try:
            storage = Storage(db_path)
        except Exception as e:
            _release_extract_lock(lock_path)
            return {"status": f"storage_error: {e}", "topics_scanned": 0, "memories_extracted": 0}

        try:
            # 获取所有活跃主题，按最后更新时间降序
            all_topics = storage.list_topics()
            # 按 last_update_stamp 排序（最近更新的优先）
            active_topics = [
                t for t in all_topics
                if t.get("is_active", 1) and t.get("topic_id")
            ]
            active_topics.sort(
                key=lambda t: t.get("last_update_stamp", ""),
                reverse=True,
            )

            # 最多处理 5 个主题
            for topic in active_topics[:5]:
                topic_id = topic["topic_id"]
                try:
                    # 获取未摘要对话
                    unsummarized = storage.get_unsummarized_conversations(topic_id)
                    if not unsummarized:
                        continue

                    # 最多 20 条
                    unsummarized = unsummarized[:20]
                    result["topics_scanned"] += 1

                    # 构建对话文本
                    conv_lines = []
                    for conv in unsummarized:
                        user_msg = (conv.get("user_msg") or "")[:500]
                        ai_msg = (conv.get("ai_msg") or "")[:1000]
                        conv_lines.append(f"User: {user_msg}\nAssistant: {ai_msg}")
                    conv_text = "\n\n".join(conv_lines)

                    if not conv_text.strip():
                        continue

                    # 用 MemoryManager 提取
                    mm = MemoryManager(storage)
                    messages = mm.build_extraction_prompt(conv_text[:4000])

                    # 获取便宜模型客户端
                    try:
                        from tea_agent.session.params import get_cheap_params
                        cheap_params = get_cheap_params("memory")
                        cfg = get_config()
                        client = None
                        model = ""

                        if cfg.cheap_model and getattr(cfg.cheap_model, 'api_key', None):
                            from openai import OpenAI
                            cheap = cfg.cheap_model
                            client = OpenAI(
                                api_key=cheap.api_key,
                                base_url=(cheap.api_url or "").rstrip("/") + "/v1",
                            )
                            model = cheap.model
                        elif cfg.main_model and getattr(cfg.main_model, 'api_key', None):
                            from openai import OpenAI
                            main = cfg.main_model
                            client = OpenAI(
                                api_key=main.api_key,
                                base_url=(main.api_url or "").rstrip("/") + "/v1",
                            )
                            model = main.model
                    except Exception:
                        client = None

                    if client is None:
                        result["skipped"] += 1
                        continue

                    response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        stream=False,
                        extra_body={"thinking": {"type": "disabled"}},
                        temperature=0.1,
                        max_tokens=1024,
                        **cheap_params,
                    )
                    result_text = response.choices[0].message.content or ""
                    extracted = mm.parse_extraction_result(result_text)

                    if extracted:
                        count = mm.ingest_extracted(extracted, topic_id)
                        result["memories_extracted"] += count

                    # 标记已提取
                    c = storage.conn.cursor()
                    for conv in unsummarized:
                        c.execute(
                            "UPDATE conversations SET is_summarized = 1 WHERE id = ?",
                            (conv["id"],),
                        )
                    storage.conn.commit()
                    c.close()

                except Exception as e:
                    logger.warning(f"记忆提取失败 topic={topic_id}: {e}")
                    result["errors"] += 1
                    continue

        finally:
            storage.close()
            _release_extract_lock(lock_path)

        result["status"] = "success"
        return result

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

        # 4. 跨主题记忆提取
        memory_result = _extract_memories_from_all_topics(db_path)
        state["last_memory_extraction"] = {
            "topics_scanned": memory_result.get("topics_scanned", 0),
            "memories_extracted": memory_result.get("memories_extracted", 0),
            "errors": memory_result.get("errors", 0),
        }

        state["last_cycle_at"] = datetime.now().isoformat()
        state["cycles_completed"] = state.get("cycles_completed", 0) + 1
        _write_state(state)

        return {
            "tool_analysis": tool_analysis,
            "readme": readme_result,
            "skills": skill_result,
            "memory_extraction": memory_result,
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

        # 记忆提取
        mem = result.get("memory_extraction", {})
        if mem.get("memories_extracted", 0):
            lines.append(f"🧠 记忆提取: {mem['memories_extracted']}条 (扫描{mem.get('topics_scanned',0)}主题)")
        elif mem.get("status") == "locked":
            lines.append("🔒 记忆提取跳过 (另一进程正在提取)")
        if mem.get("errors", 0):
            lines.append(f"⚠️ 提取错误: {mem['errors']}个")

        if n_calls:
            lines.append(f"工具: {n_tools}种 / {n_calls}次调用")
        if n_sug:
            lines.append(f"优化建议: {n_sug}条")
            for s in suggestions[:3]:
                lines.append(f"  💡 {s.get('msg','')[:80]}")
        if rd.get("synced"):
            lines.append(f"README: 已同步 ({rd.get('tools_count',0)}个工具)")
        if sk.get("skills"):
            lines.append(f"SKILL.md: {sk.get('skills',0)}个")
        if sk.get("promoted", 0):
            lines.append(f"🏆 技能晋升: {sk['promoted']}个")
        if sk.get("skipped", 0) and not sk.get("promoted", 0):
            pass  # skipped is normal (most skills don't qualify)

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
            "已启动！每小时：工具分析 · README同步 · 技能整理+晋升 · 跨主题记忆提取",
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
            "tasks": ["工具使用分析", "README同步", "技能整理+晋升", "跨主题记忆提取"],
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
            "description": "自进化后台线程 — 每小时自动运行：①工具使用率分析&优化建议 ②docs/TOOLS.md同步 ③技能模式整理 ④跨主题记忆提取。替代旧的潜意识引擎。",
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
