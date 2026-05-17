"""
AgentCore — Tea Agent 共享核心基类。

CLI (tea_main_cli.TeaCLI) 和 GUI (main_db_gui.TkGUI) 均继承此类，
消除重复代码。包含：
  - 配置加载、目录初始化、Storage/Toolkit 初始化
  - 对话后处理流水线（入库、Token 统计、摘要）
"""

import os
import sys
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, List, cast

logger = logging.getLogger("agent_core")

from tea_agent.onlinesession import OnlineToolSession
from tea_agent.store import Storage
from tea_agent import tlk
from tea_agent.config import load_config, get_config


class AgentCore:
    # 2026-05-17 gen by tea_agent, 主题漂移累计达到此阈值时建议用户开新主题
    DRIFT_SUGGEST_THRESHOLD = 3
    """Tea Agent 共享核心 — CLI 和 GUI 的公共基类。

    子类需实现:
      - _on_post_reply(ai_msg, used_tools, topic_id): AI 回复后的 UI 回调
      - _on_init_done(): 初始化完成后的 UI 回调
    """

# NOTE: 2026-05-04 19:33:59, self-evolved by tea_agent --- AgentCore.__init__ 增加 _shutting_down 标志位，用于安全重启前阻止新操作
# NOTE: 2026-05-07 11:26:49, self-evolved by tea_agent --- AgentCore.__init__ 中集成 setup_logging，并添加模型调用/失败的 DEBUG/WARNING 日志
    def __init__(self, debug: bool = False, config_path: Optional[str] = None):
# NOTE: 2026-05-07 11:35:37, self-evolved by tea_agent --- setup_logging 调用传入 debug=self.debug，默认 INFO，debug=True 时 DEBUG
        # ── 尽早初始化文件日志，确保后续所有 logger 都有文件 handler ──
        from tea_agent.logging_setup import setup_logging
        self.debug = debug
        setup_logging(debug=self.debug)
        self.generating = False
# NOTE: 2026-05-06 09:57:03, self-evolved by tea_agent --- __init__添加_pending_restart标记，支持watchdog延迟重启
        self._shutting_down = False  # 重启前安全闸门
        self._pending_restart = False  # watchdog延迟重启：会话中检测到变更时置True，会话结束后检查
        self._config_path = config_path

        # ── 1. 加载配置 ──
        self._cfg = load_config(config_path) if config_path else load_config()
        if not self._cfg.main_model.is_configured:
            print("错误: 请配置主模型 (main_model)")
            print(f"  编辑 {config_path or '$HOME/.tea_agent/config.yaml 或 tea_agent/config.yaml'}")
            sys.exit(1)

        # ── 2. 初始化目录 ──
        cfg = self._cfg
        root_path = Path(cfg.paths.data_dir_abs)
        root_path.mkdir(parents=True, exist_ok=True)
        tool_dir = Path(cfg.paths.toolkit_dir_abs)
        tool_dir.mkdir(parents=True, exist_ok=True)

        # ── 3. 初始化 Storage 和 Toolkit ──
        db_path = Path(cfg.paths.db_path_abs)
        self.db = Storage(db_path=str(db_path))
        self.toolkit = tlk.Toolkit(str(tool_dir))
        tlk._toolkit_ = self.toolkit   ## XXX: _toolkit_ 为 tlk 名字空间下的变量，这里初始化，被
                                       ##   tlk.Toolkit 中的方法使用； 
        tlk.toolkit_reload()

        # ── 5. 会话锁 ──
        self._sess_lock = threading.Lock()

# NOTE: 2026-05-07 13:25:46, self-evolved by tea_agent --- AgentCore.__init__ 增加自动启动潜意识引擎，app 启动后后台每小时循环
        # ── 6. 初始化会话 ──
        # NOTE: 2026-05-10 gen by tea_agent, 修复类型：str→int，防止 chat_stream TypeError
        self.current_topic_id: int = 0
        self._init_session()

        # ── 7. 启动潜意识引擎（后台每小时：总结/反思/创意/头脑风暴）──
        self._start_subconscious()

        # ── 7b. 启动定时任务调度器（后台每分钟检查执行）──
        self._start_scheduler()

