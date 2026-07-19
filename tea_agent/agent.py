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
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from tea_agent.config import AgentConfig

import tea_agent.session_ref as _sref
from tea_agent import tlk
from tea_agent.config import load_config, resolve_config_path
from tea_agent.litesession import LiteSession
from tea_agent.logging_setup import setup_logging
from tea_agent.onlinesession import OnlineToolSession
from tea_agent.store import Storage

from .agent_background import start_scheduler
from .agent_evolution import EvolutionAnalyzer, EvolutionActor
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

    def _load_topic_history_into_session(self, topic_id: str) -> None:
        return self.load_topic_history(topic_id)

    def _load_config(self, config_path: str | None) -> "AgentConfig":
        """优先级: config_path > config_fname > 默认路径。

        Args:
            config_path: 配置文件路径，如果为None则使用默认路径

        Returns:
            AgentConfig: 加载的配置对象

        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置不完整
        """
        if self._config_fname and not config_path:
            config_path = str(Path.home() / ".tea_agent" / self._config_fname)

        actual_path = resolve_config_path(config_path)
        if not actual_path or not os.path.isfile(actual_path):
            raise FileNotFoundError(
                f"未找到配置文件: {actual_path or '无'}。\n"
                f"请创建 ~/.tea_agent/config.yaml 或指定 --config"
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

    def _init_toolkit(self) -> None:
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

    def _init_storage(self) -> None:
        """初始化 Storage 数据库。"""
        cfg = self._cfg
        db_path = Path(cfg.paths.db_path_abs)
        self._db = Storage(db_path=str(db_path))
        logger.info(f"Storage 初始化 | db: {db_path}")

    def _init_session(self, *, update_ref: bool = True) -> None:
        """根据 behavior.session_class 选择 LiteSession 或 OnlineToolSession。

        Args:
            update_ref: 是否更新全局 session_ref（hot-switch 时若存在活跃流式会话，
                        应跳过 ref 更新以避免工具函数引用错乱）。
        """
        if self.behavior.session_class == "LiteSession":
            self._sess = self._build_lite_session()
        else:
            self._sess = self._build_online_session()

        if update_ref:
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
            enable_thinking=self._enable_thinking or cfg.enable_thinking,
            thinking_strength=cfg.thinking_strength,
            reasoning_effort=cfg.reasoning_effort,
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
            memory_dedup_threshold=cfg.memory_dedup_threshold,
            storage=self._db,
            cheap_api_key=cast(str, cheap_m.api_key),
            cheap_api_url=cast(str, cheap_m.api_url),
            cheap_model=cast(str, cheap_m.model_name),
            enable_thinking=self._enable_thinking or cfg.enable_thinking,
            thinking_strength=cfg.thinking_strength,
            reasoning_effort=cfg.reasoning_effort,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            disable_summary=self.disable_summary,
            no_stream_chunk=self.no_stream_chunk,
        )

    def _start_background_services(self) -> None:
        """启动定时任务调度器。"""
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

    def _notify(self, data: dict) -> None:
        """安全调用用户回调。

        Args:
            data: 要发送的数据字典
        """
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

        Args:
            ai_msg: AI生成的回复内容
            used_tools: 是否使用了工具
            user_msg: 用户原始消息
            topic_id: 主题ID
        """
        if not self._db:
            return

        try:
            # 步骤1: 保存对话到数据库
            conv_id = self._db.save_msg(topic_id, user_msg, "", False)
            rounds = self._sess._rounds_collector
            self._db.update_msg_rounds(
                conversation_id=conv_id,
                ai_msg=ai_msg,
                is_func_calling=used_tools,
                rounds=rounds if rounds else None,
            )

            # 步骤2: 更新Token使用统计
            self._update_token_usage(topic_id)

            # 步骤3: 提取用户文本
            user_text = self._extract_user_text(user_msg)

            # 步骤4: 推送到L2缓存（使用 config 中的 history_l2_max）
            l2_max = getattr(self._config, 'history_l2_max', 15) if hasattr(self, '_config') else 15
            l2_count, overflow_items, should_summarize = self._db.push_to_level2(
                topic_id,
                user_text,
                ai_msg,
                rounds=rounds if rounds else None,
                max_level2=l2_max,
            )
            logger.debug(
                f"L2 push: count={l2_count}, overflow={len(overflow_items)}, "
                f"summarize={should_summarize}"
            )

            # 步骤5: 启动后台任务
            self._start_background_tasks(
                topic_id, overflow_items, should_summarize,
                user_text, ai_msg, used_tools, rounds
            )

        except Exception:
            logger.exception(
                "_post_chat_pipeline failed — AI reply preserved, "
                "but DB write may be lost"
            )

    def _update_token_usage(self, topic_id: str) -> None:
        """更新Token使用统计。

        Args:
            topic_id: 主题ID
        """
        usage = self._sess._last_usage
        cheap_usage = self._sess._last_cheap_usage

        if not usage or usage.get("total_tokens", 0) <= 0:
            return

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

    def _extract_user_text(self, user_msg) -> str:
        """从用户消息中提取纯文本。

        Args:
            user_msg: 用户消息（字符串或字典）

        Returns:
            提取的纯文本
        """
        if isinstance(user_msg, str):
            return user_msg
        elif isinstance(user_msg, dict):
            return user_msg.get("text", "")
        else:
            return str(user_msg)

    def _start_background_tasks(
        self,
        topic_id: str,
        overflow_items: list,
        should_summarize: bool,
        user_text: str,
        ai_msg: str,
        used_tools: bool,
        rounds: list
    ) -> None:
        """启动后台任务线程。

        Args:
            topic_id: 主题ID
            overflow_items: 溢出项列表
            should_summarize: 是否需要摘要
            user_text: 用户文本
            ai_msg: AI回复
            used_tools: 是否使用工具
            rounds: 对话轮次
        """
        # 启动异步摘要任务
        threading.Thread(
            target=self._do_async_summaries,
            args=(topic_id, overflow_items, should_summarize),
            daemon=True,
        ).start()

        # 启动任务评估任务
        threading.Thread(
            target=self._do_task_evaluation,
            args=(user_text, ai_msg, used_tools, rounds, self._sess._last_usage),
            daemon=True,
        ).start()

        # 启动自进化任务（触发→分析→执行）
        ctx = getattr(self._sess, 'context', None)
        if ctx and getattr(ctx, 'evolution_trigger', None):
            threading.Thread(
                target=self._do_evolution,
                args=(topic_id,),
                daemon=True,
            ).start()

        # 启动跨主题汇总（每3轮触发一次）
        threading.Thread(
            target=self._do_cross_topic_summary,
            daemon=True,
        ).start()

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
        """后台线程：评估任务 → 结晶技能 → 更新记忆。

        Args:
            user_text: 用户文本
            ai_msg: AI回复
            used_tools: 是否使用工具
            rounds: 对话轮次
            usage: Token使用统计
        """
        try:
            # 步骤1: 提取使用的工具列表
            tools_used = self._extract_tools_used(rounds)

            # 步骤2: 评估任务
            evaluation_result = self._evaluate_task(
                user_text, rounds, tools_used, usage
            )

            # 步骤3: 如果需要，结晶技能
            if evaluation_result.should_crystallize and tools_used:
                self._crystallize_skill(
                    user_text, tools_used, rounds,
                    evaluation_result.success, usage
                )

            # 步骤4: 保存经验教训
            if evaluation_result.lessons and self._db:
                self._save_lessons(evaluation_result.lessons)

        except Exception as e:
            logger.debug(f"任务评估异常 (非致命): {e}")

    def _do_evolution(self, topic_id: str):
        """后台线程：自进化闭环 — 触发→分析→执行。

        只在累积了触发事件且 cheap_client 可用时执行。
        """
        try:
            ctx = getattr(self._sess, 'context', None)
            trigger = getattr(ctx, 'evolution_trigger', None) if ctx else None
            if not trigger:
                return
            events = trigger.get_pending_events()
            if not events:
                return

            cheap_client = getattr(self._sess, 'context', None) and self._sess.context.cheap_client
            if not cheap_client:
                return

            cheap_model = getattr(self._sess.context, 'cheap_model', 'gpt-4o-mini')
            analyzer = EvolutionAnalyzer(cheap_client, cheap_model)
            actions = analyzer.analyze(events)
            if not actions:
                if trigger:
                    trigger.clear_events()
                return

            actor = EvolutionActor(self._toolkit)
            results = actor.execute(actions)
            logger.info(f"evolution: 执行完成 {len(results)}/{len(actions)} 个行动")
            if trigger:
                trigger.clear_events()
        except Exception as e:
            logger.debug(f"evolution 异常 (非致命): {e}")

    def _do_cross_topic_summary(self):
        """后台线程：跨主题汇总 — 每 3 轮触发一次分析。"""
        try:
            from tea_agent.cross_topic_summarizer import CrossTopicSummarizer
            cheap_client = None
            try:
                from tea_agent.providers import get_cheap_client
                from tea_agent.config import get_config
                cheap_client = get_cheap_client(get_config())
            except Exception:
                pass
            summarizer = CrossTopicSummarizer(self._db, cheap_client)
            summarizer.on_session_complete()
        except Exception:
            logger.debug("cross_topic 汇总异常 (非致命)")

    def _extract_tools_used(self, rounds: list) -> list[str]:
        """从对话轮次中提取使用的工具列表。

        Args:
            rounds: 对话轮次列表

        Returns:
            使用的工具名称列表
        """
        tools_used = []
        if not rounds:
            return tools_used

        for round_data in rounds:
            for tc in round_data.get("tool_calls", []):
                func_name = tc.get("function", {}).get("name", "")
                if func_name and func_name not in tools_used:
                    tools_used.append(func_name)

        return tools_used

    def _evaluate_task(
        self,
        user_text: str,
        rounds: list,
        tools_used: list[str],
        usage: dict
    ):
        """评估任务执行情况。

        Args:
            user_text: 用户文本
            rounds: 对话轮次
            tools_used: 使用的工具列表
            usage: Token使用统计

        Returns:
            评估结果
        """
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
        return result

    def _crystallize_skill(
        self,
        user_text: str,
        tools_used: list[str],
        rounds: list,
        success: bool,
        usage: dict
    ) -> None:
        """结晶技能模式。

        Args:
            user_text: 用户文本
            tools_used: 使用的工具列表
            rounds: 对话轮次
            success: 是否成功
            usage: Token使用统计
        """
        token_cost = usage.get("total_tokens", 0) if usage else 0

        crystallizer = SkillCrystallizer()
        skill = crystallizer.crystallize(
            task=user_text,
            tools_used=tools_used,
            rounds=rounds,
            success=success,
            token_cost=token_cost,
        )

        registry = SkillRegistry()
        registry.register(skill)
        logger.info(f"✨ 技能结晶: {skill.name}")

    def _save_lessons(self, lessons: list[str]) -> None:
        """保存经验教训到数据库。

        Args:
            lessons: 经验教训列表
        """
        for lesson in lessons:
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

    # ────────────────────────────────────────────═══
    # 历史加载
    # ────────────────────────────────────────────═══
    def load_topic_history(self, topic_id: str) -> None:
        """加载指定主题的对话历史到会话。仅在 behavior.load_topic_history=True 时可用。

        Args:
            topic_id: 主题ID
        """
        if not self.behavior.load_topic_history or not self._db:
            logger.warning("load_topic_history 仅在 full 模式下可用")
            return

        all_light = self._db.get_conversations(topic_id, limit=-1, include_rounds=False)
        if all_light:
            # 获取最近 history_turns 轮的完整数据（含 rounds）
            history_turns = getattr(self._sess.context, 'keep_turns', 3)
            recent_n = self._db.get_conversations(topic_id, limit=history_turns, include_rounds=True)
            if recent_n:
                # 用完整数据替换 all_light 中对应条目
                for i, conv in enumerate(recent_n):
                    all_light[-(len(recent_n) - i)] = conv
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
                history_turns=history_turns,
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
    def close(self) -> None:
        """安全关闭 Agent，释放资源。"""
        _sref.clear()
        self._sess = None
        self._toolkit = None
        self._db = None
        logger.info(f"Agent ({self.mode}) 已关闭")

    def __enter__(self) -> "Agent":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
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
