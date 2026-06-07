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

MAX_INJECT = 30  # 每次会话注入上限
MAX_CRITICAL_INJECT = 10  # CRITICAL 注入上限，超出留给其他优先级
MIN_HIGH_INJECT = 3   # HIGH 保底
MIN_MEDIUM_INJECT = 2  # MEDIUM 保底
MIN_LOW_INJECT = 1    # LOW 保底（至少1条）

# 年龄衰减阈值（天）
CRITICAL_DEGRADE_DAYS = 30   # CRITICAL → HIGH
HIGH_DEGRADE_DAYS = 60       # HIGH → MEDIUM
MEDIUM_DEGRADE_DAYS = 90     # MEDIUM → LOW

# LLM 精调上限
MAX_LLM_ADJUSTMENTS = 3  # 每次最多调整条数

class MemoryManager:
    """记忆管理器：选择、格式化、提取"""

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
          1. 先执行年龄衰减（优先级降级）
          2. CRITICAL 指令优先入选（上限 MAX_CRITICAL_INJECT）
          3. 按优先级分层保底：HIGH ≥3, MEDIUM ≥2, LOW ≥1
          4. 剩余名额按 相关性×重要度×时效×优先级 排序填充
          5. 更新入选记忆的 last_accessed_at

        Args:
            topic_text: 当前对话上下文（用于相关性打分）
            limit: 注入上限

        Returns:
            入选的记忆列表，优先级高的排在前面
        """
        # 先执行年龄衰减
        self.degrade_by_age()

        all_memories = self.storage.get_active_memories(limit=100)

        if not all_memories:
            return []

        # 按优先级分组
        critical = [m for m in all_memories if m["priority"] == PRIORITY_CRITICAL]
        high = [m for m in all_memories if m["priority"] == PRIORITY_HIGH]
        medium = [m for m in all_memories if m["priority"] == PRIORITY_MEDIUM]
        low = [m for m in all_memories if m["priority"] == PRIORITY_LOW]

        # 1. CRITICAL 入选（上限 MAX_CRITICAL_INJECT, FIFO取最新）
        critical_slots = min(limit, MAX_CRITICAL_INJECT)
        selected = critical[-critical_slots:] if len(critical) > critical_slots else list(critical)
        used = len(selected)
        if used >= limit:
            self._touch_selected(selected)
            return selected

        # 2. 非 CRITICAL 打分排序
        others = high + medium + low
        scored = []
        for m in others:
            score = self._score_memory(m, topic_text)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)

        # 辅助函数：从已打分列表中按优先级取 top N
        def _pick_top_by_priority(scored_list, priority, count):
            """从 scored_list 中取出指定优先级的 top count 条，返回 (picked, remaining)"""
            candidates = [(s, m) for s, m in scored_list if m["priority"] == priority]
            picked = candidates[:count]
            picked_ids = {m["id"] for _, m in picked}
            remaining = [(s, m) for s, m in scored_list if m["id"] not in picked_ids]
            return [m for _, m in picked], remaining

        # 3. 分层保底
        remaining_slots = limit - used
        # 保底按优先级从高到低分配，但不超过剩余名额
        high_quota = min(MIN_HIGH_INJECT, remaining_slots)
        medium_quota = min(MIN_MEDIUM_INJECT, max(0, remaining_slots - high_quota))
        low_quota = min(MIN_LOW_INJECT, max(0, remaining_slots - high_quota - medium_quota))

        picked_high, scored = _pick_top_by_priority(scored, PRIORITY_HIGH, high_quota)
        picked_medium, scored = _pick_top_by_priority(scored, PRIORITY_MEDIUM, medium_quota)
        picked_low, scored = _pick_top_by_priority(scored, PRIORITY_LOW, low_quota)

        selected.extend(picked_high)
        selected.extend(picked_medium)
        selected.extend(picked_low)

        # 4. 剩余名额自由竞争（从还没选的里面取 top N）
        free_slots = limit - len(selected)
        if free_slots > 0:
            for _, m in scored[:free_slots]:
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
        """计算最近访问因子。越近越高，从未访问过给中值。

        基于 last_accessed_at 距当前时间的天数计算衰减：
        - 1天内访问: 1.0
        - 7天内访问: 0.9
        - 30天内访问: 0.7
        - 90天内访问: 0.5
        - 超过90天或从未访问: 0.3
        """
        from datetime import datetime, timezone
        last = memory.get("last_accessed_at")
        if not last:
            return 0.3  # 从未访问，给低分
        try:
            # 兼容 SQLite 格式 'YYYY-MM-DD HH:MM:SS' 和 ISO 格式
            if isinstance(last, str):
                if ' ' in last and 'T' not in last:
                    last_dt = datetime.strptime(last, '%Y-%m-%d %H:%M:%S')
                else:
                    last_dt = datetime.fromisoformat(last)
            else:
                return 0.3
            # 确保 naive datetime 可比较
            if last_dt.tzinfo is None:
                now = datetime.now()
            else:
                now = datetime.now(timezone.utc)
            delta_days = (now - last_dt).days
            if delta_days <= 1:
                return 1.0
            elif delta_days <= 7:
                return 0.9
            elif delta_days <= 30:
                return 0.7
            elif delta_days <= 90:
                return 0.5
            else:
                return 0.3
        except Exception:
            return 0.3

    def _touch_selected(self, memories: List[Dict]):
        """更新入选记忆的最后访问时间"""
        for m in memories:
            try:
                self.storage.touch_memory(m["id"])
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 优先级自动调整
    # ------------------------------------------------------------------

    def degrade_by_age(self) -> int:
        """
        基于创建时间的年龄衰减。pinned=true 的记忆豁免。

        衰减规则：
        - CRITICAL → HIGH    (创建 >30 天)
        - HIGH     → MEDIUM  (创建 >60 天)
        - MEDIUM   → LOW     (创建 >90 天)

        Returns:
            调整的记忆条数
        """
        from datetime import datetime
        now = datetime.now()
        all_memories = self.storage.get_active_memories(limit=500)
        adjusted = 0

        for m in all_memories:
            if m.get("pinned"):
                continue
            created = m.get("created_at")
            if not created:
                continue
            try:
                # SQLite 时间戳兼容 ISO 和 SQLite 格式
                if "T" in str(created):
                    age = now - datetime.fromisoformat(str(created).replace("Z", "+00:00").split("+")[0].split(".")[0])
                else:
                    age = now - datetime.strptime(str(created), "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue

            days = age.days
            old_priority = m["priority"]
            new_priority = None

            if old_priority == PRIORITY_CRITICAL and days >= CRITICAL_DEGRADE_DAYS:
                new_priority = PRIORITY_HIGH
            elif old_priority == PRIORITY_HIGH and days >= HIGH_DEGRADE_DAYS:
                new_priority = PRIORITY_MEDIUM
            elif old_priority == PRIORITY_MEDIUM and days >= MEDIUM_DEGRADE_DAYS:
                new_priority = PRIORITY_LOW

            if new_priority is not None:
                self.storage.update_memory(m["id"], priority=new_priority)
                adjusted += 1
                logger.info(
                    f"年龄衰减: #{m['id']} priority "
                    f"{PRIORITY_LABELS[old_priority]}→{PRIORITY_LABELS[new_priority]} "
                    f"(年龄={days}天)"
                )

        if adjusted:
            logger.info(f"年龄衰减完成: {adjusted} 条记忆降级")
        return adjusted

    LLM_ADJUST_SYSTEM_PROMPT = """你是一个记忆优先级评估器。根据近期对话主题，判断哪些长期记忆的优先级需要调整。

