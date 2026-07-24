"""Tests for toolkit_diff module."""

import os
import tempfile

from tea_agent.toolkit.toolkit_diff import (
    _check_conflict,
    _colorize_diff,
    _generate_diff_stats,
    _generate_unified_diff,
)


def test_generate_unified_diff():
    old = "line1\nline2\nline3\n"
    new = "line1\nline2_modified\nline3\n"
    diff = _generate_unified_diff(old, new, filename="test.py", context_lines=3)
    assert "line2" in diff
    assert "line2_modified" in diff


def test_generate_unified_diff_identical():
    old = "line1\nline2\n"
    new = "line1\nline2\n"
    diff = _generate_unified_diff(old, new, filename="test.py", context_lines=3)
    assert diff.strip() == "" or "-line1" not in diff


def test_diff_stats():
    stats = _generate_diff_stats("+1\n+2\n-3\n 4\n")
    assert stats["additions"] == 2
    assert stats["deletions"] == 1


def test_diff_stats_empty():
    stats = _generate_diff_stats(" 1\n 2\n")
    assert stats["additions"] == 0
    assert stats["deletions"] == 0


def test_colorize_diff():
    raw = "--- old\n+++ new\n@@ -1 +1 @@\n-old_line\n+new_line\n"
    result = _colorize_diff(raw)
    assert "old_line" in result
    assert "new_line" in result


def test_check_conflict_no_file():
    result = _check_conflict("/nonexistent/file.py", "old_code", "/tmp")
    assert result is not None
    assert "不存在" in result


def test_check_conflict_match():
    fp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    fp.write("x = 1\ny = 2\n")
    fp.close()
    try:
        result = _check_conflict(os.path.basename(fp.name), "x = 1", os.path.dirname(fp.name))
        assert result is None  # exactly one match = no conflict
    finally:
        os.unlink(fp.name)


def test_check_conflict_not_found():
    fp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    fp.write("x = 1\n")
    fp.close()
    try:
        result = _check_conflict(os.path.basename(fp.name), "nonexistent_code", os.path.dirname(fp.name))
        assert result is not None
        assert "未找到" in result
    finally:
        os.unlink(fp.name)
