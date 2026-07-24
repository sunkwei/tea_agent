#!/usr/bin/env python3
"""
Tea Agent TUI -- 增强版 Terminal User Interface (Textual-based).
借鉴 opencode/codex CLI 的操作模式和数据呈现模式。

特性：
  - 状态栏实时显示 model/token/cost/status
  - 彩色语法高亮的 Markdown 渲染
  - 工具调用链可视化
  - 思考过程渲染（thinking blocks）
  - 历史消息导航
  - 成本跟踪

用法:
    python -m tea_agent.tui
    python -m tea_agent.tui --config my_agent.yaml --think --verbose

快捷键:
    Enter       Send message
    Shift+Enter Newline
    Up/Down     History (when input empty)
    Ctrl+C      Quit
    Esc         Interrupt generation
    Ctrl+T      Toggle Think mode
    Ctrl+V      Toggle Verbose mode
    Ctrl+N      New topic
    Ctrl+L      List topics
    Ctrl+Up     Previous history message
    Ctrl+Down   Next history message
    Ctrl+K      Clear screen
"""

import argparse
import logging
import os
import sys
import threading
import time

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import contextlib

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, RichLog, TextArea

from tea_agent import Agent

logger = logging.getLogger("tui")


# ───────────────────────────────────────────
# 扩展 Agent 子类
# ───────────────────────────────────────────

class _TUIAgentCore(Agent):
    """TUI-specific Agent subclass that bridges streaming to Textual UI.

    增强功能：
    - 实时 token 消耗追踪
    - 工具调用链可视化数据收集
    """

    def __init__(self, tui: App, config_path: str = None,
                 enable_think: bool = False, verbose: bool = False,
                 disable_summary: bool = False, no_stream_chunk: bool = False):
        self._tui = tui
        self._tui_think = enable_think
        self._tui_verbose = verbose
        self._pending_cheap_tokens = {}
        super().__init__(mode="full", config_path=config_path,
                         disable_summary=disable_summary, no_stream_chunk=no_stream_chunk)
        self._cfg.enable_thinking = self._tui_think
        self.sess.enable_thinking = self._tui_think
        self.sess.max_iterations = 1000

    def _on_post_reply(self, ai_msg, used_tools, topic_id):
        """AI 回复后的回调钩子。"""
        pass

    def _on_init_done(self):
        """Agent 初始化完成后的回调钩子。"""
        pass

    def _chat(self, user_msg: str):
        """发送用户消息并处理流式回复的主循环。"""
        if not self.current_topic_id:
            self._auto_init_topic()
        tui = self._tui
        reply_chunks = []
        tool_round = [0]
        think_started = False
        # 成本追踪
        session_tokens = {"prompt": 0, "completion": 0, "total": 0}
        start_time = time.time()

        def on_stream(chunk: str):
            """流式数据回调。"""
            nonlocal think_started
            if chunk.startswith("[THINK]"):
                text = chunk[7:]
                if text:
                    think_started = True
                    tui.call_from_thread(tui._append_think_text, text)
                return
            if chunk.startswith("[THINK_DONE]"):
                if think_started:
                    tui.call_from_thread(tui._flush_think_buffer)
                    think_started = False
                return
            if chunk.startswith("[TOOL_START:"):
                tool_round[0] += 1
                tool_name = chunk.split(":", 1)[1].rstrip("]")
                if self._tui_verbose:
                    tui.call_from_thread(tui._append_chat, f"Tool [{tool_round[0]}]: {tool_name}")
                else:
                    tui.call_from_thread(tui._append_chat, f"⚙ {tool_name}")
                return
            if chunk.startswith("[TOOL_ARG:") or chunk.startswith("[TOOL_DONE]") or chunk.startswith("[TOOL_RESULT:"):
                return
            # token 消耗追踪
            if chunk.startswith("[USAGE:"):
                try:
                    usage_json = chunk[7:].rstrip("]")
                    import json as _json
                    usage = _json.loads(usage_json)
                    session_tokens["prompt"] += usage.get("prompt_tokens", 0)
                    session_tokens["completion"] += usage.get("completion_tokens", 0)
                    session_tokens["total"] += usage.get("total_tokens", 0)
                    elapsed = time.time() - start_time
                    tui.call_from_thread(tui._update_cost_bar, session_tokens, elapsed)
                except Exception:
                    pass
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
            """状态更新回调。"""
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

        elapsed = time.time() - start_time
        tui.call_from_thread(tui._update_cost_bar, session_tokens, elapsed, final=True)
        tui.call_from_thread(tui._flush_stream_buffer)
        tui.call_from_thread(tui._append_chat, "")
        if ai_msg:
            self._post_chat_pipeline(
                ai_msg=ai_msg, used_tools=used_tools,
                user_msg=user_msg, topic_id=self.current_topic_id,
            )

    def _auto_init_topic(self):
        """自动初始化新主题。"""
        topics = self.db.list_topics()
        if topics:
            tp = topics[0]
            self.current_topic_id = tp["topic_id"]
            self._load_topic_history_into_session(tp["topic_id"])
        else:
            self.current_topic_id = self.db.create_topic("TUI Session")
            self.sess.messages = [{"role": "system", "content": self.sess.system_prompt}]
            self.sess._history_summary = ""


