"""统一 Agent 类 — 合并 TeaAgent + AgentCore

三种模式：
- lightweight: 无存储、无后台线程，适合孤立任务
- full:        有存储/后台/流水线，适合 CLI/GUI
- lite:        LiteSession 单轮，适合子 Agent
"""

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import tea_agent.session_ref as _sref
from tea_agent import tlk
from tea_agent.config import load_config
from tea_agent.litesession import LiteSession
from tea_agent.logging_setup import setup_logging
from tea_agent.onlinesession import OnlineToolSession
from tea_agent.store import Storage

from .agent_background import start_scheduler, start_self_evolve_thread
from .agent_pipeline import do_async_summaries
from .memory import PRIORITY_MEDIUM

logger = logging.getLogger("agent")


@dataclass(frozen=True)
class _ModeBehavior:
    """每种 mode 启用的功能清单。"""

    name: str
    use_storage: bool
    use_background_services: bool
    session_class: Literal["LiteSession", "OnlineToolSession"]
    track_topic: bool
    call_post_pipeline: bool
    load_topic_history: bool


_MODE_BEHAVIORS: dict[str, _ModeBehavior] = {
    "lightweight": _ModeBehavior(
        name="lightweight",
        use_storage=False,
        use_background_services=False,
        session_class="OnlineToolSession",
        track_topic=False,
        call_post_pipeline=False,
        load_topic_history=False,
    ),
    "full": _ModeBehavior(
        name="full",
        use_storage=True,
        use_background_services=True,
        session_class="OnlineToolSession",
        track_topic=True,
        call_post_pipeline=True,
        load_topic_history=True,
    ),
    "lite": _ModeBehavior(
        name="lite",
        use_storage=False,
        use_background_services=False,
        session_class="LiteSession",
        track_topic=False,
        call_post_pipeline=False,
        load_topic_history=False,
    ),
}

_VALID_MODES = frozenset(_MODE_BEHAVIORS.keys())


