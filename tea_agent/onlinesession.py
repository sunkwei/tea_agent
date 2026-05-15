"""
在线工具调用会话 - Token 优化版
支持 OpenAI 兼容 API 的 Function Calling 功能

Token 优化策略:
1. 压缩系统提示词 (~200 tokens, 原 ~1000+)
2. 历史摘要：超过5轮的对话自动摘要，只传摘要+最近N轮
3. 工具输出截断：超长结果截断至 max_tool_output 字符
4. 助手回复截断：超长回复截断至 max_assistant_content 字符
5. 长期记忆注入：相关记忆在每次对话中自动注入（上限5条）
"""

from openai import OpenAI
from typing import List, Dict, Callable, Tuple, Any, Optional
import logging

from tea_agent.basesession import BaseChatSession
from tea_agent.session_summarizer import SessionSummarizerMixin
from tea_agent.session_tool import SessionToolMixin
from tea_agent.session_api import SessionAPIMixin
from tea_agent.session_prompts import COMPACT_SYSTEM_PROMPT
from tea_agent.session_pipeline import SessionPipeline
from tea_agent.session_memory import SessionMemoryMixin
from tea_agent.skills import SkillManager

logger = logging.getLogger("session")

class OnlineToolSession(
    BaseChatSession,
    SessionSummarizerMixin,
    SessionToolMixin,
    SessionAPIMixin,
    SessionMemoryMixin,
):
    """
    在线工具调用会话 - Token 优化版
    支持 OpenAI 兼容 API 的 Function Calling 功能

    Token 优化策略:
    - 历史摘要：超过 keep_turns 轮的对话自动摘要，只传摘要 + 最近 N 轮
    - 紧凑消息：工具输出和助手回复超长时截断
    - 精简系统提示词（~200 tokens，原 ~1000+）
    - 长期记忆：从 DB 按优先级+相关性选择最多 5 条注入

    中间轮次存储策略:
    - chat_stream 期间收集所有中间 request/response 到 _rounds_collector
    - 流结束后由调用方通过 storage.update_msg_rounds() 一次性写入 conversations 表
    - rounds_json 列存储 OpenAI API 消息格式的完整工具调用链
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
# NOTE: 2026-04-30 14:35:38, self-evolved by tea_agent --- OnlineToolSession增加memory_dedup_threshold参数
# NOTE: 2026-05-15 08:10:48, self-evolved by tea_agent --- 添加 supports_vision 参数，默认 False，避免非视觉模型发送 image_url 报错
        memory_extraction_threshold: int = 2,
# NOTE: 2026-04-30 14:39:12, self-evolved by tea_agent --- onlinesession默认dedup改为0.3
        memory_dedup_threshold: float = 0.3,
        # NOTE: 2026-05-18 gen by tea_agent, 视觉支持开关，默认关闭避免非视觉模型报 image_url 错误
        supports_vision: bool = False,
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
            cheap_api_key: 便宜模型 API密钥（用于摘要等低成本任务）
            cheap_api_url: 便宜模型 API地址
            cheap_model: 便宜模型名称
            keep_turns: 保留最近N轮完整对话，更早的对话自动摘要
            max_tool_output: 工具输出截断字符数
            max_assistant_content: 助手回复截断字符数
            extra_iterations_on_continue: 续命时追加的工具调用轮数
            memory_extraction_threshold: 触发记忆提取的最低未摘要消息数
            memory_dedup_threshold: 记忆去重相似度阈值 (0~1)
            
            # NOTE: 2026-04-30 14:35:45, self-evolved by tea_agent --- memory_dedup_threshold文档+属性赋值
        """
        sp = system_prompt or self._COMPACT_SYSTEM_PROMPT
        BaseChatSession.__init__(self, model, max_history, sp)
        SessionSummarizerMixin.__init__(self)
        SessionToolMixin.__init__(self)
        SessionAPIMixin.__init__(self)
        SessionMemoryMixin.__init__(self)

        logger.info(f"OnlineToolSession init ok: main model: {model}, cheap model: {cheap_model}")

        self.toolkit = toolkit
        # NOTE: 2026-05-18 gen by tea_agent, 禁用代理避免 localhost 请求被拦截
        import httpx
        _http_client = httpx.Client(proxy=None)
        self.client = OpenAI(api_key=api_key, base_url=api_url, http_client=_http_client)
        self.max_iterations = max_iterations
        self.enable_thinking = enable_thinking
        self.storage = storage

        # 便宜模型客户端
        self._cheap_client: Optional[OpenAI] = None
        self._cheap_model_name: str = ""
        if cheap_api_key and cheap_api_url and cheap_model:
            self._cheap_client = OpenAI(api_key=cheap_api_key, base_url=cheap_api_url, http_client=httpx.Client(proxy=None))
            self._cheap_model_name = cheap_model

        # Token 优化参数
        self.keep_turns = keep_turns
        self.max_tool_output = max_tool_output
        self.max_assistant_content = max_assistant_content
        self.extra_iterations_on_continue = extra_iterations_on_continue
