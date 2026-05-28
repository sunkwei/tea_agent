# -*- coding: utf-8 -*-
"""Sidebar panel — status, tools, memories, files in a collapsible panel."""

from textual.widgets import Static, Tree, Label
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.app import ComposeResult
from textual.widgets.tree import TreeNode


class Sidebar(Vertical):
    """Right sidebar showing status info, tools, memories, and touched files."""

    DEFAULT_CSS = """
    Sidebar {
        width: 36;
        height: 1fr;
        dock: right;
        background: $panel;
        border-left: solid $primary-background;
        padding: 1;
        display: none;
    }
    Sidebar.visible {
        display: block;
    }
    Sidebar > Vertical {
        margin-bottom: 1;
    }
    Sidebar Label {
        text-style: bold;
        color: $accent;
        margin-bottom: 0;
    }
    Sidebar Static {
        color: $text;
    }
    """

    def compose(self) -> ComposeResult:
        # ── Status section ──
        with Vertical(id="sect_status"):
            yield Label("📊 Status")
            yield Static("Model: —", id="sb_model")
            yield Static("Tools: — loaded", id="sb_tools")
            yield Static("Topic: —", id="sb_topic")
            yield Static("Tokens: —", id="sb_tokens")
            yield Static("Memories: — active", id="sb_memories")

        # ── Last Tool section ──
        with Vertical(id="sect_tool"):
            yield Label("🔧 Last Tool")
            yield Static("(none)", id="sb_last_tool")

        # ── Touched Files section ──
        with Vertical(id="sect_files"):
            yield Label("📝 Files")
            yield Static("(none)", id="sb_files")

    def update(self, **kwargs):
        """Update sidebar fields. Keys: model, tools, topic, tokens, memories, last_tool, files."""
        for key, value in kwargs.items():
            wid = self.query_one(f"#sb_{key}", None)
            if wid:
                wid.update(str(value))

    def toggle(self):
        """Toggle sidebar visibility."""
        if self.has_class("visible"):
            self.remove_class("visible")
        else:
            self.add_class("visible")
