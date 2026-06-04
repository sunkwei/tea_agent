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
    Up/Down     History (when input empty)
    Ctrl+C      Quit
    Esc         Interrupt generation
    Ctrl+T      Toggle Think mode
    Ctrl+V      Toggle Verbose mode
    Ctrl+N      New topic
    Ctrl+L      List topics
    Ctrl+Up     Previous history message
    Ctrl+Down   Next history message
"""

import argparse
import sys
import os
import threading
from datetime import datetime
from typing import Optional, List, Dict
import re

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from textual.app import App, ComposeResult
from textual.widgets import Label, RichLog, TextArea
from textual.containers import Container, ScrollableContainer
from textual.binding import Binding
from textual.css.query import NoMatches
from rich.errors import MarkupError

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
        self.agent: Optional[_TUIAgentCore] = None
        self._stream_buffer = ""
        self._think_buffer = ""       # separate buffer for think blocks
        self._stream_timer = None
        self._welcome_shown = False
        # 历史消息导航
        self._history_msgs: List[Dict] = []  # 当前主题的所有历史对话
        self._history_index: int = -1        # -1 = 不在导航状态, 0..n-1 = 当前查看的索引

    class _SendTextArea(TextArea):
        """TextArea with Enter=send, Shift+Enter=newline, Up/Down=history when empty."""

        async def _on_key(self, event):
            """Enter=send, Shift+Enter=newline, Up/Down=history when empty."""
            if event.key in ("enter", "shift+enter"):
                if event.key == "shift+enter":
                    self.insert("\n")
                else:
                    self.app._do_send()
                event.stop()
                return
            # 向上/向下键：仅在输入框为空时触发历史导航
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
        self._load_history_msgs()

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
        self._flush_think_buffer()   # flush any incomplete think block
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
        try:
            chat.write(text)
        except MarkupError:
            # @{date} gen by model, fallback for broken Rich markup tags
            from rich.text import Text
            chat.write(Text(text))

    def _append_chat_inline(self, text: str):
        self._stream_buffer += text

    def _append_think_text(self, text: str):
        """Accumulate think text in a separate buffer (no Rich markup tags)."""
        self._think_buffer += text

    def _flush_think_buffer(self):
        """Flush think buffer as a single [italic]...[/italic] unit."""
        if self._think_buffer:
            try:
                self._chat_write(f"[italic]# {self._think_buffer}[/italic]")
            except NoMatches:
                pass
            self._think_buffer = ""

    def _flush_stream_buffer(self):
        if self._stream_buffer:
            try:
                self._chat_write(self._stream_buffer)
            except NoMatches:
                pass
            self._stream_buffer = ""

    def _handle_command(self, cmd: str):
        parts = cmd.split(None, 1)
        cmd_name = parts[0].lower().lstrip("/")  # 去掉 / 前缀
        arg = parts[1] if len(parts) > 1 else ""

        # TUI 内置命令
        builtins = {
            "bye": lambda: self.exit(),
            "quit": lambda: self.exit(),
            "exit": lambda: self.exit(),
            "help": lambda: self._show_help(),
            "think": lambda: self.action_toggle_think(),
            "verbose": lambda: self.action_toggle_verbose(),
            "new": lambda: self.action_new_topic(),
            "list": lambda: self.action_list_topics(),
        }
        if cmd_name in builtins:
            builtins[cmd_name]()
            return
        if cmd_name == "set":
            self._cmd_set(arg)
            return
        if cmd_name == "switch":
            self._switch_topic(arg)
            return

        # ── 元命令 ──
        if cmd_name == "commands":
            self._list_custom_commands()
            return
        if cmd_name == "command":
            if not arg:
                self._chat_write("[bold yellow]用法: /command <name> — 查看命令详情[/]")
                return
            self._show_custom_command(arg)
            return

        # ── Custom Commands 路由 ──
        self._handle_custom_command(cmd_name, arg)

    def _handle_custom_command(self, cmd_name: str, arg: str):
        """将 /command 路由到 toolkit_custom_commands"""
        try:
            from tea_agent.toolkit.toolkit_custom_commands import toolkit_custom_commands

            # 解析参数：支持 key=val 格式和位置参数
            args_dict = {}
            if arg:
                # 尝试 key=value 对
                kv_pairs = [p for p in arg.split() if "=" in p]
                positional = [p for p in arg.split() if "=" not in p]
                for kv in kv_pairs:
                    k, _, v = kv.partition("=")
                    args_dict[k.strip()] = v.strip()
                # 位置参数作为 'args' 传入
                if positional:
                    # 第一个位置参数作为默认参数
                    if not args_dict:
                        args_dict["args"] = positional
                    else:
                        args_dict.setdefault("args", positional)

            # 先查看命令是否存在
            result = toolkit_custom_commands(action="show", name=cmd_name)
            if not result.get("ok"):
                self._chat_write(f"[bold yellow]未知命令: /{cmd_name} (/help 查看帮助)[/]")
                return

            # 获取命令的参数定义
            cmd_info = result.get("command", {})
            defined_args = cmd_info.get("args_def", [])

            # 如果是 key=value 格式，直接用；否则将位置参数映射到命令参数
            if args_dict and "args" not in args_dict:
                run_args = {k: v for k, v in args_dict.items() if k != "args"}
            else:
                # 位置参数 → 按顺序映射到命令的 args_def
                positional = args_dict.get("args", [])
                run_args = {}
                for i, pa in enumerate(positional):
                    if i < len(defined_args):
                        run_args[defined_args[i]] = pa

            # 执行命令
            result = toolkit_custom_commands(
                action="run", name=cmd_name, args=run_args if run_args else None
            )

            if not result.get("ok"):
                self._chat_write(f"[bold red]命令执行失败: {result.get('error', '')}[/]")
                return

            # 输出结果
            prompt = result.get("resolved_prompt", "")
            unresolved = result.get("unresolved_placeholders", [])

            self._chat_write(f"\n[bold cyan]▶ /{cmd_name}[/]")
            self._chat_write(f"[dim]{result.get('description', '')}[/]")

            if unresolved:
                self._chat_write(f"[bold yellow]缺少参数: {', '.join(unresolved)}[/]")
                self._chat_write(f"[dim]用法: /{cmd_name} {' '.join(f'<{a}>' for a in defined_args)}[/]")
            elif prompt:
                # 将 resolved_prompt 发送给 agent 执行
                self._chat_write(f"[bold cyan]正在执行 /{cmd_name} ...[/]")
                self._do_send_custom(prompt)

        except Exception as e:
            self._chat_write(f"[bold red]命令处理异常: {e}[/]")

    def _list_custom_commands(self):
        """列出所有可用的自定义命令"""
        try:
            from tea_agent.toolkit.toolkit_custom_commands import toolkit_custom_commands
            result = toolkit_custom_commands(action="list")
            if not result.get("ok"):
                self._chat_write(f"[bold red]获取命令列表失败[/]")
                return
            cmds = result.get("commands", [])
            self._chat_write(f"\n[bold cyan]可用命令 ({len(cmds)} 个)[/]")
            for c in cmds:
                scope_mark = "📁" if c["scope"] == "project" else "👤"
                tags = f" [{','.join(c['tags'])}]" if c.get("tags") else ""
                self._chat_write(
                    f"  {scope_mark} [bold]/{c['name']}[/] — {c['description']}{tags}"
                )
            self._chat_write("[dim]用法: /<命令名> [参数...] 或 /command <命令名> 查看详情[/]")
        except Exception as e:
            self._chat_write(f"[bold red]获取命令列表异常: {e}[/]")

    def _show_custom_command(self, name: str):
        """显示某个命令的详情"""
        try:
            from tea_agent.toolkit.toolkit_custom_commands import toolkit_custom_commands
            result = toolkit_custom_commands(action="show", name=name)
            if not result.get("ok"):
                self._chat_write(f"[bold yellow]命令 '{name}' 不存在[/]")
                return
            cmd = result.get("command", {})
            defined_args = cmd.get("args_def", [])
            usage = f"/{name} {' '.join(f'<{a}>' for a in defined_args)}" if defined_args else f"/{name}"
            self._chat_write(f"\n[bold cyan]/{name}[/]")
            self._chat_write(f"  [dim]{cmd.get('description', '')}[/]")
            self._chat_write(f"  用法: [bold]{usage}[/]")
            if cmd.get("tags"):
                self._chat_write(f"  标签: {', '.join(cmd['tags'])}")
            if cmd.get("scope"):
                self._chat_write(f"  范围: {'项目级' if cmd['scope']=='project' else '用户级'}")
        except Exception as e:
            self._chat_write(f"[bold red]异常: {e}[/]")

    def _do_send_custom(self, text: str):
        """发送自定义命令解析后的 prompt 给 agent 执行"""
        if self._generating:
            return
        self._generating = True
        self._start_stream_timer()
        self._update_status(f"Executing command...")

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

[bold cyan]Custom Commands[/]
  /init <path>       项目初始化，扫描构建项目知识库
  /explain <target>  解释指定代码文件或函数
  /plan <goal>       根据目标创建执行计划
  /review <file>     审查代码变更
  /test <pattern>    运行测试并分析结果
  /commands          列出所有可用自定义命令
  /command <name>    查看 / 执行自定义命令

[bold]Keybindings[/]
  Enter     Send    Shift+Enter  Newline
  Up/Down   History (when input empty)
  Ctrl+C    Quit    Esc          Interrupt
  Ctrl+T    Think   Ctrl+V       Verbose
  Ctrl+N    New     Ctrl+L       List
  Ctrl+Up   Prev history msg
  Ctrl+Down Next history msg
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

    def _load_history_msgs(self):
        """Load all history conversations for current topic into _history_msgs."""
        self._history_msgs = []
        self._history_index = -1
        if not self.agent or not self.agent.current_topic_id:
            return
        try:
            convs = self.agent.db.get_conversations(
                self.agent.current_topic_id, limit=-1, include_rounds=False
            )
            for c in convs:
                user_text = c.get("user_msg", "")
                ai_text = c.get("ai_msg", "")
                if isinstance(user_text, str) and user_text.startswith("{"):
                    try:
                        import json
                        parsed = json.loads(user_text)
                        user_text = parsed.get("text", user_text)
                    except Exception:
                        pass
                self._history_msgs.append({
                    "user": user_text or "",
                    "ai": ai_text or "",
                })
        except Exception as e:
            self._chat_write(f"[bold red]Failed to load history: {e}[/]")

    def action_history_up(self):
        """Ctrl+Up: 往前翻一条历史消息."""
        if not self._history_msgs:
            self._load_history_msgs()
        if not self._history_msgs:
            self._chat_write("[dim]No history messages[/]")
            return
        if self._history_index >= len(self._history_msgs) - 1:
            self._chat_write("[dim]Already at oldest message[/]")
            return
        self._history_index += 1
        self._display_history_msg()

    def action_history_down(self):
        """Ctrl+Down: 往后翻一条历史消息."""
        if not self._history_msgs:
            self._load_history_msgs()
        if self._history_index <= 0:
            if self._history_index == 0:
                self._chat_write("[dim]Already at newest message[/]")
            else:
                self._chat_write("[dim]No history messages[/]")
            return
        self._history_index -= 1
        self._display_history_msg()

    def _display_history_msg(self):
        """Display the history message at current _history_index."""
        if self._history_index < 0 or self._history_index >= len(self._history_msgs):
            return
        msg = self._history_msgs[self._history_index]
        total = len(self._history_msgs)
        idx = self._history_index
        self._chat_write(f"\n[bold cyan]--- History ({total - idx}/{total}) ---[/]")
        self._chat_write(f"[bold green]You:[/] {msg['user'][:500]}")
        self._chat_write(f"[bold blue]AI:[/] {msg['ai'][:1000]}")
        self._chat_write(f"[bold cyan]--- End ---[/]")
        self._update_status(f"History: {total - idx}/{total}")

    def _navigate_history_up(self):
        """向上键：输入框为空时，用历史user输入替换。"""
        if not self._history_msgs:
            self._load_history_msgs()
        if not self._history_msgs:
            self._update_status("No history messages")
            return
        # 从最新消息开始往前翻
        if self._history_index < len(self._history_msgs) - 1:
            self._history_index += 1
            self._display_current_history()
        else:
            self._update_status("Already at oldest message")

    def _navigate_history_down(self):
        """向下键：返回更新的历史消息。"""
        if self._history_index > 0:
            self._history_index -= 1
            self._display_current_history()
        elif self._history_index == 0:
            # 回到最新，清空输入框
            self._history_index = -1
            try:
                input_widget = self.query_one("#input-area", TextArea)
                input_widget.clear()
            except NoMatches:
                pass
            self._update_status("Ready")
        else:
            self._update_status("No history messages")

    def _display_current_history(self):
        """在输入框中显示当前历史消息的user输入。"""
        if self._history_index < 0 or self._history_index >= len(self._history_msgs):
            return
        msg = self._history_msgs[self._history_index]
        total = len(self._history_msgs)
        idx = self._history_index
        try:
            input_widget = self.query_one("#input-area", TextArea)
            input_widget.clear()
            input_widget.insert(msg["user"])
        except NoMatches:
            pass
        self._update_status(f"History: {total - idx}/{total} (Up/Down to navigate)")

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
                self._load_history_msgs()
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
        self._load_history_msgs()
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
        self._history_msgs = []
        self._history_index = -1
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