# NOTE: 2026-04-30 14:35:54, self-evolved by tea_agent --- memory_dedup_threshold属性赋值
        self.memory_extraction_threshold = memory_extraction_threshold
# NOTE: 2026-05-15 08:10:57, self-evolved by tea_agent --- 存储 supports_vision 到实例属性 self._supports_vision
        self.memory_dedup_threshold = memory_dedup_threshold
        # NOTE: 2026-05-18 gen by tea_agent, 视觉支持开关
        self._supports_vision = supports_vision

        # @2026-04-29 gen by deepseek-v4-pro, max_iterations交互式续跑
        import threading
        self._extra_iterations = 0
        self._continue_after_max = False
        self._max_iter_wait = threading.Event()


# NOTE: 2026-04-30 16:20:54, self-evolved by tea_agent --- __init__集成ReflectionManager和SystemPromptManager，使用动态系统提示词
        # 工具定义
        self.tools: List[Dict] = []
        
        # 初始化 Skill 管理器（必须在 _build_tools 之前）
        self.skill_manager = SkillManager.get_instance()
        self.skill_manager.discover_skills()
        # 默认激活 utility 和 file_system（最小可用集）
# NOTE: 2026-05-10 09:00:13, self-evolved by tea_agent --- 永久激活 memory_knowledge skill，确保记忆/模式/反思基础设施始终可用
        self.skill_manager.activate_skill("utility")
        self.skill_manager.activate_skill("file_system")
        self.skill_manager.activate_skill("memory_knowledge")
        
        self._build_tools()
        
        # 初始化 Memory 管理器（在 storage 设置之后）
        self._setup_memory()

# NOTE: 2026-04-30 16:23:02, self-evolved by tea_agent --- storage=None时安全跳过ReflectionManager/PromptManager初始化
        # 2026-04-30 gen by deepseek-v4-pro, 初始化反思管理器和提示词管理器
        if self.storage is not None:
            from tea_agent.reflection import ReflectionManager
            from tea_agent.prompt_manager import SystemPromptManager
            self.reflection_manager = ReflectionManager(
                storage=self.storage,
                cheap_client=self._cheap_client,
                cheap_model=self._cheap_model_name,
            )
            self.prompt_manager = SystemPromptManager(
                storage=self.storage,
                cheap_client=self._cheap_client,
                cheap_model=self._cheap_model_name,
            )
# NOTE: 2026-04-30 16:24:50, self-evolved by tea_agent --- 动态提示词只设置self.system_prompt，不操作self.messages[0]（会被load_history重建）
            # 加载最新系统提示词（替换默认的）
            dynamic_prompt = self.prompt_manager.initialize()
            # 如果用户没有显式指定 system_prompt，使用动态版本
            if not system_prompt:
                self.system_prompt = dynamic_prompt
            logger.info(f"系统提示词 v{self.prompt_manager.current_version} 已加载")
        else:
            self.reflection_manager = None
            self.prompt_manager = None
            logger.info("Storage 未设置，跳过 ReflectionManager/PromptManager 初始化")

        # 初始化 Pipeline
        self.pipeline = SessionPipeline()
        self._setup_default_pipeline()

    def _process_stream_with_reasoning(self, response, callback) -> Tuple[str, List[Dict], str]:
        """
        处理流式响应，收集内容、工具调用数据和 reasoning_content。
        
        Args:
            response: 流式响应迭代器
            callback: 流式输出回调函数
            
        Returns:
            Tuple[str, List[Dict], str]: (累积文本内容, 工具调用数据列表, reasoning_content)
        """
        content_parts = []
        tool_calls_data = []
        reasoning_parts = []
        
        for chunk in response:
            # 累积 usage 信息
            if hasattr(chunk, 'usage') and chunk.usage:
                self._accumulate_usage(chunk.usage)
            
            if not hasattr(chunk, 'choices') or not chunk.choices:
                continue
            
            delta = chunk.choices[0].delta
            
