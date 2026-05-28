#!/usr/bin/env python3
"""
Tea Agent TUI -- Textual-based Terminal User Interface.
2026-05-06 gen by claude, TUI entry point alongside CLI/GUI.

Usage:
    python -m tea_agent.tui
    python -m tea_agent.tui --config my_agent.yaml --think --verbose

Keybindings:
    Enter       Send message
    Shift+Enter Newline
    Ctrl+C      Quit
    Esc         Interrupt generation
    Ctrl+T      Toggle Think mode
    Ctrl+V      Toggle Verbose mode
    Ctrl+N      New topic
    Ctrl+L      List topics
"""

import argparse
import sys
import os
import threading
from datetime import datetime
from typing import Optional
import re

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from textual.app import App, ComposeResult
from textual.widgets import Label, RichLog, TextArea
from textual.containers import Container, ScrollableContainer
from textual.binding import Binding
from textual.css.query import NoMatches

from tea_agent.agent_core import AgentCore


class _TUIAgentCore(AgentCore):
    """TUI-specific AgentCore subclass that bridges streaming to Textual UI."""

    def __init__(self, tui: App, config_path: str = None,
                 enable_think: bool = False, verbose: bool = False,
                 disable_summary: bool = False, no_stream_chunk: bool = False):
        self._tui = tui
        self._tui_think = enable_think
        self._tui_verbose = verbose
        super().__init__(config_path=config_path, disable_summary=disable_summary, no_stream_chunk=no_stream_chunk)
        self._cfg.enable_thinking = self._tui_think
        self.sess.enable_thinking = self._tui_think
        self._init_session()
        self.sess.max_iterations = 1000

    def _on_post_reply(self, ai_msg, used_tools, topic_id):
        pass

    def _on_init_done(self):
        pass

    def _chat(self, user_msg: str):
        if not self.current_topic_id:
            self._auto_init_topic()
        tui = self._tui
        reply_chunks = []
        tool_round = [0]
        think_started = False

        def on_stream(chunk: str):
            nonlocal think_started
            if chunk.startswith("[THINK]"):
                text = chunk[7:]
                if text:
                    if not think_started:
                        tui.call_from_thread(tui._append_chat_inline, "[italic]# ")
                        think_started = True
                    tui.call_from_thread(tui._append_chat_inline, text)
                return
            if chunk.startswith("[THINK_DONE]"):
                if think_started:
                    tui.call_from_thread(tui._append_chat_inline, "[/italic]")
                    tui.call_from_thread(tui._flush_stream_buffer)
                    think_started = False
                return
            if chunk.startswith("[TOOL_START:"):
                tool_round[0] += 1
                tool_name = chunk.split(":", 1)[1].rstrip("]")
                if self._tui_verbose:
                    tui.call_from_thread(tui._append_chat, f"Tool [{tool_round[0]}]: {tool_name}")
                else:
                    tui.call_from_thread(tui._append_chat, f"🔧 {tool_name}")
                return
            if chunk.startswith("[TOOL_DONE]"):
                return
            if self._tui_verbose:
                if chunk.startswith("[REPLY]"):
                    text = chunk[7:]
                    reply_chunks.append(text)
                    tui.call_from_thread(tui._append_chat_inline, text)
                elif chunk.startswith("[STATUS:"):
                    status = chunk[8:].rstrip("]")
                    tui.call_from_thread(tui._update_status, status)
                elif not chunk.startswith("["):
                    reply_chunks.append(chunk)
                    tui.call_from_thread(tui._append_chat_inline, chunk)
            else:
                if chunk.startswith("[REPLY]"):
                    text = chunk[7:]
                    reply_chunks.append(text)
                    tui.call_from_thread(tui._append_chat_inline, text)
                elif not chunk.startswith("[") and not chunk.startswith("{"):
                    reply_chunks.append(chunk)
                    tui.call_from_thread(tui._append_chat_inline, chunk)

        def on_status(status_msg: str):
            if status_msg.startswith("!MAX_ITER:"):
                remaining = status_msg.split(":", 2)[1] if ":" in status_msg else "?"
                tui.call_from_thread(
                    tui._append_chat,
                    f"[bold yellow]Max iterations, auto-continue ({remaining} left)[/]"
                )
            else:
                tui.call_from_thread(tui._update_status, status_msg)

        try:
            with self._sess_lock:
                ai_msg, used_tools = self.sess.chat_stream(
                    user_msg, callback=on_stream,
                    topic_id=self.current_topic_id, on_status=on_status,
                )
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            tui.call_from_thread(
                tui._append_chat,
                f"\n[bold red]ERROR: {e}[/]\n```\n{tb[-1500:]}\n```"
            )
            return

        tui.call_from_thread(tui._flush_stream_buffer)
        tui.call_from_thread(tui._append_chat, "")
        if ai_msg:
            self._post_chat_pipeline(
                ai_msg=ai_msg, used_tools=used_tools,
                user_msg=user_msg, topic_id=self.current_topic_id,
            )

    def _auto_init_topic(self):
        topics = self.db.list_topics()
        if topics:
            tp = topics[0]
            self.current_topic_id = tp["topic_id"]
            self._load_topic_history_into_session(tp["topic_id"])
        else:
            self.current_topic_id = self.db.create_topic("TUI Session")
            self.sess.messages = [{"role": "system", "content": self.sess.system_prompt}]
            self.sess._history_summary = ""


