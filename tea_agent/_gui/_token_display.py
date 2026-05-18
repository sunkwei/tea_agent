"""
@2026-07-07 gen by tea_agent, Token 消耗显示模块
从 gui.py L1788-1847 提取：_add_token_notice_and_render — Markdown 表格显示本轮/主题累积 token
"""

import logging

if __import__('typing').TYPE_CHECKING:
    from tea_agent.gui import TkGUI

logger = logging.getLogger("main_db_gui")


class TokenDisplay:
    """Token 消耗表格渲染：本轮/主题累积 × 主模型/便宜模型/嵌入模型"""

    def __init__(self, gui):
        self.gui = gui

    def add_token_notice_and_render(self, usage: dict, cheap_usage: dict = None):
        """在聊天消息中追加 Markdown 表格：本轮/主题累积 × 主模型/便宜模型/嵌入模型 token 消耗"""
        gui = self.gui
        if cheap_usage is None:
            cheap_usage = {}
        # 本轮：主模型
        m_total = usage.get("total_tokens", 0)
        m_p = usage.get("prompt_tokens", 0)
        m_c = usage.get("completion_tokens", 0)
        # 本轮：便宜模型
        c_total = cheap_usage.get("total_tokens", 0)
        c_p = cheap_usage.get("prompt_tokens", 0)
        c_c = cheap_usage.get("completion_tokens", 0)
        # 嵌入模型 token 用量
        e_total = 0
        e_p = 0
        try:
            from tea_agent.embedding_util import get_embedding_engine
            emb_engine = get_embedding_engine()
            emb_usage = emb_engine.get_embedding_usage(reset=False)
            e_total = emb_usage.get("total_tokens", 0)
            e_p = emb_usage.get("prompt_tokens", 0)
        except Exception:
            pass
        # 主题累积
        try:
            ts = gui.db.get_topic_tokens(gui.current_topic_id)
            tm_total = ts.get("total_tokens", 0)
            tm_p = ts.get("total_prompt_tokens", 0)
            tm_c = ts.get("total_completion_tokens", 0)
            tc_total = ts.get("total_cheap_tokens", 0)
            tc_p = ts.get("total_cheap_prompt_tokens", 0)
            tc_c = ts.get("total_cheap_completion_tokens", 0)
            te_total = ts.get("total_embedding_tokens", 0)
            te_p = ts.get("total_embedding_prompt_tokens", 0)
        except Exception:
            tm_total = tm_p = tm_c = tc_total = tc_p = tc_c = te_total = te_p = 0

        def _cell(val, detail_p=None, detail_c=None):
            """格式化为 'total (P:x C:y)' 或 'total (P:x)' 或 '—'"""
            if val <= 0:
                return "—"
            if detail_p is not None and detail_c is not None:
                return f"{val:,} (P:{detail_p:,} C:{detail_c:,})"
            if detail_p is not None:
                return f"{val:,} (P:{detail_p:,})"
            return f"{val:,}"

        lines = [
            "| | 主模型 | 便宜模型 | 嵌入模型 |",
            "|-------|--------|----------|----------|",
            f"| 本轮 | {_cell(m_total, m_p, m_c)} | {_cell(c_total, c_p, c_c)} | {_cell(e_total, e_p)} |",
            f"| 主题 | {_cell(tm_total, tm_p, tm_c)} | {_cell(tc_total, tc_p, tc_c)} | {_cell(te_total, te_p)} |",
        ]
        token_msg = "\n".join(lines)
        gui.chat_messages.append({"role": "notice", "content": token_msg, "timestamp": gui._now_ts()})
        gui._render_and_show_chat()
        gui._show_raw_check_btn()