"""
会话记忆管理模块
负责记忆注入、提取、保存等功能
"""

import json
import re
from typing import List, Dict, Any, Optional, Callable


class SessionMemoryMixin:
    """
    记忆管理 mixin 类，提供记忆注入、提取、保存功能。
    期望使用者提供以下属性：
    - memory: Memory 实例
    - tool_log: 可选日志回调
    - messages: 消息列表
    - memory_inject_limit: 记忆注入条数上限
    - memory_extract_rounds: 记忆提取窗口轮数
    - memory_extract_threshold: 记忆提取触发阈值
    - _get_summarize_client(): 获取摘要客户端的方法
    """

    def __init__(self):
        self.memory = None
        self.tool_log: Optional[Callable[[str], None]] = None
        self._memory_text: str = ""
        self._memory_injected: bool = False
        self.memory_inject_limit: int = 8
        self.memory_extract_rounds: int = 6
        self.memory_extract_threshold: int = 4

    def _inject_memories(self):
        """
        将重要记忆注入到上下文中。
        记忆文本存储在 _memory_text，不修改 self.messages。
        """
        if not self.memory or self._memory_injected:
            return

        try:
            important = self.memory.get_important_memories(limit=5)
            recent = self.memory.get_recent_memories(limit=3)

            # 合并去重
            seen_ids = set()
            combined = []
            for m in important + recent:
                if m["id"] not in seen_ids:
                    seen_ids.add(m["id"])
                    combined.append(m)

            # 限制条数
            combined = combined[:self.memory_inject_limit]

            if not combined:
                self._memory_injected = True
                return

            self._memory_text = "\n".join(
                f"- [{m['category']}] {m['summary']}" for m in combined
            )

            self._memory_injected = True

            if self.tool_log:
                self.tool_log(f"🧠 已准备 {len(combined)} 条记忆注入")
        except Exception as e:
            if self.tool_log:
                self.tool_log(f"⚠️ 记忆注入失败: {e}")

    def _extract_memories_from_conversation(self) -> List[Dict]:
        """
        使用 LLM 从最近 N 轮对话中提取记忆条目。
        """
        if not self.memory:
            return []

        from tea_agent.session_prompts import (
            MEMORY_EXTRACT_SYSTEM,
            MEMORY_EXTRACT_USER_TEMPLATE,
            VALID_MEMORY_CATEGORIES,
        )

        # 只取最近 memory_extract_rounds 轮对话
        chat_lines = []
        user_count = 0
        for msg in reversed(self.messages):
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                user_count += 1
                if user_count > self.memory_extract_rounds:
                    break
            if role in ("user", "assistant") and content:
                truncated = (
                    content[:800] + "..." if len(content) > 800 else content
                )
                chat_lines.append(f"[{role.upper()}]: {truncated}")

        chat_lines.reverse()
        chat_text = "\n".join(chat_lines)

        if not chat_text.strip():
            return []

        try:
            cli, mdl = self._get_summarize_client()
            response = cli.chat.completions.create(
                model=mdl,
                messages=[
                    {"role": "system", "content": MEMORY_EXTRACT_SYSTEM},
                    {"role": "user", "content": MEMORY_EXTRACT_USER_TEMPLATE.format(
                        chat_text=chat_text)},
                ],
                temperature=0.1,
                max_tokens=1024,
            )

            raw = response.choices[0].message.content.strip()

            # 清洗：去掉可能的 markdown 代码块包裹
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            raw = raw.strip()

            # 尝试提取 JSON 数组
            json_match = re.search(r"\[.*\]", raw, re.DOTALL)
            if not json_match:
                if self.tool_log:
                    self.tool_log(f"⚠️ 记忆提取：未找到 JSON 数组，原始输出: {raw[:200]}")
                return []

            memories = json.loads(json_match.group())

            if not isinstance(memories, list):
                return []

            # 校验并规范化
            result = []
            for m in memories:
                if not isinstance(m, dict):
                    continue
                cat = m.get("category", "general")
                if cat not in VALID_MEMORY_CATEGORIES:
                    cat = "general"
                summary = m.get("summary", "").strip()
                if not summary:
                    continue
                importance = min(5, max(1, int(m.get("importance", 3))))
                tags = m.get("tags", [])
                if not isinstance(tags, list):
                    tags = []
                tags = [str(t).strip() for t in tags if str(t).strip()][:5]

                result.append({
                    "category": cat,
                    "summary": summary,
                    "importance": importance,
                    "tags": tags,
                })

            return result

        except json.JSONDecodeError as e:
            if self.tool_log:
                self.tool_log(f"⚠️ 记忆提取：JSON 解析失败: {e}")
            return []
        except Exception as e:
            if self.tool_log:
                self.tool_log(f"⚠️ 记忆提取失败: {e}")
            return []

    def _save_conversation_memory(self):
        """
        在会话结束后，通过 LLM 提取并保存记忆。
        """
        if not self.memory:
            return

        msg_count = sum(
            1 for m in self.messages if m["role"] in ("user", "assistant"))
        if msg_count < self.memory_extract_threshold:
            return

        if self.tool_log:
            self.tool_log("🧠 开始 LLM 记忆提取...")

        memories = self._extract_memories_from_conversation()

        if not memories:
            if self.tool_log:
                self.tool_log("🧠 本次对话无值得记忆的内容")
            return

        saved_count = 0
        for m in memories:
            try:
                self.memory.add_memory(
                    summary=m["summary"],
                    category=m["category"],
                    importance=m["importance"],
                    tags=m["tags"],
                )
                saved_count += 1
                if self.tool_log:
                    self.tool_log(
                        f"💾 [{m['category']}] (重要度:{m['importance']}) {m['summary'][:100]}"
                    )
            except Exception as e:
                if self.tool_log:
                    self.tool_log(f"⚠️ 保存记忆失败: {e}")

        if self.tool_log:
            self.tool_log(f"🧠 记忆提取完成，共保存 {saved_count} 条")

    def reset_memory_state(self):
        """重置记忆状态（用于新会话开始前）"""
        self._memory_text = ""
        self._memory_injected = False
