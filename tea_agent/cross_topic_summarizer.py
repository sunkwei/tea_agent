"""
@2026-07-19 gen by claude, 跨主题汇总工作线程 — 每 N 轮会话后启动一次跨主题分析

替代已删除的 subconscious(潜意识)线程。设计原则：
- 每 3 轮会话触发一次
- 后台 daemon 线程，不阻塞主交互
- 读取最近 topic，用廉价 LLM 找出跨主题模式/趋势
- 结果保存为 insight 类型记忆
"""

import json
import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger("agent.cross_topic")


def _counter_path():
    return os.path.join(os.path.expanduser("~"), ".tea_agent", "cross_topic_counter.json")


def _load_counter() -> dict:
    path = _counter_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"count": 0, "last_triggered_topics": []}


def _save_counter(data: dict):
    path = _counter_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class CrossTopicSummarizer:
    """跨主题汇总器。

    用法：
        summarizer = CrossTopicSummarizer(storage)
        # 每次会话完成后调用:
        summarizer.on_session_complete()
    """

    TRIGGER_INTERVAL = 3  # 每 3 轮触发

    ANALYZE_PROMPT = """你是一个 Agent 行为分析器。以下是最近 {topic_count} 个会话的主题摘要：

{topic_summaries}

请分析：
1. 最近的工作主题是否有模式或趋势？
2. 用户的偏好或关注点是否有变化？
3. Agent 的执行是否暴露了需要改进的问题？

输出 JSON 格式，最多 3 条洞察：
{{"insights": [{{"content": "...", "importance": 1-5}}]}}

只输出 JSON，不要额外说明。"""

    def __init__(self, storage, cheap_client=None):
        self.storage = storage
        self._cheap_client = cheap_client
        self._lock = threading.Lock()

    def on_session_complete(self):
        """每次会话完成后调用。线程安全，非阻塞。"""
        with self._lock:
            counter = _load_counter()
            counter["count"] = counter.get("count", 0) + 1
            _save_counter(counter)

        if counter["count"] % self.TRIGGER_INTERVAL == 0:
            t = threading.Thread(
                target=self._do_cross_topic_analysis,
                args=(counter["count"],),
                daemon=True,
            )
            t.start()
            logger.info(f"cross_topic: 触发第 {counter['count']} 轮跨主题分析")

    def _get_recent_topics(self, limit: int = 10) -> list[dict]:
        """获取最近的话题及其摘要。"""
        try:
            topics = self.storage.list_topics()
            if not topics:
                return []
            topics = topics[:limit]  # list_topics 已按 last_update_stamp DESC 排序
            result = []
            for t in topics:
                tid = t.get("topic_id", "")
                title = t.get("title", "") or "(无标题)"
                result.append({
                    "topic_id": tid,
                    "title": title[:100],
                    "created": t.get("last_update_stamp", "")[:19],
                })
            return result
        except Exception:
            logger.exception("cross_topic: 读取话题失败")
            return []

    def _do_cross_topic_analysis(self, count: int):
        """后台线程：跨主题分析 → 保存为 insight 记忆。"""
        try:
            topics = self._get_recent_topics(limit=10)
            if len(topics) < 2:
                logger.info("cross_topic: 话题不足 2 个，跳过分析")
                return

            insights = self._call_llm(topics)
            if not insights:
                return

            saved = 0
            for ins in insights:
                content = ins.get("content", "")
                if not content or len(content) < 10:
                    continue
                importance = max(1, min(5, ins.get("importance", 2)))
                try:
                    self.storage.add_memory(
                        content=content,
                        category="insight",
                        importance=importance,
                        tags=f"cross_topic,auto,round_{count}",
                    )
                    saved += 1
                except Exception:
                    logger.exception("cross_topic: 保存洞察失败")

            logger.info(f"cross_topic: 第 {count} 轮分析完成，保存 {saved} 条洞察")

        except Exception:
            logger.exception("cross_topic: 分析失败")

    def _call_llm(self, topics: list[dict]) -> list[dict]:
        """调用廉价 LLM 进行跨主题分析。"""
        if not self._cheap_client:
            # 尝试从 config 获取
            try:
                from tea_agent.config import get_config
                from tea_agent.providers import get_cheap_client
                cfg = get_config()
                self._cheap_client = get_cheap_client(cfg)
            except Exception:
                logger.warning("cross_topic: 无法获取 cheap LLM client")
                return self._fallback_analysis(topics)

        if not self._cheap_client:
            return self._fallback_analysis(topics)

        try:
            summaries = "\n".join(
                f"{i+1}. [{t.get('created','')[:10]}] {t.get('title','')}"
                for i, t in enumerate(topics)
            )
            prompt = self.ANALYZE_PROMPT.format(
                topic_count=len(topics),
                topic_summaries=summaries,
            )
            resp = self._cheap_client.chat.completions.create(
                model=self._cheap_client.model if hasattr(self._cheap_client, 'model') else "gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
            data = json.loads(content)
            return data.get("insights", [])
        except Exception:
            logger.exception("cross_topic: LLM 调用失败")
            return self._fallback_analysis(topics)

    def _fallback_analysis(self, topics: list[dict]) -> list[dict]:
        """LLM 不可用时的规则回退分析。"""
        titles = [t.get("title", "") for t in topics if t.get("title")]
        if len(titles) < 3:
            return []
        # 简单的统计回退：工作密度趋势
        return [{
            "content": f"最近 {len(topics)} 个会话涵盖了 {len(set(t[:20] for t in titles))} 个不同主题方向。"
                       f"建议检查是否有偏离主要工作线的情况。",
            "importance": 2,
        }]
