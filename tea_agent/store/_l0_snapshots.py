"""L0 富化系统提示词快照存储（严格审计补口）。

从 ``_conversations.py`` 拆分出来的独立 mixin（2026-09-25）：
新增本功能后该文件由 712 行涨到 942 行，越过 800 行阈值，触发
EvolutionBench 的 ``big_files`` 棘轮（23 → 24）。拆出来既消除该回归，
也与本包既有的组件化结构一致（``_component`` / ``_images`` / ``_events``
/ ``_interruptions`` / ``_tool_usage`` / ``_summaries`` …）。

背景：发给模型的 system 消息并非裸 ``system_prompt``，而是
``_build_l0_enriched_system()`` 运行时**合成**的结果（OS 信息 / AGENTS.md /
context_fragments / 小模型约束）。该合成结果此前从不落盘 → 历史任一回合都
无法复原「它当时看到的 L0」，因为配置与 AGENTS.md 早已变化。这是 L0-L3
提取里唯一完全缺失的一层。

写入时机 = 回合**首次**构建 API 消息时（见 ``session/history_builder`` 接线）。
工具循环内每轮都会重新构建，故必须幂等：靠 ``conversations.l0_recorded``
做「一次性」闸门，避免把同一份大文本重复写 N 遍。
"""

import hashlib
import logging

logger = logging.getLogger("Storage.Conversations")


