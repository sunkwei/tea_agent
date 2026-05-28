# -*- coding: utf-8 -*-
"""Status bar header displaying model, tokens, topic info."""

from textual.widgets import Static
from textual.containers import Horizontal
from textual.app import ComposeResult


class HeaderBar(Horizontal):
    """Top status bar showing model, token counts, connection info."""

    DEFAULT_CSS = """
    HeaderBar {
        height: 1;
        dock: top;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    HeaderBar Static {
        width: auto;
        margin: 0 2 0 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="header_model")
        yield Static("", id="header_tokens")
        yield Static("", id="header_topic")
        yield Static("", id="header_tools")

    def update_status(self, model: str = "", tokens: str = "",
                      topic: str = "", tools: str = ""):
        """Update all header fields."""
        if model:
            self.query_one("#header_model").update(f"🔮 {model}")
        if tokens:
            self.query_one("#header_tokens").update(f"📊 {tokens}")
        if topic:
            self.query_one("#header_topic").update(f"📌 {topic}")
        if tools:
            self.query_one("#header_tools").update(f"🔧 {tools}")