# NOTE: 2026-05-04 19:26:41, self-evolved by tea_agent --- AgentCore 添加 _start_file_watcher() — 监控非 toolkit 的 .py 变更并自动重启进程
        # ── 8. 启动文件监控（代码变更自动重启）──
        self._start_file_watcher()

# NOTE: 2026-05-04 19:27:06, self-evolved by tea_agent --- 添加 _start_file_watcher 方法实现 — watchdog 监控 + os.execv 重启
    # ═══════════════════════════════════════════════
    # 文件监控（非 toolkit .py 变更 → 自动重启）
    # ═══════════════════════════════════════════════
    def _start_file_watcher(self):
        """启动文件监控：非 toolkit/ 目录的 .py 文件变更时自动重启进程。

        使用 watchdog 库递归监控 tea_agent 包目录。
        排除 toolkit/ 子目录 — 工具文件用 toolkit_reload() 热加载即可。
        检测到变更后防抖 2 秒，然后 os.execv 原地替换进程。
        """
        try:
            import watchdog.events
            import watchdog.observers
        except ImportError:
            logger.warning("watchdog 未安装，跳过文件监控，不支持自动重启")
            return

        tea_agent_dir = Path(__file__).parent  # tea_agent/ 包目录

        class _RestartHandler(watchdog.events.FileSystemEventHandler):
            def __init__(self, agent):
                self._agent = agent
                self._timer: Optional[threading.Timer] = None
                self._lock = threading.Lock()

# NOTE: 2026-05-06 09:57:16, self-evolved by tea_agent --- on_modified增加generating检查：会话中仅标记待重启，不立即执行
            def on_modified(self, event):
                if event.is_directory:
                    return
                src = event.src_path
                if not src.endswith('.py'):
                    return
                # 排除 toolkit/ 子目录 — 工具用 toolkit_reload() 热更
                if '/toolkit/' in src or '\\toolkit\\' in src:
                    return
                logger.info(f"🔄 检测到文件变更: {src}")
                if self._agent.generating:
                    self._agent._pending_restart = True
                    logger.info("⏸ 当前会话进行中，标记待重启，会话结束后自动执行")
                else:
                    self._schedule_restart()

# NOTE: 2026-05-06 09:57:44, self-evolved by tea_agent --- 提取_do_restart为_safe_restart方法，添加_check_pending_restart延迟重启入口
            def _schedule_restart(self):
                with self._lock:
                    if self._timer:
                        self._timer.cancel()
                    self._timer = threading.Timer(2.0, self._do_restart)
                    self._timer.daemon = True
                    self._timer.start()

            def _do_restart(self):
                self._agent._safe_restart()

        handler = _RestartHandler(self)
        observer = watchdog.observers.Observer()
        observer.schedule(handler, str(tea_agent_dir), recursive=True)
        observer.daemon = True
        observer.start()
# NOTE: 2026-05-06 09:58:12, self-evolved by tea_agent --- 添加_safe_restart和_check_pending_restart方法到AgentCore
        logger.info("📁 文件监控已启动（非 toolkit .py 变更时自动重启）")

    def _safe_restart(self):
        """数据安全重启（由 watchdog 或 _check_pending_restart 触发）：
        1. 设 _shutting_down 闸门，阻止新操作
        2. 等待 _sess_lock（最长 10s），确保当前 chat_stream 完成
        3. WAL checkpoint(TRUNCATE) 刷盘 → close DB
        4. 跨平台重启进程
        """
        import subprocess
        import time as _time

        # ── 1. 设闸门 ──
        self._shutting_down = True
        logger.info("🔁 收到重启信号，等待活跃操作完成...")

        # ── 2. 等待 _sess_lock（chat_stream 释放锁后 DB 写入已完成）──
        if hasattr(self, '_sess_lock'):
            deadline = _time.monotonic() + 10.0  # 最多等10秒
            acquired = False
            while _time.monotonic() < deadline:
                if self._sess_lock.acquire(blocking=False):
                    acquired = True
                    self._sess_lock.release()
                    break
                _time.sleep(0.1)
            if not acquired:
                logger.warning("等待会话锁超时（10s），强制关闭")

        # ── 3. 安全关闭数据库 ──
        try:
            if hasattr(self, 'db') and self.db:
                self.db.close()  # 内含 WAL checkpoint(TRUNCATE)
                logger.info("数据库已安全关闭")
        except Exception as e:
            logger.warning(f"关闭数据库异常 (非致命): {e}")

        # ── 4. 跨平台重启 ──
        print("\n🔁 代码已变更，正在重启...\n", flush=True)
        logger.warning("🔁 代码已变更，正在重启...")
        args = [sys.executable] + sys.argv
        if sys.platform == 'win32':
            subprocess.Popen(args, close_fds=True)
            os._exit(0)
        else:
            os.execv(sys.executable, args)

