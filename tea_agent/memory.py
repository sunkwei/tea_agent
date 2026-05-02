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

# NOTE: 2026-05-02 12:04:27, self-evolved by tea_agent --- MAX_INJECT 从5上调至30，CRITICAL 选拔上限15，确保各优先级记忆都有机会注入
MAX_INJECT = 30  # 每次会话注入上限
MAX_CRITICAL_INJECT = 15  # CRITICAL 注入上限，超出留给其他优先级


class MemoryManager:
    """记忆管理器：选择、格式化、提取"""

# NOTE: 2026-04-30 14:33:58, self-evolved by tea_agent --- MemoryManager增加dedup_threshold参数
# NOTE: 2026-04-30 14:39:00, self-evolved by tea_agent --- MemoryManager默认dedup_threshold改为0.3与config一致
    def __init__(self, storage, extraction_threshold: int = 2, dedup_threshold: float = 0.3):
        """
        Args:
            storage: Storage 实例，提供记忆 CRUD
            extraction_threshold: 触发记忆提取的最低未摘要消息数
            dedup_threshold: 记忆去重相似度阈值 (0~1)，超过此值视为重复
        """
        self.storage = storage
        self._extraction_threshold = extraction_threshold
        self._dedup_threshold = dedup_threshold

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

# NOTE: 2026-05-02 12:04:34, self-evolved by tea_agent --- CRITICAL 选拔上限 15 条 (max(CRITICAL, MAX_CRITICAL_INJECT))，防止挤占其他优先级
        # CRITICAL 入选不超过 MAX_CRITICAL_INJECT（新的优先，FIFO）
        critical_slots = min(limit, MAX_CRITICAL_INJECT)
        selected = critical[-critical_slots:] if len(critical) > critical_slots else critical
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

# NOTE: 2026-05-02 10:11:31, self-evolved by tea_agent --- _extract_keywords 升级为 jieba 分词，替换简陋的 bigram 滑动窗口
# NOTE: 2026-05-02 10:20:00, self-evolved by tea_agent --- _extract_keywords升级为jieba分词，替换简陋bigram滑动窗口
    @staticmethod
    def _extract_keywords(text: str) -> set:
        """从文本中提取关键词（jieba 中文分词 + 英文单词）"""
        keywords = set()
        try:
            import jieba
            # jieba 精确模式分词，过滤单字和纯空白
            words = jieba.lcut(text)
            for w in words:
                w = w.strip()
                if len(w) >= 2 and not w.isspace():
                    keywords.add(w)
        except ImportError:
            # 降级：bigram 滑动窗口
            chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
            for i in range(len(chinese_chars) - 1):
                keywords.add(chinese_chars[i] + chinese_chars[i+1])
        # 英文单词（3字母以上）
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