# NOTE: 2026-05-07 17:31:36, self-evolved by tea_agent --- _process_stream_with_reasoning: reasoning_content 也回调给 GUI（[THINK]前缀标记）
            # 处理 reasoning_content（流式回调，让用户看到模型正在思考）
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)
                # 带 [THINK] 前缀标记，供 GUI 识别并渲染为思考块
                callback(f"[THINK]{delta.reasoning_content}")
            
            # 处理内容
            if delta.content:
                content_parts.append(delta.content)
                callback(delta.content)
            
            # 处理工具调用
            if delta.tool_calls:
                self._accumulate_tool_calls_from_delta(delta, tool_calls_data)
        
        content = "".join(content_parts)
        reasoning_content = "".join(reasoning_parts)
        return content, tool_calls_data, reasoning_content

    def _setup_default_pipeline(self):
        """设置默认的 Pipeline 步骤"""
        # 1. 记忆注入（在用户消息添加后、摘要前）
        self.pipeline.register_step(
            name="inject_memories",
            func=self._pipeline_inject_memories,
            enabled=True,
            description="从长期记忆中注入相关记忆",
            position=15,
        )
        
        # 2. 添加用户消息
        self.pipeline.register_step(
            name="add_user_message",
            func=lambda ctx: (self.add_user_message(ctx.get("user_msg", "")), self.messages)[1],
            enabled=True,
            description="添加用户消息到会话历史",
            position=20,
        )
        
        # 3. 摘要旧历史
        self.pipeline.register_step(
            name="summarize_old_history",
            func=lambda ctx: (self._summarize_old_history(), self.messages)[1],
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

    # NOTE: 2026-04-29, self-evolved by claude-agent ---
    # _build_api_messages 在系统提示词之后注入长期记忆。
    # 记忆注入位置：system prompt → [记忆] → summary → recent messages
    # 这样模型在处理当前请求时能优先看到相关记忆。
        # @2026-04-29 gen by deepseek-v4-pro, on_status回调+记忆注入至_build_api_messages
    def _build_api_messages(self) -> List[Dict]:
        """
        三级历史拼接：
            Level 0: 系统提示词 + 长期记忆注入
            Level 3: 语义摘要 + 工具链摘要
            Level 2: 按语义相关性筛选的 user+assistant 对
            Level 1: 最新一轮完整对话（含工具调用链）
        """
        result: List[Dict] = []

        # ── Level 0: 系统提示词 + Skill 注入 ──
        sys_msg = dict(self.messages[0])
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

# NOTE: 2026-05-15 14:13:14, self-evolved by tea_agent --- 在 _build_api_messages 中注入潜意识目标与洞察
        # ── 潜意识引擎状态注入 (Subconscious State) ──
        sub_ctx = self._get_subconscious_context()
        if sub_ctx:
            result.append({
                "role": "user",
                "content": sub_ctx
            })

        # ── 长期记忆注入 ──
        if self._injected_memories_text:
            result.append({
                "role": "user",
                "content": self._injected_memories_text
            })

        # ── Level 3: 摘要 ──
        has_level3 = False
        parts = []
        sem = getattr(self, '_semantic_summary', '')
        tc = getattr(self, '_tool_chain_summary', '')
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
            result.append({
                "role": "assistant",
                "content": "好的，我已经了解了之前的对话背景。请问有什么我可以帮您的？",
                "reasoning_content": ""
            })

        # ── 兼容旧 _history_summary ──
        if not has_level3 and self._history_summary:
            result.append({
                "role": "user",
                "content": f"这是我们之前对话的摘要：\n{self._history_summary}"
            })
            result.append({
                "role": "assistant",
                "content": "好的，我已经了解了之前的对话背景。请问有什么我可以帮您的？",
                "reasoning_content": ""
            })

        # ── Level 2: 按语义相关性筛选 ──
        level2 = getattr(self, '_level2', [])
        if level2:
            current_user_msg = ""
            for i in range(len(self.messages)-1, 0, -1):
                if self.messages[i].get("role") == "user":
                    cur_content = self.messages[i].get("content", "")
                    # NOTE: 2026-05-15 gen by tea_agent, 处理多模态 content（list 格式）
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
                    result.append({"role": "assistant", "content": item.get("assistant", ""),
                                  "reasoning_content": ""})

        # ── Level 1: 最新一轮完整对话 ──
        for i in range(1, len(self.messages)):
            msg = self.messages[i]
            msg_copy = dict(msg)
            if msg_copy["role"] == "assistant" and "reasoning_content" not in msg_copy:
                msg_copy["reasoning_content"] = ""
            # NOTE: 2026-05-15 gen by tea_agent, 将含 images 的消息转为多模态格式
            msg_copy = self._to_multimodal(msg_copy)
            # NOTE: 2026-05-19 gen by tea_agent, 清理历史中残留的 image_url 格式 content，避免非视觉模型 API 400 错误
            if isinstance(msg_copy.get("content"), list) and not getattr(self, '_supports_vision', False):
                text_parts = []
                for p in msg_copy["content"]:
                    if isinstance(p, dict):
                        if p.get("type") == "text":
                            text_parts.append(p.get("text", ""))
                        elif p.get("type") == "image_url":
                            text_parts.append("[图片]")
                msg_copy["content"] = "\n".join(text_parts) if text_parts else "[图片]"
            result.append(msg_copy)

        return result

    # NOTE: 2026-05-15 gen by tea_agent, 将消息中的 images 字段转换为 OpenAI 多模态 content 格式
# NOTE: 2026-05-15 08:11:10, self-evolved by tea_agent --- _to_multimodal 检查 supports_vision，不支持则跳过图片并记录警告
# NOTE: 2026-05-15 14:13:58, self-evolved by tea_agent --- 添加 _get_subconscious_context 辅助方法
    def _get_subconscious_context(self):
        """读取潜意识引擎状态并格式化为上下文，注入到每一轮对话中"""
        import os, json
        try:
            # 1. 获取状态文件路径
            try:
                from tea_agent.config import get_config
                cfg = get_config()
                data_dir = cfg.paths.data_dir_abs
            except:
                data_dir = os.path.expanduser("~/.tea_agent")
            
            state_file = os.path.join(data_dir, "subconscious_state.json")
            if not os.path.exists(state_file):
                return None

            # 2. 读取状态
            with open(state_file, 'r') as f:
                state = json.load(f)

            # 3. 提取目标和洞察
            goals = state.get("goals", [])
            insights = state.get("insights", [])
            focus = state.get("last_focus", "mixed")
            
            if not goals and not insights:
                return None

            # 4. 格式化
            lines = [f"## 潜意识引擎状态 (场景: {focus})"]
            
            if goals:
                lines.append("### 🎯 当前目标 (Goals)")
                for g in goals[:3]:  # 限制数量，避免占用过多 token
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
        # NOTE: 2026-05-18 gen by tea_agent, 检查模型是否支持视觉，不支持则跳过图片
        if not getattr(self, '_supports_vision', False):
            skipped = len(images)
            logger.warning(f"模型 {self.model} 不支持视觉，跳过 {skipped} 张图片")
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

    # NOTE: 2025-07-16 gen by tea_agent, Level 2 语义相关性过滤
    def _filter_level2_by_relevance(self, level2: list, current_msg: str) -> list:
        """按语义相关性筛选 Level 2 条目。

        HIGH  → 保留完整 user+assistant
        MEDIUM → 压缩为一行摘要
        LOW   → 丢弃

        评分 = 关键词重叠(Jaccard) + 文件重叠加成。
        文件重叠：从 current_msg 提取路径 → 匹配 Level 2 条目的 files 字段。
        """
        if not level2 or not current_msg:
            return [{"kind": "full", **p} for p in level2]

        # ── 1. 关键词重叠快速打分 ──
        def _key_words(text):
            import re
            # 提取中文词(2+字)、英文词(3+字母)
            cn = re.findall(r'[一-鿿]{2,}', text)
            en = re.findall(r'[a-zA-Z_]{3,}', text.lower())
            return set(cn + en)

        # ── 1b. 从当前消息提取文件路径 ──
        def _extract_files_from_text(text):
            import re
            files = set()
            # 匹配显式文件路径: foo/bar.py, tea_agent/store.py 等
            for m in re.finditer(r'[\w.-]+/[\w.-]+(?:/[\w.-]+)*\.\w+', text):
                files.add(m.group())
            # 尝试 explr 符号索引：提取可能为函数/类名的标识符，反查文件
            symbols = set(re.findall(r'[a-zA-Z_]\w{2,}', text))
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
                    pass  # explr 不可用时静默跳过
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

            # ── 文件重叠加成 ──
            pair_files = set(pair.get("files", []))
            if current_files and pair_files:
                file_overlap = len(current_files & pair_files)
                if file_overlap > 0:
                    # 文件匹配直接拉至 HIGH，最小 0.4 + 每个匹配文件 +0.1
                    score = max(score, 0.4 + file_overlap * 0.1)

            scored.append((score, pair))

        # ── 2. 按分数分类 ──
        result = []
        for score, pair in scored:
            if score >= 0.15:
                # HIGH: keep full
                result.append({"kind": "full", **pair})
            elif score >= 0.05:
                # MEDIUM: brief summary
                user_brief = pair.get("user", "")[:80]
                ai_brief = pair.get("assistant", "")[:120]
                result.append({
                    "kind": "summary",
                    "content": f"User: {user_brief}... → Assistant: {ai_brief}..."
                })
            # else LOW: discard

        # ── 3. 如果全部被过滤，至少保留最近1条 ──
        if not result and scored:
            _, best = max(scored, key=lambda x: x[0])
            result = [{"kind": "full", **best}]

        logger.debug(
            f"L2 filter: {len(level2)} in -> {len(result)} out "
            f"(scores: {[round(s,3) for s,_ in scored]})"
        )
        return result

# NOTE: 2026-05-15 14:27:27, self-evolved by tea_agent --- 添加 _analyze_intent 并修改 _execute_tool_loop 支持跳过
    def _analyze_intent(self, text: str) -> dict:
        """轻量级意图分析：用于动态工具注入和流水线跳过"""
        import re
        text_lower = text.lower().strip()
        
        # 1. 闲聊/确认 -> 跳过工具循环
        if re.match(r'^(你好|谢谢|在吗|确认|好的|是的|不是|收到|ok|yes|no|bye|hello|hi)\W*$', text_lower):
            return {'type': 'chat', 'skip_tool_loop': True, 'required_tools': []}
        
        # 2. 任务意图 -> 动态工具集
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

        Args:
            context: 上下文，包含 msg, callback 等

        Returns:
            结果字典，包含 full_reply, used_tools 等
        """
        msg = context.get("msg", "")
        callback = context.get("callback", lambda x: None)
        on_status = context.get("on_status", None)

        # Level 1: 动态跳过 - 如果是闲聊/确认，直接生成回答
        if context.get("skip_tool_loop"):
            logger.info("[Pipe Dynamic] Skipping tool loop (chat intent)")
            try:
                api_messages = self._build_api_messages()
                # 不传 tools，强制模型直接回答
                response = self._create_chat_stream(api_messages, tools=[])
                content, _, reasoning = self._process_stream_with_reasoning(response, callback)
                self.add_assistant_message(content, reasoning)
                self._collect_assistant_text_round(content, reasoning)
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
                self._collect_interruption_round(final_msg)
                return {
                    "full_reply": final_msg,
                    "used_tools": used_tools,
                    "interrupted": True,
                }

# NOTE: 2026-05-07 07:57:11, self-evolved by tea_agent --- 首次模型调用时 print 到控制台：时间 + 模型名 + 用户消息，工具循环轮次不打印
# NOTE: 2026-05-07 11:27:27, self-evolved by tea_agent --- _execute_tool_loop 添加模型请求/响应和工具调用的 DEBUG 日志，API 错误 WARNING 日志
            api_messages = self._build_api_messages()

            # 首次调用打印到控制台（工具调用循环的后续轮次不打印）
            if iterations == 0:
                import time
                asctime = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"{asctime}: call model: {self.model}, {msg}")
                logger.info(f"call model: {self.model}, {msg}")

            logger.debug(f"model request: model={self.model}, msgs={len(api_messages)}, tools={len(self.tools)}, iteration={iterations}")
            sys_msg_preview = api_messages[0]['content'][:100] if api_messages else ""
            logger.debug(f"system_prompt preview: {sys_msg_preview}")

            try:
                response = self._create_chat_stream(api_messages, self.tools)
            except Exception as e:
                error_msg = f"API调用错误: {e}"
                logger.warning(f"API调用失败: model={self.model}, error={e}, iteration={iterations}")
                callback(error_msg)
                self.add_assistant_message(full_reply + error_msg)
                self._collect_api_error_round(full_reply + error_msg)
                return {
                    "full_reply": full_reply + error_msg,
                    "used_tools": used_tools,
                    "error": e,
                }

            # 处理流式响应
            content, tool_calls_data, reasoning_content = self._process_stream_with_reasoning(response, callback)
            full_reply += content
            logger.debug(f"model response: content_len={len(content)}, reasoning_len={len(reasoning_content)}, tool_calls_data={len(tool_calls_data)}, usage={self._last_usage}")

            # 解析工具调用
            valid_tool_calls = self._parse_tool_calls_from_stream(tool_calls_data)

            if valid_tool_calls:
                used_tools = True

                # @2026-05-16 gen by tea_agent, 通知 GUI 本轮思考结束，单独存为思考消息
                callback("[THINK_DONE]")

                if on_status:
                    on_status(f"⏳ 生成中... 调用工具第{iterations+1}轮 (ESC 打断)")

                # NOTE: 2026-04-28, self-evolved by claude-agent ---
                # 收集 assistant tool_calls 时传递 reasoning_content，
                # 确保持久化到 rounds_json 时不会丢失。
                self._collect_assistant_tool_calls_round(content, valid_tool_calls, reasoning_content)

                # 存入完整历史（包含 reasoning_content）
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
                # 如果有 reasoning_content，添加到消息中
                if reasoning_content:
                    assistant_msg["reasoning_content"] = reasoning_content
                
                self.messages.append(assistant_msg)

                # 执行工具调用
                has_reload = any(
                    tc.function.name == "toolkit_reload"
                    for tc in valid_tool_calls
                )

# NOTE: 2026-05-07 08:15:01, self-evolved by tea_agent --- 工具调用循环中打印轮次和工具名：print(f\"\\t#{轮次}: 调用工具:{tool name}\")
# NOTE: 2026-05-07 11:27:40, self-evolved by tea_agent --- 工具调用执行添加 DEBUG 日志：调用名+参数和返回结果
                for call in valid_tool_calls:
                    import time as _time
                    _asctime = _time.strftime("%Y-%m-%d %H:%M:%S")
                    print(f"{_asctime}: \t#{iterations+1}: 调用工具:{call.function.name}")
                    logger.info(f"    tool call #{iterations+1}: {call.function.name}, args_len={len(call.function.arguments)}")
                    call_id, func_name, result_str = self._execute_tool_call(call)
                    logger.debug(f"tool result #{iterations+1}: {func_name}, result_len={len(result_str) if result_str else 0}")
                    self._collect_tool_call_round(call_id, result_str)

                # 如果调用了 reload，刷新本地工具定义
                if has_reload:
                    self._build_tools()

                iterations += 1

                # 达到最大迭代次数 - 交互式续跑
                if iterations >= self.max_iterations + self._extra_iterations:
                    if on_status:
                        # 通知 GUI 弹框询问，轮询等待支持 ESC 打断
                        on_status(f"!MAX_ITER:已执行{iterations}轮，上限{self.max_iterations + self._extra_iterations}，是否继续？")
                        while not self._max_iter_wait.wait(timeout=0.5):
                            if self.interrupted:
                                final_msg = full_reply + "\n[已打断]"
                                self.add_assistant_message(final_msg)
                                self._collect_interruption_round(final_msg)
                                return {
                                    "full_reply": final_msg,
                                    "used_tools": used_tools,
                                    "interrupted": True,
                                }
                        if not self._continue_after_max:
                            # 用户选择终止
                            warning = f"\n\n[用户选择终止，已执行 {iterations} 轮工具调用]"
                            callback(warning)
                            full_reply += warning
                            self.add_assistant_message(full_reply)
                            self._collect_max_iterations_round(full_reply)
                            break
                        # 用户选择继续：追加5轮
                        self._extra_iterations += self.extra_iterations_on_continue
                        self._continue_after_max = False
                        self._max_iter_wait.clear()
                        on_status("⏳ 已续命5轮，继续生成... (ESC 打断)")
                        continue
                    else:
                        # 无 GUI，直接终止
                        warning = f"\n\n[警告：已达到最大迭代次数 {self.max_iterations}，对话终止]"
                        callback(warning)
                        full_reply += warning
                        self.add_assistant_message(full_reply)
                        self._collect_max_iterations_round(full_reply)
                        break


                # 流式反馈
                if content:
                    callback("\n\n[正在执行工具，处理中...]\n\n")

                continue

            elif content:
                # 最终文本回答（包含 reasoning_content）
                iterations += 1  # 计数最后一轮
                assistant_msg = {"role": "assistant", "content": content}
                if reasoning_content:
                    assistant_msg["reasoning_content"] = reasoning_content
                self.messages.append(assistant_msg)
                self._collect_assistant_text_round(content, reasoning_content)
                break
            else:
                break

        return {
            "full_reply": full_reply,
            "used_tools": used_tools,
            "iterations": iterations,
        }

# NOTE: 2026-05-15 14:27:49, self-evolved by tea_agent --- 修改 _build_tools 支持 tool_filter 参数
    def _build_tools(self, tool_filter: list = None):
        """构建工具定义列表（通过 SkillManager 过滤，按需加载）"""
        all_tools = super()._build_tools()
        # 通过 SkillManager 过滤：仅返回激活 Skill 包含的工具
        active_meta_map = self.skill_manager.get_active_tools_meta(self.toolkit.meta_map)
        if active_meta_map:
            tools = active_meta_map
        else:
            # 回退：如果没有任何工具被激活，使用全部
            tools = all_tools
            
        # Level 2: 动态工具注入
        if tool_filter:
            # 强制保留基础 introspection 工具
            essential = {'toolkit_memory', 'toolkit_kb'} 
            allowed = set(tool_filter) | essential
            self.tools = [t for t in tools if t['function']['name'] in allowed]
            logger.info(f"[Pipe Dynamic] Tool Injection: enabled {len(self.tools)} tools based on intent")
        else:
            self.tools = tools

    def update_tools(self):
        """重新加载并刷新工具定义"""
        self.toolkit.reload()
        self._build_tools()

# NOTE: 2026-05-09 20:07:40, self-evolved by tea_agent --- 添加 _auto_detect_mode 方法：每次对话前根据用户输入自动切换 Agent 模式
    def _auto_detect_mode(self, user_text: str):
        """根据用户输入自动检测并切换 Agent 模式。
        
        在每次 chat_stream 入口调用，无感切换。
        模式切换以 CRITICAL 记忆注入，影响后续所有回复风格。
        检测失败不阻塞对话。
        """
        try:
            result = self.toolkit.call_tool('toolkit_mode', action='auto', text=user_text)
            if isinstance(result, dict) and result.get('switched'):
                logger.info(
                    f"🤖 自动切换模式: {result.get('from_mode')} → {result.get('to_mode')} "
                    f"(原因: {result.get('reason', 'N/A')})"
                )
        except Exception:
            pass  # 模式检测失败不影响对话

    def _get_summarize_client(self) -> Tuple[Any, str]:
        """获取用于摘要/提取任务的客户端和模型名。"""
        if self._cheap_client and self._cheap_model_name:
            return self._cheap_client, self._cheap_model_name
        return self.client, self.model

    def reset_session_state(self):
        """
        重置会话状态。
        """
        self.reset_usage()
        self.reset_cheap_usage()
        self._rounds_collector = []
        self._extra_iterations = 0
        self._max_iter_wait.clear()
        
        # NOTE: 2026-04-28, self-evolved by claude-agent ---
        # 清除上一轮 API 会话遗留的 reasoning_content，
        # 避免跨 chat_stream 传递失效的 reasoning_content。
# NOTE: 2026-05-02 10:59:41, self-evolved by tea_agent --- 添加 _notify_reflection_done 和 _notify_prompt_evolved 通知方法
        self._strip_reasoning_content(self.messages)

    # NOTE: 2026-05-02, self-evolved by tea_agent --- 反思/提示词进化的桌面通知方法
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

# NOTE: 2026-04-30 16:21:40, self-evolved by tea_agent --- chat_stream添加反思追踪：start_trace/finish_trace + 异步触发反思
    def chat_stream(self, msg: str, callback: Callable[[str], None], topic_id: int = -1, on_status: Optional[Callable[[str], None]] = None) -> Tuple[str, bool]:
        """
        流式对话，支持工具调用。
        
        使用 Pipeline 执行可配置的步骤。

        Args:
            msg: 用户消息
            callback: 流式输出回调函数
            topic_id: 当前会话的主题 ID

        Returns:
            Tuple[str, bool]: (助手完整回复, 是否使用了工具调用)
        """

        # NOTE: 2026-06-18 gen by tea_agent, UUID migration: topic_id 已是 str，无需 int 转换

# NOTE: 2026-05-15 gen by tea_agent, 支持图片输入：msg 可以是 str 或 {"text": str, "images": [str]}
# NOTE: 2026-05-15 15:46:09, self-evolved by tea_agent --- 在 chat_stream 入口添加视觉支持检查，不支持时提前提示用户
        _msg_text = msg if isinstance(msg, str) else msg.get("text", "")
        _msg_images = None if isinstance(msg, str) else msg.get("images", [])

        # NOTE: 2026-05-18 gen by tea_agent, 视觉支持检查：不支持时提前提示用户，避免发送到 API 后报错
        if _msg_images and not getattr(self, '_supports_vision', False):
            error_msg = f"⚠️ 当前模型 {self.model} 不支持图片输入，请更换支持视觉的模型或移除图片后重试。"
            logger.warning(error_msg)
            callback(error_msg)
            return error_msg, False

# NOTE: 2026-05-07 11:27:48, self-evolved by tea_agent --- chat_stream 入口添加 DEBUG 日志
        logger.debug(f"chat_stream start: msg_len={len(str(msg))}, topic_id={topic_id}, model={self.model}, enable_thinking={self.enable_thinking}")
        logger.debug(f"chat_stream user message: {_msg_text[:200]}..." if len(_msg_text) > 200 else f"chat_stream user message: {_msg_text}")

        self.current_topic_id = topic_id
        self.reset_interrupt()
        self.reset_session_state()
        
# NOTE: 2026-05-09 20:07:25, self-evolved by tea_agent --- chat_stream 在 skill auto_activate 后自动检测并切换模式（基于用户输入）
        # 自动激活匹配的 Skill（基于用户输入触发词）
# NOTE: 2026-05-15 14:28:07, self-evolved by tea_agent --- 修改 chat_stream 集成意图分析与动态工具注入
        self.skill_manager.auto_activate(_msg_text)
        # 自动检测并切换 Agent 模式（基于用户输入）
        self._auto_detect_mode(_msg_text)
        
        # Level 1 & 2: 动态意图分析与流水线调整
        intent = self._analyze_intent(_msg_text)
        
        # Level 2: 按需注入工具
        if intent.get('required_tools'):
            self._build_tools(tool_filter=intent['required_tools'])
        else:
            self._build_tools() # 重置为默认

        # Level 1: 动态跳过控制
        if intent.get('skip_tool_loop'):
            context['skip_tool_loop'] = True

        # 刷新工具列表（反映最新的激活状态） - 已在上面由 intent 控制
        # self._build_tools() 

# NOTE: 2026-04-30 16:23:12, self-evolved by tea_agent --- chat_stream中reflection_manager为None时安全跳过追踪和反思
        # 2026-04-30 gen by deepseek-v4-pro, 开始反思追踪
        if self.reflection_manager is not None:
            trace = self.reflection_manager.start_trace(topic_id, _msg_text)
            self._current_trace = trace
        else:
            self._current_trace = None

        # 构建执行上下文
        # NOTE: 2026-05-15 gen by tea_agent, user_msg 传递原始 msg（可能是包含 images 的 dict）
        context = {
            "user_msg": msg,
            "msg": _msg_text,
            "callback": callback,
            "on_status": on_status,
        }

        # 执行 Pipeline
        result = self.pipeline.execute(context)
        
        # 提取结果
        full_reply = result.get("full_reply", "")
        used_tools = result.get("used_tools", False)
        iterations = result.get("iterations", 0)
        
# NOTE: 2026-04-30 16:23:23, self-evolved by tea_agent --- finish_trace和反思触发处增加None保护
        # 2026-04-30 gen by deepseek-v4-pro, 完成追踪
        if self.reflection_manager is not None and self._current_trace is not None:
            self.reflection_manager.finish_trace(
                self._current_trace,
                total_iterations=iterations,
                used_tools=used_tools,
                interrupted=result.get("interrupted", False),
                error=str(result.get("error", "")) if result.get("error") else None,
            )

        # 自动提取记忆（真正异步，不阻塞）
        # 仅在有效 topic_id 且非打断时触发
        import threading

        if isinstance(topic_id, str) and topic_id and not result.get("interrupted", False):
            def _auto_extract():
                try:
                    count = self.trigger_memory_extraction(topic_id)
                    if count > 0 and on_status:
                        on_status(f"🧠 自动提取了 {count} 条新记忆")
                except Exception:
                    pass
            threading.Thread(target=_auto_extract, daemon=True).start()

# NOTE: 2026-04-30 16:23:38, self-evolved by tea_agent --- 异步反思触发增加reflection_manager/prompt_manager为None的保护
        # 2026-04-30 gen by deepseek-v4-pro, 异步触发反思（不阻塞主流程）
        if not result.get("interrupted", False) and self.reflection_manager is not None:
# NOTE: 2026-05-02 10:59:14, self-evolved by tea_agent --- 反思完成后发送桌面通知，含建议数量和提示词进化信息
            def _auto_reflect():
                try:
                    if self.reflection_manager.should_reflect():
                        rid = self.reflection_manager.generate_reflection()
                        if rid:
                            if on_status:
                                on_status(f"🔍 元认知反思完成 (id={rid})")
                            # NOTE: 2026-05-02, self-evolved by tea_agent --- 反思完成后始终发送桌面通知
                            self._notify_reflection_done(rid)
                        # 如果反思产生了提示词建议，触发提示词进化
                        if self.reflection_manager.last_prompt_suggestion and self.prompt_manager is not None:
                            new_pid = self.prompt_manager.evolve(
                                reflection_suggestion=self.reflection_manager.last_prompt_suggestion
                            )
                            if new_pid:
                                if on_status:
                                    on_status(f"📝 系统提示词进化到 v{self.prompt_manager.current_version}")
                                # NOTE: 2026-05-02, self-evolved by tea_agent --- 提示词进化后发送桌面通知
                                self._notify_prompt_evolved(self.prompt_manager.current_version)
                except Exception:
                    pass
            threading.Thread(target=_auto_reflect, daemon=True).start()
        
        return full_reply, used_tools
