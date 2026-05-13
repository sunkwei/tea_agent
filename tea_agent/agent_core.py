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

    def _init_session(self):
        """初始化 OnlineToolSession。子类可覆盖以添加 UI 回调。"""
        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model
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
            enable_thinking=cfg.enable_thinking,
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
    def _post_chat_pipeline(self, ai_msg: str, used_tools: bool,
                            user_msg: str, topic_id: str) -> None:
        """AI 回复后流水线。1.入库 2.三级推送 3.Token 4.摘要"""
        conv_id = self.db.save_msg(topic_id, user_msg, "", False)
        rounds = self.sess._rounds_collector
        self.db.update_msg_rounds(
            conversation_id=conv_id, ai_msg=ai_msg,
            is_func_calling=used_tools, rounds=rounds if rounds else None,
        )
        # Level 2 push: 获取上一轮（旧 Level 1）推入 Level 2
        prev_convs = self.db.get_conversations(topic_id, limit=2, include_rounds=False)
        if len(prev_convs) >= 2:
            old_l1 = prev_convs[-2]
            overflow = self.db.push_to_level2(
                topic_id, old_l1["user_msg"], old_l1["ai_msg"]
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
        self._check_pending_restart()

    def _update_level3_summary(self, topic_id: str, overflow: list):
        if not overflow:
            return
        try:
            cli, mdl = self.sess._get_summarize_client()
            old_text = ""
            for pair in overflow:
                old_text += f"User: {pair.get('user', '')}\nAssistant: {pair.get('assistant', '')}\n\n"
            old_sem = self.db.get_semantic_summary(topic_id)
            sem_prompt = (
                "更新此前对话摘要（长期偏好/任务背景/关键结论，<=300字，中文）："
                f"\n[已有]\n{old_sem if old_sem else '(无)'}"
                f"\n[新对话]\n{old_text}"
            )
            r = cli.chat.completions.create(
                model=mdl, messages=[{"role": "user", "content": sem_prompt}],
                temperature=0.3, max_tokens=512,
            )
            new_sem = r.choices[0].message.content.strip() if r.choices else old_sem or ""
            self.db.set_semantic_summary(topic_id, new_sem)
            logger.info(f"L3 semantic: {len(new_sem)} chars")
            has_tools = any("tool" in pair.get("assistant", "").lower() for pair in overflow)
            if has_tools:
                old_tc = self.db.get_tool_chain_summary(topic_id)
                tc_prompt = (
                    "更新工具调用链摘要（工具名/关键I/O/结论，<=200字，中文，无工具则说无）："
                    f"\n[已有]\n{old_tc if old_tc else '(无)'}"
                    f"\n[新对话]\n{old_text}"
                )
                r2 = cli.chat.completions.create(
                    model=mdl, messages=[{"role": "user", "content": tc_prompt}],
                    temperature=0.3, max_tokens=384,
                )
                new_tc = r2.choices[0].message.content.strip() if r2.choices else old_tc or ""
                if new_tc and new_tc != "\u65e0":
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

    def _on_summary_updated(self, topic_id: str, summary: str):
        """摘要更新后的 UI 回调（子类覆盖）。"""
        pass
