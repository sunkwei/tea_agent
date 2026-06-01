"""
统一 Agent 类 — 合并 TeaAgent + AgentCore

支持两种模式：
- lightweight: 无存储、无后台线程，适合孤立任务
- full: 有存储、有后台线程，适合 CLI/GUI

用法:
    # 轻量模式（原 TeaAgent）
    with Agent(mode='lightweight') as agent:
        rounds = agent.chat("你好")

    # 完整模式（原 AgentCore）
    agent = Agent(mode='full')
    agent.chat("你好", topic_id="xxx")

    # 向后兼容
    from tea_agent import TeaAgent  # 现在是 Agent 的别名
"""

import os
import sys
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Callable, cast

logger = logging.getLogger("agent")


class Agent:
    """统一 Agent 类 — 支持 lightweight/full 两种模式。

    Args:
        mode: 'lightweight' (无存储) 或 'full' (有存储+后台线程)
        config_path: 配置文件路径
        callback: 中间轮次回调（lightweight 模式常用）
        use_tools: 是否启用工具调用
        enable_thinking: 是否启用思考链
        disable_summary: 禁用历史压缩
        no_stream_chunk: 禁用流式分块
        debug: 调试模式
    """

    def __init__(
        self,
        mode: str = "lightweight",
        config_path: Optional[str] = None,
        callback: Optional[Callable[[Dict], None]] = None,
        use_tools: bool = True,
        enable_thinking: bool = True,
        disable_summary: bool = False,
        no_stream_chunk: bool = False,
        debug: bool = False,
    ):
        if mode not in ("lightweight", "full"):
            raise ValueError(f"mode 必须是 'lightweight' 或 'full'，收到: {mode}")

        from tea_agent.logging_setup import setup_logging
        self.mode = mode
        self.debug = debug
        self.disable_summary = disable_summary
        self.no_stream_chunk = no_stream_chunk
        setup_logging(debug=debug)

        self._callback = callback
        self._generating = False
        self._sess_lock = threading.Lock()
        self._toolkit = None
        self._sess = None
        self._use_tools = use_tools
        self._enable_thinking = enable_thinking
        self._db = None  # 仅 full 模式使用

        # ── 加载配置 ──
        self._cfg = self._load_config(config_path)

        # ── 初始化 Toolkit ──
        self._init_toolkit()

        # ── 初始化 Storage（仅 full 模式）──
        if mode == "full":
            self._init_storage()

        # ── 初始化会话 ──
        self._init_session()

        # ── 启动后台服务（仅 full 模式）──
        if mode == "full":
            self._start_background_services()

    @property
    def sess(self):
        """向后兼容：返回底层会话对象。"""
        return self._sess

    @sess.setter
    def sess(self, value):
        """向后兼容：允许设置底层会话对象。"""
        self._sess = value

    @property
    def toolkit(self):
        """向后兼容：返回 Toolkit 实例。"""
        return self._toolkit

    @property
    def db(self):
        """向后兼容：返回 Storage 实例（仅 full 模式）。"""
        return self._db

    def _init_session_info_str(self) -> str:
        """向后兼容：返回会话初始化的摘要。"""
        main_m = self._cfg.main_model
        return (
            f"Mode: {self.mode} | "
            f"Model: {main_m.model_name} | "
            f"Tools: {'ON' if self.mode == 'full' or self._use_tools else 'OFF'}"
        )

    def _load_topic_history_into_session(self, topic_id: str):
        """向后兼容：桥接到 load_topic_history。"""
        return self.load_topic_history(topic_id)

    # ═══════════════════════════════════════════════
    # 配置加载
    # ═══════════════════════════════════════════════
    def _load_config(self, config_path: Optional[str]):
        """加载并验证配置。"""
        from tea_agent.config import load_config

        if config_path:
            if not os.path.isfile(config_path):
                raise FileNotFoundError(f"配置文件不存在: {config_path}")
            actual_path = config_path
        else:
            default_path = str(Path.home() / ".tea_agent" / "config.yaml")
            fallback_path = str(Path(__file__).parent / "config.yaml")
            if os.path.isfile(default_path):
                actual_path = default_path
            elif os.path.isfile(fallback_path):
                actual_path = fallback_path
            else:
                raise FileNotFoundError(
                    f"未找到配置文件。请在以下位置之一创建 config.yaml:\n"
                    f"  1) {default_path}\n"
                    f"  2) {fallback_path}"
                )

        cfg = load_config(actual_path)

        main_m = cfg.main_model
        if not main_m.is_configured:
            raise ValueError(
                f"main_model 配置不完整:\n"
                f"  api_key: {'✓' if main_m.api_key else '✗'}\n"
                f"  api_url: {'✓' if main_m.api_url else '✗'}\n"
                f"  model:   {'✓' if main_m.model_name else '✗'}\n"
                f"  config:  {actual_path}"
            )

        logger.info(f"配置加载: {actual_path} | 模型: {main_m.model_name}")
        return cfg

    # ═══════════════════════════════════════════════
    # Toolkit 初始化
    # ═══════════════════════════════════════════════
    def _init_toolkit(self):
        """初始化 Toolkit 和 KB 目录。"""
        from tea_agent import tlk

        cfg = self._cfg
        tool_dir = Path(cfg.paths.toolkit_dir_abs)
        tool_dir.mkdir(parents=True, exist_ok=True)
        kb_dir = Path(cfg.paths.kb_dir_abs)
        kb_dir.mkdir(parents=True, exist_ok=True)

        self._toolkit = tlk.Toolkit(str(tool_dir))
        tlk._toolkit_ = self._toolkit
        tlk.toolkit_reload()

        logger.info(
            f"Toolkit 初始化 | 工具: {len(self._toolkit.func_map)} 个 | "
            f"toolkit_dir: {tool_dir} | kb_dir: {kb_dir}"
        )

    # ═══════════════════════════════════════════════
    # Storage 初始化（仅 full 模式）
    # ═══════════════════════════════════════════════
    def _init_storage(self):
        """初始化 Storage 数据库。"""
        from tea_agent.store import Storage

        cfg = self._cfg
        db_path = Path(cfg.paths.db_path_abs)
        self._db = Storage(db_path=str(db_path))
        logger.info(f"Storage 初始化 | db: {db_path}")

    # ═══════════════════════════════════════════════
    # 会话初始化
    # ═══════════════════════════════════════════════
    def _init_session(self):
        """初始化 OnlineToolSession。"""
        from tea_agent.onlinesession import OnlineToolSession
        import tea_agent.session_ref as _sref

        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model

        _options = getattr(main_m, 'options', {}) or {}
        supports_vision = _options.get('supports_vision', False) if isinstance(_options, dict) else False
        supports_reasoning = _options.get('supports_reasoning', True) if isinstance(_options, dict) else True

        self._sess = OnlineToolSession(
            toolkit=self._toolkit,
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
            storage=self._db,  # None for lightweight, Storage for full
            cheap_api_key=cast(str, cheap_m.api_key),
            cheap_api_url=cast(str, cheap_m.api_url),
            cheap_model=cast(str, cheap_m.model_name),
            enable_thinking=self._enable_thinking,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            disable_summary=self.disable_summary,
            no_stream_chunk=self.no_stream_chunk,
        )

        _sref.set_session(self._sess, setter=f"Agent({self.mode})")
        _sref.set_agent(self, setter=f"Agent({self.mode})")

        # lightweight 模式不使用工具：清空工具列表
        if self.mode == "lightweight" and not self._use_tools:
            self._sess.tools = []

        logger.info(
            f"会话初始化 | 模式: {self.mode} | "
            f"主模型: {main_m.model_name} | "
            f"工具: {'开' if self._use_tools or self.mode == 'full' else '关'}"
        )

    # ═══════════════════════════════════════════════
    # 后台服务（仅 full 模式）
    # ═══════════════════════════════════════════════
    def _start_background_services(self):
        """启动潜意识引擎和定时任务调度器。"""
        self._start_subconscious()
        self._start_scheduler()

    def _start_subconscious(self):
        """启动潜意识引擎 daemon 线程。"""
        try:
            import importlib.util
            fpath = os.path.join(self._toolkit.root_dir, "toolkit_subconscious.py")
            if not os.path.exists(fpath):
                return
            spec = importlib.util.spec_from_file_location("_subconscious_startup", fpath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.toolkit_subconscious("start")
            if result.get("status") == "started":
                logger.info("🧠 潜意识引擎已自动启动")
        except Exception as e:
            logger.debug(f"潜意识引擎启动跳过: {e}")

    def _start_scheduler(self):
        """启动定时任务调度器 daemon 线程。"""
        try:
            from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
            toolkit_scheduler("start")
        except Exception as e:
            logger.debug(f"定时任务调度器启动跳过: {e}")

    # ═══════════════════════════════════════════════
    # 工具管理
    # ═══════════════════════════════════════════════
    def toolkit_save(self, name: str, meta: dict, pycode: str) -> bool:
        """添加/更新工具。"""
        result = self._toolkit.call_tool("toolkit_save", name=name, meta=meta, pycode=pycode)
        return bool(result and (isinstance(result, dict) and result.get("ok")))

    def toolkit_reload(self) -> dict:
        """重新加载所有工具并刷新会话工具定义。"""
        result = self._toolkit.call_tool("toolkit_reload")
        if self._sess:
            self._sess._build_tools()
        return result or {"ok": False}

    # ═══════════════════════════════════════════════
    # 回调辅助
    # ═══════════════════════════════════════════════
    def _notify(self, data: Dict):
        """安全调用用户回调。"""
        if self._callback:
            try:
                self._callback(data)
            except Exception as e:
                logger.warning(f"回调执行异常: {e}")

    # ═══════════════════════════════════════════════
    # 对话接口
    # ═══════════════════════════════════════════════
    def chat(
        self,
        user_input: str,
        topic_id: str = "",
        on_status: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        发送用户消息，阻塞直到 AI 返回完整回复。

        Args:
            user_input: 用户输入文本
            topic_id: 主题 ID（full 模式用于入库，lightweight 模式忽略）
            on_status: 状态回调（full 模式用于 GUI）

        Returns:
            本轮对话的所有消息列表
        """
        if self._generating:
            raise RuntimeError("正在生成中，请等待当前对话完成")

        with self._sess_lock:
            self._generating = True
            try:
                return self._chat_impl(user_input, topic_id, on_status)
            finally:
                self._generating = False

    def _chat_impl(
        self,
        user_input: str,
        topic_id: str,
        on_status: Optional[Callable],
    ) -> List[Dict]:
        """chat 的内部实现。"""

        # ── 流式回调 ──
        def stream_cb(text: str):
            if text.startswith("[THINK]"):
                self._notify({"type": "thinking", "text": text[7:]})
            else:
                self._notify({"type": "token", "text": text})

        def status_cb(status_msg: str):
            if status_msg.startswith("!MAX_ITER:"):
                self._sess._continue_after_max = True
                extra = getattr(self._sess.context, "extra_iterations_on_continue", 10)
                self._sess._extra_iterations += extra
                self._sess._max_iter_wait.set()
                self._notify({"type": "status", "text": f"已达最大轮次，自动续命 {extra} 轮..."})
            elif on_status:
                on_status(status_msg)
            else:
                self._notify({"type": "status", "text": status_msg})

        # ── 执行对话 ──
        effective_topic = topic_id if self.mode == "full" else ""
        ai_msg, used_tools = self._sess.chat_stream(
            user_input,
            callback=stream_cb,
            topic_id=effective_topic,
            on_status=status_cb,
        )

        # ── full 模式：后处理流水线 ──
        if self.mode == "full" and self._db and topic_id:
            self._post_chat_pipeline(ai_msg, used_tools, user_input, topic_id)

        # ── 构建返回结果 ──
        rounds = self._sess._rounds_collector
        result: List[Dict] = [{"role": "user", "content": user_input}]
        if rounds:
            result.extend(rounds)

        self._notify({"type": "done", "used_tools": used_tools})
        return result

    # ═══════════════════════════════════════════════
    # 后处理流水线（仅 full 模式）
    # ═══════════════════════════════════════════════
    def _post_chat_pipeline(self, ai_msg: str, used_tools: bool,
                            user_msg, topic_id: str) -> None:
        """AI 回复后流水线：入库 → Token 统计 → 摘要。"""
        if not self._db:
            return

        conv_id = self._db.save_msg(topic_id, user_msg, "", False)
        rounds = self._sess._rounds_collector
        self._db.update_msg_rounds(
            conversation_id=conv_id, ai_msg=ai_msg,
            is_func_calling=used_tools, rounds=rounds if rounds else None,
        )

        # Token stats
        usage = self._sess._last_usage
        if usage and usage.get("total_tokens", 0) > 0:
            self._db.add_topic_tokens(
                topic_id, total_tokens=usage["total_tokens"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
            )

        # 异步摘要
        threading.Thread(
            target=self._do_async_summaries,
            args=(topic_id,),
            daemon=True
        ).start()

    def _do_async_summaries(self, topic_id: str):
        """后台线程：执行摘要。"""
        try:
            self._auto_summary(topic_id)
        except Exception as e:
            logger.warning(f"异步摘要失败: {e}")

    def _auto_summary(self, topic_id: str):
        """自动生成主题摘要。"""
        if not self._db:
            return
        tp = self._db.get_topic(topic_id)
        if tp and (tp.get("title") or "").startswith("※"):
            return
        recent = self._db.get_recent_conversations(topic_id, limit=10)
        if not recent:
            return
        try:
            cli, mdl = self._sess._get_summarize_client()
            from tea_agent._gui._topic_summary import _generate_topic_summary
            summary = _generate_topic_summary(client=cli, model=mdl, conversations=recent)
            if summary:
                self._db.update_topic_title(topic_id, summary)
                logger.info(f"📝 主题摘要更新: {summary}")
        except Exception as e:
            logger.warning(f"自动摘要失败: {e}")

    # ═══════════════════════════════════════════════
    # 历史加载（仅 full 模式）
    # ═══════════════════════════════════════════════
    def load_topic_history(self, topic_id: str):
        """加载指定主题的对话历史到会话。"""
        if self.mode != "full" or not self._db:
            logger.warning("load_topic_history 仅在 full 模式下可用")
            return

        all_light = self._db.get_conversations(topic_id, limit=-1, include_rounds=False)
        if all_light:
            recent = self._db.get_conversations(topic_id, limit=1, include_rounds=True)
            if recent:
                all_light[-1] = recent[-1]
            level2 = self._db.get_level2(topic_id)
            semantic = self._db.get_semantic_summary(topic_id)
            tool_chain = self._db.get_tool_chain_summary(topic_id)
            old_summary = self._db.get_topic_summary(topic_id) or ""
            self._sess.load_history(
                all_light, summary=old_summary,
                level2=level2, semantic_summary=semantic,
                tool_chain_summary=tool_chain,
            )
        else:
            self._sess.messages = [{"role": "system", "content": self._sess.system_prompt}]
            self._sess._history_summary = ""
            self._sess._semantic_summary = ""
            self._sess._tool_chain_summary = ""
            self._sess._level2 = []

    # ═══════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════
    def close(self):
        """安全关闭 Agent，释放资源。"""
        import tea_agent.session_ref as _sref
        _sref.clear()  # 清除所有全局引用
        self._sess = None
        self._toolkit = None
        self._db = None
        logger.info(f"Agent ({self.mode}) 已关闭")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ═══════════════════════════════════════════════
    # 属性
    # ═══════════════════════════════════════════════
    @property
    def config(self):
        """返回当前配置对象。"""
        return self._cfg

    @property
    def toolkit(self):
        """返回 Toolkit 实例。"""
        return self._toolkit

    @property
    def session(self):
        """返回 OnlineToolSession 实例。"""
        return self._sess

    @property
    def db(self):
        """返回 Storage 实例（仅 full 模式）。"""
        return self._db

    @property
    def current_topic_id(self) -> str:
        """返回当前主题 ID。"""
        return getattr(self, '_current_topic_id', '')

    @current_topic_id.setter
    def current_topic_id(self, value: str):
        self._current_topic_id = value


# ═══════════════════════════════════════════════════════════════
# 向后兼容别名
# ═══════════════════════════════════════════════════════════════

def TeaAgent(
    config_path: Optional[str] = None,
    callback: Optional[Callable[[Dict], None]] = None,
    use_tools: bool = False,
    enable_thinking: bool = False,
    debug: bool = False,
) -> Agent:
    """TeaAgent 向后兼容工厂函数。返回 lightweight 模式的 Agent。"""
    return Agent(
        mode="lightweight",
        config_path=config_path,
        callback=callback,
        use_tools=use_tools,
        enable_thinking=enable_thinking,
        debug=debug,
    )