def l0_content_hash(content: str) -> str:
    """L0 富化系统提示词的内容地址（纯函数，无 IO）。

    抽成模块级纯函数而非内联到写入路径：hash 是 ``l0_snapshots`` 的主键，
    也是「两个回合看到的是否同一份 L0」的唯一判据，必须可被单测确定性
    覆盖（不依赖 DB、不依赖会话状态）。

    用完整 sha256 十六进制（64 字符）而非截断：该值同时承担审计时的
    完整性比对职责，截断会把碰撞概率从密码学级别拉到生日悖论级别。

    Args:
        content: L0 富化系统提示词全文。

    Returns:
        64 字符的 sha256 十六进制摘要；content 为空时返回空串。
    """
    if not content:
        return ""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class L0SnapshotStoreMixin:
    """L0 快照读写（内容寻址 + 回合起始值不可覆盖）。

    依赖宿主类提供 ``self.conn``（``StoreComponent`` 的线程本地连接）。
    """

    def record_l0_snapshot(self, conversation_id: str, content: str) -> str:
        """记录本回合的 L0 富化系统提示词（内容寻址 + 一次性，幂等）。

        语义是「该回合**开始时**模型看到的 L0」：
        - 同一 conversation_id 只写第一次，后续调用直接返回已记录的 hash
          （工具循环内 build_api_messages 会被调 N 次，必须幂等）；
        - 内容是**快照**而非引用 —— 即便后续 AGENTS.md/配置变化，历史仍可读。

        fail-open：任何异常只记日志并返回空串，绝不把主对话流程带崩
        （与 append_round 等旁路写入的既有约定一致）。

        Args:
            conversation_id: 回合 ID。
            content: L0 富化系统提示词全文。

        Returns:
            写入（或已存在）的内容 hash；未写入时为空串。
        """
        if not conversation_id:
            return ""
        h = l0_content_hash(content)
        if not h:
            return ""
        try:
            c = self.conn.cursor()
            try:
                row = c.execute(
                    "SELECT l0_hash, l0_recorded FROM conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
                if row is None:
                    # conversation 行尚不存在（如非 Web 路径未提前建行）：
                    # 不隐式建行 —— 那会与 create_turn 的生命周期语义冲突。
                    logger.debug("record_l0_snapshot: 回合 %s 不存在，跳过", conversation_id)
                    return ""
                existing_hash = row["l0_hash"] or ""
                recorded = row["l0_recorded"] or 0
                if recorded:
                    # 已记录过：返回既有 hash（不重写，保证「回合开始那份」不被覆盖）
                    return existing_hash
                # 内容寻址：同一份 L0 只存一列（同 topic 内逐字节稳定，去重率高）
                c.execute(
                    "INSERT OR IGNORE INTO l0_snapshots "
                    "(hash, content, chars, first_topic_id, first_conversation_id) "
                    "VALUES (?, ?, ?, "
                    " (SELECT topic_id FROM conversations WHERE id = ?), ?)",
                    (h, content, len(content), conversation_id, conversation_id),
                )
                c.execute(
                    "UPDATE conversations SET l0_hash = ?, l0_recorded = 1 WHERE id = ?",
                    (h, conversation_id),
                )
                self.conn.commit()
                return h
            finally:
                c.close()
        except Exception:
            # fail-open：审计旁路失败绝不影响主流程
            logger.debug("record_l0_snapshot failed (isolated)", exc_info=True)
            return ""

    def get_l0_snapshot(self, conversation_id: str) -> dict | None:
        """读取某回合的 L0 快照。

        Args:
            conversation_id: 回合 ID。

        Returns:
            ``{"hash","content","chars","created_at","recorded"}``；
            回合不存在或未记录 L0 时返回 None。
            注意区分「未记录」（返回 None）与「记录了但内容为空」（content=""）。
        """
        if not conversation_id:
            return None
        try:
            c = self.conn.cursor()
            try:
                row = c.execute(
                    "SELECT l0_hash, l0_recorded FROM conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
                if row is None:
                    return None
                # ⚠️ 直接按列名取值，**不要**写 `"l0_hash" in row`：
                # sqlite3.Row 的 `in` 是**值**语义而非键语义（实测
                # `"l0_hash" in row` 恒为 False，即使该列存在）。误用它会让
                # recorded 恒读成 0，从而「回合起始 L0 不可覆盖」的守卫永不生效。
                h = row["l0_hash"] or ""
                recorded = row["l0_recorded"] or 0
                if not recorded and not h:
                    return None
                if not h:
                    # 标记为已记录但无 hash（当时 L0 为空）
                    return {"hash": "", "content": "", "chars": 0,
                            "created_at": "", "recorded": 1}
                snap = c.execute(
                    "SELECT hash, content, chars, created_at FROM l0_snapshots WHERE hash = ?",
                    (h,),
                ).fetchone()
                if snap is None:
                    # 有指针但内容缺失（快照表被清理/跨库搬迁）——留痕而非静默
                    logger.debug(
                        "get_l0_snapshot: hash %s 在 l0_snapshots 中缺失（conv=%s）",
                        h[:12], conversation_id,
                    )
                    return {"hash": h, "content": "", "chars": 0,
                            "created_at": "", "recorded": 1, "missing": True}
                return {
                    "hash": snap["hash"],
                    "content": snap["content"] or "",
                    "chars": snap["chars"] or 0,
                    "created_at": str(snap["created_at"] or ""),
                    "recorded": 1,
                }
            finally:
                c.close()
        except Exception:
            logger.debug("get_l0_snapshot failed (isolated)", exc_info=True)
            return None

    def conversation_exists(self, conversation_id: str) -> bool:
        """判断回合是否存在（含已软删除的行）。

        存在的理由：``get_l0_snapshot`` 对「回合不存在」与「回合存在但未记录
        L0」都返回 None —— 对写入路径这是合理的（二者都表示"取不到"），
        但审计读取时二者含义完全不同：前者说明**问错了 ID**，后者说明
        **该回合早于功能上线**。若不加区分，审计报告会把"ID 打错"误述成
        "这是历史回合"，属静默误导。

        Args:
            conversation_id: 回合 ID。

        Returns:
            是否存在该 conversation 行。
        """
        if not conversation_id:
            return False
        try:
            c = self.conn.cursor()
            try:
                row = c.execute(
                    "SELECT 1 FROM conversations WHERE id = ? LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                return row is not None
            finally:
                c.close()
        except Exception:
            logger.debug("conversation_exists failed (isolated)", exc_info=True)
            return False

    def list_l0_snapshots(self, topic_id: str = "", limit: int = 50) -> list[dict]:
        """列出 L0 快照（可按 topic 过滤），供审计比对版本差异。

        Args:
            topic_id: 主题 ID（空=全部）。
            limit: 上限（<=0 表示不限）。

        Returns:
            快照 dict 列表（含 hash/chars/created_at/first_conversation_id）。
        """
        try:
            c = self.conn.cursor()
            try:
                sql = ("SELECT hash, chars, first_topic_id, first_conversation_id, created_at "
                       "FROM l0_snapshots")
                params: tuple = ()
                if topic_id:
                    sql += " WHERE first_topic_id = ?"
                    params = (topic_id,)
                sql += " ORDER BY created_at DESC" + (" LIMIT ?" if limit > 0 else "")
                if limit > 0:
                    params = params + (limit,)
                return [dict(r) for r in c.execute(sql, params).fetchall()]
            finally:
                c.close()
        except Exception:
            logger.debug("list_l0_snapshots failed (isolated)", exc_info=True)
            return []
