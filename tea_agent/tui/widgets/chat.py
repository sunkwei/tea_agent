# -*- coding: utf-8 -*-
"""Chat log widget — scrollable message display with Rich markup."""

from textual.widgets import Static, RichLog
from textual.containers import VerticalScroll
from textual.markup import escape

from rich.text import Text
from rich.panel import Panel
from rich.markdown import Markdown
from rich.console import RenderableType
from typing import Optional


class ChatLog(VerticalScroll, can_focus=False):
    """Scrollable chat message display area.

    Shows user messages and AI responses with Rich rendering.
    Supports Markdown in AI responses.
    """

    DEFAULT_CSS = """
    ChatLog {
        height: 1fr;
        border: none;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self):
        super().__init__()
        self._message_count = 0

    def on_mount(self):
        """Welcome message on first render."""
        self.add_user_message("Welcome to Tea Agent TUI! Type a message or /help for commands.")

    # ── public API ──────────────────────────────────────

    def add_user_message(self, text: str):
        """Display a user message."""
        user_label = Text("▸ You", style="bold cyan")
        content = Text(text.strip(), style="white")
        panel = Panel(
            content,
            title=user_label,
            border_style="cyan",
            padding=(0, 1),
        )
        self.mount(Static(panel))
        self._scroll_to_bottom()

    def add_ai_message(self, text: str):
        """Display a complete AI message with Markdown rendering."""
        ai_label = Text("◆ Tea", style="bold green")
        try:
            md = Markdown(text, code_theme="monokai")
            panel = Panel(
                md,
                title=ai_label,
                border_style="green",
                padding=(1, 1),
            )
        except Exception:
            panel = Panel(
                Text(text, style="white"),
                title=ai_label,
                border_style="green",
            )
        self.mount(Static(panel))
        self._scroll_to_bottom()

    def add_system_message(self, text: str):
        """Display a system/status message."""
        label = Text("⚡ System", style="bold yellow")
        panel = Panel(
            Text(text, style="dim yellow"),
            title=label,
            border_style="yellow",
        )
        self.mount(Static(panel))
        self._scroll_to_bottom()

    def add_error_message(self, text: str):
        """Display an error message."""
        label = Text("✗ Error", style="bold red")
        panel = Panel(
            Text(text, style="red"),
            title=label,
            border_style="red",
        )
        self.mount(Static(panel))
        self._scroll_to_bottom()

    def begin_stream(self):
        """Begin a streaming AI message. Returns a mutable panel container."""
        self._stream_label = Text("◆ Tea", style="bold green")
        self._stream_content = Text("", style="white")
        self._stream_panel = Panel(
            self._stream_content,
            title=self._stream_label,
            border_style="green",
        )
        self._stream_widget = Static(self._stream_panel)
        self.mount(self._stream_widget)

    def append_stream(self, chunk: str):
        """Append a chunk to the current streaming message."""
        if not hasattr(self, '_stream_content'):
            self.begin_stream()
        self._stream_content.append(chunk)
        # Update: rebuild panel with new content
        new_panel = Panel(
            self._stream_content,
            title=self._stream_label,
            border_style="green",
        )
        self._stream_widget.update(new_panel)
        self._scroll_to_bottom()

    def end_stream(self):
        """Finalize the streaming message."""
        pass  # The stream widget stays in place

    def clear(self):
        """Clear all messages."""
        for child in list(self.children):
            child.remove()
        self._message_count = 0

    # ── internal ──────────────────────────────────────

    def _scroll_to_bottom(self):
        """Scroll to the bottom of the chat log."""
        self.call_after_refresh(self.scroll_end, animate=False)
