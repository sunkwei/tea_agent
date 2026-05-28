"""
从 gui.py L1258-1519 提取：主题列表、切换、加载、回调
"""

import tkinter as tk
import threading
import json as _json_um
import logging
from datetime import datetime
from typing import Optional, Dict, List, cast

if __import__('typing').TYPE_CHECKING:
    from tea_agent.gui import TkGUI

logger = logging.getLogger("main_db_gui")

class TopicManager:
    """主题列表管理：创建、切换、加载、刷新"""

    def __init__(self, gui):
        """Initialize  .
        
        Args:
            gui: Description.
        """
        self.gui = gui

    def clear_chat(self):
        """Clear chat."""
        gui = self.gui
        gui.console.config(state=tk.NORMAL)
        gui.console.delete("1.0", tk.END)
        gui.console.config(state=tk.DISABLED)
        gui.chat_messages.clear()
        gui._stream_buffer = ""
        gui._think_buffer = ""
        gui._pending_console_text.clear()
        gui._pending_images.clear()
        gui._img_label.config(text="")
        gui._clear_img_btn.pack_forget()

    def auto_new_topic(self):
        """Auto new topic."""
        gui = self.gui
        topics = gui.db.list_topics()
        if topics:
            children = gui.topic_list.get_children()
            if children:
                gui.topic_list.selection_set(children[0])
            # 直接 switch_topic，不依赖 on_topic_select。
            # 原因：refresh_topics() 已将 current_topic_id 设为第一个活跃主题的 ID，
            # 若走 on_topic_select 会因为 ID 相同被短路跳过，导致 HtmlFrame 不显示、历史不加载。
            first_topic_id = topics[0]["topic_id"]
            gui.switch_topic(first_topic_id)
        else:
            gui.new_topic()

    def new_topic(self):
        """New topic."""
        gui = self.gui
        title = f"主题 {datetime.now().strftime('%m-%d %H:%M:%S')}"
        tid = gui.db.create_topic(title)
        gui.current_topic_id = tid
        gui.refresh_topics()
        gui.switch_topic(tid)

    def refresh_topics(self):
        """Refresh topics."""
        gui = self.gui
        for item in gui.topic_list.get_children():
            gui.topic_list.delete(item)
        all_topics = gui.db.list_topics()
        topics = [tp for tp in all_topics if tp.get("is_active", 1)]
        gui._topic_cache = all_topics  # 缓存全部供 tooltip 使用
        current_tid = getattr(gui, 'current_topic_id', None)
        # 如果当前主题被停用，自动切到第一个活跃主题
        if not any(tp.get("topic_id") == current_tid for tp in topics):
            if topics:
                current_tid = topics[0].get("topic_id")
                gui.current_topic_id = current_tid
        highlight_iid = ""
        for i, tp in enumerate(topics):
            title = tp.get("title", "")
            display = title[:20] if len(title) > 20 else title
            iid = str(i)
            gui.topic_list.insert("", tk.END, iid=iid, text=display, tags=("topic_item",))
            if tp.get("topic_id") == current_tid:
                highlight_iid = iid
        if topics:
            gui.topic_list.selection_set(highlight_iid)
            gui.topic_list.see(highlight_iid)
    def _update_title(self, topic_title=""):
        """Internal: update title.
        
        Args:
            topic_title: Description.
        """
        gui = self.gui
        cwd = getattr(gui, "_initial_cwd", "")
        if topic_title:
            gui.root.title(f"AI助手 - {topic_title} - cwd {cwd}")
        else:
            gui.root.title(f"AI助手 - cwd {cwd}")

    def switch_topic(self, topic_id):
        """Switch topic.
        
        Args:
            topic_id: Description.
        """
        gui = self.gui
        gui.current_topic_id = topic_id
        try:
            tp = gui.db.get_topic(topic_id)
            title = (tp or {}).get("title", "")
            self._update_title(title)
        except Exception:
            self._update_title()
        self.clear_chat()
        # 加载期间阻塞输入
        gui.generating = True
        gui._show_loading("正在加载历史记录")
        gui._update_status("⏳ 加载中...")
        gui._progress_queue = []
        gui._poll_loading_progress()

        recent_turns = 10

        def load_worker():
            """后台线程：DB 查询 + JSON 解析 + 构建渲染列表"""
            try:
                topic = cast(dict, gui.db.get_topic(topic_id))
                ts = gui.db.get_topic_tokens(topic_id)

                all_light = gui.db.get_conversations(topic_id, limit=-1, include_rounds=False)
                total_convs = len(all_light)
                old_count = max(0, total_convs - recent_turns)

                if total_convs > 0:
                    recent_full = gui.db.get_conversations(topic_id, limit=recent_turns, include_rounds=True)
                    offset = total_convs - min(total_convs, recent_turns)
                    for i in range(offset, total_convs):
                        j = i - offset
                        if j < len(recent_full):
                            all_light[i] = recent_full[j]

                summary = gui.db.get_topic_summary(topic_id) or ""

                gui.sess.load_history(all_light, summary, recent_turns=recent_turns)

                render_items = []
                render_items.append(("title", f"📌 当前主题：{topic['title']}"))
                render_items.append(("notice", "-" * 50))

                total_tokens = ts.get("total_tokens", 0)
                if total_tokens > 0:
                    render_items.append(("notice",
                        f"📊 Token 消耗: {total_tokens:,} "
                        f"(prompt: {ts.get('total_prompt_tokens', 0):,}, "
                        f"completion: {ts.get('total_completion_tokens', 0):,})"))
                    render_items.append(("notice", ""))

                if summary:
                    render_items.append(("notice", f"📖 历史摘要：{summary}"))
                    render_items.append(("notice", "-" * 50))

                if old_count > 0:
                    render_items.append(("notice",
                        f"📖 最近 {recent_turns} 轮显示完整对话，更早的 {old_count} 轮仅显示问答"))
                    render_items.append(("notice", ""))

                for i, c in enumerate(all_light):
                    gui._progress_queue.append((i + 1, total_convs))

                    is_old = i < old_count
                    raw_user_msg = c['user_msg']
                    user_images = []
                    user_text = raw_user_msg
                    if raw_user_msg and raw_user_msg.startswith('{'):
                        try:
                            parsed = _json_um.loads(raw_user_msg)
                            if isinstance(parsed, dict):
                                user_text = parsed.get("text", raw_user_msg)
                                user_images = parsed.get("images", [])
                        except Exception:
                            pass
                    render_items.append(("user", f"你：{user_text}", user_images))

                    if is_old:
                        render_items.append(("ai", f"AI：{c['ai_msg']}"))
                    else:
                        rounds = c.get("rounds_json_parsed")
                        tool_names = []
                        if rounds and c.get("is_func_calling"):
                            for rd in rounds:
                                rd_role = rd.get("role", "")
                                if rd_role == "assistant" and rd.get("tool_calls"):
                                    for tc in rd["tool_calls"]:
                                        fn_name = tc.get("function", {}).get("name", "unknown")
                                        fn_args = tc.get("function", {}).get("arguments", "")
                                        if fn_name not in tool_names:
                                            tool_names.append(fn_name)
                                        import json as _json_tc2
                                        try:
                                            args_dict = _json_tc2.loads(fn_args) if fn_args else {}
                                            args_lines = []
                                            for k, v in args_dict.items():
                                                v_str = _json_tc2.dumps(v, ensure_ascii=False)
                                                if len(v_str) > 160:
                                                    v_str = v_str[:160] + "..."
                                                args_lines.append(f"    {k}: {v_str}")
                                            args_block = "\n".join(args_lines)
                                            render_items.append(("tool", f"🔧 调用工具：{fn_name}\n参数：\n{args_block}"))
                                        except Exception:
                                            render_items.append(("tool", f"🔧 调用工具：{fn_name}\n参数：\n    {fn_args[:200]}"))
                                    if rd.get("content"):
                                        render_items.append(("ai", f"AI：{rd['content']}"))
                                elif rd_role == "tool":
                                    result_preview = rd.get("content", "")
                                    if len(result_preview) > 200:
                                        result_preview = result_preview[:200] + "..."
                                    render_items.append(("tool", f"📋 结果：{result_preview}"))
                                elif rd_role == "assistant" and rd.get("content"):
                                    render_items.append(("ai", f"AI：{rd['content']}"))
                        else:
                            render_items.append(("ai", f"AI：{c['ai_msg']}"))

                        if c["is_func_calling"]:
                            if tool_names:
                                render_items.append(("tool", f"ℹ️ 工具：{', '.join(tool_names)}"))
                            else:
                                render_items.append(("tool", "ℹ️ 本条使用了工具调用"))
                    render_items.append(("notice", ""))

                gui._pending_render = render_items
                gui._loading_done = True
            except Exception as e:
                gui._pending_error = str(e)
                gui._loading_done = True

        gui.root.after(60, lambda: threading.Thread(target=load_worker, daemon=True).start())

    def on_topic_select(self, e):
        """Handle topic select event.
        
        Args:
            e: Description.
        """
        gui = self.gui
        sel = gui.topic_list.selection()
        if not sel:
            return
        idx = gui.topic_list.index(sel[0])
        # 使用活跃主题列表（与 refresh_topics 过滤一致），避免停用主题导致索引错位
        active_topics = [tp for tp in gui.db.list_topics() if tp.get("is_active", 1)]
        if idx >= len(active_topics):
            return
        tp = active_topics[idx]
        if tp["topic_id"] == gui.current_topic_id:
            return
        gui.switch_topic(tp["topic_id"])

    def newline(self, e=None):
        """Newline.
        
        Args:
            e: Description.
        """
        self.gui.input_box.insert(tk.INSERT, "\n")
        return "break"

    def _suggest_new_topic_if_needed(self, topic_id: str):
        """Internal: suggest new topic if needed.
        
        Args:
            topic_id: Description.
        """
        gui = self.gui
        count = getattr(gui, '_pending_topic_suggestion', 0)
        if count > 0:
            gui.root.after(100, lambda c=count: gui._update_status(
                f"💡 已切换 {c} 次方向，建议「➕ 新建主题」保持聚焦"
            ))
            gui._pending_topic_suggestion = 0

    def _on_summary_updated(self, topic_id: str, summary: str):
        """摘要更新后刷新 GUI 主题列表和状态栏。"""
        gui = self.gui
        gui.root.after(200, self._refresh_topics_preserve_selection)
        gui.root.after(100, lambda s=summary: gui._update_status(f"📝 摘要: {s}"))

    def _refresh_topics_preserve_selection(self):
        """刷新主题列表，refresh_topics() 已按 current_topic_id 自动高亮。"""
        self.refresh_topics()

    def _on_topic_hover(self, event):
        """鼠标在主题列表上移动时，延迟显示 tooltip"""
        gui = self.gui
        item_id = gui.topic_list.identify_row(event.y)
        idx = gui.topic_list.index(item_id) if item_id else -1
        if idx < 0 or idx >= len(gui._topic_cache):
            self._hide_tooltip()
            return
        if gui._topic_hover_after:
            gui.root.after_cancel(gui._topic_hover_after)
            gui._topic_hover_after = None
        gui._topic_hover_after = gui.root.after(
            300, lambda: self._show_tooltip(event, idx)
        )

    def _on_topic_leave(self, event):
        """鼠标离开列表时隐藏 tooltip"""
        gui = self.gui
        if gui._topic_hover_after:
            gui.root.after_cancel(gui._topic_hover_after)
            gui._topic_hover_after = None
        self._hide_tooltip()

    def _show_tooltip(self, event, idx):
        """在鼠标位置显示主题日期 tooltip"""
        gui = self.gui
        if idx < 0 or idx >= len(gui._topic_cache):
            return
        from tea_agent._gui._fonts import _fs, SYSTEM_FONT
        tp = gui._topic_cache[idx]
        create_ts = tp.get("create_stamp", "")
        update_ts = tp.get("last_update_stamp", "")
        def fmt(ts):
            """Fmt.
            
            Args:
                ts: Description.
            """
            if not ts:
                return "未知"
            s = str(ts)
            return s[:16] if len(s) >= 16 else s
        self._hide_tooltip()
        tip = tk.Toplevel(gui.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg="#ffffcc")
        lines = [f"📅 创建: {fmt(create_ts)}", f"🕐 最后使用: {fmt(update_ts)}"]
        tip_text = "\n".join(lines)
        label = tk.Label(
            tip, text=tip_text,
            bg="#ffffcc", fg="#333333",
            font=(SYSTEM_FONT, _fs(10)),
            padx=8, pady=4,
            relief=tk.SOLID, borderwidth=1,
        )
        label.pack()
        x = gui.root.winfo_pointerx() + 12
        y = gui.root.winfo_pointery() + 8
        tip.geometry(f"+{x}+{y}")
        gui._topic_tooltip = tip

    def _hide_tooltip(self):
        """隐藏 tooltip"""
        gui = self.gui
        if gui._topic_tooltip:
            try:
                gui._topic_tooltip.destroy()
            except Exception:
                pass
            gui._topic_tooltip = None
