"""图片存储能力（mixin）—— ``images`` 表 BLOB 为唯一事实源。

从 ``_conversations.py`` 拆出（该文件因图片能力一度达 897 行，越过
 ``evo_bench`` 的 800 行阈值 → ``hard-bigfile-ratchet`` 失败）。

为何用 mixin 而非独立 StoreComponent：

- 图片与对话**强耦合** —— ``ConversationStore.create_turn`` 必须把入参里的
  图片归属到新会话（``_store_images``）。独立组件会引入组件间互相引用；
  项目里 ``events`` 用过注入（``self._conversations.events = self._events``），
  但那要 ``try/except`` 兜底且失败即静默降级。
- mixin 让「图片是对话存储的一项能力」直接体现在类型上，且 ``Storage``
  既有的 48 个显式委托（``self._conversations.get_image``）**一行都不用改**。

依赖宿主类提供 ``self.conn``（``StoreComponent`` 的线程本地连接）。
"""

from __future__ import annotations

import logging
import os
import sqlite3

from tea_agent.image_ref import (
    MIME_BY_EXT,
    make_image_ref,
    parse_data_url,
    parse_image_ref,
)

from ._sql_safety import safe_placeholders

logger = logging.getLogger("Storage.Conversations")


class ImageStoreMixin:
    """``images`` 表的读写：入库 / 归属 / 孤儿清理 / 回读。

    宿主类须为 ``StoreComponent`` 子类（提供 ``self.conn``）。
    """

    def _store_images(self, conv_id: str, items: list) -> list[str]:
        """把图片二进制写入 ``images`` 表，返回轻量引用列表。

        接受三种入参，逐项失败隔离（单项异常只保留原值并告警，不拖垮对话保存）：
        - data URL（``data:image/png;base64,...``）→ 解码入库（Web/API 主路径）
        - 文件路径 → 读文件入库（旧调用方兼容）
        - ``img:<id>`` 引用 / http(s) 外链 → 原样保留（幂等，重复保存不重复入库）

        Args:
            conv_id: 所属对话 ID。
            items: 图片入参列表。

        Returns:
            引用列表（解析失败项原样回填，保证不静默丢数据）。
        """
        refs: list[str] = []
        for item in items:
            if not isinstance(item, str) or not item:
                continue
            if parse_image_ref(item) is not None or item.startswith(("http://", "https://")):
                # 引用：把「回合开始即入库」的图片补上本会话归属（幂等）
                self._adopt_image(item, conv_id)
                refs.append(item)
                continue
            try:
                if item.startswith("data:"):
                    mime, blob = parse_data_url(item)
                    if not blob:
                        refs.append(item)  # 解析失败：保留原值，不丢数据
                        continue
                else:
                    if not os.path.isfile(item):
                        refs.append(item)  # 未知形态（外链/占位符）：保留原值
                        continue
                    with open(item, "rb") as f:
                        blob = f.read()
                    mime = MIME_BY_EXT.get(os.path.splitext(item)[1].lower(), "image/png")
                refs.append(make_image_ref(self._insert_image(conv_id, blob, mime)))
            except Exception:
                logger.exception("store image failed (isolated)")
                refs.append(item)
        return refs

    def _insert_image(self, conv_id: str, blob: bytes, mime: str) -> int:
        """写入一张图片，返回 ``images.id``。"""
        c = self.conn.cursor()
        try:
            c.execute(
                "INSERT INTO images (conversation_id, image_blob, mime_type) VALUES (?, ?, ?)",
                (conv_id, sqlite3.Binary(blob), mime or "image/png"),
            )
            self.conn.commit()
            return int(c.lastrowid or 0)
        finally:
            c.close()

    def add_pending_image(self, blob: bytes, mime: str = "image/png") -> int:
        """回合**开始**即入库（``conversation_id=''`` 暂未归属），返回 ``images.id``。

        这是「输入不丢失」的关键：回合进行中该提问尚未写库（``save_msg`` 在回合
        结束时才调用），若图片也只活在内存里，用户切走再切回就无从恢复 ——
        实测表现为「切回后看不到刚发的图」。先入库拿到 id，快照即可只携带
        ``img:<id>`` 短引用（而非会被 ``_shrink`` 截断成损坏值的超长 data URL）。

        归属由回合结束时的 ``save_msg`` 补上（见 ``_adopt_image``）。
        """
        return self._insert_image("", blob, mime)

    def _adopt_image(self, ref, conv_id: str) -> None:
        """把「尚未归属」的图片补上本会话归属（幂等）。

        只更新 ``conversation_id=''`` 的行：已归属的图片保持不变，否则重复保存
        同一引用会把它从原会话抢走（历史轮引用会因此指向错误会话）。
        """
        img_id = parse_image_ref(ref)
        if not img_id:
            return
        try:
            c = self.conn.cursor()
            c.execute(
                "UPDATE images SET conversation_id = ? "
                "WHERE id = ? AND conversation_id = '' AND deleted_at IS NULL",
                (conv_id, img_id),
            )
            self.conn.commit()
            c.close()
        except Exception:
            logger.exception("adopt image failed (isolated)")

    def cleanup_orphan_images(self, keep_ids=None) -> int:
        """标记删除「回合未完成即中断」遗留的未归属图片，返回标记条数。

        append-only 语义：只写 ``deleted_at``，不物理删除（行仍在库中，可审计）。

        ``keep_ids`` 必须传入**被在途快照引用的图片 id** —— 那些图片同样是
        ``conversation_id=''``（回合没走完就没归属），却是恢复中的回合要显示的
        内容；无条件标记删除会让「切回可见」当场失效（比占几 MB 磁盘严重得多）。

        Args:
            keep_ids: 需要保留的图片 id 集合（通常取自在途快照）。

        Returns:
            实际标记条数。
        """
        keep = sorted({int(i) for i in (keep_ids or []) if i})
        c = self.conn.cursor()
        try:
            now = "datetime('now', 'localtime')"
            base = f"UPDATE images SET deleted_at = {now} WHERE conversation_id = '' AND deleted_at IS NULL"
            if keep:
                # 上限 500：在途回合数量有限，避免触及 SQLite 变量数上限
                keep = keep[:500]
                ph = safe_placeholders(len(keep))
                c.execute(f"{base} AND id NOT IN ({ph})", keep)
            else:
                c.execute(base)
            n = int(c.rowcount or 0)
            self.conn.commit()
            return n
        finally:
            c.close()

    def get_images(self, conversation_ids: list[str]) -> dict[str, list[dict]]:
        """批量读取多轮对话的图片（导出/回读用）。

        Args:
            conversation_ids: 对话 ID 列表。

        Returns:
            ``{conversation_id: [{"id","mime_type","blob"}, ...]}``，按 id 升序。
            未命中或无图的对话不出现在结果里。
        """
        ids = [str(c) for c in (conversation_ids or []) if c]
        if not ids:
            return {}
        grouped: dict[str, list[dict]] = {}
        c = self.conn.cursor()
        try:
            # 分批查询，避免 SQLite 变量数上限（默认 999）
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                ph = safe_placeholders(len(chunk))
                c.execute(
                    f"SELECT id, conversation_id, image_blob, mime_type FROM images "
                    f"WHERE conversation_id IN ({ph}) AND deleted_at IS NULL ORDER BY id ASC",
                    chunk,
                )
                for row in c.fetchall():
                    grouped.setdefault(row["conversation_id"], []).append({
                        "id": row["id"],
                        "mime_type": row["mime_type"] or "image/png",
                        "blob": bytes(row["image_blob"] or b""),
                    })
        finally:
            c.close()
        return grouped

    def get_image(self, image_id: int) -> dict | None:
        """读取单张图片（HTTP 回读接口用）。

        Args:
            image_id: ``images.id``。

        Returns:
            ``{"id","conversation_id","mime_type","blob"}``；不存在返回 ``None``。
        """
        if not image_id:
            return None
        c = self.conn.cursor()
        try:
            c.execute(
                "SELECT id, conversation_id, image_blob, mime_type FROM images "
                "WHERE id = ? AND deleted_at IS NULL",
                (int(image_id),),
            )
            row = c.fetchone()
        finally:
            c.close()
        if not row:
            return None
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "mime_type": row["mime_type"] or "image/png",
            "blob": bytes(row["image_blob"] or b""),
        }
