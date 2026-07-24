"""Tests for toolkit_clean_comments module."""

import os
import tempfile

from tea_agent.toolkit.toolkit_clean_comments import (
    _clean_comments,
    _enhance_comments,
    _scan_comments,
    toolkit_clean_comments,
)


def _make_py_file(content):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    f.write(content)
    f.close()
    return f.name


def test_scan_empty_comment():
    fp = _make_py_file("#\nx = 1\n")
    try:
        result = _scan_comments(fp)
        assert "empty" in result or "问题" in result
    finally:
        os.unlink(fp)


def test_scan_clean_file():
    fp = _make_py_file('"""Module doc."""\n\nx = 1\ny = x + 1\n')
    try:
        result = _scan_comments(fp)
        assert "问题数: 0" in result or "0" in result.split("问题数:")[1].strip()[0] == "0"
    finally:
        os.unlink(fp)


def test_clean_removes_empty_comment():
    fp = _make_py_file("#\nx = 1\n#\ny = 2\n")
    try:
        result = _clean_comments(fp, dry_run=True)
        assert "预览" in result or "删除" in result
    finally:
        os.unlink(fp)


def test_enhance_missing_docstring():
    fp = _make_py_file("class Foo:\n    pass\n\ndef bar():\n    pass\n")
    try:
        result = _enhance_comments(fp, dry_run=True)
        assert "Foo" in result or "bar" in result
    finally:
        os.unlink(fp)


def test_enhance_has_docstring():
    fp = _make_py_file('"""Mod doc."""\n\ndef foo():\n    """Foo doc."""\n    pass\n')
    try:
        result = _enhance_comments(fp, dry_run=True)
        assert "需要添加 0 个" in result or "预览模式" in result
    finally:
        os.unlink(fp)


def test_auto_clean():
    fp = _make_py_file("#\n# ===\ndef foo():\n    pass\n")
    try:
        result = toolkit_clean_comments(action="auto", file_path=fp, dry_run=True)
        assert "自动清理" in result
    finally:
        os.unlink(fp)


def test_scan_no_file():
    result = toolkit_clean_comments(action="scan", file_path="/nonexistent/file.py")
    assert "不存在" in result


def test_no_file_path():
    result = toolkit_clean_comments(action="scan", file_path="")
    assert "请指定" in result
