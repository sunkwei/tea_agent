"""
"""
import json
import logging
from typing import Dict, List, Optional
from ._component import StoreComponent

logger = logging.getLogger("Storage.Summaries")

class SummaryStore(StoreComponent):
    """摘要管理：话题摘要、三级历史（Level1/2/3）、语义摘要、工具链摘要。"""

    # ── 话题摘要 (t_conv_summary) ──

    def get_topic_summary(self, topic_id: str) -> Optional[str]:
        """Get the topic summary.
        
        Args:
            topic_id: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT summary FROM t_conv_summary WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row["summary"] if row else None

    def update_topic_summary(self, topic_id: str, summary: str,
                              last_summarized_id: Optional[int] = None):
        """Update topic summary.
        
        Args:
            topic_id: Description.
            summary: Description.
            last_summarized_id: Description.
        """
        c = self.conn.cursor()
        if last_summarized_id is not None:
            c.execute('''
                INSERT INTO t_conv_summary (topic_id, summary, last_summarized_id, last_update)
                VALUES (?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(topic_id) DO UPDATE SET
                    summary = excluded.summary,
                    last_summarized_id = excluded.last_summarized_id,
                    last_update = datetime('now', 'localtime')
            ''', (topic_id, summary, last_summarized_id))
        else:
            c.execute('''
                INSERT INTO t_conv_summary (topic_id, summary, last_update)
                VALUES (?, ?, datetime('now', 'localtime'))
                ON CONFLICT(topic_id) DO UPDATE SET
                    summary = excluded.summary,
                    last_update = datetime('now', 'localtime')
            ''', (topic_id, summary))
        self.conn.commit()
        c.close()

    # ── 三级历史 Level 2 ──

    def get_level2(self, topic_id: str) -> list:
        """Get the level2.
        
        Args:
            topic_id: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT level2_json FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return []
        return []

    def set_level2(self, topic_id: str, level2: list):
        """Set the level2.
        
        Args:
            topic_id: Description.
            level2: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET level2_json = ? WHERE topic_id = ?",
            (json.dumps(level2, ensure_ascii=False), topic_id),
        )
        self.conn.commit()
        c.close()

    # ── 三级历史 Level 3: 语义摘要 ──

    def get_semantic_summary(self, topic_id: str) -> str:
        """Get the semantic summary.
        
        Args:
            topic_id: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT semantic_summary FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row[0] if row and row[0] else ""

    def set_semantic_summary(self, topic_id: str, summary: str):
        """Set the semantic summary.
        
        Args:
            topic_id: Description.
            summary: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET semantic_summary = ? WHERE topic_id = ?",
            (summary, topic_id),
        )
        self.conn.commit()
        c.close()

    def get_tool_chain_summary(self, topic_id: str) -> str:
        """Get the tool chain summary.
        
        Args:
            topic_id: Description.
        """
        c = self.conn.cursor()
        c.execute("SELECT tool_chain_summary FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        return row[0] if row and row[0] else ""

    def set_tool_chain_summary(self, topic_id: str, summary: str):
        """Set the tool chain summary.
        
        Args:
            topic_id: Description.
            summary: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET tool_chain_summary = ? WHERE topic_id = ?",
            (summary, topic_id),
        )
        self.conn.commit()
        c.close()

    def push_to_level2(self, topic_id: str, user_msg: str, ai_msg: str,
                        files: list = None, rounds: list = None,
                        max_level2: int = 50) -> tuple:
        """
        将一轮对话推入 Level 2，最多保留 max_level2 条。

        L2 条目包含完整 user + ai thinking + ai final msg（不含工具轮）。
        thinking 从 rounds 中提取所有带 tool_calls 的 assistant content。

        当 L2 达到上限时：保留最新 20 条，返回最老 30 条溢出 + 触发摘要信号。

        Returns:
            (level2_count, overflow_items, should_summarize)
            - level2_count: 当前 L2 条目数
            - overflow_items: 溢出的最老条目（待摘要），[] 表示无溢出
            - should_summarize: 是否需要触发 L2→L3 摘要
        """
        level2 = self.get_level2(topic_id)

        # 从 rounds 提取 thinking：所有带 tool_calls 的 assistant 消息
        thinking_parts = []
        if rounds:
            for r in rounds:
                if r.get("role") == "assistant" and r.get("tool_calls"):
                    parts = []
                    if r.get("reasoning_content"):
                        parts.append(f"[思考] {r['reasoning_content']}")
                    if r.get("content"):
                        parts.append(r["content"])
                    if parts:
                        thinking_parts.append("\n".join(parts))

        entry = {"user": user_msg, "assistant": ai_msg}
        if thinking_parts:
            entry["thinking"] = "\n\n".join(thinking_parts)
        if files:
            entry["files"] = files
        level2.append(entry)

        overflow_items = []
        should_summarize = False

        if len(level2) >= max_level2:
            # L2 达到 50 条：取最老 30 条做 L3 摘要，保留最新 20 条
            overflow_items = level2[:30]
            level2 = level2[-20:]
            should_summarize = True

        self.set_level2(topic_id, level2)
        return len(level2), overflow_items, should_summarize

    # ── L2→L3 摘要生成 ──

    def generate_l2_to_l3_summary(
        self, topic_id: str, overflow_items: list,
        existing_l3: str, summarize_client, summarize_model: str,
        extra_params: dict = None,
    ) -> str:
        """
        将 L2 溢出条目 + 现有 L3 摘要合并，调用 LLM 生成新的 L3 摘要。

        策略：每 30 轮触发一次（50→20），而非每轮更新，大幅节省 Token。

        Args:
            topic_id: 主题 ID
            overflow_items: 溢出的最老 L2 条目列表
            existing_l3: 现有 L3 语义摘要（可能为空）
            summarize_client: OpenAI 客户端
            summarize_model: 摘要模型名
            extra_params: 额外参数（temperature 等）

        Returns:
            新生成的 L3 语义摘要文本
        """
        if not overflow_items:
            return existing_l3

        # 构建对话文本
        conv_lines = []
        for idx, item in enumerate(overflow_items, 1):
            u = item.get("user", "")[:2000]
            t = item.get("thinking", "")
            a = item.get("assistant", "")[:2000]
            if t:
                conv_lines.append(
                    f"[对话 {idx}]\nUser: {u}\nAI思考: {t[:2000]}\nAI回复: {a}"
                )
            else:
                conv_lines.append(f"[对话 {idx}]\nUser: {u}\nAssistant: {a}")

        conv_text = "\n\n".join(conv_lines)

        existing_text = existing_l3 if existing_l3 else "（无）"

        prompt = f"""你是一个编程项目对话摘要助手。请将以下历史对话提炼为结构化的技术摘要，供后续 AI 编码会话使用。

## 现有背景摘要
{existing_text}

## 新增历史对话（共 {len(overflow_items)} 轮）
{conv_text}

## 摘要格式要求
请按以下结构输出摘要（每个段落用 ## 标题分隔）：

## 项目背景
（项目类型、技术栈、当前阶段）
## 已完成的修改
（列出具体改动的文件及变更内容，格式: file.py — 变更描述）
## 关键决策与原因
（做了什么重要选择，为什么这样选）
## 遇到的错误及解决方案
（如果对话中有调试/报错，记录错误和修复方法）
## 架构约束与注意事项
（不可违反的规则、兼容性要求、特殊约定）
## 用户偏好与长期要求
（用户明确表达的编码风格、工具偏好、全局要求）
## 当前待办事项
（未完成的任务、下一步计划）

要求：
1. 中文输出，控制在 32000 字符以内
2. 信息密度优先 — 避免冗长的叙述，用列表和简洁陈述
3. 丢弃已过时或与当前任务无关的内容
4. 直接输出摘要正文，无需额外解释"""

        try:
            params = {"max_tokens": 4096, "temperature": 0.3}
            if extra_params:
                params.update(extra_params)

            response = summarize_client.chat.completions.create(
                model=summarize_model,
                messages=[{"role": "user", "content": prompt}],
                **params,
            )
            new_summary = response.choices[0].message.content or ""
            new_summary = new_summary.strip()[:32000]

            if new_summary:
                self.set_semantic_summary(topic_id, new_summary)
                logger.info(
                    f"L3 摘要更新: {len(overflow_items)}条L2→{len(new_summary)}字符 "
                    f"(现有L3={len(existing_l3)}字符)"
                )
            return new_summary
        except Exception as e:
            logger.warning(f"L2→L3 摘要生成失败: {e}")
            return existing_l3

    # ── L3 待处理缓冲（批处理：攒够 N 条再触发摘要）──

    def get_l3_pending(self, topic_id: str) -> list:
        """获取该 topic 的 L3 待处理缓冲。"""
        c = self.conn.cursor()
        c.execute("SELECT l3_pending_json FROM topics WHERE topic_id = ?", (topic_id,))
        row = c.fetchone()
        c.close()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return []
        return []

    def push_l3_pending(self, topic_id: str, items: list):
        """将溢出条目追加到 L3 待处理缓冲。"""
        existing = self.get_l3_pending(topic_id)
        existing.extend(items)
        c = self.conn.cursor()
        c.execute(
            "UPDATE topics SET l3_pending_json = ? WHERE topic_id = ?",
            (json.dumps(existing, ensure_ascii=False), topic_id),
        )
        self.conn.commit()
        c.close()

    def clear_l3_pending(self, topic_id: str):
        """清空 L3 待处理缓冲（摘要完成后调用）。"""
        c = self.conn.cursor()
        c.execute("UPDATE topics SET l3_pending_json = '' WHERE topic_id = ?", (topic_id,))
        self.conn.commit()
        c.close()
    # ── 摘要标记 ──

    def mark_as_summarized(self, conversation_id: str):
        """Mark as summarized.
        
        Args:
            conversation_id: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "UPDATE conversations SET is_summarized = 1 WHERE id = ?",
            (conversation_id,),
        )
        self.conn.commit()
        c.close()

    def get_unsummarized_conversations(self, topic_id: str, limit: int = 50) -> List[Dict]:
        """Get the unsummarized conversations.
        
        Args:
            topic_id: Description.
            limit: Description.
        """
        c = self.conn.cursor()
        if limit < 0:
            c.execute(
                "SELECT * FROM conversations WHERE topic_id = ? AND is_summarized = 0 "
                "ORDER BY stamp ASC",
                (topic_id,),
            )
        else:
            c.execute(
                "SELECT * FROM conversations WHERE topic_id = ? AND is_summarized = 0 "
                "ORDER BY stamp ASC LIMIT ?",
                (topic_id, limit),
            )
        rows = c.fetchall()
        c.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("rounds_json"):
                try:
                    d["rounds_json_parsed"] = json.loads(d["rounds_json"])
                except (json.JSONDecodeError, TypeError):
                    d["rounds_json_parsed"] = None
            else:
                d["rounds_json_parsed"] = None
            result.append(d)
        return result