# NOTE: 2026-04-30 14:35:03, self-evolved by tea_agent --- 新增_compute_similarity/_find_duplicate/_merge_memory去重合并方法，改造ingest_extracted写入前查重
    # ------------------------------------------------------------------
    # 去重合并
    # ------------------------------------------------------------------

    def _compute_similarity(self, text_a: str, text_b: str) -> float:
        """
        计算两段文本的关键词 Jaccard 相似度。

        返回值 0~1，越高越相似。
        """
        if not text_a or not text_b:
            return 0.0
        kw_a = self._extract_keywords(text_a.lower())
        kw_b = self._extract_keywords(text_b.lower())
        if not kw_a or not kw_b:
            # 退化为字符级 Jaccard
            set_a = set(text_a)
            set_b = set(text_b)
            if not set_a or not set_b:
                return 0.0
            return len(set_a & set_b) / len(set_a | set_b)
        return len(kw_a & kw_b) / len(kw_a | kw_b)

    def _find_duplicate(self, content: str, category: str = "") -> Optional[Dict]:
        """
        在活跃记忆中查找与 content 相似度超过阈值的记忆。

        Args:
            content: 待查重的记忆内容
            category: 可选分类过滤（同分类优先匹配）

        Returns:
            找到的重复记忆 Dict；无重复返回 None
        """
        existing = self.storage.get_active_memories(limit=200)
        best = None
        best_score = 0.0

        for mem in existing:
            score = self._compute_similarity(content, mem.get("content", ""))
            # 同分类加权 10%
            if category and mem.get("category") == category:
                score *= 1.1
            if score > best_score:
                best_score = score
                best = mem

        if best and best_score >= self._dedup_threshold:
            logger.info(
                f"发现重复记忆 #{best['id']} (相似度={best_score:.2f}>={self._dedup_threshold}): "
                f"\"{content[:50]}...\""
            )
            return best
        return None

    def _merge_memory(self, existing: Dict, new_item: Dict) -> Dict:
        """
        合并新旧记忆，返回合并后的字段 dict。

        合并策略：
        - content: 保留更长的，或拼接（若两者都较长且不包含对方）
        - importance: 取较高值
        - priority: 取较小值（越关键）
        - tags: 并集（去重）
        - category: 保持不变（已有分类优先）
        - expires_at: 保留更早的过期时间
        """
        old_content = existing.get("content", "")
        new_content = new_item.get("content", "").strip()

        # 内容合并：若新内容更长且不包含在旧内容中，拼接
        if new_content and new_content not in old_content:
            if len(new_content) > len(old_content):
                merged_content = new_content
            elif len(old_content) < 200 and len(new_content) > 10:
                merged_content = f"{old_content}；{new_content}"
            else:
                merged_content = old_content
        else:
            merged_content = old_content

        # 标签合并
        old_tags = set(t.strip() for t in (existing.get("tags") or "").split(",") if t.strip())
        new_tags_raw = new_item.get("tags", "")
        if isinstance(new_tags_raw, list):
            new_tags = set(t.strip() for t in new_tags_raw if t.strip())
        else:
            new_tags = set(t.strip() for t in str(new_tags_raw).split(",") if t.strip())
        merged_tags = ", ".join(sorted(old_tags | new_tags))

        # 优先级取更关键（数字更小）
        old_priority = existing.get("priority", 2)
        new_priority = new_item.get("priority", 2)
        merged_priority = min(old_priority, new_priority)

        # 重要度取更高
        merged_importance = max(
            existing.get("importance", 3),
            new_item.get("importance", 3)
        )

        # 过期时间取更早
        old_expires = existing.get("expires_at")
        new_expires = new_item.get("expires_at")
        if old_expires and new_expires:
            merged_expires = min(str(old_expires), str(new_expires))
        else:
            merged_expires = old_expires or new_expires

        merged = {
            "content": merged_content,
            "category": existing.get("category", new_item.get("category", "general")),
            "priority": merged_priority,
            "importance": merged_importance,
            "tags": merged_tags,
            "expires_at": merged_expires,
        }

        logger.info(
            f"合并记忆 #{existing['id']}: "
            f"priority {old_priority}→{merged_priority}, "
            f"importance {existing.get('importance')}→{merged_importance}, "
            f"tags \"{existing.get('tags','')}\"→\"{merged_tags}\""
        )
        return merged

    def ingest_extracted(self, results: List[Dict], topic_id: Optional[int] = None) -> int:
        """
        将提取结果写入存储（带去重合并）。

        对每条提取结果：
        1. 查找是否已有相似记忆
        2. 有 → 合并更新
        3. 无 → 新增

        Args:
            results: parse_extraction_result 的输出
            topic_id: 来源会话 ID

        Returns:
            新增/更新的记忆数量
        """
        new_count = 0
        merged_count = 0

        for item in results:
            try:
                tags = item.get("tags", "")
                if isinstance(tags, list):
                    tags = ", ".join(tags)
                content = item.get("content", "").strip()
                category = item.get("category", "general")

                if not content:
                    continue

                # 查重
                duplicate = self._find_duplicate(content, category)

                if duplicate:
                    # 合并更新
                    merged = self._merge_memory(duplicate, item)
                    self.storage.update_memory(duplicate["id"], **merged)
                    self.storage.touch_memory(duplicate["id"])
                    merged_count += 1
                else:
                    # 新增
                    self.storage.add_memory(
                        content=content,
                        category=category,
                        priority=item.get("priority", 2),
                        importance=item.get("importance", 3),
                        expires_at=item.get("expires_at"),
                        tags=tags,
                        source_topic_id=topic_id,
                    )
                    new_count += 1

            except Exception as e:
                logger.warning(f"Failed to ingest memory '{item.get('content', '')}': {e}")

        if merged_count > 0:
            logger.info(f"记忆提取完成: 新增 {new_count} 条, 合并更新 {merged_count} 条")
        return new_count + merged_count

    def is_extraction_needed(self, unsummarized_count: int) -> bool:
        """判断是否需要触发记忆提取"""
        return unsummarized_count >= self._extraction_threshold
