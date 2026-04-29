# @2026-04-29 gen by deepseek-v4-pro, MemoryManager: 记忆选择/格式化/提取策略
"""
Memory 管理器
负责记忆的选择、格式化注入和从对话中提取新记忆。
"""

import logging
import re
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger("MemoryManager")

# 优先级常量
PRIORITY_CRITICAL = 0   # 有效指令，必须遵循
PRIORITY_HIGH = 1       # 用户偏好、项目关键决策
PRIORITY_MEDIUM = 2     # 经验教训、工具使用技巧
PRIORITY_LOW = 3        # 一般参考信息

PRIORITY_LABELS = {
    0: "CRITICAL",
    1: "HIGH",
    2: "MEDIUM",
    3: "LOW",
}

MAX_INJECT = 5  # 每次会话注入上限


class MemoryManager:
    """记忆管理器：选择、格式化、提取"""

    def __init__(self, storage, extraction_threshold: int = 2):
        """
        Args:
            storage: Storage 实例，提供记忆 CRUD
            extraction_threshold: 触发记忆提取的最低未摘要消息数
        """
        self.storage = storage
        self._extraction_threshold = extraction_threshold

    # ------------------------------------------------------------------
    # 记忆选择
    # ------------------------------------------------------------------

    def select_memories(
        self,
        topic_text: str = "",
        limit: int = MAX_INJECT,
    ) -> List[Dict]:
        """
        从活跃记忆中选出最相关的若干条（上限 limit）。

        选择逻辑：
          1. CRITICAL 指令优先入选（不受 limit 限制，但通常不超过 limit）
          2. 剩余名额按 相关性 × 重要度 × 最近访问 排序填充
          3. 更新入选记忆的 last_accessed_at

        Args:
            topic_text: 当前对话上下文（用于相关性打分）
            limit: 注入上限

        Returns:
            入选的记忆列表，优先级高的排在前面
        """
        all_memories = self.storage.get_active_memories(limit=100)

        if not all_memories:
            return []

        # 分离 CRITICAL 和非 CRITICAL
        critical = [m for m in all_memories if m["priority"] == PRIORITY_CRITICAL]
        others = [m for m in all_memories if m["priority"] != PRIORITY_CRITICAL]

        # CRITICAL 全部入选（但不超过 limit）
        selected = critical[:limit]
        remaining_slots = limit - len(selected)

        if remaining_slots <= 0:
            self._touch_selected(selected)
            return selected

        # 对非 CRITICAL 打分排序
        scored = []
        for m in others:
            score = self._score_memory(m, topic_text)
            scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)

        # 取 top N 填充剩余名额
        for _, m in scored[:remaining_slots]:
            selected.append(m)

        self._touch_selected(selected)
        return selected

    def _score_memory(self, memory: Dict, topic_text: str) -> float:
        """
        计算记忆与当前对话的相关性分数。

        分数 = 相关性 × 重要度 × 最近访问因子 × 优先级因子

        - 相关性: 关键词匹配率 (0.1~1.0)
        - 重要度: importance / 5
        - 最近访问因子: 越近越高 (0.5~1.0)
        - 优先级因子: (4 - priority) / 4
        """
        relevance = self._compute_relevance(memory, topic_text)
        importance = max(memory.get("importance", 3), 1) / 5.0
        recency = self._compute_recency(memory)
        priority_factor = (4 - memory.get("priority", 2)) / 4.0

        return relevance * importance * recency * priority_factor

    def _compute_relevance(self, memory: Dict, topic_text: str) -> float:
        """简单关键词匹配计算相关性"""
        if not topic_text:
            return 0.5  # 无上下文时给中等分

        text_lower = topic_text.lower()

        # 从记忆 content 和 tags 中提取关键词
        keywords = set()
        content = memory.get("content", "").lower()
        tags = (memory.get("tags") or "").lower()

        # 提取 content 中的中文词组和英文单词
        keywords.update(self._extract_keywords(content))
        keywords.update(t.strip() for t in tags.split(",") if t.strip())

        if not keywords:
            return 0.3

        # 计算匹配率
        matched = sum(1 for kw in keywords if kw in text_lower)
        rate = matched / len(keywords)

        # 映射到 0.1 ~ 1.0 范围
        return max(0.1, min(1.0, rate * 2.0))

    @staticmethod
    def _extract_keywords(text: str) -> set:
        """从文本中提取关键词"""
        keywords = set()
        # 中文字符序列
        chinese = re.findall(r'[\u4e00-\u9fff]{2,}', text)
        keywords.update(chinese)
        # 英文单词
        english = re.findall(r'[a-zA-Z]{3,}', text)
        keywords.update(w.lower() for w in english)
        return keywords

    @staticmethod
    def _compute_recency(memory: Dict) -> float:
        """计算最近访问因子。越近越高，从未访问过给中值。"""
        last = memory.get("last_accessed_at")
        if not last:
            return 0.7  # 从未访问，给略高分数鼓励使用
        # SQLite timestamp 格式可直接字符串比较
        # 简化：有访问记录就给 0.85（实际应解析时间差）
        # 精确实现留给后续优化
        return 0.85

    def _touch_selected(self, memories: List[Dict]):
        """更新入选记忆的最后访问时间"""
        for m in memories:
            try:
                self.storage.touch_memory(m["id"])
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 格式化注入
    # ------------------------------------------------------------------

    @staticmethod
    def format_memories(memories: List[Dict]) -> str:
        """
        将记忆列表格式化为可注入消息的文本。

        格式示例:
            [系统记忆]
            !!! 必须遵循: 修改代码时标注前缀 ...
            ⏰ 提醒 (有效期至 2026-04-30T08:00): 明天检查服务器
            📌 本项目使用 SQLite 存储
        """
        if not memories:
            return ""

        lines = [
            "[系统记忆 — 以下为需要遵循的有效信息和规则，共 {n} 条]".format(
                n=len(memories)
            ),
            ""
        ]

        for m in memories:
            prefix = MemoryManager._prefix_for(m)
            lines.append("{prefix} {content}".format(
                prefix=prefix,
                content=m["content"]
            ))

        return "\n".join(lines)

    @staticmethod
    def _prefix_for(memory: Dict) -> str:
        """根据优先级和分类返回行前缀"""
        priority = memory.get("priority", 2)
        category = memory.get("category", "general")
        expires = memory.get("expires_at")

        if priority == PRIORITY_CRITICAL:
            return "!!! 必须遵循:"

        if category == "reminder":
            exp = f" (有效期至 {expires})" if expires else ""
            return f"⏰ 提醒{exp}:"

        if category == "preference":
            return "💡 偏好:"

        if category == "fact":
            return "📌 事实:"

        return "📎"

    # ------------------------------------------------------------------
    # 记忆提取
    # ------------------------------------------------------------------

    EXTRACTION_SYSTEM_PROMPT = """你是一个记忆提取器。从对话中识别值得长期保存的信息，输出 JSON 数组。

提取规则：
1. instruction: 用户明确要求"记住"的规则/指令，priority=0 (CRITICAL)
2. preference: 用户表达的习惯、偏好、风格选择，priority=1 (HIGH)
3. reminder: 有时效性的提醒事项，必须包含 expires_at 字段
4. fact: 项目中确认的技术事实、架构决策，priority=2 (MEDIUM)
5. general: 其他可能有用的参考信息，priority=3 (LOW)

importance 评分：
- 5: 关键信息，忽略会导致严重问题
- 4: 重要，影响后续决策
- 3: 有用参考
- 2: 一般备忘
- 1: 琐碎信息

格式：
[{"content": "简洁的记忆内容", "category": "...", "priority": N, "importance": N, "tags": "tag1,tag2", "expires_at": null}]

只输出对后续对话有价值的记忆。如果对话中无明显值得记忆的内容，输出空数组 []。"""

    def build_extraction_prompt(self, conversations_text: str) -> List[Dict[str, str]]:
        """构建记忆提取的 API 消息列表"""
        return [
            {"role": "system", "content": self.EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"请从以下对话中提取值得保留的记忆：\n\n{conversations_text}"}
        ]

    @staticmethod
    def parse_extraction_result(result_text: str) -> List[Dict]:
        """解析 LLM 提取结果"""
        import json
        try:
            # 尝试提取 JSON 数组
            text = result_text.strip()
            # 处理可能的 markdown 代码块包裹
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        return []

    def ingest_extracted(self, results: List[Dict], topic_id: Optional[int] = None) -> int:
        """
        将提取结果写入存储。

        Args:
            results: parse_extraction_result 的输出
            topic_id: 来源会话 ID

        Returns:
            新增记忆数量
        """
        count = 0
        for item in results:
            try:
# NOTE: 2026-04-29 11:29:55, self-evolved by tea_agent --- 修复 ingest_extracted: tags 为 list 时转为逗号分隔字符串
                tags = item.get("tags", "")
                if isinstance(tags, list):
                    tags = ", ".join(tags)
                self.storage.add_memory(
                    content=item.get("content", "").strip(),
                    category=item.get("category", "general"),
                    priority=item.get("priority", 2),
                    importance=item.get("importance", 3),
                    expires_at=item.get("expires_at"),
                    tags=tags,
                    source_topic_id=topic_id,
                )
                count += 1
            except Exception as e:
                logger.warning(f"Failed to ingest memory '{item.get('content', '')}': {e}")
        return count

    def is_extraction_needed(self, unsummarized_count: int) -> bool:
        """判断是否需要触发记忆提取"""
        return unsummarized_count >= self._extraction_threshold