class TeaTUI(App):
    """Tea Agent Terminal UI -- Textual-based, alongside CLI and GUI."""

    CSS = """
    Screen {
        background: $surface;
    }

    #header-bar {
        dock: top;
        height: auto;
        padding: 0 1;
        background: $panel;
        border-bottom: solid $primary;
    }

    #header-bar Label {
        padding: 0 1;
    }

    #chat-container {
        height: 1fr;
        border-bottom: solid $primary-darken-2;
    }

    RichLog#chat-area {
        height: 100%;
        overflow-y: auto;
        padding: 0 1;
        background: $surface;
        min-height: 10;
    }

    #input-container {
        dock: bottom;
        height: auto;
        max-height: 12;
        min-height: 3;
        background: $panel;
        border-top: solid $primary;
        padding: 0 1;
    }

    #input-area {
        height: auto;
        min-height: 3;
        max-height: 10;
        border: none;
        background: $panel;
        color: $text;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }

    #status-left {
        width: 1fr;
    }

    #status-right {
        width: auto;
        content-align: right middle;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "interrupt", "Interrupt"),
        Binding("ctrl+t", "toggle_think", "Think"),
        Binding("ctrl+v", "toggle_verbose", "Verbose"),
        Binding("ctrl+n", "new_topic", "NewTopic"),
        Binding("ctrl+l", "list_topics", "ListTopics"),
    ]

    def __init__(self, config_path: str = None, enable_think: bool = False,
                 verbose: bool = False, disable_summary: bool = False,
                 no_stream_chunk: bool = False):
        super().__init__()
        self._config_path = config_path
        self._cli_think = enable_think
        self._cli_verbose = verbose
        self._disable_summary = disable_summary
        self._no_stream_chunk = no_stream_chunk
        self._generating = False
        self._agent_ready = threading.Event()
        self.agent: Optional[_TUIAgentCore] = None
        self._stream_buffer = ""
        self._stream_timer = None
        self._welcome_shown = False

    class _SendTextArea(TextArea):
        """TextArea with Enter=send, Shift+Enter=newline."""

        async def _on_key(self, event):
            """Enter=send, Shift+Enter=newline."""
            if event.key in ("enter", "shift+enter"):
                if event.key == "shift+enter":
                    self.insert("\n")
                else:
                    self.app._do_send()
                event.stop()
                return
            await super()._on_key(event)

    def compose(self) -> ComposeResult:
        with Container(id="header-bar"):
            yield Label("Tea Agent TUI", id="header-title")
            yield Label("", id="header-model")
        with ScrollableContainer(id="chat-container"):
            yield RichLog(id="chat-area", highlight=True, markup=True, wrap=True)
        with Container(id="input-container"):
            yield self._SendTextArea(id="input-area", language=None, show_line_numbers=False)
        with Container(id="status-bar"):
            yield Label("Initializing...", id="status-left")
            yield Label("Think:OFF Verbose:OFF", id="status-right")


    def on_mount(self):
        """On mount — init agent daemon, start ready-check timer, focus input"""
        self._update_status("Initializing Tea Agent...")
        threading.Thread(target=self._init_agent, daemon=True).start()
        self.set_interval(0.5, self._check_agent_ready)
        try:
            self.query_one("#input-area", TextArea).focus()
        except NoMatches:
            pass

    def _init_agent(self):
        try:
            self.agent = _TUIAgentCore(
                tui=self, config_path=self._config_path,
                enable_think=self._cli_think, verbose=self._cli_verbose,
                disable_summary=self._disable_summary,
                no_stream_chunk=self._no_stream_chunk,
            )
            self._agent_ready.set()
        except Exception as e:
            self.call_from_thread(self._show_error, f"Init failed: {e}")

    def _check_agent_ready(self):
        if self._agent_ready.is_set() and not self._welcome_shown:
            self._welcome_shown = True
            self._show_welcome()

    def _show_welcome(self):
        cfg = self.agent._cfg
        model_name = cfg.main_model.model_name
        tool_count = len(self.agent.toolkit.func_map)
        self.query_one("#header-model", Label).update(
            f"Model: {model_name} | Tools: {tool_count}"
        )
        info = self.agent._init_session_info_str()
        self._update_status(info.replace("\\n", " | "))
        self._chat_write("[bold cyan]Tea Agent TUI[/]")
        self._chat_write(f"   Model: {model_name}")
        self._chat_write(f"   Think: [bold]{'ON' if self._cli_think else 'OFF'}[/]  "
                    f"Verbose: [bold]{'ON' if self._cli_verbose else 'OFF'}[/]")
        self._chat_write(f"   Tools: {tool_count} loaded")
        self._chat_write("   Ctrl+C quit | Esc interrupt | Ctrl+T Think | Ctrl+V Verbose")
        self._chat_write("")
        self._update_status_right()
        self.agent._auto_init_topic()

    def _show_error(self, msg: str):
        try:
            self._chat_write(f"[bold red]ERROR: {msg}[/]")
        except NoMatches:
            pass
        self._update_status(f"ERROR: {msg}")

    def _update_status(self, msg: str):
        try:
            self.query_one("#status-left", Label).update(msg[:80])
        except NoMatches:
            pass

    def _update_status_right(self):
        try:
            self.query_one("#status-right", Label).update(
                f"Think:{'ON' if self._cli_think else 'OFF'} "
                f"Verbose:{'ON' if self._cli_verbose else 'OFF'}"
            )
        except NoMatches:
            pass

    def _start_stream_timer(self):
        self._stop_stream_timer()
        self._stream_timer = self.set_interval(0.5, self._flush_stream_buffer)

    def _stop_stream_timer(self):
        if self._stream_timer:
            self._stream_timer.stop()
            self._stream_timer = None

    def on_key(self, event):
        pass

    def _do_send(self):
        if self._generating:
            return
        try:
            input_widget = self.query_one("#input-area", TextArea)
        except NoMatches:
            return
        text = input_widget.text.strip()
        if not text:
            return
        input_widget.clear()
        self._chat_write(f"\n[bold green]You:[/] {text}")
        if text.startswith("/"):
            self._handle_command(text)
            return
        self._generating = True
        self._start_stream_timer()
        self._update_status("Generating...")

        def run_chat():
            try:
                self.agent._chat(text)
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                self.call_from_thread(
                    self._append_chat,
                    f"\n[bold red]ERROR: {e}[/]\n```\n{tb[-1000:]}\n```"
                )
            finally:
                self._generating = False
                self.call_from_thread(self._on_chat_done)

        threading.Thread(target=run_chat, daemon=True).start()

    def _on_chat_done(self):
        self._flush_stream_buffer()
        self._stop_stream_timer()
        try:
            usage = self.agent.sess._last_usage
            if usage and usage.get("total_tokens", 0) > 0:
                self._update_status(
                    f"Done | Tokens: {usage['total_tokens']:,} "
                    f"(P:{usage['prompt_tokens']:,} C:{usage['completion_tokens']:,})"
                )
            else:
                self._update_status("Done")
        except Exception:
            self._update_status("Done")

    def _append_chat(self, text: str):
        try:
            self._chat_write(text)
        except NoMatches:
            pass

    def _chat_write(self, text: str) -> None:
        chat = self.query_one("#chat-area", RichLog)
        chat.write(text)

    def _append_chat_inline(self, text: str):
        self._stream_buffer += text

    def _flush_stream_buffer(self):
        if self._stream_buffer:
            try:
                self._chat_write(self._stream_buffer)
            except NoMatches:
                pass
            self._stream_buffer = ""

    def _handle_command(self, cmd: str):
        parts = cmd.split(None, 1)
        cmd_name = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        chat = self.query_one("#chat-area", RichLog)

        if cmd_name in ("/bye", "/quit", "/exit"):
            self.exit()
        elif cmd_name == "/help":
            self._show_help()
        elif cmd_name == "/set":
            self._cmd_set(arg)
        elif cmd_name == "/think":
            self.action_toggle_think()
        elif cmd_name == "/verbose":
            self.action_toggle_verbose()
        elif cmd_name == "/new":
            self.action_new_topic()
        elif cmd_name == "/list":
            self.action_list_topics()
        elif cmd_name == "/switch":
            self._switch_topic(arg)
        else:
            self._chat_write(f"[bold yellow]Unknown: {cmd_name} (/help for help)[/]")

    def _show_help(self):
        self._chat_write("""
