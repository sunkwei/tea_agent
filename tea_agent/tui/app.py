# -*- coding: utf-8 -*-
"""Tea Agent TUI - Terminal User Interface powered by Textual."""

from __future__ import annotations

import os, sys, asyncio, threading
from pathlib import Path
from typing import Optional

_parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from textual.app import App, ComposeResult, Binding
from textual.widgets import Footer, Input
from textual.containers import Container

from tea_agent.agent_core import AgentCore
from tea_agent.tui.widgets.chat import ChatLog
from tea_agent.tui.widgets.input import CommandInput
from tea_agent.tui.widgets.header import HeaderBar
from tea_agent.tui.widgets.sidebar import Sidebar

import logging
logger = logging.getLogger("tea_tui")


class TeaTUI(App):
    """Tea Agent Terminal User Interface."""

    CSS = """
    TeaTUI { background: $surface; }
    Container { height: 1fr; }
    Footer { background: $panel; }
    """

    BINDINGS = [
        Binding("ctrl+s", "toggle_sidebar", "Sidebar", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+c", "interrupt", "Interrupt", show=True),
        Binding("ctrl+l", "clear_screen", "Clear", show=True),
    ]

    def __init__(self, debug: bool = False, config_path: Optional[str] = None):
        super().__init__()
        self._debug = debug
        self._config_path = config_path
        self._agent: Optional[AgentCore] = None
        self._generating: bool = False
        self._sidebar_visible: bool = False

    def on_mount(self) -> None:
        try:
            self._agent = AgentCore(debug=self._debug, config_path=self._config_path)
        except Exception as e:
            self.query_one(ChatLog).add_error_message(f"Failed to init: {e}")
            return
        agent = self._agent
        topics = agent.db.list_topics()
        if topics:
            agent.current_topic_id = topics[0]["topic_id"]
            agent._load_topic_history_into_session(agent.current_topic_id)
        else:
            agent._new_topic()
        self._refresh_header()
        self._refresh_sidebar()
        chat = self.query_one(ChatLog)
        chat.add_system_message(f"Connected | Model: {agent._cfg.main_model.model_name} | {len(agent.toolkit.func_map)} tools")
        chat.add_system_message("Type /help for commands")

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Container():
            yield ChatLog()
            yield Sidebar()
        yield CommandInput()
        yield Footer()

    def action_toggle_sidebar(self):
        sidebar = self.query_one(Sidebar)
        sidebar.toggle()
        self._sidebar_visible = sidebar.has_class("visible")
        if self._sidebar_visible:
            self._refresh_sidebar()

    def action_interrupt(self):
        if self._agent and self._agent.sess:
            self._agent.sess.interrupt()
            self._generating = False
            self.query_one(ChatLog).add_system_message("Interrupted.")

    def action_clear_screen(self):
        self.query_one(ChatLog).clear()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
        else:
            self._handle_chat(text)

    def _handle_chat(self, text: str):
        if not self._agent:
            return
        if self._generating:
            self.query_one(ChatLog).add_system_message("Already generating. Ctrl+C to interrupt.")
            return
        chat = self.query_one(ChatLog)
        agent = self._agent
        chat.add_user_message(text)
        chat.begin_stream()
        self._generating = True
        chunk_queue = []
        result_holder = {}
        error_holder = {}

        def stream_cb(chunk: str):
            if chunk.startswith("[THINK]"):
                chunk = chunk[7:]
            chunk_queue.append(chunk)
            try:
                loop = asyncio.get_event_loop()
                loop.call_soon_threadsafe(self._flush_chunks, chunk_queue, chat)
            except RuntimeError:
                pass

        def status_cb(status_msg: str):
            if status_msg.startswith("!MAX_ITER:"):
                display = status_msg.replace("!MAX_ITER:", "")
                try:
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(
                        lambda: chat.add_system_message(f"{display}.Auto-continuing...")
                    )
                except RuntimeError:
                    pass
                agent.sess._continue_after_max = True
                agent.sess._extra_iterations += 10
                agent.sess._max_iter_wait.set()

        def run_chat():
            try:
                ai_msg, used_tools = agent.sess.chat_stream(
                    text, callback=stream_cb,
                    topic_id=agent.current_topic_id,
                    on_status=status_cb,
                )
                result_holder["ai_msg"] = ai_msg
                result_holder["used_tools"] = used_tools
            except Exception as e:
                error_holder["error"] = str(e)
            finally:
                try:
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(
                        self._finish_chat, chunk_queue, chat,
                        result_holder, error_holder, agent, text
                    )
                except RuntimeError:
                    pass

        t = threading.Thread(target=run_chat, daemon=True)
        t.start()

    def _flush_chunks(self, queue: list, chat: ChatLog):
        while queue:
            chunk = queue.pop(0)
            chat.append_stream(chunk)

    def _finish_chat(self, queue: list, chat: ChatLog,
                     result: dict, error: dict,
                     agent: AgentCore, user_msg: str):
        self._flush_chunks(queue, chat)
        chat.end_stream()
        self._generating = False
        if error:
            chat.add_error_message(f"Error: {error['error']}")
            return
        ai_msg = result.get("ai_msg", "")
        used_tools = result.get("used_tools", False)
        try:
            agent._post_chat_pipeline(ai_msg, used_tools, user_msg, agent.current_topic_id)
        except Exception as e:
            logger.warning(f"Post-chat error: {e}")
        self._refresh_header()
        self._refresh_sidebar()

    def _handle_command(self, raw: str):
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        chat = self.query_one(ChatLog)
        agent = self._agent

        if cmd == "/help":
            chat.add_system_message("""Commands:
/new - New topic
/topics - List topics
/switch <id> - Switch topic
/memories - Show memories
/status - Show status
/clear - Clear chat
/exit, /quit - Quit

Keys: Ctrl+S=Sidebar Ctrl+C=Interrupt Ctrl+L=Clear Ctrl+Q=Quit""")
        elif cmd == "/new":
            if agent:
                tid = agent._new_topic()
                self._refresh_header()
                chat.add_system_message(f"New topic [{tid}]")
        elif cmd == "/topics":
            if agent:
                topics = agent.db.list_topics()
                if not topics:
                    chat.add_system_message("(no topics)")
                else:
                    lines = ["Topics:"]
                    for tp in topics:
                        tid = tp["topic_id"]
                        title = (tp.get("title", "") or "?")[:40]
                        mark = " <=" if tid == agent.current_topic_id else ""
                        lines.append(f"  [{tid}] {title}{mark}")
                    chat.add_system_message("\n".join(lines))
        elif cmd == "/switch":
            if agent:
                try:
                    tid = int(arg)
                    tp = agent.db.get_topic(tid)
                    if not tp:
                        chat.add_system_message(f"Topic [{tid}] not found")
                    else:
                        agent.current_topic_id = tid
                        agent.sess.clear_history()
                        agent._load_topic_history_into_session(tid)
                        chat.clear()
                        chat.add_system_message(f"Switched to [{tid}]: {tp.get('title','')}")
                        self._refresh_header()
                except ValueError:
                    chat.add_system_message("Usage: /switch <id>")
        elif cmd == "/memories":
            if agent:
                memories = agent.db.get_active_memories(limit=20)
                if not memories:
                    chat.add_system_message("(no memories)")
                else:
                    labels = {0: "!!!", 1: "!", 2: "*", 3: "-"}
                    lines = ["Memories:"]
                    for m in memories:
                        pri = labels.get(m.get("priority", 2), "?")
                        cat = m.get("category", "general")
                        content = (m.get("content", "") or "")[:80]
                        lines.append(f"  [{m['id']}] {pri} [{cat}] {content}")
                    chat.add_system_message("\n".join(lines))
        elif cmd == "/status":
            if agent:
                tp = agent.db.get_topic(agent.current_topic_id)
                ts = agent.db.get_topic_tokens(agent.current_topic_id)
                mem = len(agent.db.get_active_memories(50))
                lines = [
                    f"Model: {agent._cfg.main_model.model_name}",
                    f"Topic: [{agent.current_topic_id}] {tp.get('title','?') if tp else '?'}",
                    f"Tools: {len(agent.toolkit.func_map)} loaded",
                    f"Memories: {mem} active",
                ]
                if ts:
                    t = ts.get("total_tokens", 0)
                    p = ts.get("total_prompt_tokens", 0)
                    c = ts.get("total_completion_tokens", 0)
                    lines.append(f"Tokens: {t:,} (P:{p:,} C:{c:,})")
                chat.add_system_message("\n".join(lines))
        elif cmd == "/clear":
            chat.clear()
        elif cmd in ("/exit", "/quit", "/q"):
            self.exit()
        else:
            chat.add_system_message(f"Unknown: {cmd}. /help for help.")

    def _refresh_header(self):
        if not self._agent:
            return
        agent = self._agent
        ts = agent.db.get_topic_tokens(agent.current_topic_id)
        header = self.query_one(HeaderBar)
        header.update_status(
            model=agent._cfg.main_model.model_name,
            tokens=f"Tokens: {ts.get('total_tokens', 0):,}" if ts else "Tokens: 0",
            topic=f"Topic [{agent.current_topic_id}]",
            tools=f"{len(agent.toolkit.func_map)} tools",
        )

    def _refresh_sidebar(self):
        if not self._agent:
            return
        agent = self._agent
        tp = agent.db.get_topic(agent.current_topic_id)
        ts = agent.db.get_topic_tokens(agent.current_topic_id)
        mem = len(agent.db.get_active_memories(50))
        sidebar = self.query_one(Sidebar)
        sidebar.update(
            model=agent._cfg.main_model.model_name,
            tools=str(len(agent.toolkit.func_map)),
            topic=f"[{agent.current_topic_id}] {(tp.get('title','?') or '?')[:20] if tp else '?'}",
            tokens=f"{ts.get('total_tokens', 0):,}" if ts else "0",
            memories=str(mem),
        )


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Tea Agent TUI")
    ap.add_argument("--debug", action="store_true", help="Debug mode")
    ap.add_argument("--config", type=str, default=None, help="Config path")
    args = ap.parse_args()
    app = TeaTUI(debug=args.debug, config_path=args.config)
    app.run()


if __name__ == "__main__":
    main()
