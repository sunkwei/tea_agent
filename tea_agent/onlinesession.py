"""
在线工具调用会话 - Token 优化版 (重构版：组合模式)
支持 OpenAI 兼容 API 的 Function Calling 功能

Token 优化策略:
1. 压缩系统提示词 (~200 tokens, 原 ~1000+)
2. 历史摘要：超过5轮的对话自动摘要，只传摘要+最近N轮
3. 工具输出截断：超长结果截断至 max_tool_output 字符
4. 助手回复截断：超长回复截断至 max_assistant_content 字符
5. 长期记忆注入：相关记忆在每次对话中自动注入（上限5条）

重构说明:
- 从 Mixin 多重继承改为组合模式
- 所有共享状态通过 SessionContext 管理
- 功能委派给各个 Component：API, Tool, Memory, Summarizer
"""

from openai import OpenAI
from typing import List, Dict, Callable, Tuple, Any, Optional
import logging

from tea_agent.basesession import BaseChatSession
from tea_agent.session_prompts import COMPACT_SYSTEM_PROMPT
from tea_agent.session_pipeline import SessionPipeline
from tea_agent.skills import SkillManager

# 组件导入（替代 Mixin）
from tea_agent.session_context import SessionContext
from tea_agent.session_api_component import APIComponent
from tea_agent.session_tool_component import ToolComponent
from tea_agent.session_memory_component import MemoryComponent
from tea_agent.session_summarizer_component import SummarizerComponent

logger = logging.getLogger("session")