[bold]Tea Agent TUI Help[/]
  /help              Show this help
  /bye, /quit, /exit Quit
  /set think=on|off  Toggle Think mode
  /set verbose=on|off Toggle Verbose mode
  /think             Toggle Think
  /verbose           Toggle Verbose
  /new               New topic
  /list              List recent topics
  /switch <N/id>     Switch by list number or topic id

  Enter     Send    Shift+Enter  Newline
  Ctrl+C    Quit    Esc          Interrupt
  Ctrl+T    Think   Ctrl+V       Verbose
  Ctrl+N    New     Ctrl+L       List
""")

    def _cmd_set(self, arg: str):
        if "=" not in arg:
            self._chat_write("[bold yellow]Usage: /set think=on|off or /set verbose=on|off[/]")
            return
        k, v = arg.split("=", 1)
        k, v = k.strip().lower(), v.strip().lower()
        if k == "think":
            val = v in ("on", "true", "1", "yes")
            self._cli_think = val
            if self.agent:
                self.agent._tui_think = val
                self.agent._cfg.enable_thinking = val
                self.agent.sess.enable_thinking = val
            self._update_status_right()
            self._chat_write(f"[bold]Think = {'ON' if val else 'OFF'}[/]")
        elif k == "verbose":
            val = v in ("on", "true", "1", "yes")
            self._cli_verbose = val
            if self.agent:
                self.agent._tui_verbose = val
            self._update_status_right()
            self._chat_write(f"[bold]Verbose = {'ON' if val else 'OFF'}[/]")
        else:
            self._chat_write(f"[bold yellow]Unknown setting: {k} (think, verbose)[/]")

    def _switch_topic(self, arg: str):
        """
        Switch topic. Supports:
          /switch <N>     — switch by list number (1-based, from /list output)
          /switch <id>    — switch by topic_id prefix
        """
        if not self.agent:
            self._chat_write("[bold red]Agent not ready[/]")
            return
        topics = self.agent.db.list_topics()
        if not topics:
            self._chat_write("[bold yellow]No topics found[/]")
            return
        s = arg.strip()
        # Try numeric index first (1-based, matching /list numbering)
        if s.isdigit():
            idx = int(s) - 1
            if 0 <= idx < len(topics):
                tp = topics[idx]
                self.agent.current_topic_id = tp["topic_id"]
                self.agent._load_topic_history_into_session(tp["topic_id"])
                self._chat_write(
                    f"[bold]Switched to ({idx+1}): {tp.get('title', tp['topic_id'][:8])}[/]"
                )
                return
            else:
                self._chat_write(
                    f"[bold yellow]Invalid number: {s} (1-{len(topics)} available)[/]"
                )
                return
        # Fallback: match by topic_id prefix
        matched = [t for t in topics if t["topic_id"].startswith(s)]
        if len(matched) == 1:
            tp = matched[0]
        elif len(matched) > 1:
            self._chat_write("[bold yellow]Multiple matches, use /list number or more chars[/]")
            return
        else:
            self._chat_write(f"[bold yellow]Topic not found: {s}[/]")
            return
        self.agent.current_topic_id = tp["topic_id"]
        self.agent._load_topic_history_into_session(tp["topic_id"])
        self._chat_write(f"[bold]Switched to: {tp.get('title', tp['topic_id'][:8])}[/]")

    def action_interrupt(self):
        if self._generating and self.agent and self.agent.sess:
            self.agent.sess.interrupt()
            self._append_chat("[bold yellow]Interrupted[/]")
            self._generating = False
            self._update_status("Interrupted")

    def action_toggle_think(self):
        self._cli_think = not self._cli_think
        if self.agent:
            self.agent._tui_think = self._cli_think
            self.agent._cfg.enable_thinking = self._cli_think
            self.agent.sess.enable_thinking = self._cli_think
        self._update_status_right()
        self._append_chat(f"[bold]Think = {'ON' if self._cli_think else 'OFF'}[/]")

    def action_toggle_verbose(self):
        self._cli_verbose = not self._cli_verbose
        if self.agent:
            self.agent._tui_verbose = self._cli_verbose
        self._update_status_right()
        self._append_chat(f"[bold]Verbose = {'ON' if self._cli_verbose else 'OFF'}[/]")

    def action_new_topic(self):
        if not self.agent:
            return
        tid = self.agent.db.create_topic("TUI Session")
        self.agent.current_topic_id = tid
        self.agent.sess.messages = [
            {"role": "system", "content": self.agent.sess.system_prompt}
        ]
        self.agent.sess._history_summary = ""
        self._append_chat(f"[bold]New topic: {tid[:10]}...[/]")

    def action_list_topics(self):
        if not self.agent:
            return
        topics = self.agent.db.list_topics()
        self._chat_write("\n[bold]Recent Topics:[/]")
        for i, t in enumerate(topics[:20]):
            tid = t["topic_id"][:10]
            title = t.get("title", "")[:35]
            stamp = str(t.get("last_update_stamp", ""))[:19]
            mark = " <--" if t["topic_id"] == self.agent.current_topic_id else ""
            self._chat_write(f"  {i+1}. `{tid}` {title} {stamp}{mark}")


def main():
    parser = argparse.ArgumentParser(
        description="Tea Agent TUI -- Terminal AI Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tea_agent.tui
  python -m tea_agent.tui --config my_agent.yaml --think
  python -m tea_agent.tui --verbose --think
        """,
    )
    parser.add_argument("--config", type=str, default=None,
                        help="Config file path (auto-detect by default)")
    parser.add_argument("--think", action="store_true", default=False,
                        help="Enable thinking mode")
    parser.add_argument("--verbose", action="store_true", default=False,
                        help="Show tool call intermediate rounds")
    parser.add_argument("--disable_summary", action="store_true", default=False,
                        help="Disable history compression and summary")
    parser.add_argument("--no_stream_chunk", action="store_true", default=False,
                        help="Non-streaming mode, easier for step debugging")
    args = parser.parse_args()
    app = TeaTUI(
        config_path=args.config, enable_think=args.think,
        verbose=args.verbose, disable_summary=args.disable_summary,
        no_stream_chunk=args.no_stream_chunk,
    )
    app.run()


if __name__ == "__main__":
    main()