# NOTE: 2026-05-07 13:26:33, self-evolved by tea_agent --- 新增 _start_subconscious 方法：启动潜意识引擎 daemon 线程（每小时总结/反思）
    def _check_pending_restart(self):
        """会话结束后调用：检查 watchdog 是否在会话期间标记了待重启。"""
        if self._pending_restart:
            self._pending_restart = False
            logger.info("🔁 会话已完成，执行待定重启...")
            self._safe_restart()

    def _start_subconscious(self):
        """自动启动潜意识引擎 daemon 线程。

        每小时一次后台循环：消化记忆 → 对话提取 → 交叉关联 → 生成洞察 → 设定目标。
        场景自适应：bug期收敛务实分析，创意期发散联想。
        启动失败不阻塞主流程。
        """
        try:
            # 在 toolkit 目录找 toolkit_subconscious.py
            import importlib.util
            fpath = os.path.join(self.toolkit.root_dir, "toolkit_subconscious.py")
            if not os.path.exists(fpath):
                logger.debug(f"潜意识引擎文件不存在: {fpath}")
                return
            spec = importlib.util.spec_from_file_location("_subconscious_startup", fpath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.toolkit_subconscious("start")
            if result.get("status") == "started":
                logger.info("🧠 潜意识引擎已自动启动 | 间隔1小时 | 场景自适应")
            elif result.get("status") == "already_running":
                logger.info(
                    f"🧠 潜意识引擎已在运行中 "
                    f"| 周期: {result.get('cycles_completed', 0)}"
                )
            else:
                logger.debug(f"潜意识引擎状态: {result.get('status')}")
        except Exception as e:
            # 启动失败不影响主体功能
            logger.debug(f"潜意识引擎自动启动跳过: {e}")

    # NOTE: 2026-05-16 gen by tea_agent, 定时任务调度器 auto-start
    def _start_scheduler(self):
        """启动定时任务调度器 daemon 线程，每分钟检查一次。"""
        try:
            from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
            result = toolkit_scheduler("start")
            status = result.get("status", "unknown")
            if status == "already_running":
                logger.info(f"⏰ 定时任务调度器已在运行中 (pid={result.get('pid')})")
            else:
                logger.info(f"⏰ 定时任务调度器已自动启动")
        except Exception as e:
            logger.debug(f"定时任务调度器自动启动跳过: {e}")

# NOTE: 2026-05-15 08:11:30, self-evolved by tea_agent --- _init_session 从 main_model.options 读取 supports_vision 传递给 OnlineToolSession
    def _init_session(self):
        """初始化 OnlineToolSession。子类可覆盖以添加 UI 回调。"""
        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model
# NOTE: 2026-05-16 19:33:10, self-evolved by tea_agent --- _init_session 从 options 读取 supports_reasoning 传给 OnlineToolSession
        # NOTE: 2026-05-18 gen by tea_agent, 从 options 读取 supports_vision
        supports_vision = main_m.options.get("supports_vision", False) if main_m.options else False
        # NOTE: 2026-05-20 gen by tea_agent, 从 options 读取 supports_reasoning
        supports_reasoning = main_m.options.get("supports_reasoning", True) if main_m.options else True
        self.sess = OnlineToolSession(
            toolkit=self.toolkit,
            api_key=cast(str, main_m.api_key),
            api_url=cast(str, main_m.api_url),
            model=cast(str, main_m.model_name),
            max_history=cfg.max_history,
            max_iterations=cfg.max_iterations,
            keep_turns=cfg.keep_turns,
            max_tool_output=cfg.max_tool_output,
            max_assistant_content=cfg.max_assistant_content,
            extra_iterations_on_continue=cfg.extra_iterations_on_continue,
            memory_extraction_threshold=cfg.memory_extraction_threshold,
            storage=self.db,
            cheap_api_key=cast(str, cheap_m.api_key),
            cheap_api_url=cast(str, cheap_m.api_url),
            cheap_model=cast(str, cheap_m.model_name),
# NOTE: 2026-05-16 19:33:14, self-evolved by tea_agent --- 传递 supports_reasoning 参数到 OnlineToolSession
            enable_thinking=cfg.enable_thinking,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
        )

        import tea_agent.session_ref as _sref
        _sref.set_session(self.sess)
        _sref.set_agent(self)  # NOTE: 2026-05-08 09:20:09, self-evolved by tea_agent --- 供 toolkit 函数访问 current_topic_id / db

    def _init_session_info_str(self) -> str:
        """返回会话初始化信息字符串（子类用于显示）。"""
        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model
        cheap_info = f" | 摘要: {cheap_m.model_name}" if cheap_m.model_name else ""
        return f"📡 已连接 | 模型: {main_m.model_name}{cheap_info}\n🔧 工具: {len(self.toolkit.func_map)} 个已加载"

    # ═══════════════════════════════════════════════
    # 对话后处理流水线（入库 → Token → 摘要）
    # ═══════════════════════════════════════════════
    @staticmethod
    def _extract_files_from_rounds(rounds: list) -> list:
        """从工具调用轮次中提取触碰的文件路径列表。

        扫描 tool_calls 中的参数，提取文件路径。
        覆盖 toolkit_file(filename=), toolkit_self_evolve(file_path=), 
        toolkit_exec(args containing paths) 等。
        """
        import re, json as _json
        files = []
        seen = set()
        # 工具参数名 → 文件路径模式的映射
        FILE_ARG_NAMES = {'filename', 'file_path', 'path', 'file', 'directory'}
        # 排除非文件路径的参数值
        SKIP_VALUES = {'.', '..', '/', 'true', 'false'}

        if not rounds:
            return files

        for rd in rounds:
            # 从 assistant tool_calls 中提取
            tool_calls = rd.get('tool_calls', [])
            if not tool_calls:
                continue
            for tc in tool_calls:
                fn = tc.get('function', {})
                fn_name = fn.get('name', '')
                args_str = fn.get('arguments', '{}')
                try:
                    args = _json.loads(args_str) if isinstance(args_str, str) else args_str
                except _json.JSONDecodeError:
                    continue
                if not isinstance(args, dict):
                    continue

                # 从已知参数名提取路径
                for key in FILE_ARG_NAMES:
                    val = args.get(key)
                    if isinstance(val, str) and val not in SKIP_VALUES and len(val) > 1:
                        # 检查是否像文件路径（含扩展名或目录分隔符）
                        if '.' in val or '/' in val or '\\' in val:
                            if val not in seen:
                                files.append(val)
                                seen.add(val)

                # 从 cmd/args 中额外提取路径（toolkit_exec）
                cmd = args.get('cmd', '') or args.get('command', '')
                if cmd and isinstance(cmd, str):
                    # 匹配常见的文件路径模式
                    for m in re.finditer(r'[a-zA-Z0-9_./\\-]+\.py\b', cmd):
                        fp = m.group()
                        if fp not in seen:
                            files.append(fp)
                            seen.add(fp)

        return files

    def _post_chat_pipeline(self, ai_msg: str, used_tools: bool,
                            user_msg, topic_id: str) -> None:
        """AI 回复后流水线。1.入库 2.三级推送 3.Token 4.摘要
        user_msg 可为 str 或 {"text": str, "images": [str]}（图片附件）。
        """
        # NOTE: 2026-05-15 gen by tea_agent, 支持图片消息入库
        conv_id = self.db.save_msg(topic_id, user_msg, "", False)
        rounds = self.sess._rounds_collector
        self.db.update_msg_rounds(
            conversation_id=conv_id, ai_msg=ai_msg,
            is_func_calling=used_tools, rounds=rounds if rounds else None,
        )
        # Level 2 push: push OLD L1 (previous conversation) to Level 2
        prev_convs = self.db.get_conversations(topic_id, limit=2, include_rounds=True)
        if len(prev_convs) >= 2:
            old_l1 = prev_convs[-2]
            # 从旧 L1 的 tool calls 中提取触碰文件，用于文件级语义匹配
            old_rounds = old_l1.get('rounds_json_parsed') or []
            old_files = self._extract_files_from_rounds(old_rounds)
            overflow = self.db.push_to_level2(
                topic_id, old_l1["user_msg"], old_l1["ai_msg"], files=old_files
            )
            if overflow:
                logger.info(f"Level 2 overflow {len(overflow)} -> L3 (topic={topic_id})")
                self._update_level3_summary(topic_id, overflow)
        # Token stats
        usage = self.sess._last_usage
        cheap_usage = self.sess._last_cheap_usage
        if usage and usage.get("total_tokens", 0) > 0:
            try:
                from tea_agent.embedding_util import get_embedding_engine
                emb_engine = get_embedding_engine()
                emb_usage = emb_engine.get_embedding_usage(reset=True)
                emb_tokens = emb_usage.get("total_tokens", 0)
                emb_prompt = emb_usage.get("prompt_tokens", 0)
            except Exception:
                emb_tokens = 0; emb_prompt = 0
            self.db.add_topic_tokens(
                topic_id, total_tokens=usage["total_tokens"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                cheap_tokens=cheap_usage.get("total_tokens", 0),
                cheap_prompt_tokens=cheap_usage.get("prompt_tokens", 0),
                cheap_completion_tokens=cheap_usage.get("completion_tokens", 0),
                embedding_tokens=emb_tokens, embedding_prompt_tokens=emb_prompt,
            )
        self._auto_summary(topic_id)
        # 2026-05-17 gen by tea_agent, 主题漂移累计达阈值时建议新主题
        self._suggest_new_topic_if_needed(topic_id)
        self._check_pending_restart()

    def _update_level3_summary(self, topic_id: str, overflow: list):
        """L3 增量摘要：语义 + 工具链。
        2026-05-17 gen by tea_agent, 重构：(1)去除字数限制改用16K token上限 (2)主题漂移检测-匹配度低时追加新段落而非全量覆盖
        """
        if not overflow:
            return
        try:
            cli, mdl = self.sess._get_summarize_client()

            new_text = ""
            for pair in overflow:
                new_text += f"User: {pair.get('user', '')}\nAssistant: {pair.get('assistant', '')}\n\n"

            old_sem = self.db.get_semantic_summary(topic_id) or ""

            # ── 主题漂移检测 ──
            is_drift = False
            drift_label = ""
            if old_sem.strip():
                drift_prompt = (
                    "对比「已有摘要」与「新对话片段」，判断新对话的主题是否发生本质变化。\n"
                    "本质变化：讨论方向、任务类型、关注领域发生明显转移。\n"
                    "如果显著变化，输出 DRIFT: <新阶段简短主题名>。否则输出 SAME。\n"
                    f"[已有摘要末尾]\n{old_sem[-3000:]}\n\n"
                    f"[新对话片段]\n{new_text[:3000]}\n\n"
                    "请输出 DRIFT: <主题名> 或 SAME："
                )
                try:
                    r_d = cli.chat.completions.create(
                        model=mdl, messages=[{"role": "user", "content": drift_prompt}],
                        temperature=0.1, max_tokens=50,
                    )
                    dr = (r_d.choices[0].message.content or "").strip() if r_d.choices else "SAME"
                    if dr.upper().startswith("DRIFT"):
                        is_drift = True
                        drift_label = dr.replace("DRIFT:", "").replace("DRIFT", "").strip().lstrip(":").strip() or "新阶段"
                        # 递增漂移计数
                        new_count = self.db.increment_drift_count(topic_id)
                        if new_count >= self.DRIFT_SUGGEST_THRESHOLD:
                            self._pending_topic_suggestion = new_count
                    logger.info(f"L3 drift check: {dr[:60]}")
                except Exception as de:
                    logger.warning(f"L3 drift check fail: {de}, assume SAME")

            # ── A. 语义摘要 ──
            if is_drift:
                sem_prompt = (
                    "以下是一个长对话的历史摘要。由于新对话主题发生了显著变化，"
                    "请在现有摘要基础上追加一个新段落（不要删除或修改历史段落）。"
                    f"新段落标题为 '## 阶段：{drift_label}'。\n"
                    "新段落格式：\n"
                    "- 本阶段核心主题：...\n"
                    "- 用户偏好/约束：...\n"
                    "- 任务背景与目标：...\n"
                    "- 关键步骤与进展：...\n"
                    "- 重要结论/产出：...\n"
                    "- 使用的关键文件/模块：...\n\n"
                    f"[已有摘要——全部保留，不可删除]\n{old_sem}\n\n"
                    f"[新对话片段]\n{new_text}\n\n"
                    "请输出完整摘要（保留全部历史段落 + 追加新阶段段落）："
                )
            else:
                sem_prompt = (
                    "更新对话摘要。如果已有摘要包含多个 '## 阶段：' 段落，"
                    "请保留所有历史段落不变，仅更新/补充最后一个段落的末尾。\n"
                    "如果历史段落已完整覆盖新对话内容，仅追加新的进展点。\n"
                    "聚焦：用户偏好、长期任务背景、关键结论、领域知识、涉及的文件/模块。\n"
                    "使用 Markdown 格式，以 '## ' 开头的段落组织。\n"
                    "不要删除或截断任何已有内容。\n"
                    f"[已有摘要]\n{old_sem if old_sem else '(无)'}\n\n"
                    f"[新对话]\n{new_text}\n\n"
                    "请输出更新后的完整摘要："
                )

            r = cli.chat.completions.create(
                model=mdl, messages=[{"role": "user", "content": sem_prompt}],
                temperature=0.3, max_tokens=16384,
            )
            new_sem = r.choices[0].message.content.strip() if r.choices else old_sem or ""
            if new_sem:
                self.db.set_semantic_summary(topic_id, new_sem)
                logger.info(f"L3 semantic: {len(new_sem)} chars (drift={is_drift}, label={drift_label})")

            # ── B. 工具链摘要 ──
            has_tools = any("tool" in (pair.get("assistant", "") or "").lower() for pair in overflow)
            if has_tools:
                old_tc = self.db.get_tool_chain_summary(topic_id) or ""

                if is_drift:
                    tc_prompt = (
                        "追加新的工具调用链段落（保留全部历史段落）。"
                        f"新段落标题为 '## 阶段工具链：{drift_label}'。\n"
                        "格式：\n"
                        "- 任务：...\n"
                        "- 使用工具：A -> B -> C -> ...\n"
                        "- 关键I/O：...\n"
                        "- 最终结论：...\n\n"
                        f"[已有工具链——全部保留]\n{old_tc}\n\n"
                        f"[新对话]\n{new_text}\n\n"
                        "请输出完整工具链摘要（保留全部历史段落 + 追加新段落）："
                    )
                else:
                    tc_prompt = (
                        "更新工具调用链摘要。保留所有历史段落，在最后补充新工具调用信息。\n"
                        "如有新任务，追加新的段落。格式：每个段落以 '## ' 标题开头。\n"
                        f"[已有]\n{old_tc if old_tc else '(无)'}\n\n"
                        f"[新对话]\n{new_text}\n\n"
                        "请输出更新后的完整工具链摘要："
                    )

                r2 = cli.chat.completions.create(
                    model=mdl, messages=[{"role": "user", "content": tc_prompt}],
                    temperature=0.3, max_tokens=16384,
                )
                new_tc = r2.choices[0].message.content.strip() if r2.choices else old_tc or ""
                if new_tc and new_tc != "\u65e0" and new_tc != "NONE":
                    self.db.set_tool_chain_summary(topic_id, new_tc)
                    logger.info(f"L3 toolchain: {len(new_tc)} chars")

        except Exception as e:
            logger.warning(f"L3 summary fail: {type(e).__name__}: {e}")
    def _load_topic_history_into_session(self, tid: str):
        """将指定 topic 的对话历史按三级结构加载到 session"""
        # Level 1: 最新一条完整对话（含工具链）
        all_light = self.db.get_conversations(tid, limit=-1, include_rounds=False)
        if all_light:
            total = len(all_light)
            recent = self.db.get_conversations(tid, limit=1, include_rounds=True)
            if recent:
                all_light[-1] = recent[-1]
            level2 = self.db.get_level2(tid)
            semantic = self.db.get_semantic_summary(tid)
            tool_chain = self.db.get_tool_chain_summary(tid)
            old_summary = self.db.get_topic_summary(tid) or ""
            self.sess.load_history(
                all_light, summary=old_summary,
                level2=level2, semantic_summary=semantic,
                tool_chain_summary=tool_chain,
            )
        else:
            self.sess.messages = [{"role": "system", "content": self.sess.system_prompt}]
            self.sess._history_summary = ""
            self.sess._semantic_summary = ""
            self.sess._tool_chain_summary = ""
            self.sess._level2 = []
        self.current_topic_id = tid

    # ═══════════════════════════════════════════════
    # 摘要
    # ═══════════════════════════════════════════════
    def _auto_summary(self, topic_id: str = None):
        """自动生成主题摘要。CLI/GUI 共用核心逻辑，子类加 UI 回调。"""
        if topic_id is None:
            topic_id = self.current_topic_id
        if not topic_id:
            return
        # NOTE: 2026-05-08 09:20:53, self-evolved by tea_agent --- 手动设置标题（※前缀）时跳过自动摘要
        tp = self.db.get_topic(topic_id)
        if tp and (tp.get("title") or "").startswith("※"):
            logger.debug(f"跳过自动摘要: topic={topic_id} 标题为手动设置 (※前缀)")
            return
# NOTE: 2026-05-06 10:23:01, self-evolved by tea_agent --- _auto_summary 摘要输入从3条改为10条对话，确保足够上下文
        recent = self.db.get_recent_conversations(topic_id, limit=10)
        if not recent:
            return
# NOTE: 2026-05-07 11:27:01, self-evolved by tea_agent --- _auto_summary 添加模型调用 DEBUG 日志
        try:
            cli, mdl = self.sess._get_summarize_client()
            # 2026-05-06 gen by tea_agent, debug: check what client/model is being used
            logger.debug(f"call summarize model: {mdl}, topic={topic_id}, msgs={len(recent)}")
            from tea_agent.main_db_gui import _generate_topic_summary
            summary = _generate_topic_summary(client=cli, model=mdl, conversations=recent)
# NOTE: 2026-05-06 10:35:56, self-evolved by tea_agent --- _auto_summary 添加异常日志，不再静默吞错
            if summary:
                self.db.update_topic_title(topic_id, summary)
                logger.info(f"📝 主题摘要更新: topic={topic_id} → {summary}")
                self._on_summary_updated(topic_id, summary)
            else:
                logger.warning(f"摘要生成返回空: topic={topic_id}, model={mdl}, msgs={len(recent)}")
        except Exception as e:
            logger.warning(f"自动摘要失败 (topic={topic_id}): {type(e).__name__}: {e}")

    def _suggest_new_topic_if_needed(self, topic_id: str):
        """2026-05-17 gen by tea_agent, 检查主题漂移计数，达阈值时建议用户开新主题。
        子类可覆盖以自定义 UI 提示。"""
        count = getattr(self, '_pending_topic_suggestion', 0)
        if count > 0:
            logger.info(
                f"\n💡 本主题已切换 {count} 次讨论方向 (阈值={self.DRIFT_SUGGEST_THRESHOLD})，"
                f"建议 /new 开新主题以保持上下文聚焦。"
            )
            self._pending_topic_suggestion = 0  # 重置，每个主题只提醒一次

    def _on_summary_updated(self, topic_id: str, summary: str):
        """摘要更新后的 UI 回调（子类覆盖）。"""
        pass
