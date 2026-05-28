# -*- coding: utf-8 -*-
"""Command input widget with slash-command autocomplete and history."""

from textual.widgets import Input, Static, RichLog
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.app import ComposeResult
from textual.binding import Binding
from typing import Optional, List


class CommandInput(Input):
    """Text input with slash-command support.

    Slash commands:
        /help       — show help
        /new        — new topic
        /topics     — list topics
        /switch N   — switch to topic N
        /memories   — show long-term memories
        /status     — show current status
        /clear      — clear chat log
        /exit, /quit — quit

    Binds:
        ctrl+s    — toggle sidebar
        ctrl+c    — interrupt generation
        escape    — focus input
    """

    BINDINGS = [
        Binding("ctrl+s", "toggle_sidebar", "Sidebar", show=True),
        Binding("ctrl+c", "interrupt", "Interrupt", show=True),
        Binding("escape", "focus('input')", "Focus Input", show=False),
    ]

    COMMANDS = [
        "/help", "/new", "/topics", "/switch", "/memories",
        "/status", "/clear", "/exit", "/quit",
    ]

    DEFAULT_CSS = """
    CommandInput {
        border: solid $accent;
        border-title-color: $accent;
        border-title-background: $surface;
        border-title-style: bold;
        padding: 0 1;
        height: 3;
        margin: 0 1 1 1;
    }
    """

    def __init__(self, placeholder: str = "Type a message or /command..."):
        super().__init__(placeholder=placeholder)

    def on_mount(self):
        self.border_title = " Message "
