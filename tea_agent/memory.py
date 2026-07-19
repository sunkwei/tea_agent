# @2026-04-29 gen by deepseek-v4-pro, MemoryManager: 记忆选择/格式化/提取策略
"""
Memory 管理器
负责记忆的选择、格式化注入和从对话中提取新记忆。
"""

import logging
import re

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

# 年龄衰减阈值（天）— 基础值，会被动态遗忘机制调整
# 动态调整范围：基础值 × [0.3, 3.0]
_BASE_CRITICAL_DEGRADE_DAYS = 30   # CRITICAL → HIGH
_BASE_HIGH_DEGRADE_DAYS = 60       # HIGH → MEDIUM
_BASE_MEDIUM_DEGRADE_DAYS = 90     # MEDIUM → LOW

# 当前实际使用的阈值（动态调整后）
CRITICAL_DEGRADE_DAYS = 30
HIGH_DEGRADE_DAYS = 60
MEDIUM_DEGRADE_DAYS = 90

class MemoryManager:
    """记忆管理器：选择、格式化、提取"""

    def __init__(self, storage, extraction_threshold: int = 2, dedup_threshold: float = 0.6):
        """
        Args:
            storage: Storage 实例，提供记忆 CRUD
            extraction_threshold: 触发记忆提取的最低未摘要消息数
            dedup_threshold: 记忆去重相似度阈值 (0~1)，超过此值视为重复
        """
        self.storage = storage
        self._extraction_threshold = extraction_threshold
        self._dedup_threshold = dedup_threshold
        # embedding 缓存（惰性加载）
        self._embedding_engine = None
        self._embedding_cache = {}  # memory_id → embedding vector

    # ------------------------------------------------------------------
    # 记忆选择
    # ------------------------------------------------------------------

    def select_memories(
        self,
        topic_text: str = "",
        limit: int = MAX_INJECT,
    ) -> list[dict]:
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

        # 2. 非 CRITICAL 打分排序（预计算查询向量，避免每条记忆重复请求）
        query_emb = None
        engine = self._get_embedding_engine()
        if engine and topic_text:
            try:
                query_emb = engine.embed(topic_text)
            except Exception:
                query_emb = None

        others = high + medium + low
        scored = []
        for m in others:
            score = self._score_memory_cached(m, topic_text, query_emb)
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

    def _score_memory_cached(self, memory: dict, topic_text: str, query_emb=None) -> float:
        """计算记忆与当前对话的相关性分数（Hybrid），复用预计算的查询向量。"""
        # 关键词得分
        keyword_relevance = self._compute_relevance(memory, topic_text)

        # embedding 语义得分（使用预计算向量）
        if query_emb is not None:
            emb_sim = self._compute_embedding_similarity_cached(memory, query_emb)
            if emb_sim is not None:
                kw = max(keyword_relevance, 0.1)
                relevance = 0.4 * kw + 0.6 * emb_sim
            else:
                relevance = keyword_relevance
        else:
            relevance = keyword_relevance

        importance = max(memory.get("importance", 3), 1) / 5.0
        recency = self._compute_recency(memory)
        priority_factor = (4 - memory.get("priority", 2)) / 4.0

        return relevance * importance * recency * priority_factor

    def _compute_relevance(self, memory: dict, topic_text: str) -> float:
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
    def _compute_recency(memory: dict) -> float:
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
                last_dt = datetime.strptime(last, '%Y-%m-%d %H:%M:%S') if ' ' in last and 'T' not in last else datetime.fromisoformat(last)
            else:
                return 0.3
            # 确保 naive datetime 可比较
            now = datetime.now() if last_dt.tzinfo is None else datetime.now(timezone.utc)
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

    def _touch_selected(self, memories: list[dict]):
        """更新入选记忆的最后访问时间"""
        for m in memories:
            try:
                self.storage.touch_memory(m["id"])
            except Exception:
                logger.exception('op_failed')


    # ------------------------------------------------------------------
    # Hybrid 检索：Embedding 相似度 + 缓存
    # ------------------------------------------------------------------

    def _get_embedding_engine(self):
        """惰性获取 embedding 引擎（通过 storage.memories.embedding_engine）"""
        if self._embedding_engine is not None:
            return self._embedding_engine
        try:
            engine = getattr(self.storage.memories, 'embedding_engine', None)
            if engine is not None and engine.configured:
                self._embedding_engine = engine
                return engine
        except Exception:
            pass
        return None


    # ------------------------------------------------------------------
    # 优先级自动调整
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 动态遗忘：根据记忆插入频率调整衰减阈值
    # ------------------------------------------------------------------


    def _compute_embedding_similarity_cached(self, memory: dict, query_emb):
        """使用预计算的查询向量计算余弦相似度（避免重复 embedding 请求）。"""
        if query_emb is None:
            return None

        mid = memory.get("id", "")
        mem_emb = self._embedding_cache.get(mid)
        if mem_emb is None:
            try:
                mem_emb = self.storage.memories.get_memory_embedding(mid)
                if mem_emb:
                    self._embedding_cache[mid] = mem_emb
            except Exception:
                pass

        if not mem_emb or len(mem_emb) != len(query_emb):
            return None

        import numpy as np
        q_arr = np.array(query_emb, dtype=np.float32)
        m_arr = np.array(mem_emb, dtype=np.float32)
        q_norm = np.linalg.norm(q_arr)
        m_norm = np.linalg.norm(m_arr)
        if q_norm == 0 or m_norm == 0:
            return None
        return float(q_arr @ m_arr) / (q_norm * m_norm)

    def _update_dynamic_thresholds(self):
        """
        根据近期记忆插入频率动态调整衰老衰减阈值。

        哲学含义（来自用户的比喻）：
        - 低频（中年打工）→ 阈值放大，记忆保留更久，珍惜每一段经历
        - 高频（学生时代）→ 阈值缩小，记忆快速刷新，拥抱变化

        算法：
        1. 统计最近 N 天（7/30/90）的记忆创建数量
        2. 计算加权平均频率（条/天），近期权重更高
        3. 映射到 [0.3, 3.0] 的缩放因子
        4. 更新全局 CRITICAL/HIGH/MEDIUM_DEGRADE_DAYS
        """
        global CRITICAL_DEGRADE_DAYS, HIGH_DEGRADE_DAYS, MEDIUM_DEGRADE_DAYS

        try:
            from datetime import datetime, timedelta
            now = datetime.now()

            # 查询不同时间窗口的记忆数量
            windows = [7, 30, 90]
            counts = {}
            c = self.storage.conn.cursor()
            for days in windows:
                since = (now - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                c.execute(
                    "SELECT COUNT(*) FROM memories "
                    "WHERE is_active = 1 AND created_at >= ?",
                    (since,),
                )
                counts[days] = c.fetchone()[0]
            c.close()

            # 加权平均频率（条/天）：7天权重3，30天权重2，90天权重1
            freq_7d = counts[7] / 7.0
            freq_30d = counts[30] / 30.0
            freq_90d = counts[90] / 90.0
            weighted_freq = (freq_7d * 3 + freq_30d * 2 + freq_90d * 1) / 6.0

            # 映射到缩放因子 [0.3, 3.0]
            # 中位频率 = 1.0 条/天 → 缩放因子 = 1.0（无变化）
            # 频率 → 缩放因子使用幂函数映射
            if weighted_freq <= 0:
                scale = 3.0  # 没有新记忆，极度慢速遗忘
            elif weighted_freq < 0.3:
                # 极低频（<0.3条/天）：3x → 2x 线性插值
                scale = 3.0 - (weighted_freq / 0.3) * 1.0
            elif weighted_freq < 1.0:
                # 低频（0.3~1条/天）：2x → 1x
                ratio = (weighted_freq - 0.3) / 0.7
                scale = 2.0 - ratio * 1.0
            elif weighted_freq < 3.0:
                # 中等（1~3条/天）：1x → 0.7x
                ratio = (weighted_freq - 1.0) / 2.0
                scale = 1.0 - ratio * 0.3
            elif weighted_freq < 10:
                # 高频（3~10条/天）：0.7x → 0.4x
                ratio = (weighted_freq - 3.0) / 7.0
                scale = 0.7 - ratio * 0.3
            else:
                # 极高频率（>10条/天，学生时代）：0.4x → 0.3x 渐近
                scale = max(0.3, 0.4 - (weighted_freq - 10) * 0.01)

            # 更新全局阈值
            CRITICAL_DEGRADE_DAYS = max(5, int(_BASE_CRITICAL_DEGRADE_DAYS * scale))
            HIGH_DEGRADE_DAYS = max(10, int(_BASE_HIGH_DEGRADE_DAYS * scale))
            MEDIUM_DEGRADE_DAYS = max(15, int(_BASE_MEDIUM_DEGRADE_DAYS * scale))

            logger.info(
                f"动态遗忘: 频率={weighted_freq:.2f}条/天, "
                f"缩放因子={scale:.2f}x, "
                f"阈值=[{CRITICAL_DEGRADE_DAYS}/{HIGH_DEGRADE_DAYS}/{MEDIUM_DEGRADE_DAYS}]天"
            )

        except Exception as e:
            logger.debug(f"动态阈值更新跳过: {e}")

    def degrade_by_age(self) -> int:
        """
        基于创建时间的年龄衰减。pinned=true 的记忆豁免。

        先调用 _update_dynamic_thresholds() 根据近期记忆插入频率
        动态调整衰减阈值（你提出的"中年打工 vs 学生时代"机制）。

        衰减规则（动态阈值）：
        - CRITICAL → HIGH    (创建 >CRITICAL_DEGRADE_DAYS 天)
        - HIGH     → MEDIUM  (创建 >HIGH_DEGRADE_DAYS 天)
        - MEDIUM   → LOW     (创建 >MEDIUM_DEGRADE_DAYS 天)

        Returns:
            调整的记忆条数
        """
        from datetime import datetime
        now = datetime.now()

        # 先根据插入频率动态调整阈值
        self._update_dynamic_thresholds()

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

    # ------------------------------------------------------------------
    # 格式化注入
    # ------------------------------------------------------------------

    @staticmethod
    def format_memories(memories: list[dict]) -> str:
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
            f"[系统记忆 — 以下为需要遵循的有效信息和规则，共 {len(memories)} 条]",
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
    def _prefix_for(memory: dict) -> str:
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

    def build_extraction_prompt(self, conversations_text: str) -> list[dict[str, str]]:
        """构建记忆提取的 API 消息列表"""
        return [
            {"role": "system", "content": self.EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"请从以下对话中提取值得保留的记忆：\n\n{conversations_text}"}
        ]

    @staticmethod
    def parse_extraction_result(result_text: str) -> list[dict]:
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
            logger.exception('op_failed')


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

    def _find_duplicate(self, content: str, category: str, existing: list[dict]) -> dict | None:
        """
        在活跃记忆中查找与 content 相似度超过阈值的记忆。

        Args:
            content: 待查重的记忆内容
            category: 可选分类过滤（同分类优先匹配）
            existing: 已加载的活跃记忆列表（由调用方缓存）

        Returns:
            找到的重复记忆 Dict；无重复返回 None
        """
        # 0. content_hash 精确匹配（最快，O(n) 短路）
        import hashlib
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
        for mem in existing:
            if mem.get("content_hash") == content_hash:
                logger.info(
                    f"发现重复记忆 #{mem['id']} (content_hash 精确匹配): "
                    f"\"{content[:50]}...\""
                )
                return mem

        # 1. Jaccard 关键词相似度
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

    def _merge_memory(self, existing: dict, new_item: dict) -> dict:
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
        old_tags = {t.strip() for t in (existing.get("tags") or "").split(",") if t.strip()}
        new_tags_raw = new_item.get("tags", "")
        if isinstance(new_tags_raw, list):
            new_tags = {t.strip() for t in new_tags_raw if t.strip()}
        else:
            new_tags = {t.strip() for t in str(new_tags_raw).split(",") if t.strip()}
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
        merged_expires = min(str(old_expires), str(new_expires)) if old_expires and new_expires else old_expires or new_expires

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

    def ingest_extracted(self, results: list[dict], topic_id: int | None = None) -> int:
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

        # 分页加载活跃记忆进行去重，避免200条硬限制遗漏
        existing_memories = self.storage.get_active_memories(limit=500)

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

    # ------------------------------------------------------------------
    # 重复检测与合并提权（原 store._memories.MemoryStore 迁入）
    # ------------------------------------------------------------------

    def detect_duplicates(self, threshold: float = 0.92) -> list[tuple]:
        """通过 embedding 余弦相似度扫描活跃记忆中的近似重复对。"""
        mems = self.storage.memories.batch_get_embeddings(limit=500)
        if len(mems) < 2:
            return []

        import numpy as np
        pairs = []
        for i in range(len(mems)):
            emb_i = mems[i].get('embedding')
            if emb_i is None:
                continue
            arr_i = np.array(emb_i, dtype=np.float32)
            ni = np.linalg.norm(arr_i)
            if ni == 0:
                continue
            for j in range(i + 1, len(mems)):
                emb_j = mems[j].get('embedding')
                if emb_j is None or len(emb_j) != len(emb_i):
                    continue
                arr_j = np.array(emb_j, dtype=np.float32)
                sim = float(arr_i @ arr_j) / (ni * np.linalg.norm(arr_j))
                if sim >= threshold:
                    pairs.append((mems[i]['id'], mems[j]['id'], round(sim, 4)))

        pairs.sort(key=lambda x: x[2], reverse=True)
        return pairs

    def merge_duplicates(self, keep_id: str, remove_id: str) -> bool:
        """合并两条重复记忆：融合内容、提权、软删除。"""
        try:
            # 通过 storage API 读取两条记忆
            all_mems = self.storage.get_active_memories(limit=500)
            keep = next((m for m in all_mems if m['id'] == keep_id), None)
            remove = next((m for m in all_mems if m['id'] == remove_id), None)
            if not keep or not remove:
                logger.warning(f'Merge failed: memory not found keep={keep_id} remove={remove_id}')
                return False

            # Merge content
            merged = keep['content']
            if remove['content'] not in merged:
                merged = keep['content'] + '\n---\n' + remove['content']

            # Merge tags
            ktags = {t.strip() for t in (keep.get('tags', '') or '').split(',') if t.strip()}
            rtags = {t.strip() for t in (remove.get('tags', '') or '').split(',') if t.strip()}
            merged_tags = ','.join(sorted(ktags | rtags))

            # Boost
            new_priority = max(0, keep['priority'] - 1)
            new_importance = min(5, (keep['importance'] or 3) + 1)

            self.storage.update_memory(keep_id,
                content=merged, tags=merged_tags,
                priority=new_priority, importance=new_importance)
            self.storage.deactivate_memory(remove_id)
            logger.info(f'Merged: {remove_id} -> {keep_id}, priority={new_priority}, importance={new_importance}')
            return True

        except Exception as e:
            logger.error(f'Merge failed: {e}')
            return False

    def auto_dedup(self, threshold: float = 0.92) -> dict:
        """自动检测并合并所有重复记忆对。"""
        pairs = self.detect_duplicates(threshold=threshold)
        merged = 0
        errors = 0
        processed = set()
        for a_id, b_id, _sim in pairs:
            if a_id in processed or b_id in processed:
                continue
            if self.merge_duplicates(a_id, b_id):
                merged += 1
                processed.add(a_id)
                processed.add(b_id)
            else:
                errors += 1
        return {'scanned': len(pairs), 'merged': merged, 'errors': errors, 'threshold': threshold}

    def is_extraction_needed(self, unsummarized_count: int) -> bool:
        """判断是否需要触发记忆提取"""
        return unsummarized_count >= self._extraction_threshold
