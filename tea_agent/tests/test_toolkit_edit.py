"""Tests for toolkit_edit module."""

import os
import tempfile

from tea_agent.toolkit.toolkit_edit import _verify_after_write, toolkit_edit


def _make_file(content="print('hello')\n"):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    f.write(content)
    f.close()
    return f.name


def test_replace_text_basic():
    fp = _make_file("x = 1\nprint(x)\n")
    try:
        result = toolkit_edit(fp, action="replace_text", old_text="x = 1", new_text="x = 2")
        assert result["ok"] is True
        with open(fp) as f:
            assert "x = 2" in f.read()
    finally:
        os.unlink(fp)


def test_replace_text_not_found():
    fp = _make_file("x = 1\n")
    try:
        result = toolkit_edit(fp, action="replace_text", old_text="nonexistent", new_text="x = 2")
        assert result["ok"] is False
    finally:
        os.unlink(fp)


def test_replace_text_empty_old():
    fp = _make_file("x = 1\n")
    try:
        result = toolkit_edit(fp, action="replace_text", old_text="", new_text="x = 2")
        assert result["ok"] is False
    finally:
        os.unlink(fp)


def test_replace_text_verify_after_write():
    fp = _make_file("x = 1\n")
    try:
        warn = _verify_after_write(fp, old_text="x = 1", new_text="x = 2", label="test")
        assert "旧内容仍然存在" in warn
    finally:
        os.unlink(fp)


def test_insert_lines():
    fp = _make_file("line1\nline3\n")
    try:
        result = toolkit_edit(fp, action="insert_lines", start_line=2, new_text="line2")
        assert result["ok"] is True
        with open(fp) as f:
            content = f.read()
            assert "line1" in content
            assert "line2" in content
            assert "line3" in content
    finally:
        os.unlink(fp)


def test_delete_lines():
    fp = _make_file("line1\nline2\nline3\n")
    try:
        result = toolkit_edit(fp, action="delete_lines", start_line=2, end_line=2)
        assert result["ok"] is True
        with open(fp) as f:
            assert "line2" not in f.read()
    finally:
        os.unlink(fp)


def test_replace_lines():
    fp = _make_file("line1\nbad\nline3\n")
    try:
        result = toolkit_edit(fp, action="replace_lines", start_line=2, end_line=2,
                              new_text="good")
        assert result["ok"] is True
        with open(fp) as f:
            content = f.read()
            assert "good" in content
            assert "bad" not in content
    finally:
        os.unlink(fp)


def test_preview_patch():
    fp = _make_file("x = 1\n")
    try:
        result = toolkit_edit(fp, action="preview_patch", content="@@ -1 +1 @@\n-x = 1\n+x = 2\n")
        assert result["ok"] is True
        msg = result.get("message", "")
        assert "preview" in msg or "diff" in msg or "status" in msg
    finally:
        os.unlink(fp)


def test_file_not_found():
    result = toolkit_edit("/nonexistent/path.py", action="replace_text",
                          old_text="x", new_text="y")
    assert result["ok"] is False
    assert "不存在" in result.get("error", "")


def test_unknown_action():
    fp = _make_file("x = 1\n")
    try:
        result = toolkit_edit(fp, action="nonexistent_action")
        assert result["ok"] is False
    finally:
        os.unlink(fp)