# ───────────────────────────────────────────
# Token 成本估算
# ───────────────────────────────────────────

def _estimate_cost(tokens: dict, model: str = "default") -> float:
    """粗略估算 API 调用成本 (USD)。"""
    total = tokens.get("total", 0)
    prompt = tokens.get("prompt", total // 2)
    completion = tokens.get("completion", total // 2)
    model = model.lower()
    if "gpt-4" in model or "claude-3" in model or "claude-3.5" in model:
        prompt_cost = prompt * 2.5 / 1_000_000
        completion_cost = completion * 10 / 1_000_000
    elif "deepseek" in model or "qwen" in model:
        prompt_cost = prompt * 0.5 / 1_000_000
        completion_cost = completion * 2 / 1_000_000
    else:
        prompt_cost = prompt * 1 / 1_000_000
        completion_cost = completion * 4 / 1_000_000
    return round(prompt_cost + completion_cost, 6)


# ───────────────────────────────────────────
# 状态栏组件
# ───────────────────────────────────────────

class CostStatusBar(Widget):
    """底部成本/状态栏 — 实时显示 token 消耗和估算成本。"""

    tokens = reactive({"prompt": 0, "completion": 0, "total": 0})
    elapsed = reactive(0.0)
    status_text = reactive("Ready")
    model_name = reactive("")

    def render(self) -> Text:
        result = Text()
        result.append(f" {self.status_text} ", style=Style(color="cyan"))
        result.append("│", style=Style(dim=True))
        if self.model_name:
            result.append(f" {self.model_name[:20]} ", style=Style(color="green"))
            result.append("│", style=Style(dim=True))
        t = self.tokens
        total = t.get("total", 0)
        prompt = t.get("prompt", 0)
        completion = t.get("completion", 0)
        if total > 0:
            cost = _estimate_cost(t, self.model_name)
            result.append(f" T:{total} ", style=Style(color="yellow"))
            result.append(f"(P:{prompt}+C:{completion}) ", style=Style(dim=True))
            result.append(f"${cost:.5f} ", style=Style(color="green" if cost < 0.1 else "red"))
            result.append("│", style=Style(dim=True))
        if self.elapsed > 0:
            m, s = divmod(int(self.elapsed), 60)
            result.append(f" {m:02d}:{s:02d} ", style=Style(dim=True))
        return result


# ───────────────────────────────────────────
# 主 TUI 应用
# ───────────────────────────────────────────

class TeaTUI(App):
    """Tea Agent Terminal UI -- 增强版，借鉴 opencode/codex 模式。"""

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

    CostStatusBar {
        dock: bottom;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "interrupt", "Interrupt"),
        Binding("ctrl+t", "toggle_think", "Think"),
        Binding("ctrl+v", "toggle_verbose", "Verbose"),
        Binding("ctrl+n", "new_topic", "NewTopic"),
        Binding("ctrl+l", "list_topics", "ListTopics"),
        Binding("ctrl+k", "clear_screen", "Clear"),
        Binding("ctrl+up", "history_up", "HistoryUp"),
        Binding("ctrl+down", "history_down", "HistoryDown"),
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
        self.agent: _TUIAgentCore | None = None
        self._stream_buffer = ""
        self._think_buffer = ""
        self._stream_timer = None
        self._welcome_shown = False
        self._cost_bar: CostStatusBar | None = None
        self._history_msgs: list[dict] = []
        self._history_index: int = -1

    class _SendTextArea(TextArea):
        """TextArea with Enter=send, Shift+Enter=newline, Up/Down=history when empty."""

        async def _on_key(self, event):
            if event.key in ("enter", "shift+enter"):
                if event.key == "shift+enter":
                    self.insert("\n")
                else:
                    self.app._do_send()
                event.stop()
                return
            if event.key == "up" and not self.text.strip():
                self.app._navigate_history_up()
                event.stop()
                return
            if event.key == "down" and not self.text.strip():
                self.app._navigate_history_down()
                event.stop()
                return
            await super()._on_key(event)

    def compose(self) -> ComposeResult:
        with Container(id="header-bar"):
            yield Label("☕ Tea Agent TUI", id="header-title")
            yield Label("", id="header-model")
        with ScrollableContainer(id="chat-container"):
            yield RichLog(id="chat-area", highlight=True, markup=True, wrap=True)
        with Container(id="input-container"):
            yield self._SendTextArea(id="input-area", language=None, show_line_numbers=False)
        yield CostStatusBar()

    def on_mount(self):
        self._cost_bar = self.query_one(CostStatusBar)
        self._update_status("Initializing Tea Agent...")
        threading.Thread(target=self._init_agent, daemon=True).start()
        self.set_interval(0.5, self._check_agent_ready)
        with contextlib.suppress(NoMatches):
            self.query_one("#input-area", TextArea).focus()

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
        if self._cost_bar:
            self._cost_bar.model_name = model_name
            self._cost_bar.status_text = "Ready"
        info = self.agent._init_session_info_str()
        self._update_status(info.replace("\\n", " | "))
        self._chat_write("[bold cyan]☕ Tea Agent TUI — 增强版[/]")
        self._chat_write(f"   Model: {model_name}")
        self._chat_write(f"   Think: [bold]{'ON' if self._cli_think else 'OFF'}[/]  "
                    f"Verbose: [bold]{'ON' if self._cli_verbose else 'OFF'}[/]")
        self._chat_write(f"   Tools: {tool_count} loaded")
        self._chat_write("   Ctrl+C quit | Esc interrupt | Ctrl+T Think | Ctrl+V Verbose | Ctrl+K Clear")
        self._chat_write("")
        self._update_status("Ready — Enter to send message")
        self.agent._auto_init_topic()

    def _show_error(self, msg: str):
        with contextlib.suppress(NoMatches):
            self._chat_write(f"[bold red]ERROR: {msg}[/]")
        self._update_status(f"ERROR: {msg}")

    def _update_status(self, text: str):
        if self._cost_bar:
            self._cost_bar.status_text = text

    def _update_cost_bar(self, tokens: dict, elapsed: float, final: bool = False):
        if self._cost_bar:
            self._cost_bar.tokens = tokens
            self._cost_bar.elapsed = elapsed
            if final:
                self._cost_bar.status_text = "Done"

    def _chat_write(self, text: str):
        with contextlib.suppress(NoMatches):
            area = self.query_one("#chat-area", RichLog)
            area.write(text)

    def _append_chat(self, text: str):
        with contextlib.suppress(NoMatches):
            area = self.query_one("#chat-area", RichLog)
            try:
                area.write(text)
            except Exception:
                area.write(str(text))

    def _append_chat_inline(self, text: str):
        self._stream_buffer += text
        if self._stream_timer is None:
            self._stream_timer = self.set_interval(0.05, self._flush_stream_buffer)

    def _flush_stream_buffer(self):
        if not self._stream_buffer:
            return
        with contextlib.suppress(NoMatches):
            area = self.query_one("#chat-area", RichLog)
            try:
                area.write(self._stream_buffer)
            except Exception:
                area.write(str(self._stream_buffer))
            self._stream_buffer = ""
        if self._stream_timer:
            self._stream_timer.stop()
            self._stream_timer = None

    def _append_think_text(self, text: str):
        self._think_buffer += text

    def _flush_think_buffer(self):
        if not self._think_buffer:
            return
        content = self._think_buffer
        self._think_buffer = ""
        self._chat_write(f"\n[dim]── {self._format_think(content)} ──[/]\n")

    @staticmethod
    def _format_think(text: str) -> str:
        if len(text) > 600:
            return text[:300] + "\n... (思考过程截断) ...\n" + text[-300:]
        return text

    def _do_send(self):
        if self._generating or not self._agent_ready.is_set():
            return
        area = self.query_one("#input-area", TextArea)
        text = area.text.strip()
        if not text:
            return
        area.clear()
        self._generating = True
        self._chat_write(f"\n[bold cyan]You:[/] {text}\n")
        self._update_status("Generating...")
        if self._cost_bar:
            self._cost_bar.tokens = {"prompt": 0, "completion": 0, "total": 0}
            self._cost_bar.elapsed = 0.0
        threading.Thread(target=self._do_generate, args=(text,), daemon=True).start()

    def _do_generate(self, text: str):
        try:
            self.agent._chat(text)
        except Exception as e:
            self.call_from_thread(self._show_error, str(e))
        finally:
            self._generating = False
            self.call_from_thread(self._after_generate)

    def _after_generate(self):
        self._update_status("Ready")
        with contextlib.suppress(NoMatches):
            self.query_one("#input-area", TextArea).focus()

    def action_toggle_think(self):
        self._cli_think = not self._cli_think
        if self.agent:
            self.agent._tui_think = self._cli_think
            self.agent._cfg.enable_thinking = self._cli_think
            self.agent.sess.enable_thinking = self._cli_think
        self._append_chat(f"[dim]Think {'ON' if self._cli_think else 'OFF'}[/]")

    def action_toggle_verbose(self):
        self._cli_verbose = not self._cli_verbose
        if self.agent:
            self.agent._tui_verbose = self._cli_verbose
        self._append_chat(f"[dim]Verbose {'ON' if self._cli_verbose else 'OFF'}[/]")

    def action_new_topic(self):
        if self.agent:
            topic_id = self.agent.db.create_topic("TUI Session")
            self.agent.current_topic_id = topic_id
            self.agent.sess.messages = [{"role": "system", "content": self.agent.sess.system_prompt}]
            self.agent.sess._history_summary = ""
            self._chat_write("\n[bold green]── 新对话 ──[/]\n")

    def action_list_topics(self):
        if not self.agent:
            return
        topics = self.agent.db.list_topics()
        if not topics:
            self._chat_write("[dim]暂无历史对话[/]")
            return
        self._chat_write("[bold]历史对话:[/]")
        for i, tp in enumerate(topics[:10]):
            title = tp.get("title", tp["topic_id"][:8])
            marker = "→" if tp["topic_id"] == self.agent.current_topic_id else " "
            self._chat_write(f"  {marker} [{i}] {title} ({tp['topic_id'][:8]})")
        if len(topics) > 10:
            self._chat_write(f"  ... 还有 {len(topics)-10} 个")

    def action_clear_screen(self):
        with contextlib.suppress(NoMatches):
            area = self.query_one("#chat-area", RichLog)
            area.clear()
        self._chat_write("[bold cyan]☕ Tea Agent TUI[/]")
        self._chat_write("")

    def action_interrupt(self):
        if self._generating and self.agent:
            self.agent.sess.interrupted = True
            self._update_status("Interrupted")
            self._append_chat("\n[bold yellow]⏹ 已中断[/]")

    def _navigate_history_up(self):
        if not self._history_msgs:
            self._load_history()
        if not self._history_msgs:
            return
        self._history_index = min(self._history_index + 1, len(self._history_msgs) - 1)
        self._show_history_item()

    def _navigate_history_down(self):
        if self._history_index <= 0:
            self._history_index = -1
            with contextlib.suppress(NoMatches):
                self.query_one("#input-area", TextArea).clear()
            return
        self._history_index -= 1
        self._show_history_item()

    def _load_history(self):
        if not self.agent or not self.agent.current_topic_id:
            return
        messages = self.agent.db.get_messages(self.agent.current_topic_id)
        self._history_msgs = [m for m in messages if m.get("role") == "user"]

    def _show_history_item(self):
        if self._history_index < 0 or self._history_index >= len(self._history_msgs):
            return
        msg = self._history_msgs[self._history_index]
        content = msg.get("content", "")
        with contextlib.suppress(NoMatches):
            area = self.query_one("#input-area", TextArea)
            area.clear()
            area.insert(content)

    def action_quit(self):
        if self.agent:
            self.agent.shutdown()
        self.exit()


# ───────────────────────────────────────────
# 命令行入口
# ───────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tea Agent TUI (Enhanced)")
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument("--think", "-t", action="store_true", help="Enable thinking")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--disable-summary", action="store_true", help="Disable L2/L3 summary")
    parser.add_argument("--no-stream-chunk", action="store_true", help="Disable stream chunking")
    args = parser.parse_args()

    app = TeaTUI(
        config_path=args.config,
        enable_think=args.think,
        verbose=args.verbose,
        disable_summary=args.disable_summary,
        no_stream_chunk=args.no_stream_chunk,
    )
    app.run()


if __name__ == "__main__":
    main()
