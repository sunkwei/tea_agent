"""
会话记忆管理模块
负责记忆注入、提取、保存等功能

记忆生命周期:
1. 注入 (Inject)   - 会话开始时，将重要记忆加载到上下文
2. 提取 (Extract)  - 会话结束时，使用 LLM 从对话中提取新记忆
3. 保存 (Save)     - 将提取的记忆条目持久化到存储
"""

import json
import re
from typing import List, Dict, Any, Optional, Callable
import logging

logger = logging.getLogger("session_memory")

from tea_agent.session_prompts import (
    MEMORY_EXTRACT_SYSTEM,
    MEMORY_EXTRACT_USER_TEMPLATE,
    VALID_MEMORY_CATEGORIES,
)

class SessionMemoryMixin:
    """
    记忆管理 Mixin 类，提供记忆注入、提取、保存功能。

    依赖属性 (由使用者提供):
        memory: Memory 实例，用于记忆的存储和检索
        tool_log: 可选的日志回调函数
        messages: 消息列表，当前会话的完整对话历史
        memory_inject_limit: 记忆注入条数上限 (默认 8)
        memory_extract_rounds: 记忆提取窗口轮数 (默认 6)
        memory_extract_threshold: 记忆提取触发阈值 (默认 4)
        _get_summarize_client(): 获取摘要客户端的方法

    内部状态:
        _memory_text: 注入的记忆文本，用于构建 API 消息
        _memory_injected: 记忆注入标志，防止重复注入
    """

    def __init__(self):
        self.memory: Any = None
        self.tool_log: Optional[Callable[[str], None]] = None
        self.messages: List[Dict] = []

        # 记忆注入状态
        self._memory_text: str = ""
        self._memory_injected: bool = False

        # 记忆配置
        self.memory_inject_limit: int = 8
        self.memory_extract_rounds: int = 6
        self.memory_extract_threshold: int = 4

    # ──────────────────────────────────────────────
    # 记忆注入 (Inject)
    # ──────────────────────────────────────────────

    def _inject_memories(self) -> None:
        """
        将重要记忆注入到上下文中。

        从 Memory 中获取重要记忆和最近记忆，合并去重后限制条数，
        存储到 _memory_text 中，由 _build_api_messages 使用。

        注意:
            - 不修改 self.messages，记忆文本独立于消息列表
            - 使用 _memory_injected 标志防止重复注入
        """
        if not self.memory or self._memory_injected:
            return

        try:
            # 获取重要记忆和最近记忆
            important = self.memory.get_important_memories(limit=5)
            recent = self.memory.get_recent_memories(limit=3)

            # 合并去重
            combined = self._merge_and_deduplicate_memories(important + recent)

            # 限制条数
            combined = combined[: self.memory_inject_limit]

            if not combined:
                self._memory_injected = True
                return

            # 构建记忆文本
            self._memory_text = "\n".join(
                f"- [{m['category']}] {m['summary']}" for m in combined
            )
            self._memory_injected = True

            if self.tool_log:
                self.tool_log(f"🧠 已准备 {len(combined)} 条记忆注入")

            logger.debug(f"注入了 {len(combined)} 条记忆, ==> memory text\n{self._memory_text}\n")

        except Exception as e:
            self._log_memory_error("记忆注入", e)

    def _merge_and_deduplicate_memories(self, memories: List[Dict]) -> List[Dict]:
        """
        合并并去重记忆列表。

        Args:
            memories: 记忆条目列表

        Returns:
            去重后的记忆列表，保持原始顺序
        """
        seen_ids: set = set()
        combined: List[Dict] = []

        for m in memories:
            mem_id = m.get("id")
            if mem_id and mem_id not in seen_ids:
                seen_ids.add(mem_id)
                combined.append(m)

        return combined

    # ──────────────────────────────────────────────
    # 记忆提取 (Extract)
    # ──────────────────────────────────────────────

    def _extract_memories_from_conversation(self) -> List[Dict]:
        """
        使用 LLM 从最近 N 轮对话中提取记忆条目。

        提取流程:
            1. 从 self.messages 中提取最近 memory_extract_rounds 轮对话
            2. 构建 Prompt，调用 LLM 进行提取
            3. 解析 LLM 返回的 JSON，校验并规范化记忆条目

        Returns:
            规范化的记忆条目列表，每项包含:
                - category: 记忆类别 (必须在 VALID_MEMORY_CATEGORIES 中)
                - summary: 记忆摘要 (不超过 150 字)
                - importance: 重要度 (1-5)
                - tags: 标签列表 (最多 5 个)
        """
        if not self.memory:
            return []

        # 提取最近 N 轮对话
        chat_text = self._extract_conversation_window()

        if not chat_text.strip():
            return []

        try:
            # 调用 LLM 提取记忆
            raw_response = self._call_llm_for_memory_extraction(chat_text)

            if not raw_response:
                return []

            # 解析并规范化
            memories = self._parse_and_normalize_memories(raw_response)

            logger.debug(f"提取到了 {len(memories)} 条记忆, ==> raw response:\n{json.dumps(raw_response, ensure_ascii=False, indent=4)}\n")

            return memories

        except Exception as e:
            self._log_memory_error("记忆提取", e)
            return []

    def _extract_conversation_window(self) -> str:
        """
        从消息列表中提取最近 N 轮对话文本。

        Returns:
            格式化的对话文本，每行格式: [ROLE]: content
        """
        chat_lines: List[str] = []
        user_count = 0

        # 倒序遍历，提取最近 memory_extract_rounds 轮用户对话
        for msg in reversed(self.messages):
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
                user_count += 1
                if user_count > self.memory_extract_rounds:
                    break

            if role in ("user", "assistant") and content:
                # 截断超长内容
                truncated = (
                    content[:800] + "..." if len(content) > 800 else content
                )
                chat_lines.append(f"[{role.upper()}]: {truncated}")

        # 恢复正序
        chat_lines.reverse()

        return "\n".join(chat_lines)

    def _call_llm_for_memory_extraction(self, chat_text: str) -> Optional[str]:
        """
        调用 LLM 进行记忆提取。

        Args:
            chat_text: 格式化的对话文本

        Returns:
            LLM 返回的原始响应文本，失败时返回 None
        """
        cli, mdl = self._get_summarize_client()

        logger.debug(f"使用模型 {mdl} 进行记忆提取, ==> chat_text:\n{chat_text}")
        response = cli.chat.completions.create(
            model=mdl,
            messages=[
                {"role": "system", "content": MEMORY_EXTRACT_SYSTEM},
                {
                    "role": "user",
                    "content": MEMORY_EXTRACT_USER_TEMPLATE.format(
                        chat_text=chat_text
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        logger.debug(f"<== 记忆提取完成:\n{response.choices[0].message.content.strip()}")

        return response.choices[0].message.content.strip()

    def _parse_and_normalize_memories(self, raw_response: str) -> List[Dict]:
        """
        解析并规范化 LLM 返回的记忆条目。

        Args:
            raw_response: LLM 返回的原始文本

        Returns:
            规范化的记忆条目列表
        """
        # 清洗：去掉可能的 markdown 代码块包裹
        cleaned = self._clean_json_response(raw_response)

        # 提取 JSON 数组
        json_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not json_match:
            if self.tool_log:
                self.tool_log(
                    f"⚠️ 记忆提取：未找到 JSON 数组，原始输出: {raw_response[:200]}"
                )
            return []

        try:
            memories = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            if self.tool_log:
                self.tool_log(f"⚠️ 记忆提取：JSON 解析失败: {e}")
            return []

        if not isinstance(memories, list):
            return []

        # 校验并规范化
        result: List[Dict] = []
        for m in memories:
            normalized = self._normalize_single_memory(m)
            if normalized:
                result.append(normalized)

        return result

    def _clean_json_response(self, raw: str) -> str:
        """
        清洗 LLM 返回的 JSON 文本。

        去除 markdown 代码块标记、首尾空白等。

        Args:
            raw: 原始响应文本

        Returns:
            清洗后的文本
        """
        # 去除 markdown 代码块
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        return cleaned.strip()

    def _normalize_single_memory(self, m: Dict) -> Optional[Dict]:
        """
        校验并规范化单个记忆条目。

        Args:
            m: 原始记忆字典

        Returns:
            规范化后的记忆字典，无效时返回 None
        """
        if not isinstance(m, dict):
            return None

        # 校验 category
        cat = m.get("category", "general")
        if cat not in VALID_MEMORY_CATEGORIES:
            cat = "general"

        # 校验 summary (必须非空)
        summary = m.get("summary", "").strip()
        if not summary:
            return None

        # 校验 importance (1-5)
        try:
            importance = min(5, max(1, int(m.get("importance", 3))))
        except (ValueError, TypeError):
            importance = 3

        # 校验 tags (最多 5 个)
        tags = m.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t).strip() for t in tags if str(t).strip()][:5]

        return {
            "category": cat,
            "summary": summary,
            "importance": importance,
            "tags": tags,
        }

    # ──────────────────────────────────────────────
    # 记忆保存 (Save)
    # ──────────────────────────────────────────────

    def _save_conversation_memory(self) -> None:
        """
        在会话结束后，通过 LLM 提取并保存记忆。

        保存流程:
            1. 检查消息数量是否达到提取阈值
            2. 调用 LLM 从对话中提取记忆
            3. 将提取的记忆条目保存到 Memory 存储
        """
        if not self.memory:
            return

        # 检查是否达到提取阈值
        msg_count = sum(
            1 for m in self.messages if m["role"] in ("user", "assistant")
        )
        if msg_count < self.memory_extract_threshold:
            return

        if self.tool_log:
            self.tool_log("🧠 开始 LLM 记忆提取...")

        # 提取记忆
        memories = self._extract_memories_from_conversation()

        if not memories:
            if self.tool_log:
                self.tool_log("🧠 本次对话无值得记忆的内容")
            return

        # 保存记忆
        saved_count = 0
        for m in memories:
            if self._save_single_memory(m):
                saved_count += 1

        if self.tool_log:
            self.tool_log(f"🧠 记忆提取完成，共保存 {saved_count} 条")

    def _save_single_memory(self, m: Dict) -> bool:
        """
        保存单个记忆条目到 Memory 存储。

        Args:
            m: 规范化的记忆条目

        Returns:
            保存成功返回 True，失败返回 False
        """
        try:
            self.memory.add_memory(
                summary=m["summary"],
                category=m["category"],
                importance=m["importance"],
                tags=m["tags"],
            )

            if self.tool_log:
                self.tool_log(
                    f"💾 [{m['category']}] (重要度:{m['importance']}) "
                    f"{m['summary'][:100]}"
                )

            return True

        except Exception as e:
            self._log_memory_error("保存记忆", e)
            return False

    # ──────────────────────────────────────────────
    # 状态重置
    # ──────────────────────────────────────────────

    def reset_memory_state(self) -> None:
        """
        重置记忆状态（用于新会话开始前）。

        清空注入的记忆文本和标志，但不影响 Memory 存储中的持久化数据。
        """
        self._memory_text = ""
        self._memory_injected = False

    # ──────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────

    def _log_memory_error(self, operation: str, error: Exception) -> None:
        """
        统一的记忆错误日志记录。

        Args:
            operation: 操作名称 (如 "记忆注入", "记忆提取")
            error: 异常对象
        """
        if self.tool_log:
            self.tool_log(f"⚠️ {operation}失败: {error}")
