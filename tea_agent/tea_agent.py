"""

封装与 LLM 对话（含工具调用）的完整流程为单一接口。
无 Storage（不写数据库）、不启动后台线程（Dream 等），
适合创建大量 instances 跑孤立任务，互不影响。

用法:
    from tea_agent import TeaAgent

    with TeaAgent() as agent:
        rounds = agent.chat("帮我查询今天的天气")
        # rounds: [{"role": "user", ...}, {"role": "assistant", ...}, ...]

    # 指定配置
    agent = TeaAgent(config_path="my.yaml")

    # 回调通知
    agent = TeaAgent(callback=lambda d: print(d["type"], d.get("text", "")))
"""

import os
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Callable, cast

logger = logging.getLogger("tea_agent")

class TeaAgent:
    """Tea Agent 对外接口 — 轻量、隔离、无状态持久化。

    特性:
      - 默认使用 $HOME/.tea_agent/config.yaml
      - 仅加载 Toolkit + KB 路径，不启动 Storage / Dream
      - 回调通知中间轮次（流式 token、工具调用、状态变更）
      - 阻塞式 chat()，返回完整轮次列表
      - 支持上下文管理器，自动释放资源
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        callback: Optional[Callable[[Dict], None]] = None,
        use_tools: bool = False,
        enable_thinking: bool = False,
        debug: bool = False,
    ):
        """
        初始化 TeaAgent。

        Args:
            config_path: 配置文件路径，默认 $HOME/.tea_agent/config.yaml。
                         无效则抛出 FileNotFoundError 或 ValueError。
            callback: 中间轮次回调，接收 dict:
                {"type": "token",    "text": "..."}     — 流式 token
                {"type": "thinking", "text": "..."}     — 思考过程
                {"type": "status",   "text": "..."}     — 状态消息
                {"type": "done",     "used_tools": bool} — 本轮完成
            use_tools: 是否启用工具调用，默认 False（纯文本对话）。
                      为 True 时 LLM 可以调用 toolkit_* 工具。
            enable_thinking: 是否启用模型思考链（thinking/reasoning），默认 False。
            debug: 调试模式
        """
        from tea_agent.logging_setup import setup_logging
        self.debug = debug
        setup_logging(debug=debug)

        self._callback = callback
        self._generating = False
        self._sess_lock = threading.Lock()
        self._toolkit = None
        self._sess = None
        self._use_tools = use_tools
        self._enable_thinking = enable_thinking

        # ── 加载配置 ──
        self._cfg = self._load_config(config_path)

        # ── 初始化 Toolkit ──
        self._init_toolkit()

        # ── 初始化会话（无 Storage） ──
        self._init_session()

    # ═══════════════════════════════════════════════
    # 配置加载
    # ═══════════════════════════════════════════════
    def _load_config(self, config_path: Optional[str]):
        """加载并验证配置。无效时抛出异常。"""
        from tea_agent.config import load_config

        actual_path = config_path or str(Path.home() / ".tea_agent" / "config.yaml")

        if config_path:
            if not os.path.isfile(config_path):
                raise FileNotFoundError(f"配置文件不存在: {config_path}")
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
        """仅初始化 Toolkit 和 KB 目录，不初始化 Storage。"""
        from tea_agent import tlk

        cfg = self._cfg

        # 确保 toolkit 目录存在
        tool_dir = Path(cfg.paths.toolkit_dir_abs)
        tool_dir.mkdir(parents=True, exist_ok=True)

        # 确保 kb 目录存在
        kb_dir = Path(cfg.paths.kb_dir_abs)
        kb_dir.mkdir(parents=True, exist_ok=True)

        # Toolkit
        self._toolkit = tlk.Toolkit(str(tool_dir))
        tlk._toolkit_ = self._toolkit
        tlk.toolkit_reload()

        logger.info(
            f"Toolkit 初始化 | 工具: {len(self._toolkit.func_map)} 个 | "
            f"toolkit_dir: {tool_dir} | kb_dir: {kb_dir}"
        )

    # ═══════════════════════════════════════════════
    # 会话初始化（无 Storage）
    # ═══════════════════════════════════════════════
    def _init_session(self):
        """初始化 OnlineToolSession，不传 Storage。"""
        from tea_agent.onlinesession import OnlineToolSession
        import tea_agent.session_ref as _sref

        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model

        _options = getattr(main_m, 'options', {}) or {}
        if isinstance(_options, dict):
            _supports_vision = _options.get('supports_vision', False)
        else:
            _supports_vision = False

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
            storage=None,  # ← 不传入 Storage，避免 DB 写入
            cheap_api_key=cast(str, cheap_m.api_key),
            cheap_api_url=cast(str, cheap_m.api_url),
            cheap_model=cast(str, cheap_m.model_name),
            enable_thinking=self._enable_thinking,
            supports_vision=_supports_vision,
        )

        _sref.set_session(self._sess)
        _sref.set_agent(self)

        # 若不使用工具，在 API 层拦截：强制 tools=[] 且 tool_choice="none"
        if not self._use_tools:
            self._sess._real_create_chat_stream = self._sess._create_chat_stream
            def _no_tools_chat(api_messages, tools, client=None, model=None, is_cheap=False):
                """Internal: no tools chat.
                
                Args:
                    api_messages: Description.
                    tools: Description.
                    client: Description.
                    model: Description.
                    is_cheap: Description.
                """
                return self._sess._real_create_chat_stream(
                    api_messages, [], client=client, model=model, is_cheap=is_cheap
                )
            self._sess._create_chat_stream = _no_tools_chat
            self._sess.tools = []

        logger.info(f"会话初始化（无 Storage）| 主模型: {main_m.model_name} | 工具: {'开' if self._use_tools else '关'}")

    # ═══════════════════════════════════════════════
    # 工具管理
    # ═══════════════════════════════════════════════
    def toolkit_save(self, name: str, meta: dict, pycode: str) -> bool:
        """添加/更新工具。等价于 toolkit_save() 工具函数。"""
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
    def chat(self, user_input: str) -> List[Dict]:
        """
        发送用户消息，阻塞直到 AI 返回完整回复。

        Args:
            user_input: 用户输入文本

        Returns:
            本轮对话的所有消息列表，每条为 dict:
              - {"role": "user",      "content": "..."}
              - {"role": "assistant", "content": "...", "reasoning_content": "..."}
              - {"role": "assistant", "tool_calls": [...], ...}
              - {"role": "tool",      "tool_call_id": "...", "content": "..."}
        """
        if self._generating:
            raise RuntimeError("正在生成中，请等待当前对话完成")

        with self._sess_lock:
            self._generating = True
            try:
                return self._chat_impl(user_input)
            finally:
                self._generating = False

    def _chat_impl(self, user_input: str) -> List[Dict]:
        """chat 的内部实现。"""

        # ── 流式回调 ──
        def stream_cb(text: str):
            """Stream cb.
            
            Args:
                text: Description.
            """
            if text.startswith("[THINK]"):
                self._notify({"type": "thinking", "text": text[7:]})
            else:
                self._notify({"type": "token", "text": text})

        def status_cb(status_msg: str):
            """Status cb.
            
            Args:
                status_msg: Description.
            """
            if status_msg.startswith("!MAX_ITER:"):
                self._sess._continue_after_max = True
                extra = getattr(self._sess.context, "extra_iterations_on_continue", 10)
                self._sess._extra_iterations += extra
                self._sess._max_iter_wait.set()
                self._notify({"type": "status", "text": f"已达最大轮次，自动续命 {extra} 轮..."})
            else:
                self._notify({"type": "status", "text": status_msg})

        # ── 执行对话 ──
        ai_msg, used_tools = self._sess.chat_stream(
            user_input,
            callback=stream_cb,
            topic_id="",  # 空字符串 = 不入库
            on_status=status_cb,
        )

        # ── 构建返回结果 ──
        rounds = self._sess._rounds_collector
        result: List[Dict] = [{"role": "user", "content": user_input}]
        if rounds:
            result.extend(rounds)

        self._notify({"type": "done", "used_tools": used_tools})
        return result

    # ═══════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════
    def close(self):
        """安全关闭 TeaAgent，释放资源。"""
        import tea_agent.session_ref as _sref
        # 清理全局引用，避免跨实例污染
        _sref.set_session(None)
        _sref.set_agent(None)
        self._sess = None
        self._toolkit = None
        logger.info("TeaAgent 已关闭")

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