class Agent:
    """统一 Agent — lightweight/full/lite 三种模式。"""

    def __init__(
        self,
        mode: str = "lightweight",
        config_path: str | None = None,
        config_fname: str | None = None,
        callback: Callable[[dict], None] | None = None,
        use_tools: bool = True,
        enable_thinking: bool = True,
        disable_summary: bool = False,
        no_stream_chunk: bool = False,
        debug: bool = False,
        use_cheap_model: bool = False,
    ):
        if mode not in _VALID_MODES:
            raise ValueError(f"mode 必须是 {sorted(_VALID_MODES)}，收到: {mode}")

        self.mode = mode
        self.behavior = _MODE_BEHAVIORS[mode]
        self.debug = debug
        self.disable_summary = disable_summary
        self.no_stream_chunk = no_stream_chunk
        self._use_cheap_model = use_cheap_model
        self._config_fname = config_fname
        setup_logging(debug=debug)

        self._callback = callback
        self._generating = False
        self._sess_lock = threading.Lock()
        self._toolkit = None
        self._sess = None
        self._use_tools = use_tools
        self._enable_thinking = enable_thinking
        self._db = None
        self._pending_cheap_tokens = {}

        self._config_path = config_path
        self._cfg = self._load_config(config_path)
        self._init_toolkit()
        if self.behavior.use_storage:
            self._init_storage()
        self._init_session()
        if self.behavior.use_background_services:
            self._start_background_services()

    def _init_session_info_str(self) -> str:
        """向后兼容：返回会话初始化的摘要。"""
        main_m = self._cfg.main_model
        tools_on = self.behavior.use_background_services or self._use_tools
        return f"Mode: {self.mode} | Model: {main_m.model_name} | Tools: {'ON' if tools_on else 'OFF'}"

    def _load_topic_history_into_session(self, topic_id: str):
        return self.load_topic_history(topic_id)

    def _load_config(self, config_path: str | None):
        """优先级: config_path > config_fname > 默认路径。"""
        if config_path:
            if not os.path.isfile(config_path):
                raise FileNotFoundError(f"配置文件不存在: {config_path}")
            actual_path = config_path
        elif self._config_fname:
            fname_path = str(Path.home() / ".tea_agent" / self._config_fname)
            if not os.path.isfile(fname_path):
                raise FileNotFoundError(f"配置文件不存在: {fname_path}")
            actual_path = fname_path
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
                    f"  1) {default_path}\n  2) {fallback_path}"
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

        self._config_path = actual_path
        logger.info(f"配置加载: {actual_path} | 模型: {main_m.model_name}")
        return cfg

    def _init_toolkit(self):
        """初始化 Toolkit 和 KB 目录。"""
        cfg = self._cfg
        tool_dir = Path(cfg.paths.toolkit_dir_abs)
        tool_dir.mkdir(parents=True, exist_ok=True)
        kb_dir = Path(cfg.paths.kb_dir_abs)
        kb_dir.mkdir(parents=True, exist_ok=True)

        self._toolkit = tlk.Toolkit(str(tool_dir))
        tlk.toolkit = self._toolkit

        logger.info(
            f"Toolkit 初始化 | 工具: {len(self._toolkit.func_map)} 个 | "
            f"toolkit_dir: {tool_dir} | kb_dir: {kb_dir}"
        )

    def _init_storage(self):
        """初始化 Storage 数据库。"""
        cfg = self._cfg
        db_path = Path(cfg.paths.db_path_abs)
        self._db = Storage(db_path=str(db_path))
        logger.info(f"Storage 初始化 | db: {db_path}")

    def _init_session(self):
        """根据 behavior.session_class 选择 LiteSession 或 OnlineToolSession。"""
        if self.behavior.session_class == "LiteSession":
            self._sess = self._build_lite_session()
        else:
            self._sess = self._build_online_session()

        _sref.set_session(self._sess, setter=f"Agent({self.mode})")
        _sref.set_agent(self, setter=f"Agent({self.mode})")

        tools_on = self._use_tools or self.behavior.use_background_services
        # lightweight 模式可显式关闭工具
        if self.mode == "lightweight" and not self._use_tools:
            self._sess.tools = []

        logger.info(
            f"会话初始化 | 模式: {self.mode} | "
            f"主模型: {self._cfg.main_model.model_name} | "
            f"工具: {'开' if tools_on else '关'}"
        )

    def _build_lite_session(self) -> LiteSession:
        """构造 LiteSession 实例（lite 模式专用）。"""
        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model

        # 根据 use_cheap_model 选择模型
        if self._use_cheap_model and cheap_m.api_key:
            model_key = cast(str, cheap_m.api_key)
            model_url = cast(str, cheap_m.api_url)
            model_name = cast(str, cheap_m.model_name)
            logger.info(f"Lite 模式使用便宜模型: {model_name}")
        else:
            model_key = cast(str, main_m.api_key)
            model_url = cast(str, main_m.api_url)
            model_name = cast(str, main_m.model_name)

        _options = getattr(main_m, "options", {}) or {}
        supports_reasoning = (
            _options.get("supports_reasoning", True)
            if isinstance(_options, dict)
            else True
        )

        return LiteSession(
            toolkit=self._toolkit,
            api_key=model_key,
            api_url=model_url,
            model=model_name,
            enable_thinking=self._enable_thinking,
            max_iterations=cfg.max_iterations,
            supports_reasoning=supports_reasoning,
        )

    def _build_online_session(self) -> OnlineToolSession:
        """构造 OnlineToolSession 实例（lightweight/full 共用）。"""
        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model

        _options = getattr(main_m, "options", {}) or {}
        supports_vision = (
            _options.get("supports_vision", False)
            if isinstance(_options, dict)
            else False
        )
        supports_reasoning = (
            _options.get("supports_reasoning", True)
            if isinstance(_options, dict)
            else True
        )

        return OnlineToolSession(
            toolkit=self._toolkit,
            api_key=cast(str, main_m.api_key),
            api_url=cast(str, main_m.api_url),
            model=cast(str, main_m.model_name),
            max_history=cfg.max_history,
            max_iterations=cfg.max_iterations,
            keep_turns=cfg.keep_turns,
            max_tool_output=cfg.max_tool_output,
            max_assistant_content=cfg.max_assistant_content,
            max_context_tokens=main_m.max_context_tokens,
            extra_iterations_on_continue=cfg.extra_iterations_on_continue,
            memory_extraction_threshold=cfg.memory_extraction_threshold,
            storage=self._db,
            cheap_api_key=cast(str, cheap_m.api_key),
            cheap_api_url=cast(str, cheap_m.api_url),
            cheap_model=cast(str, cheap_m.model_name),
            enable_thinking=self._enable_thinking,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            disable_summary=self.disable_summary,
            no_stream_chunk=self.no_stream_chunk,
        )

    def _start_background_services(self):
        """启动自进化引擎和定时任务调度器。"""
        start_self_evolve_thread(self._toolkit.tool_dir)
        start_scheduler()

    def toolkit_save(self, name: str, meta: dict, pycode: str) -> bool:
        """添加/更新工具。"""
        result = self._toolkit.call_tool(
            "toolkit_save", name=name, meta=meta, pycode=pycode
        )
        return bool(result and (isinstance(result, dict) and result.get("ok")))

    def toolkit_reload(self) -> dict:
        """重新加载所有工具并刷新会话工具定义。"""
        result = self._toolkit.call_tool("toolkit_reload")
        if self._sess:
            self._sess._build_tools()
        return result or {"ok": False}

    def _notify(self, data: dict):
        """安全调用用户回调。"""
        if self._callback:
            try:
                self._callback(data)
            except Exception as e:
                logger.warning(f"回调执行异常: {e}")

    def chat(
        self,
        user_input: str,
        topic_id: str = "",
        on_status: Callable | None = None,
    ) -> list[dict] | dict:
        """发送用户消息，返回回复。

        Args:
            user_input: 用户输入
            topic_id: 主题 ID（track_topic=True 才生效）
            on_status: 状态回调

        Returns: 非 lite 返回消息列表，lite 返回 {user,thinking,assistant,tool_calls,error}
        """
        if self._generating:
            raise RuntimeError("正在生成中，请等待当前对话完成")

        with self._sess_lock:
            self._generating = True
            try:
                if self.behavior.session_class == "LiteSession":

                    def stream_cb(text: str):
                        if self._callback:
                            self._callback({"type": "chunk", "content": text})

                    return self._sess.chat(user_input, callback=stream_cb)

                return self._chat_impl(user_input, topic_id, on_status)
            finally:
                self._generating = False

    def _chat_impl(
        self,
        user_input: str,
        topic_id: str,
        on_status: Callable | None,
    ) -> list[dict]:
        """chat 的内部实现（lightweight/full 模式）。"""

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
                self._notify(
                    {"type": "status", "text": f"已达最大轮次，自动续命 {extra} 轮..."}
                )
            elif on_status:
                on_status(status_msg)
            else:
                self._notify({"type": "status", "text": status_msg})

        effective_topic = topic_id if self.behavior.track_topic else ""
        # 同步 topic_id 到 Agent 级别，供 toolkit_todo 等工具持久化使用
        if effective_topic:
            self.current_topic_id = effective_topic
        ai_msg, used_tools = self._sess.chat_stream(
            user_input,
            callback=stream_cb,
            topic_id=effective_topic,
            on_status=status_cb,
        )

        if self.behavior.call_post_pipeline and self._db and topic_id:
            self._post_chat_pipeline(ai_msg, used_tools, user_input, topic_id)

        rounds = self._sess._rounds_collector
        result: list[dict] = [{"role": "user", "content": user_input}]
        if rounds:
            result.extend(rounds)

        self._notify({"type": "done", "used_tools": used_tools})
        return result

    # ────────────────────────────────────────────═══
    # 后处理流水线
    # ────────────────────────────────────────────═══
    def _post_chat_pipeline(
        self, ai_msg: str, used_tools: bool, user_msg, topic_id: str
    ) -> None:
        """AI 回复后流水线：入库 → Token 统计 → L2 推送 → 条件摘要。

        ⚠️ 此方法在 AI 回复已生成后运行。任何异常只记录日志不冒泡，
        以免丢失已生成的 AI 回复。
        """
        if not self._db:
            return

        try:
            conv_id = self._db.save_msg(topic_id, user_msg, "", False)
            rounds = self._sess._rounds_collector
            self._db.update_msg_rounds(
                conversation_id=conv_id,
                ai_msg=ai_msg,
                is_func_calling=used_tools,
                rounds=rounds if rounds else None,
            )

            usage = self._sess._last_usage
            cheap_usage = self._sess._last_cheap_usage
            if usage and usage.get("total_tokens", 0) > 0:
                kwargs = {
                    "total_tokens": usage["total_tokens"],
                    "prompt_tokens": usage["prompt_tokens"],
                    "completion_tokens": usage["completion_tokens"],
                }
                if cheap_usage and cheap_usage.get("total_tokens", 0) > 0:
                    kwargs["cheap_tokens"] = cheap_usage["total_tokens"]
                    kwargs["cheap_prompt_tokens"] = cheap_usage["prompt_tokens"]
                    kwargs["cheap_completion_tokens"] = cheap_usage["completion_tokens"]
                self._db.add_topic_tokens(topic_id, **kwargs)

            user_text = (
                user_msg
                if isinstance(user_msg, str)
                else (
                    user_msg.get("text", "")
                    if isinstance(user_msg, dict)
                    else str(user_msg)
                )
            )

            l2_count, overflow_items, should_summarize = self._db.push_to_level2(
                topic_id,
                user_text,
                ai_msg,
                rounds=rounds if rounds else None,
            )
            logger.debug(
                f"L2 push: count={l2_count}, overflow={len(overflow_items)}, "
                f"summarize={should_summarize}"
            )

            threading.Thread(
                target=self._do_async_summaries,
                args=(topic_id, overflow_items, should_summarize),
                daemon=True,
            ).start()

            threading.Thread(
                target=self._do_task_evaluation,
                args=(user_text, ai_msg, used_tools, rounds, usage),
                daemon=True,
            ).start()
        except Exception:
            logger.exception(
                "_post_chat_pipeline failed — AI reply preserved, "
                "but DB write may be lost"
            )

    def _do_async_summaries(
        self, topic_id: str, overflow_items: list = None, should_summarize: bool = False
    ):
        """后台线程：执行标题摘要 + 条件 L2→L3 摘要。"""
        do_async_summaries(self, topic_id, overflow_items, should_summarize)

    def _do_task_evaluation(
        self,
        user_text: str,
        ai_msg: str,
        used_tools: bool,
        rounds: list,
        usage: dict,
    ):
        """后台线程：评估任务 → 结晶技能 → 更新记忆。"""
        try:
            tools_used = []
            if rounds:
                for round_data in rounds:
                    for tc in round_data.get("tool_calls", []):
                        func_name = tc.get("function", {}).get("name", "")
                        if func_name and func_name not in tools_used:
                            tools_used.append(func_name)

            from .evaluation import TaskEvaluator

            evaluator = TaskEvaluator()
            token_cost = usage.get("total_tokens", 0) if usage else 0

            result = evaluator.evaluate(
                task=user_text,
                rounds=rounds or [],
                tools_used=tools_used,
                token_cost=token_cost,
                time_seconds=0,
            )

            logger.debug(f"📊 评估结果: {result.summary}")

            if result.should_crystallize and tools_used:
                crystallizer = SkillCrystallizer()
                skill = crystallizer.crystallize(
                    task=user_text,
                    tools_used=tools_used,
                    rounds=rounds,
                    success=result.success,
                    token_cost=token_cost,
                )
                registry = SkillRegistry()
                registry.register(skill)
                logger.info(f"✨ 技能结晶: {skill.name}")

            if result.lessons and self._db:
                for lesson in result.lessons:
                    try:
                        self._db.add_memory(
                            content=lesson,
                            category="fact",
                            importance=3,
                            priority=PRIORITY_MEDIUM,
                            tags="经验教训,自动提取",
                        )
                    except Exception as e:
                        logger.debug(f"记录经验失败: {e}")

        except Exception as e:
            logger.debug(f"任务评估异常 (非致命): {e}")

    # ────────────────────────────────────────────═══
    # 历史加载
    # ────────────────────────────────────────────═══
    def load_topic_history(self, topic_id: str):
        """加载指定主题的对话历史到会话。仅在 behavior.load_topic_history=True 时可用。"""
        if not self.behavior.load_topic_history or not self._db:
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
                all_light,
                summary=old_summary,
                level2=level2,
                semantic_summary=semantic,
                tool_chain_summary=tool_chain,
            )
        else:
            self._sess.messages = [
                {"role": "system", "content": self._sess.system_prompt}
            ]
            self._sess._history_summary = ""
            self._sess._semantic_summary = ""
            self._sess._tool_chain_summary = ""
            self._sess.context._level2 = []

    # ────────────────────────────────────────────═══
    # 生命周期
    # ────────────────────────────────────────────═══
    def close(self):
        """安全关闭 Agent，释放资源。"""
        _sref.clear()
        self._sess = None
        self._toolkit = None
        self._db = None
        logger.info(f"Agent ({self.mode}) 已关闭")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ────────────────────────────────────────────═══
    # 属性
    # ────────────────────────────────────────────═══

    @property
    def config(self):
        return self._cfg

    @property
    def toolkit(self):
        return self._toolkit

    @property
    def sess(self):
        return self._sess

    @sess.setter
    def sess(self, v):
        self._sess = v

    @property
    def session(self):
        return self._sess

    @property
    def db(self):
        return self._db

    @property
    def current_topic_id(self) -> str:
        return getattr(self, "_current_topic_id", "")

    @current_topic_id.setter
    def current_topic_id(self, value: str):
        self._current_topic_id = value


# ────────────────────────────────────────────────────────────═══
# 向后兼容别名
# ────────────────────────────────────────────────────────────═══


def TeaAgent(
    config_path: str | None = None,
    callback: Callable[[dict], None] | None = None,
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