class OnlineToolSession(BaseChatSession):
    """
    在线工具调用会话 - Token 优化版
    支持 OpenAI 兼容 API 的 Function Calling 功能

    重构说明：
    - 使用组合模式替代 Mixin 多重继承
    - 共享状态通过 self.context (SessionContext) 管理
    - 功能委派给 self.api, self.tools, self.memory, self.summarizer 组件
    """

    # 压缩后的系统提示词
    _COMPACT_SYSTEM_PROMPT = COMPACT_SYSTEM_PROMPT

    def __init__(
        self,
        toolkit,
        api_key: str,
        api_url: str,
        model: str = "glm-5",
        max_history: int = 10,
        system_prompt: str = "",
        max_iterations: int = 50,
        enable_thinking: bool = True,
        storage=None,
        cheap_api_key: str = "",
        cheap_api_url: str = "",
        cheap_model: str = "",
        keep_turns: int = 5,
        max_tool_output: int = 128 * 1024,
        max_assistant_content: int = 128 * 1024,
        extra_iterations_on_continue: int = 5,
        memory_extraction_threshold: int = 2,
        memory_dedup_threshold: float = 0.3,
        supports_vision: bool = False,
        supports_reasoning: bool = True,
        disable_summary: bool = False,
    ):
        """
        初始化会话

        Args:
            toolkit: Toolkit 工具库实例
            api_key: API密钥
            api_url: API地址
            model: 模型名称
            max_history: 最大历史消息数
            system_prompt: 系统提示词（为空则使用压缩版）
            max_iterations: 最大工具调用迭代次数
            enable_thinking: 是否启用 thinking 功能
            storage: Storage 实例，用于持久化存储
            cheap_api_key: 便宜模型 API密钥
            cheap_api_url: 便宜模型 API地址
            cheap_model: 便宜模型名称
            keep_turns: 保留最近N轮完整对话
            max_tool_output: 工具输出截断字符数
            max_assistant_content: 助手回复截断字符数
            extra_iterations_on_continue: 续命时追加的工具调用轮数
            memory_extraction_threshold: 触发记忆提取的最低未摘要消息数
            memory_dedup_threshold: 记忆去重相似度阈值 (0~1)
            supports_vision: 是否支持视觉输入
            supports_reasoning: 是否支持 reasoning
            disable_summary: 禁用历史压缩和摘要
        """
        sp = system_prompt or self._COMPACT_SYSTEM_PROMPT

        # ── 1. 创建共享上下文 ──
        import httpx
        _http_client = httpx.Client(proxy=None)
        main_client = OpenAI(api_key=api_key, base_url=api_url, http_client=_http_client)
        
        cheap_client: Optional[OpenAI] = None
        if cheap_api_key and cheap_api_url and cheap_model:
            cheap_client = OpenAI(api_key=cheap_api_key, base_url=cheap_api_url, http_client=httpx.Client(proxy=None))

        self.context = SessionContext(
            messages=[],  # 稍后由 BaseChatSession.__init__ 初始化
            model=model,
            enable_thinking=enable_thinking,
            client=main_client,
            cheap_client=cheap_client,
            cheap_model=cheap_model,
            toolkit=toolkit,
            storage=storage,
            keep_turns=keep_turns,
            max_tool_output=max_tool_output,
            max_assistant_content=max_assistant_content,
            memory_extraction_threshold=memory_extraction_threshold,
            memory_dedup_threshold=memory_dedup_threshold,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            disable_summary=disable_summary,
            extra_iterations_on_continue=extra_iterations_on_continue,
        )

        # ── 2. 调用基类初始化（会触发属性桥接） ──
        BaseChatSession.__init__(self, model, max_history, sp)

        logger.info(f"OnlineToolSession init ok: main model: {model}, cheap model: {cheap_model}")

        # ── 3. 创建并初始化组件 ──
        self.api = APIComponent(self.context)
        self.tools_comp = ToolComponent(self.context)
        self.memory_comp = MemoryComponent(self.context)
        self.summarizer_comp = SummarizerComponent(self.context)
        
        for comp in [self.api, self.tools_comp, self.memory_comp, self.summarizer_comp]:
            comp.initialize()

        # ── 兼容属性（指向 context）──
        # 这些属性保持与旧代码的兼容性，但实际数据存储在 context 中
        self.max_iterations = 50
        self.storage = storage
        self._cheap_client = cheap_client
        self._cheap_model_name = cheap_model
        self._current_mode = "mixed"
        self._supports_vision = supports_vision
        self._supports_reasoning = supports_reasoning
        self._disable_summary = disable_summary

        # ── 续跑控制 ──
        import threading
        self._extra_iterations = 0
        self._continue_after_max = False
        self._max_iter_wait = threading.Event()

        # ── 工具定义 ──
        self.tools: List[Dict] = []

        # ── Skill 管理器 ──
        self.skill_manager = SkillManager.get_instance()
        self.skill_manager.discover_skills()
        self.skill_manager.activate_skill("utility")
        self.skill_manager.activate_skill("file_system")
        self.skill_manager.activate_skill("memory_knowledge")

        # 构建工具列表（委派给组件）
        self.tools = self.tools_comp.build_tools()

        # 初始化 Memory 管理器（委派给组件）
        self.memory_comp.initialize()

        # ── 反思和提示词管理器 ──
        if self.storage is not None:
            from tea_agent.reflection import ReflectionManager
            from tea_agent.prompt_manager import SystemPromptManager
            self.reflection_manager = ReflectionManager(
                storage=self.storage,
                cheap_client=cheap_client,
                cheap_model=cheap_model,
            )
            self.prompt_manager = SystemPromptManager(
                storage=self.storage,
                cheap_client=cheap_client,
                cheap_model=cheap_model,
            )
            dynamic_prompt = self.prompt_manager.initialize()
            if not system_prompt:
                self.system_prompt = dynamic_prompt
            logger.info(f"系统提示词 v{self.prompt_manager.current_version} 已加载")
            
            # 同步到 context
            self.context.reflection_manager = self.reflection_manager
        else:
            self.reflection_manager = None
            self.prompt_manager = None
            logger.info("Storage 未设置，跳过 ReflectionManager/PromptManager 初始化")

        # ── Pipeline ──
        self.pipeline = SessionPipeline()
        self.context.pipeline = self.pipeline
        self._setup_default_pipeline()

    # ── 属性桥接（兼容旧代码直接访问 self._rounds_collector 等） ──
    # 重构后数据存储在 self.context 中，通过 property 桥接访问
    @property
    def messages(self):
        return self.context.messages

    @messages.setter
    def messages(self, value):
        self.context.messages = value

    @property
    def model(self):
        return self.context.model

    @model.setter
    def model(self, value):
        self.context.model = value

    @property
    def _rounds_collector(self):
        return self.context._rounds_collector

    @_rounds_collector.setter
    def _rounds_collector(self, value):
        self.context._rounds_collector = value

    @property
    def _last_usage(self):
        return self.context._last_usage

    @_last_usage.setter
    def _last_usage(self, value):
        self.context._last_usage = value

    @property
    def _last_cheap_usage(self):
        return self.context._last_cheap_usage

    @_last_cheap_usage.setter
    def _last_cheap_usage(self, value):
        self.context._last_cheap_usage = value

    @property
    def _history_summary(self):
        return self.context._history_summary

    @_history_summary.setter
    def _history_summary(self, value):
        self.context._history_summary = value

    @property
    def _semantic_summary(self):
        return self.context._semantic_summary

    @_semantic_summary.setter
    def _semantic_summary(self, value):
        self.context._semantic_summary = value

    @property
    def _tool_chain_summary(self):
        return self.context._tool_chain_summary

    @_tool_chain_summary.setter
    def _tool_chain_summary(self, value):
        self.context._tool_chain_summary = value

    @property
    def _level2(self):
        return self.context._level2

    @_level2.setter
    def _level2(self, value):
        self.context._level2 = value

    # ──────────────────────────────────────────────
    # 委派方法（保持向后兼容）
    # ──────────────────────────────────────────────

    def _get_summarize_client(self) -> Tuple[Any, str]:
        """获取用于摘要/提取任务的客户端和模型名。"""
        if self._cheap_client and self._cheap_model_name:
            return self._cheap_client, self._cheap_model_name
        return self.context.client, self.context.model

    def _get_effective_params(self, model_type: str = "main") -> Dict[str, Any]:
        """返回 {temperature, max_tokens, top_p}，失败时返回空 dict。"""
        try:
            from .config import get_config
            return get_config().get_effective_params(model_type, self._current_mode)
        except Exception:
            return {}

    # ──────────────────────────────────────────────
    # 流式处理（委派给 API 组件）
    # ──────────────────────────────────────────────

    def _process_stream_with_reasoning(self, response, callback) -> Tuple[str, List[Dict], str]:
        """
        处理流式响应，收集内容、工具调用数据和 reasoning_content。
        """
        content_parts = []
        tool_calls_data = []
        reasoning_parts = []

        for chunk in response:
            # 累积 usage 信息（委派给 API 组件）
            if hasattr(chunk, 'usage') and chunk.usage:
                self.api._accumulate_usage(chunk.usage)

            if not hasattr(chunk, 'choices') or not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # 处理 reasoning_content
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)
                callback(f"[THINK]{delta.reasoning_content}")

            # 处理内容
            if delta.content:
                content_parts.append(delta.content)
                callback(delta.content)

            # 处理工具调用（委派给 API 组件）
            if delta.tool_calls:
                self.api.accumulate_tool_calls_from_delta(delta, tool_calls_data)

        content = "".join(content_parts)
        reasoning_content = "".join(reasoning_parts)
        return content, tool_calls_data, reasoning_content

    # ──────────────────────────────────────────────
    # Pipeline 设置（委派给组件）
    # ──────────────────────────────────────────────

    def _setup_default_pipeline(self):
        """设置默认的 Pipeline 步骤"""
        # 1. 记忆注入（委派给 Memory 组件）
        self.pipeline.register_step(
            name="inject_memories",
            func=self.memory_comp.inject_memories,
            enabled=True,
            description="从长期记忆中注入相关记忆",
            position=15,
        )

        # 2. 添加用户消息
        self.pipeline.register_step(
            name="add_user_message",
            func=lambda ctx: (self.add_user_message(ctx.get("user_msg", "")), self.context.messages)[1],
            enabled=True,
            description="添加用户消息到会话历史",
            position=20,
        )

        # 3. 摘要旧历史（委派给 Summarizer 组件）
        self.pipeline.register_step(
            name="summarize_old_history",
            func=lambda ctx: (self.summarizer_comp.summarize_old_history(self.api, self._get_summarize_client), self.context.messages)[1],
            enabled=True,
            description="将旧对话历史压缩为摘要",
            position=30,
        )

        # 4. 工具调用循环（核心）
        self.pipeline.register_step(
            name="tool_loop",
            func=self._execute_tool_loop,
            enabled=True,
            description="执行工具调用循环",
            position=40,
        )

    # ──────────────────────────────────────────────
    # 构建 API 消息（使用 context 状态）
    # ──────────────────────────────────────────────

    def _build_api_messages(self) -> List[Dict]:
        """
        三级历史拼接：
            Level 0: 系统提示词 + 长期记忆注入
            Level 3: 语义摘要 + 工具链摘要
            Level 2: 按语义相关性筛选的 user+assistant 对
            Level 1: 最新一轮压缩对话
        """
        result: List[Dict] = []

        # ── Level 0: 系统提示词 + Skill 注入 ──
        sys_msg = dict(self.context.messages[0])
        skill_prompt = self.skill_manager.get_active_prompt()
        skill_summary = self.skill_manager.get_skill_summary()
        if skill_prompt or skill_summary:
            enhanced = sys_msg["content"]
            if skill_summary:
                enhanced = enhanced + "\n\n" + skill_summary
            if skill_prompt:
                enhanced = enhanced + "\n\n" + skill_prompt
            sys_msg["content"] = enhanced
        result.append(sys_msg)

        # ── 潜意识引擎状态注入 ──
        sub_ctx = self._get_subconscious_context()
        if sub_ctx:
            result.append({
                "role": "user",
                "content": sub_ctx
            })

        # ── 长期记忆注入 ──
        if self.context._injected_memories_text:
            result.append({
                "role": "user",
                "content": self.context._injected_memories_text
            })

        # NOTE: disable_summary 启用时跳过 L3/L2 历史构造
        if not self.context.disable_summary:
            # ── Level 3: 摘要 ──
            has_level3 = False
            parts = []
            sem = self.context._semantic_summary
            tc = self.context._tool_chain_summary
            if sem:
                parts.append(f"## 长期背景/偏好/关键结论\n{sem}")
                has_level3 = True
            if tc:
                parts.append(f"## 历史工具调用链回顾\n{tc}")
                has_level3 = True

            if has_level3:
                result.append({
                    "role": "user",
                    "content": "[系统记忆 — 以下为需要遵循的有效信息和规则]\n\n" + "\n\n---\n\n".join(parts)
                })
                _asst = {"role": "assistant", "content": "好的，我已经了解了之前的对话背景。请问有什么我可以帮您的？"}
                if self.context.supports_reasoning:
                    _asst["reasoning_content"] = ""
                result.append(_asst)

            # ── 兼容旧 _history_summary ──
            if not has_level3 and self.context._history_summary:
                result.append({
                    "role": "user",
                    "content": f"这是我们之前对话的摘要：\n{self.context._history_summary}"
                })
                _asst2 = {"role": "assistant", "content": "好的，我已经了解了之前的对话背景。请问有什么我可以帮您的？"}
                if self.context.supports_reasoning:
                    _asst2["reasoning_content"] = ""
                result.append(_asst2)

            # ── Level 2: 按语义相关性筛选 ──
            level2 = self.context._level2
            if level2:
                current_user_msg = ""
                for i in range(len(self.context.messages)-1, 0, -1):
                    if self.context.messages[i].get("role") == "user":
                        cur_content = self.context.messages[i].get("content", "")
                        if isinstance(cur_content, list):
                            current_user_msg = "".join(
                                p.get("text", "") for p in cur_content if p.get("type") == "text"
                            )
                        else:
                            current_user_msg = str(cur_content)
                        break
                filtered = self._filter_level2_by_relevance(level2, current_user_msg)
                for item in filtered:
                    kind = item.get("kind", "full")
                    if kind == "summary":
                        result.append({
                            "role": "user",
                            "content": f"[历史相关对话摘要] {item['content']}"
                        })
                    else:
                        result.append({"role": "user", "content": item.get("user", "")})
                        _msg = {"role": "assistant", "content": item.get("assistant", "")}
                        if self.context.supports_reasoning:
                            _msg["reasoning_content"] = ""
                        result.append(_msg)

        # ── Level 1: 最新一轮压缩对话 ──
        disable_summary = self.context.disable_summary
        max_turns_limit = 30

        start_idx = 1
        if disable_summary:
            user_msg_indices = []
            for i in range(1, len(self.context.messages)):
                if self.context.messages[i].get("role") == "user":
                    user_msg_indices.append(i)

            if len(user_msg_indices) > max_turns_limit:
                start_idx = user_msg_indices[-max_turns_limit]
                logger.info(f"disable_summary 启用: 丢弃早期历史，保留最近 {max_turns_limit} 轮 (共 {len(user_msg_indices)} 轮)")

        for i in range(start_idx, len(self.context.messages)):
            msg = self.context.messages[i]
            msg_copy = dict(msg)
            if msg_copy["role"] == "assistant" and self.context.supports_reasoning and "reasoning_content" not in msg_copy:
                msg_copy["reasoning_content"] = ""
            msg_copy = self._to_multimodal(msg_copy)
            if isinstance(msg_copy.get("content"), list) and not self.context.supports_vision:
                text_parts = []
                for p in msg_copy["content"]:
                    if isinstance(p, dict):
                        if p.get("type") == "text":
                            text_parts.append(p.get("text", ""))
                        elif p.get("type") == "image_url":
                            text_parts.append("[图片]")
                msg_copy["content"] = "\n".join(text_parts) if text_parts else "[图片]"
            result.append(msg_copy)

        # JSON完整性校验
        result = self._sanitize_api_messages(result)

        # Safeguard: 移除孤立 tool 消息
        valid_ids = set()
        cleaned = []
        for msg in result:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    if tc.get("id"):
                        valid_ids.add(tc["id"])
                cleaned.append(msg)
            elif msg.get("role") == "tool":
                if msg.get("tool_call_id") in valid_ids:
                    cleaned.append(msg)
                else:
                    logger.warning(f"_build_api_messages: 移除孤立 tool 消息 (id={msg.get('tool_call_id')})")
            else:
                cleaned.append(msg)
        result = cleaned

        return result

    # ──────────────────────────────────────────────
    # JSON 校验与修复（保持原有逻辑）
    # ──────────────────────────────────────────────

    def _sanitize_api_messages(self, messages: List[Dict]) -> List[Dict]:
        """校验并修复 API 消息中的 tool_calls JSON"""
        import json as _json
        sanitized = []
        removed_count = 0
        for msg in messages:
            if msg.get("role") != "assistant":
                sanitized.append(msg)
                continue

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                sanitized.append(msg)
                continue

            valid_calls = []
            for tc in tool_calls:
                func = tc.get("function", {})
                raw_args = func.get("arguments", "")

                if isinstance(raw_args, dict):
                    valid_calls.append(tc)
                    continue

                if not raw_args or not raw_args.strip():
                    valid_calls.append(tc)
                    continue

                try:
                    _json.loads(raw_args)
                    valid_calls.append(tc)
                    continue
                except _json.JSONDecodeError:
                    pass

                fixed = self._try_fix_truncated_json(raw_args)
                if fixed is not None:
                    tc_copy = dict(tc)
                    tc_copy["function"] = dict(func)
                    tc_copy["function"]["arguments"] = fixed
                    valid_calls.append(tc_copy)
                    logger.warning(f"_sanitize_api_messages: 修复截断JSON → {fixed[:80]}...")
                else:
                    removed_count += 1
                    logger.warning(f"_sanitize_api_messages: 移除非法tool_call → func={func.get('name','?')}, args前80={raw_args[:80]}")

            if valid_calls:
                msg_copy = dict(msg)
                msg_copy["tool_calls"] = valid_calls
                sanitized.append(msg_copy)
            else:
                sanitized.append({
                    "role": "assistant",
                    "content": msg.get("content", "") or "[工具调用参数损坏，已移除]"
                })

        if removed_count > 0:
            logger.info(f"_sanitize_api_messages: 共移除 {removed_count} 个非法 tool_call")
        return sanitized

    def _try_fix_truncated_json(self, s: str) -> Optional[str]:
        """尝试修复被截断的 JSON 字符串"""
        import json as _json
        if not s or not s.strip():
            return None

        s = s.strip()
        stack = []
        in_str = False
        escape = False
        for ch in s:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in '{[':
                stack.append(ch)
            elif ch in '}]':
                if stack and ((ch == '}' and stack[-1] == '{') or (ch == ']' and stack[-1] == '[')):
                    stack.pop()

        if not stack:
            if in_str:
                s = s + '"'
            try:
                _json.loads(s)
                return s
            except _json.JSONDecodeError:
                return None

        close_map = {'{': '}', '[': ']'}
        suffix = ''.join(close_map[c] for c in reversed(stack))
        if in_str:
            suffix = '"' + suffix

        fixed = s + suffix
        try:
            _json.loads(fixed)
            return fixed
        except _json.JSONDecodeError:
            return None

    # ──────────────────────────────────────────────
    # 辅助方法（潜意识、多模态、L2 过滤）
    # ──────────────────────────────────────────────

    def _get_subconscious_context(self):
        """读取潜意识引擎状态并格式化为上下文"""
        import os, json
        try:
            try:
                from tea_agent.config import get_config
                cfg = get_config()
                data_dir = cfg.paths.data_dir_abs
            except:
                data_dir = os.path.expanduser("~/.tea_agent")

            state_file = os.path.join(data_dir, "subconscious_state.json")
            if not os.path.exists(state_file):
                return None

            with open(state_file, 'r') as f:
                state = json.load(f)

            goals = state.get("goals", [])
            insights = state.get("insights", [])
            focus = state.get("last_focus", "mixed")

            if not goals and not insights:
                return None

            lines = [f"## 潜意识引擎状态 (场景: {focus})"]

            if goals:
                lines.append("### 🎯 当前目标 (Goals)")
                for g in goals[:3]:
                    lines.append(f"- {g}")

            if insights:
                lines.append("### 💡 最新洞察 (Insights)")
                for i in insights[:3]:
                    lines.append(f"- {i}")

            return "\n".join(lines)
        except Exception:
            return None

    def _to_multimodal(self, msg: Dict) -> Dict:
        """如果消息包含 images 字段，将 content 转换为多模态格式。"""
        images = msg.pop("images", None)
        if not images:
            return msg
        if not self.context.supports_vision:
            skipped = len(images)
            logger.warning(f"模型 {self.context.model} 不支持视觉，跳过 {skipped} 张图片")
            text = msg.get("content", "")
            if not text:
                msg["content"] = "[图片]（当前模型不支持视觉，图片已跳过）"
            return msg
        import base64, os
        text = msg.get("content", "")
        parts = []
        if text:
            parts.append({"type": "text", "text": text})
        for img_path in images:
            if not os.path.isfile(img_path):
                continue
            try:
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                ext = os.path.splitext(img_path)[1].lower()
                mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                           ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
                mime = mime_map.get(ext, "image/png")
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                })
            except Exception as e:
                logger.warning(f"图片编码失败 {img_path}: {e}")
        if not parts:
            msg["content"] = ""
            return msg
        if len(parts) == 1 and parts[0]["type"] == "text":
            msg["content"] = text
            return msg
        msg["content"] = parts
        return msg

    def _filter_level2_by_relevance(self, level2: list, current_msg: str) -> list:
        """按语义相关性筛选 Level 2 条目。"""
        if not level2 or not current_msg:
            return [{"kind": "full", **p} for p in level2]

        def _key_words(text):
            import re
            cn = re.findall(r'[一-鿿]{2,}', text)
            en = re.findall(r'[a-zA-Z_]{3,}', text.lower())
            return set(cn + en)

        def _extract_files_from_text(text):
            import re
            files = set()
            for m in re.finditer(r'[\w.-]+/[\w.-]+(?:/[\w.-]+)*\.\w+', text):
                files.add(m.group())
            symbols = set(re.findall(r'\b[a-zA-Z_]\w{2,}\b', text))
            if symbols:
                try:
                    import os, json as _json
                    idx_path = os.path.join('.tea_agent_run', 'symbol_index.json')
                    if os.path.exists(idx_path):
                        with open(idx_path, 'r', encoding='utf-8') as _f:
                            sym_index = _json.load(_f)
                        for sym in symbols:
                            if sym in sym_index:
                                for entry in sym_index[sym]:
                                    fp = entry.get('path', '')
                                    if fp:
                                        files.add(fp)
                except Exception:
                    pass
            return files

        k_current = _key_words(current_msg)
        current_files = _extract_files_from_text(current_msg)

        scored = []
        for pair in level2:
            k_pair = _key_words(pair.get("user", "") + " " + pair.get("assistant", ""))
            if not k_current or not k_pair:
                score = 0.5
            else:
                intersection = k_current & k_pair
                union = k_current | k_pair
                score = len(intersection) / max(len(union), 1)

            pair_files = set(pair.get("files", []))
            if current_files and pair_files:
                file_overlap = len(current_files & pair_files)
                if file_overlap > 0:
                    score = max(score, 0.4 + file_overlap * 0.1)

            scored.append((score, pair))

        result = []
        for score, pair in scored:
            if score >= 0.15:
                result.append({"kind": "full", **pair})
            elif score >= 0.05:
                user_brief = pair.get("user", "")[:80]
                ai_brief = pair.get("assistant", "")[:120]
                result.append({
                    "kind": "summary",
                    "content": f"User: {user_brief}... → Assistant: {ai_brief}..."
                })

        if not result and scored:
            _, best = max(scored, key=lambda x: x[0])
            result = [{"kind": "full", **best}]

        logger.debug(
            f"L2 filter: {len(level2)} in -> {len(result)} out "
            f"(scores: {[round(s,3) for s,_ in scored]})"
        )
        return result

    # ──────────────────────────────────────────────
    # 意图分析与工具循环
    # ──────────────────────────────────────────────

    def _analyze_intent(self, text: str) -> dict:
        """轻量级意图分析"""
        import re
        text_lower = text.lower().strip()

        if re.match(r'^(你好|谢谢|在吗|确认|好的|是的|不是|收到|ok|yes|no|bye|hello|hi)\W*$', text_lower):
            return {'type': 'chat', 'skip_tool_loop': True, 'required_tools': []}

        tools = []
        if re.search(r'文件|目录|读取|写入|列表|file|dir|list|read|write', text_lower):
            tools.extend(['toolkit_file', 'toolkit_exec'])
        if re.search(r'天气|气温|forecast|weather|温度', text_lower):
            tools.append('toolkit_weather_my')
        if re.search(r'时间|日期|农历|几点了|time|date|星期', text_lower):
            tools.extend(['toolkit_gettime', 'toolkit_date_diff', 'toolkit_lunar'])
        if re.search(r'安装|包|依赖|pip|install|package|模块', text_lower):
            tools.append('toolkit_pkg')
        if re.search(r'命令|执行|运行|shell|cmd|run|execute|git|push', text_lower):
            tools.append('toolkit_exec')
        if re.search(r'记忆|搜索|记录|search|memory|remember|遗忘', text_lower):
            tools.append('toolkit_memory')
        if re.search(r'知识|文档|笔记|kb|note|knowledge', text_lower):
            tools.append('toolkit_kb')
        if re.search(r'模式|pragmatic|creative|切换', text_lower):
            tools.append('toolkit_mode')

        if tools:
            return {'type': 'task', 'skip_tool_loop': False, 'required_tools': list(set(tools))}

        return {'type': 'general', 'skip_tool_loop': False, 'required_tools': None}

    def _execute_tool_loop(self, context: Dict) -> Dict:
        """
        执行工具调用循环。
        委派给各个组件处理。
        """
        msg = context.get("msg", "")
        callback = context.get("callback", lambda x: None)
        on_status = context.get("on_status", None)

        # Level 1: 动态跳过
        if context.get("skip_tool_loop"):
            logger.info("[Pipe Dynamic] Skipping tool loop (chat intent)")
            try:
                api_messages = self._build_api_messages()
                eff = self._get_effective_params("main")
                response = self.api.create_chat_stream(
                    api_messages, tools=[],
                    temperature=eff.get("temperature"),
                    max_tokens=eff.get("max_tokens"),
                    top_p=eff.get("top_p"),
                )
                content, _, reasoning = self._process_stream_with_reasoning(response, callback)
                self.add_assistant_message(content, reasoning)
                self.tools_comp.collect_assistant_text_round(content, reasoning)
                return {"full_reply": content, "used_tools": False, "iterations": 1}
            except Exception as e:
                logger.warning(f"Direct answer failed, falling back: {e}")

        full_reply = ""
        used_tools = False
        iterations = 0

        while iterations < self.max_iterations + self._extra_iterations:
            if self.interrupted:
                final_msg = full_reply + "\n[已打断]"
                self.add_assistant_message(final_msg)
                self.tools_comp.collect_interruption_round(final_msg)
                return {
                    "full_reply": final_msg,
                    "used_tools": used_tools,
                    "interrupted": True,
                }

            api_messages = self._build_api_messages()

            if iterations == 0:
                import time
                asctime = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"{asctime}: call model: {self.context.model}, {msg}")
                logger.info(f"call model: {self.context.model}, {msg}")

            logger.debug(f"model request: model={self.context.model}, msgs={len(api_messages)}, tools={len(self.tools)}, iteration={iterations}")
            sys_msg_preview = api_messages[0]['content'][:100] if api_messages else ""
            logger.debug(f"system_prompt preview: {sys_msg_preview}")

            try:
                eff = self._get_effective_params("main")
                response = self.api.create_chat_stream(
                    api_messages, self.tools,
                    temperature=eff.get("temperature"),
                    max_tokens=eff.get("max_tokens"),
                    top_p=eff.get("top_p"),
                )
            except Exception as e:
                error_msg = f"API调用错误: {e}"
                logger.warning(f"API调用失败: model={self.context.model}, error={e}, iteration={iterations}")
                callback(error_msg)
                self.add_assistant_message(full_reply + error_msg)
                self.tools_comp.collect_api_error_round(full_reply + error_msg)
                return {
                    "full_reply": full_reply + error_msg,
                    "used_tools": used_tools,
                    "error": e,
                }

            # 处理流式响应
            content, tool_calls_data, reasoning_content = self._process_stream_with_reasoning(response, callback)
            full_reply += content
            logger.debug(f"model response: content_len={len(content)}, reasoning_len={len(reasoning_content)}, tool_calls_data={len(tool_calls_data)}, usage={self.context._last_usage}")

            # 解析工具调用（委派给 Tool 组件）
            valid_tool_calls = self.tools_comp.parse_tool_calls_from_stream(tool_calls_data)

            if valid_tool_calls:
                used_tools = True
                callback("[THINK_DONE]")

                if on_status:
                    on_status(f"⏳ 生成中... 调用工具第{iterations+1}轮 (ESC 打断)")

                # 收集 assistant tool_calls（委派给 Tool 组件）
                self.tools_comp.collect_assistant_tool_calls_round(content, valid_tool_calls, reasoning_content)

                assistant_msg = {
                    "role": "assistant",
                    "content": content if content else None,
                    "tool_calls": [{
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in valid_tool_calls]
                }
                if reasoning_content:
                    assistant_msg["reasoning_content"] = reasoning_content

                self.context.messages.append(assistant_msg)

                has_reload = any(
                    tc.function.name == "toolkit_reload"
                    for tc in valid_tool_calls
                )

                for call in valid_tool_calls:
                    import time as _time
                    _asctime = _time.strftime("%Y-%m-%d %H:%M:%S")
                    print(f"{_asctime}: \t#{iterations+1}: 调用工具:{call.function.name}")
                    logger.info(f"    tool call #{iterations+1}: {call.function.name}, args_len={len(call.function.arguments)}")
                    # 委派给 Tool 组件执行
                    call_id, func_name, result_str = self.tools_comp.execute_tool_call(call)
                    logger.debug(f"tool result #{iterations+1}: {func_name}, result_len={len(result_str) if result_str else 0}")
                    self.tools_comp.collect_tool_call_round(call_id, result_str)

                if has_reload:
                    self._build_tools()

                iterations += 1

                if iterations >= self.max_iterations + self._extra_iterations:
                    if on_status:
                        on_status(f"!MAX_ITER:已执行{iterations}轮，上限{self.max_iterations + self._extra_iterations}，是否继续？")
                        while not self._max_iter_wait.wait(timeout=0.5):
                            if self.interrupted:
                                final_msg = full_reply + "\n[已打断]"
                                self.add_assistant_message(final_msg)
                                self.tools_comp.collect_interruption_round(final_msg)
                                return {
                                    "full_reply": final_msg,
                                    "used_tools": used_tools,
                                    "interrupted": True,
                                }
                        if not self._continue_after_max:
                            warning = f"\n\n[用户选择终止，已执行 {iterations} 轮工具调用]"
                            callback(warning)
                            full_reply += warning
                            self.add_assistant_message(full_reply)
                            self.tools_comp.collect_max_iterations_round(full_reply)
                            break
                        self._extra_iterations += self.context.extra_iterations_on_continue
                        self._continue_after_max = False
                        self._max_iter_wait.clear()
                        on_status("⏳ 已续命5轮，继续生成... (ESC 打断)")
                        continue
                    else:
                        warning = f"\n\n[警告：已达到最大迭代次数 {self.max_iterations}，对话终止]"
                        callback(warning)
                        full_reply += warning
                        self.add_assistant_message(full_reply)
                        self.tools_comp.collect_max_iterations_round(full_reply)
                        break

                if content:
                    callback("\n\n[正在执行工具，处理中...]\n\n")

                continue

            elif content:
                iterations += 1
                assistant_msg = {"role": "assistant", "content": content}
                if reasoning_content:
                    assistant_msg["reasoning_content"] = reasoning_content
                self.context.messages.append(assistant_msg)
                self.tools_comp.collect_assistant_text_round(content, reasoning_content)
                break
            else:
                break

        return {
            "full_reply": full_reply,
            "used_tools": used_tools,
            "iterations": iterations,
        }

    def _build_tools(self, tool_filter: list = None):
        """构建工具定义列表"""
        tools = self.tools_comp.build_tools()
        
        # 通过 SkillManager 过滤
        active_tools = self.skill_manager.get_active_tools_meta(self.context.toolkit.meta_map)
        if active_tools:
            tools = active_tools
        else:
            tools = tools

        if tool_filter:
            essential = {'toolkit_memory', 'toolkit_kb'}
            allowed = set(tool_filter) | essential
            self.tools = [t for t in tools if t['function']['name'] in allowed]
            logger.info(f"[Pipe Dynamic] Tool Injection: enabled {len(self.tools)} tools based on intent")
        else:
            self.tools = tools

    def update_tools(self):
        """重新加载并刷新工具定义"""
        self.context.toolkit.reload()
        self._build_tools()

    def _auto_detect_mode(self, user_text: str):
        """根据用户输入自动检测并切换 Agent 模式。"""
        try:
            result = self.context.toolkit.call_tool('toolkit_mode', action='auto', text=user_text)
            if isinstance(result, dict):
                if result.get('switched'):
                    logger.info(
                        f"🤖 自动切换模式: {result.get('from_mode')} → {result.get('to_mode')} "
                        f"(原因: {result.get('reason', 'N/A')})"
                    )
                detected = result.get('to_mode') or result.get('mode') or result.get('detected')
                if detected and detected in ("pragmatic", "creative", "mixed"):
                    self._current_mode = detected
        except Exception:
            pass

    def reset_session_state(self):
        """重置会话状态。"""
        self.api.reset_usage()
        self.api.reset_cheap_usage()
        self._rounds_collector = []
        self._extra_iterations = 0
        self._max_iter_wait.clear()
        self._strip_reasoning_content(self.context.messages)

    def _notify_reflection_done(self, reflection_id: int):
        """反思完成后发送桌面通知"""
        try:
            import subprocess
            subprocess.run([
                "notify-send", "🔍 元认知反思完成",
                f"反思 #{reflection_id} 已生成\n建议已存储到数据库",
                "--expire-time=5000"
            ], capture_output=True, timeout=3)
        except Exception:
            pass

    def _notify_prompt_evolved(self, version: int):
        """提示词进化后发送桌面通知"""
        try:
            import subprocess
            subprocess.run([
                "notify-send", "📝 提示词进化",
                f"系统提示词已进化到 v{version}\n优化已应用于下一轮对话",
                "--expire-time=5000"
            ], capture_output=True, timeout=3)
        except Exception:
            pass

    def chat_stream(self, msg: str, callback: Callable[[str], None], topic_id: int = -1, on_status: Optional[Callable[[str], None]] = None) -> Tuple[str, bool]:
        """
        流式对话，支持工具调用。
        使用 Pipeline 执行可配置的步骤。
        """
        _msg_text = msg if isinstance(msg, str) else msg.get("text", "")
        _msg_images = None if isinstance(msg, str) else msg.get("images", [])

        if _msg_images and not self.context.supports_vision:
            error_msg = f"⚠️ 当前模型 {self.context.model} 不支持图片输入，请更换支持视觉的模型或移除图片后重试。"
            logger.warning(error_msg)
            callback(error_msg)
            return error_msg, False

        logger.debug(f"chat_stream start: msg_len={len(str(msg))}, topic_id={topic_id}, model={self.context.model}, enable_thinking={self.context.enable_thinking}")
        logger.debug(f"chat_stream user message: {_msg_text[:200]}..." if len(_msg_text) > 200 else f"chat_stream user message: {_msg_text}")

        self.current_topic_id = topic_id
        self.reset_interrupt()
        self.reset_session_state()

        self.skill_manager.auto_activate(_msg_text)
        self._auto_detect_mode(_msg_text)

        intent = self._analyze_intent(_msg_text)

        if intent.get('required_tools'):
            self._build_tools(tool_filter=intent['required_tools'])
        else:
            self._build_tools()

        context = {
            "user_msg": msg,
            "msg": _msg_text,
            "callback": callback,
            "on_status": on_status,
        }

        if intent.get('skip_tool_loop'):
            context['skip_tool_loop'] = True

        # 开始反思追踪
        if self.reflection_manager is not None:
            trace = self.reflection_manager.start_trace(topic_id, _msg_text)
            self.context._current_trace = trace
        else:
            self.context._current_trace = None

        # 执行 Pipeline
        result = self.pipeline.execute(context)

        full_reply = result.get("full_reply", "")
        used_tools = result.get("used_tools", False)
        iterations = result.get("iterations", 0)

        # 完成追踪
        if self.reflection_manager is not None and self.context._current_trace is not None:
            self.reflection_manager.finish_trace(
                self.context._current_trace,
                total_iterations=iterations,
                used_tools=used_tools,
                interrupted=result.get("interrupted", False),
                error=str(result.get("error", "")) if result.get("error") else None,
            )

        # 自动提取记忆
        import threading
        if isinstance(topic_id, str) and topic_id and not result.get("interrupted", False):
            def _auto_extract():
                try:
                    count = self.memory_comp.trigger_memory_extraction(topic_id)
                    if count > 0 and on_status:
                        on_status(f"🧠 自动提取了 {count} 条新记忆")
                except Exception:
                    pass
            threading.Thread(target=_auto_extract, daemon=True).start()

        # 异步触发反思
        if not result.get("interrupted", False) and self.reflection_manager is not None:
            def _auto_reflect():
                try:
                    if self.reflection_manager.should_reflect():
                        rid = self.reflection_manager.generate_reflection()
                        if rid:
                            if on_status:
                                on_status(f"🔍 元认知反思完成 (id={rid})")
                            self._notify_reflection_done(rid)
                        if self.reflection_manager.last_prompt_suggestion and self.prompt_manager is not None:
                            new_pid = self.prompt_manager.evolve(
                                reflection_suggestion=self.reflection_manager.last_prompt_suggestion
                            )
                            if new_pid:
                                if on_status:
                                    on_status(f"📝 系统提示词进化到 v{self.prompt_manager.current_version}")
                                self._notify_prompt_evolved(self.prompt_manager.current_version)
                except Exception:
                    pass
            threading.Thread(target=_auto_reflect, daemon=True).start()

        return full_reply, used_tools
