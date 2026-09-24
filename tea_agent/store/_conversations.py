"""
"""
import json
import logging

from ._component import StoreComponent
from ._images import ImageStoreMixin
from ._sql_safety import safe_placeholders, safe_where_clause

logger = logging.getLogger("Storage.Conversations")

class ConversationStore(ImageStoreMixin, StoreComponent):
    """对话管理：保存消息、更新轮次、查询对话历史、Agent 轮次记录。

    图片存取（``images`` 表）由 ``ImageStoreMixin`` 提供 —— 与对话强耦合
    （``create_turn`` 需把入参图片归属到新会话），故用 mixin 而非独立组件。
    """

    # ── 回合生命周期（append-only）────────────────────────────────
    #
    # 回合开始 → create_turn   （建 pending 行，事件从此有 conversation_id 可挂）
    # 回合进行 → append_round  （工具轮实时落盘，崩溃不丢）
    # 回合结束 → finalize_turn （补 ai_msg + 状态，兜底补齐漏写的轮次）
    #
    # 此前只有"回合结束一次性写一条 conversation + 批量写 agent_rounds"，
    # 导致：① 回合中的工具/增量事件无归属（实测 tool/call 的 conversation_id
    # 100% 为 NULL）；② 崩溃即丢整轮明细。

    @staticmethod
    def _split_user_msg(user_msg) -> tuple[str, str]:
        """把 user_msg 拆成 ``(json 文本, 纯文本)``。"""
        if isinstance(user_msg, dict):
            return json.dumps(user_msg, ensure_ascii=False), user_msg.get("text", "")
        return str(user_msg), str(user_msg)

    def create_turn(self, topic_id: str, user_msg, status: str = "pending") -> str:
        """回合**开始**即创建 conversation 行，返回 conversation_id。

        为什么必须提前建行：回合进行中的工具调用与助手增量事件都需要
        ``conversation_id`` 才能归属到具体轮次。此前该 id 由回合结束时的
        ``save_msg`` 生成，于是工具类事件的 conversation_id **100% 为 NULL**
        （实测 404 条 tool/call 全部无归属），轮次级审计形同虚设。

        Args:
            topic_id: 主题 ID。
            user_msg: 用户消息（str 或 {"text","images"}）。
            status: 初始状态（默认 pending=进行中）。

        Returns:
            conversation_id
        """
        conv_id = self._new_id()

        if isinstance(user_msg, dict) and "images" in user_msg:
            user_msg["images"] = self._store_images(conv_id, user_msg.get("images") or [])

        user_msg_json, user_msg_text = self._split_user_msg(user_msg)

        c = self.conn.cursor()
        c.execute(
            "INSERT INTO conversations "
            "(id, topic_id, user_msg, ai_msg, is_func_calling, status, stamp) "
            "VALUES (?, ?, ?, '', 0, ?, datetime('now', 'localtime'))",
            (conv_id, topic_id, user_msg_json, status),
        )
        self.conn.commit()
        c.close()

        # P2 事件溯源：turn/start + user/message（审计事实源）
        self._log_event(topic_id, "turn/start", {}, conversation_id=conv_id)
        self._log_event(topic_id, "user/message",
                        {"content": user_msg_text, "raw": user_msg_json},
                        conversation_id=conv_id)
        return conv_id

    def save_msg(self, topic_id: str, user_msg, ai_msg: str, is_func: bool,
                 update_active_cb=None) -> str:
        """一次性写入完整对话（``create_turn`` + 定稿的便捷封装，兼容旧调用方）。

        Args:
            topic_id: 主题 ID。
            user_msg: 用户消息（str 或 {"text","images"}）。
            ai_msg: 助手回复。
            is_func: 是否使用了工具调用。
            update_active_cb: 更新主题活跃时间的回调（异常隔离）。

        Returns:
            conversation_id
        """
        conv_id = self.create_turn(topic_id, user_msg, status="done")
        c = self.conn.cursor()
        c.execute(
            "UPDATE conversations SET ai_msg = ?, is_func_calling = ? WHERE id = ?",
            (ai_msg, 1 if is_func else 0, conv_id),
        )
        self.conn.commit()
        c.close()

        if update_active_cb:
            # 回调异常隔离：用户回调抛异常不影响保存主流程
            try:
                update_active_cb(topic_id)
            except Exception:
                logger.exception("update_active_cb failed (isolated)")
        return conv_id

    def append_round(self, conversation_id: str, round_num: int, role: str,
                     content: str = "", tool_calls=None, tool_call_id=None,
                     reasoning_content: str = "") -> bool:
        """实时追加单轮明细（append-only，幂等）。

        ``reasoning_content`` 独立成列：此前它被拼进 content 的 ``[思考] `` 前缀，
        无法还原为结构化 rounds（DeepSeek thinking 模式要求 RC 原样回传）。

        Args:
            conversation_id: 所属对话。
            round_num: 轮次序号（对话内递增，用于幂等去重）。
            role: assistant / tool / user。
            content: 文本内容。
            tool_calls: 工具调用列表（assistant 轮）。
            tool_call_id: 工具结果对应的调用 id（tool 轮）。
            reasoning_content: 思考内容（assistant 轮）。

        Returns:
            True=已写入；False=已存在同 round_num（幂等跳过）或参数非法。
        """
        if not conversation_id:
            return False
        tc_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
        c = self.conn.cursor()
        try:
            # 幂等键 = (round_num, role, tool_call_id)：round_num 单独不足以定位一行 ——
            # 既有 API 允许同一 round_num 存在多行（如 assistant + 其 tool 结果）。
            c.execute(
                "SELECT 1 FROM agent_rounds WHERE conversation_id = ? AND round_num = ? "
                "AND role = ? AND COALESCE(tool_call_id, '') = ? LIMIT 1",
                (conversation_id, int(round_num), role or "", tool_call_id or ""),
            )
            if c.fetchone():
                return False
            c.execute(
                "INSERT INTO agent_rounds "
                "(id, conversation_id, round_num, role, content, tool_calls, "
                " tool_call_id, reasoning_content, stamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                (self._new_id(), conversation_id, int(round_num), role, content or "",
                 tc_json, tool_call_id, reasoning_content or ""),
            )
            self.conn.commit()
            return True
        finally:
            c.close()

    def _write_rounds(self, conversation_id: str, rounds: list) -> int:
        """幂等批量写入 rounds（单事务；已存在的 round_num 跳过）。返回新增条数。

        用 executemany 而非逐条 append_round：真实会话单轮可达 5815 个轮次，
        逐条 commit 会让回合收尾耗时不可接受。
        """
        if not rounds:
            return 0
        c = self.conn.cursor()
        try:
            c.execute(
                "SELECT round_num, role, COALESCE(tool_call_id, '') FROM agent_rounds "
                "WHERE conversation_id = ?",
                (conversation_id,),
            )
            existing = {(int(x[0]), x[1] or "", x[2] or "") for x in c.fetchall()}
            rows = []
            for i, r in enumerate(rounds):
                if not isinstance(r, dict):
                    continue
                # 幂等键与 append_round 一致（round_num 单独不足以定位一行）
                if (i, r.get("role", "") or "", r.get("tool_call_id") or "") in existing:
                    continue
                tc = r.get("tool_calls")
                rows.append((
                    self._new_id(), conversation_id, i, r.get("role", ""),
                    r.get("content", "") or "",
                    json.dumps(tc, ensure_ascii=False) if tc else None,
                    r.get("tool_call_id"),
                    r.get("reasoning_content", "") or "",
                ))
            if not rows:
                return 0
            c.executemany(
                "INSERT INTO agent_rounds "
                "(id, conversation_id, round_num, role, content, tool_calls, "
                " tool_call_id, reasoning_content, stamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                rows,
            )
            self.conn.commit()
            return len(rows)
        finally:
            c.close()

    def finalize_turn(self, conversation_id: str, ai_msg: str,
                      is_func_calling: bool = False,
                      rounds: list | None = None,
                      status: str = "done") -> bool:
        """回合结束：补齐 ai_msg / 状态，并兜底写入尚未落盘的轮次。

        ``rounds`` 若已在回合中经 ``append_round`` 实时落盘，此处按 round_num
        幂等跳过（重试/恢复场景下同一轮可能被重复提交）。

        Args:
            conversation_id: 对话 ID。
            ai_msg: 助手最终回复。
            is_func_calling: 是否使用了工具调用。
            rounds: 完整轮次列表（兜底补齐用，可为 None）。
            status: 终态（done / error / interrupted）。

        Returns:
            是否更新成功。
        """
        if not conversation_id:
            return False
        try:
            self._write_rounds(conversation_id, rounds or [])
            c = self.conn.cursor()
            c.execute(
                "UPDATE conversations SET ai_msg = ?, is_func_calling = ?, status = ? "
                "WHERE id = ?",
                (ai_msg or "", 1 if is_func_calling else 0, status, conversation_id),
            )
            self.conn.commit()
            c.close()
        except Exception:
            logger.exception("finalize_turn failed")
            return False

        # P2 事件溯源：assistant/message（含 tool_calls 概览）+ turn/end
        try:
            topic_id = self._topic_of_conv(conversation_id)
            if topic_id:
                tool_calls_summary = None
                if rounds:
                    tcs = [r.get("tool_calls") for r in rounds
                           if isinstance(r, dict) and r.get("tool_calls")]
                    if tcs:
                        tool_calls_summary = [
                            {"name": tc.get("function", {}).get("name", ""),
                             "arguments": tc.get("function", {}).get("arguments", "")}
                            for tc_list in tcs
                            for tc in (tc_list if isinstance(tc_list, list) else [tc_list])
                        ][:20]
                self._log_event(topic_id, "assistant/message",
                                {"content": ai_msg or "", "tool_calls": tool_calls_summary},
                                conversation_id=conversation_id)
                self._log_event(topic_id, "turn/end",
                                {"reason": status}, conversation_id=conversation_id)
        except Exception:
            logger.exception("append assistant event failed (isolated)")
        return True

    def _topic_of_conv(self, conversation_id: str) -> str:
        """查询会话所属 topic（事件日志关联用）。"""
        try:
            c = self.conn.cursor()
            c.execute("SELECT topic_id FROM conversations WHERE id = ?", (conversation_id,))
            row = c.fetchone()
            c.close()
            return row["topic_id"] if row else ""
        except Exception:
            return ""

    def _log_event(self, topic_id: str, event_type: str, payload: dict,
                   conversation_id: str = "") -> None:
        """P2 事件溯源：追加事件日志（失败仅告警，不影响主流程）。"""
        try:
            self.events.append_event(topic_id, event_type, payload, conversation_id)
        except Exception:
            logger.exception("append event failed (isolated)")

    def update_msg_rounds(
        self, conversation_id: int, ai_msg: str, is_func_calling: bool,
        rounds: list[dict] | None = None,
    ):
        """Update msg rounds and persist individual rounds to agent_rounds table.

        Saves the full rounds as JSON in conversations.rounds_json (L0),
        and also writes each individual round to agent_rounds table (L1)
        for SQL-based tool calling analysis and benchmarking.

        Args:
            conversation_id: conversation id.
            ai_msg: AI message text.
            is_func_calling: whether tool calling was used.
            rounds: list of round dicts with role/content/tool_calls.
        """
        # rounds_json 已废弃：它与 agent_rounds 重复存储（实测占库 38.4%，
        # 单轮最大 8.79 MB），且写入前需把全部轮次 json.dumps 一次。
        # 统一走 finalize_turn：幂等补齐轮次 + 补 ai_msg/状态 + 事件溯源。
        self.finalize_turn(conversation_id, ai_msg,
                           is_func_calling=is_func_calling, rounds=rounds)

    def save_agent_round(
        self, conversation_id: int, round_num: int, role: str, content: str,
        tool_calls: list[dict] | None = None, tool_call_id: str | None = None,
    ):
        """写入单轮明细（薄封装，幂等）。

        Args:
            conversation_id: 所属对话。
            round_num: 轮次序号。
            role: 角色。
            content: 文本内容。
            tool_calls: 工具调用列表。
            tool_call_id: 工具结果对应的调用 id。
        """
        self.append_round(conversation_id, round_num, role, content,
                          tool_calls=tool_calls, tool_call_id=tool_call_id)

    def get_rounds(self, conversation_id: str) -> list[dict]:
        """从 ``agent_rounds`` 派生结构化轮次（唯一事实源）。

        替代已废弃的 ``conversations.rounds_json``：同一份内容此前存两处
        （实测重复 30 MB），现在只留本表，按需派生。

        ``reasoning_content`` 来自独立列（此前被拼进 content 的 ``[思考] `` 前缀，
        导致无法还原结构 —— DeepSeek thinking 模式要求 RC 原样回传）。

        Args:
            conversation_id: 对话 ID。

        Returns:
            轮次列表（按 round_num 升序），元素形如
            ``{"role","content","tool_calls","tool_call_id","reasoning_content"}``；
            与旧 ``rounds_json`` 结构兼容（可直接喂给 load_history）。
        """
        if not conversation_id:
            return []
        c = self.conn.cursor()
        c.execute(
            "SELECT round_num, role, content, tool_calls, tool_call_id, reasoning_content "
            "FROM agent_rounds WHERE conversation_id = ? AND deleted_at IS NULL "
            "ORDER BY round_num ASC, rowid ASC",
            (conversation_id,),
        )
        rows = c.fetchall()
        c.close()
        out: list[dict] = []
        for r in rows:
            entry: dict = {"role": r["role"], "content": r["content"] or ""}
            if r["tool_calls"]:
                try:
                    entry["tool_calls"] = json.loads(r["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    # 损坏的 tool_calls：降级为空（该轮仍可读），但**留痕** ——
                    # 静默 pass 会让数据损坏永远不可见（且触碰 except:pass 基线）
                    logger.debug(
                        "round %s 的 tool_calls 不是合法 JSON，已降级为空",
                        r["id"], exc_info=True,
                    )
            if r["tool_call_id"]:
                entry["tool_call_id"] = r["tool_call_id"]
            rc = r["reasoning_content"]
            if rc:
                entry["reasoning_content"] = rc
            out.append(entry)
        return out

    def get_conversations(self, topic_id: str, limit: int = 5, include_rounds: bool = True) -> list[dict]:
        """读取主题下的对话轮次（按时间升序）。

        已标记删除的轮次不出现在结果里（append-only：行仍在库中，仅带 deleted_at）。

        Args:
            topic_id: 主题 ID。
            limit: 上限（<=0 表示不限；>0 取最后 limit 条）。
            include_rounds: 是否附带 ``rounds_json_parsed``。

        Returns:
            对话 dict 列表。
        """
        c = self.conn.cursor()
        if include_rounds:
            c.execute(
                "SELECT * FROM conversations WHERE topic_id = ? AND deleted_at IS NULL "
                "ORDER BY stamp ASC", (topic_id,)
            )
        else:
            c.execute(
                "SELECT id, topic_id, user_msg, ai_msg, is_func_calling, is_summarized, stamp "
                "FROM conversations WHERE topic_id = ? AND deleted_at IS NULL ORDER BY stamp ASC",
                (topic_id,)
            )
        rows = c.fetchall()
        c.close()

        # limit <= 0 表示不限制，limit > 0 则截取最后 limit 条
        if limit > 0 and len(rows) > limit:
            rows = rows[-limit:]
        result = []
        for r in rows:
            d = dict(r)
            if include_rounds:
                # 从 agent_rounds 派生（唯一事实源）。rounds_json 列已废弃 ——
                # 它与本表重复存储（实测 30 MB / 占库 38%，单轮最大 8.79 MB）。
                d["rounds_json_parsed"] = self.get_rounds(d["id"]) or None
            result.append(d)
        return result

    def get_recent_conversations(self, topic_id: str, limit: int = 3) -> list[dict]:
        """Get the recent conversations.

        Args:
            topic_id: Description.
            limit: Description.
        """
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM conversations WHERE topic_id = ? ORDER BY stamp DESC LIMIT ?",
            (topic_id, limit),
        )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in reversed(rows)]

    def get_agent_rounds(self, conversation_id: str) -> list[dict]:
        """获取对话的 agent rounds（按插入顺序）。

        排序必须用 ``rowid``（插入序）而非 ``id``：``id`` 是 UUID，按它排序
        得到的是**随机顺序**。旧实现之所以看起来正常，是因为其 INSERT 未写
        ``id``（留 NULL）—— 一旦补上 UUID 就会错乱（实测 test_save_agent_round
        断言 assistant 在前，实际取到 tool）。
        """
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM agent_rounds WHERE conversation_id = ? AND deleted_at IS NULL "
            "ORDER BY rowid ASC",
            (conversation_id,),
        )
        rows = c.fetchall()
        c.close()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("tool_calls"):
                d["tool_calls"] = json.loads(d["tool_calls"])
            result.append(d)
        return result

    # ── 全文搜索（FTS5 fallback LIKE）──

    def search_conversations(self, query: str, limit: int = 30,
                              include_ai: bool = True, include_rounds: bool = True,
                              date_from: str = "", date_to: str = "") -> list[dict]:
        """跨主题全文搜索对话内容。

        同时搜索 user_msg、ai_msg 和 agent_rounds.content，
        结果按相关度排序，附带主题标题和上下文片段。

        Args:
            query: 搜索关键词。
            limit: 返回结果上限。
            include_ai: 是否搜索 ai_msg 字段。
            include_rounds: 是否搜索 agent_rounds 内容。
            date_from: 起始日期 YYYY-MM-DD（可选）。
            date_to: 结束日期 YYYY-MM-DD（可选）。

        Returns:
            搜索结果列表：conversation_id, topic_id, topic_title,
            user_msg, ai_msg, snippet, rank_score, stamp
        """
        if not query or not query.strip():
            return []

        q = query.strip()
        like_pat = f"%{q}%"
        conditions = ["c.user_msg LIKE ?"]
        params = [like_pat]

        if include_ai:
            conditions.append("c.ai_msg LIKE ?")
            params.append(like_pat)

        if date_from:
            conditions.append("c.stamp >= ?")
            params.append(f"{date_from} 00:00:00")
        if date_to:
            conditions.append("c.stamp <= ?")
            params.append(f"{date_to} 23:59:59")

        where = safe_where_clause(conditions, joiner=" OR ", wrap=True)

        sql = f'''
            SELECT c.id as conversation_id, c.topic_id, t.title as topic_title,
                   c.user_msg, c.ai_msg, c.stamp
            FROM conversations c
            JOIN topics t ON c.topic_id = t.topic_id
            WHERE ({where})
            ORDER BY c.stamp DESC
            LIMIT ?
        '''
        params.append(limit)

        c = self.conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall()
        conv_results = [dict(r) for r in rows]

        # 如果也搜索 agent_rounds，补充查询
        if include_rounds:
            rc = self.conn.cursor()
            rc.execute('''
                SELECT DISTINCT r.conversation_id
                FROM agent_rounds r
                WHERE r.content LIKE ?
            ''', (like_pat,))
            round_conv_ids = {row["conversation_id"] for row in rc.fetchall()}
            rc.close()

            if round_conv_ids:
                existing_ids = {r["conversation_id"] for r in conv_results}
                missing_ids = round_conv_ids - existing_ids
                if missing_ids:
                    placeholders = safe_placeholders(len(missing_ids))
                    rc2 = self.conn.cursor()
                    rc2.execute(f'''
                        SELECT c.id as conversation_id, c.topic_id, t.title as topic_title,
                               c.user_msg, c.ai_msg, c.stamp
                        FROM conversations c
                        JOIN topics t ON c.topic_id = t.topic_id
                        WHERE c.id IN ({placeholders})
                    ''', list(missing_ids))
                    conv_results.extend(dict(r) for r in rc2.fetchall())
                    rc2.close()

        c.close()

        # 计算排序分数
        q_lower = q.lower()
        for r in conv_results:
            score = 0
            user_msg = r.get("user_msg", "") or ""
            ai_msg = r.get("ai_msg", "") or ""
            for field in [user_msg, ai_msg]:
                field_lower = field.lower()
                count = field_lower.count(q_lower)
                score += count * 10
                if field_lower.startswith(q_lower):
                    score += 50
                if field_lower == q_lower:
                    score += 200
            r["rank_score"] = score
            r["snippet"] = self._make_snippet(user_msg + " " + ai_msg, q)

        conv_results.sort(key=lambda x: x["rank_score"], reverse=True)
        return conv_results

    @staticmethod
    def _make_snippet(text: str, query: str, context_chars: int = 60) -> str:
        """从文本中提取包含关键词的上下文片段。"""
        if not text:
            return ""
        q_lower = query.lower()
        text_lower = text.lower()
        idx = text_lower.find(q_lower)
        if idx < 0:
            return text[:context_chars * 2] + ("..." if len(text) > context_chars * 2 else "")
        start = max(0, idx - context_chars)
        end = min(len(text), idx + len(query) + context_chars)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        snippet = snippet.replace("\n", " ").replace("\r", " ").strip()
        return snippet

    # ── Session Fork（分支实验，借鉴 DeepSeek Harness） ──

    def fork_topic(self, source_topic_id: str, target_topic_id: str,
                   title: str = "", boundary_conv_id: str = "") -> dict:
        """将源 topic 的全部对话复制到目标 topic（session fork）。

        分支语义：
        - 复制 conversations 记录，新记录标记 fork_source_id=源会话ID
        - 复制 agent_rounds（对话轮次细节）
        - 记录 forks 元数据（源→目标 lineage）
        - 目标 topic 需已存在（由调用方通过 topics.create_topic 创建）

        Args:
            source_topic_id: 源主题
            target_topic_id: 目标主题（需已存在）
            title: 目标主题标题（仅记录用）
            boundary_conv_id: 边界会话 ID；非空时仅复制该会话之前的对话

        Returns:
            {"ok": bool, "copied": int, "source": str, "target": str,
             "boundary": str, "error": str}
        """
        import uuid as _uuid

        # ── S3 幂等守卫：禁止重复 fork（同一 source→target） ──
        dup = self.conn.execute(
            "SELECT 1 FROM forks WHERE source_topic_id = ? AND target_topic_id = ? LIMIT 1",
            (source_topic_id, target_topic_id),
        ).fetchone()
        if dup:
            return {"ok": False, "copied": 0, "source": source_topic_id,
                    "target": target_topic_id, "boundary": boundary_conv_id,
                    "error": "该分支已存在（禁止重复 fork，请换 target_topic_id 或复用现有分支）"}

        copied = 0
        # ── S2 事务包裹：全部 INSERT 在单事务内，异常自动 rollback，杜绝半 fork ──
        with self._get_connection() as _tx:
            c = _tx.cursor()
            if boundary_conv_id:
                # 用 rowid（插入顺序）精确定位边界，避免随机 UUID 字符串比较失真
                c.execute("SELECT rowid FROM conversations WHERE id = ?", (boundary_conv_id,))
                brow = c.fetchone()
                if brow:
                    boundary_rowid = brow["rowid"]
                    c.execute(
                        "SELECT id, topic_id, user_msg, ai_msg, is_func_calling, is_summarized, "
                        "stamp, rounds_json FROM conversations "
                        "WHERE topic_id = ? AND rowid <= ? ORDER BY rowid ASC",
                        (source_topic_id, boundary_rowid),
                    )
                else:
                    # 边界会话不存在 → 全量复制
                    c.execute(
                        "SELECT id, topic_id, user_msg, ai_msg, is_func_calling, is_summarized, "
                        "stamp, rounds_json FROM conversations "
                        "WHERE topic_id = ? ORDER BY rowid ASC",
                        (source_topic_id,),
                    )
            else:
                c.execute(
                    "SELECT id, topic_id, user_msg, ai_msg, is_func_calling, is_summarized, "
                    "stamp, rounds_json FROM conversations "
                    "WHERE topic_id = ? ORDER BY rowid ASC",
                    (source_topic_id,),
                )
            rows = c.fetchall()
            if not rows:
                return {"ok": True, "copied": 0, "source": source_topic_id,
                        "target": target_topic_id, "boundary": boundary_conv_id, "error": ""}

            # 记录旧 id → 新 id 映射（用于 agent_rounds 外键迁移）
            id_map: dict[str, str] = {}
            for r in rows:
                new_id = _uuid.uuid4().hex
                id_map[r["id"]] = new_id
                c.execute(
                    "INSERT INTO conversations (id, topic_id, user_msg, ai_msg, "
                    "is_func_calling, is_summarized, stamp, rounds_json, "
                    "fork_source_id, fork_stamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                    (new_id, target_topic_id, r["user_msg"], r["ai_msg"],
                     r["is_func_calling"], r["is_summarized"], r["stamp"],
                     r["rounds_json"], r["id"]),
                )
                copied += 1

            # 复制 agent_rounds（保持轮次细节）
            round_copied = 0
            for old_id, new_id in id_map.items():
                c.execute(
                    "SELECT round_num, role, content, tool_calls, tool_call_id, stamp "
                    "FROM agent_rounds WHERE conversation_id = ? "
                    "ORDER BY round_num, rowid",
                    (old_id,),
                )
                for rr in c.fetchall():
                    rid = _uuid.uuid4().hex
                    c.execute(
                        "INSERT INTO agent_rounds (id, conversation_id, round_num, role, "
                        "content, tool_calls, tool_call_id, stamp) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (rid, new_id, rr["round_num"], rr["role"], rr["content"],
                         rr["tool_calls"], rr["tool_call_id"], rr["stamp"]),
                    )
                    round_copied += 1

            # 记录 fork 元数据
            fork_id = _uuid.uuid4().hex
            c.execute(
                "INSERT INTO forks (id, source_topic_id, target_topic_id, "
                "boundary_conv_id, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now', 'localtime'))",
                (fork_id, source_topic_id, target_topic_id, boundary_conv_id or None),
            )
            # 事务提交在 with 块退出时自动 commit；异常自动 rollback

        logger.info(
            f"fork_topic: {source_topic_id} → {target_topic_id} "
            f"(conversations={copied}, rounds={round_copied})"
        )
        return {"ok": True, "copied": copied, "rounds_copied": round_copied,
                "source": source_topic_id, "target": target_topic_id,
                "boundary": boundary_conv_id, "error": ""}

    def get_fork_lineage(self, topic_id: str, limit: int = 10) -> list[dict]:
        """查询 topic 的 fork 血统（被谁 fork / 从谁 fork）。

        返回按时间倒序的 fork 记录列表。
        """
        c = self.conn.cursor()
        c.execute(
            "SELECT id, source_topic_id, target_topic_id, boundary_conv_id, created_at "
            "FROM forks WHERE source_topic_id = ? OR target_topic_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (topic_id, topic_id, limit),
        )
        rows = c.fetchall()
        c.close()
        return [dict(r) for r in rows]
