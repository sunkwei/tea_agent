"""Tests for toolkit_code_review module."""

import os
import tempfile

from tea_agent.toolkit.toolkit_code_review import (
    _check_compile,
    _check_security,
    _assess_complexity,
    _check_style,
    _complexity_score,
    _generate_report,
)


def test_check_compile_ok():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("x = 1\n")
        fpath = f.name
    try:
        result = _check_compile(fpath)
        assert result["ok"] is True
        assert result["errors"] == []
    finally:
        os.unlink(fpath)


def test_check_compile_syntax_error():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("def foo(:\n")
        fpath = f.name
    try:
        result = _check_compile(fpath)
        assert result["ok"] is False
        assert len(result["errors"]) > 0
    finally:
        os.unlink(fpath)


def test_check_security_no_findings():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("x = 1\nprint(x)\n")
        fpath = f.name
    try:
        result = _check_security(fpath)
        assert result["ok"] is True
        assert result["count"] == 0
    finally:
        os.unlink(fpath)


def test_check_security_hardcoded_credential():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('api_key = "sk-12345678901234567890"\n')
        fpath = f.name
    try:
        result = _check_security(fpath)
        assert result["count"] >= 1
        assert result["findings"][0]["category"] == "hardcoded_credential"
    finally:
        os.unlink(fpath)


def test_check_security_dangerous_exec():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('eval("print(1)")\n')
        fpath = f.name
    try:
        result = _check_security(fpath)
        assert result["count"] >= 1
        assert result["findings"][0]["category"] == "dangerous_exec"
    finally:
        os.unlink(fpath)


def test_assess_complexity():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("\n".join([
            "import os",
            "",
            "def foo():",
            "    pass",
            "",
            "class Bar:",
            "    pass",
        ]))
        fpath = f.name
    try:
        result = _assess_complexity(fpath)
        assert result["ok"] is True
        m = result["metrics"]
        assert m["function_count"] >= 1
        assert m["class_count"] >= 1
        assert m["total_lines"] >= 6
    finally:
        os.unlink(fpath)


def test_assess_complexity_empty():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("")
        fpath = f.name
    try:
        result = _assess_complexity(fpath)
        assert result["ok"] is True
        assert result["metrics"]["total_lines"] <= 1
    finally:
        os.unlink(fpath)


def test_complexity_score_simple():
    assert _complexity_score(30, 20, 1) == "简单"


def test_complexity_score_complex():
    assert _complexity_score(600, 400, 10) == "复杂"


def test_check_style_line_too_long():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("x = " + "a" * 120 + "\n")
        fpath = f.name
    try:
        result = _check_style(fpath)
        assert result["ok"] is False
        assert any(i["type"] == "line_too_long" for i in result["issues"])
    finally:
        os.unlink(fpath)


def test_check_style_clean():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('"""Module docstring."""\n\nx = 1\n')
        fpath = f.name
    try:
        result = _check_style(fpath)
        assert result["ok"] is True
    finally:
        os.unlink(fpath)


def test_generate_report_empty_issues():
    compile_r = {"ok": True, "errors": []}
    lint_r = {"ok": True, "issues": [], "count": 0}
    semantic_r = {"ok": True, "issues": []}
    security_r = {"ok": True, "findings": [], "count": 0}
    complexity_r = {"ok": True, "metrics": {"total_lines": 10, "code_lines": 8, "blank_lines": 1, "comment_lines": 1,
                                             "comment_ratio": 12.5, "function_count": 1, "class_count": 0, "max_indent": 4,
                                             "avg_line_length": 20.0}, "complexity_score": "简单"}
    style_r = {"ok": True, "issues": [], "count": 0}
    report = _generate_report("test.py", compile_r, lint_r, semantic_r, security_r, complexity_r, style_r)
    assert "代码质量优秀" in report
    assert "0 个问题" in report


def test_generate_report_with_issues():
    compile_r = {"ok": False, "errors": ["SyntaxError: invalid syntax"]}
    lint_r = {"ok": False, "issues": [{"code": "F401", "location": {"row": 1, "column": 1}, "message": "unused import"}], "count": 1}
    semantic_r = {"ok": True, "issues": [{"type": "unresolved_reference", "name": "foo", "line": 2, "column": 0, "message": "undef"}], "total": 1}
    security_r = {"ok": False, "findings": [{"line": 1, "severity": "high", "category": "dangerous_exec", "description": "危险动态执行", "matched": "eval"}], "count": 1}
    complexity_r = {"ok": True, "metrics": {"total_lines": 50, "code_lines": 40}, "complexity_score": "中等"}
    style_r = {"ok": False, "issues": [{"line": 1, "type": "line_too_long", "description": "行过长: 120字符", "severity": "low"}], "count": 1}
    report = _generate_report("test.py", compile_r, lint_r, semantic_r, security_r, complexity_r, style_r)
    assert "需要修复" in report
    assert "SyntaxError" in report
    assert "F401" in report
    assert "危险动态执行" in report