调整规则（非常重要）：
1. 只提供与近期对话主题直接相关的调整
2. 每次最多输出 {max_adjustments} 条调整建议
3. 只能将优先级上下调整 1 级（如 CRITICAL⇄HIGH, HIGH⇄MEDIUM, MEDIUM⇄LOW）
4. 优先级的含义：0=CRITICAL(必须遵循的指令), 1=HIGH(偏好/关键决策), 2=MEDIUM(经验教训), 3=LOW(一般参考)
5. 近期对话中反复涉及的主题 → 相关记忆可升级
6. 近期对话中完全未涉及 → 不操作（让年龄衰减处理）

输出纯 JSON 数组：
[{"memory_id": "xxx", "new_priority": 1, "reason": "近期大量讨论该主题，建议提升"}, ...]

如果不需要调整，输出空数组 []。"""

    def llm_adjust_priorities(
        self,
        recent_topics: str,
        client=None,
        model: str = "deepseek-v4-flash",
    ) -> int:
        """
        使用便宜 LLM 评估近期对话主题，微调记忆优先级。

        Args:
            recent_topics: 近期对话主题摘要文本
            client: OpenAI 客户端实例（由调用方注入，如 session.client）
            model: 使用的模型名称

        Returns:
            调整的记忆条数。client 为 None 时返回 0。
        """
        if client is None:
            logger.warning("llm_adjust_priorities: 未提供 client，跳过精调")
            return 0
        if not recent_topics or not recent_topics.strip():
            return 0

        all_memories = self.storage.get_active_memories(limit=200)
        if len(all_memories) < 3:
            return 0  # 太少不值得调

        # 构建记忆摘要（不含内容细节，防 token 爆炸）
        memory_summary_lines = []
        for m in all_memories:
            content_preview = (m.get("content") or "")[:80].replace("\n", " ")
            memory_summary_lines.append(
                f"  [{m['id']}] P{PRIORITY_LABELS.get(m['priority'], '?')}/I{m.get('importance',0)} "
                f"cat={m.get('category','?')} tags={m.get('tags','')} | {content_preview}"
            )
        memory_summary = "\n".join(memory_summary_lines[:100])  # 最多100条

        system_prompt = self.LLM_ADJUST_SYSTEM_PROMPT.format(
            max_adjustments=MAX_LLM_ADJUSTMENTS
        )
        user_prompt = (
            f"近期对话主题摘要：\n{recent_topics[:2000]}\n\n"
            f"当前活跃记忆列表：\n{memory_summary}\n\n"
            f"请判断哪些记忆的优先级需要调整（最多{MAX_LLM_ADJUSTMENTS}条）。"
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
                extra_body={"thinking": {"type": "disabled"}},
                temperature=0.3,
                max_tokens=500,
            )
            result_text = response.choices[0].message.content or ""
            adjustments = self.parse_extraction_result(result_text)
        except Exception as e:
            logger.warning(f"LLM 优先级精调失败: {e}")
            return 0

        adjusted = 0
        for adj in adjustments:
            try:
                mid = adj.get("memory_id", "")
                new_priority = adj.get("new_priority")
                reason = adj.get("reason", "无说明")

                if new_priority is None or not mid:
                    continue
                if new_priority not in (0, 1, 2, 3):
                    continue

                # 找到原始记忆
                orig = next((m for m in all_memories if m["id"] == mid), None)
                if not orig:
                    continue
                old_priority = orig["priority"]

                # 只允许 ±1 级调整
                if abs(new_priority - old_priority) > 1:
                    logger.warning(
                        f"LLM 建议跳级调整 #{mid}: {old_priority}→{new_priority}, 已忽略"
                    )
                    continue

                if new_priority == old_priority:
                    continue

                # 升级时重置 created_at（重新计时年龄衰减）
                updates = {"priority": new_priority}
                if new_priority < old_priority:
                    updates["created_at"] = "CURRENT_TIMESTAMP"

                self.storage.update_memory(mid, **updates)
                adjusted += 1
                logger.info(
                    f"LLM 精调: #{mid} priority "
                    f"{PRIORITY_LABELS[old_priority]}→{PRIORITY_LABELS[new_priority]} "
                    f"原因: {reason}"
                )

            except Exception as e:
                logger.warning(f"LLM 精调单条失败: {e}")

        if adjusted:
            logger.info(f"LLM 优先级精调完成: {adjusted} 条调整")
        return adjusted

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
        """解析 LLM 提取结果。
        
        增强健壮性:
        1. 处理 markdown 代码块包裹
        2. 处理 JSON 前后的额外文本
        3. 处理多个 JSON 块
        4. 处理嵌套在对象中的数组
        """
        import json
        import re
        
        if not result_text or not result_text.strip():
            return []
        
        text = result_text.strip()
        
        # 1. 尝试直接解析
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                # 尝试从常见键名提取数组
                for key in ("memories", "items", "results", "data"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
        except (json.JSONDecodeError, ValueError):
            pass
        
        # 2. 处理 markdown 代码块
        code_block_pattern = r'```(?:json)?\s*\n?(.*?)\n?\s*```'
        matches = re.findall(code_block_pattern, text, re.DOTALL)
        for match in matches:
            try:
                data = json.loads(match.strip())
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for key in ("memories", "items", "results", "data"):
                        if key in data and isinstance(data[key], list):
                            return data[key]
            except (json.JSONDecodeError, ValueError):
                continue
        
        # 3. 尝试提取文本中的 JSON 数组（处理前后有额外文本的情况）
        array_pattern = r'\[\s*\{.*?\}\s*\]'
        array_matches = re.findall(array_pattern, text, re.DOTALL)
        for match in array_matches:
            try:
                data = json.loads(match)
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, ValueError):
                continue
        
        return []

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

    def _find_duplicate(self, content: str, category: str, existing: List[Dict]) -> Optional[Dict]:
        """
        在活跃记忆中查找与 content 相似度超过阈值的记忆。

        Args:
            content: 待查重的记忆内容
            category: 可选分类过滤（同分类优先匹配）
            existing: 已加载的活跃记忆列表（由调用方缓存）

        Returns:
            找到的重复记忆 Dict；无重复返回 None
        """
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

        # 一次性加载活跃记忆，避免每条提取都重复查询
        existing_memories = self.storage.get_active_memories(limit=200)

        for item in results:
            try:
                tags = item.get("tags", "")
                if isinstance(tags, list):
                    tags = ", ".join(tags)
                content = item.get("content", "").strip()
                category = item.get("category", "general")

                if not content:
                    continue

                # 查重（使用缓存的记忆列表）
                duplicate = self._find_duplicate(content, category, existing_memories)

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
