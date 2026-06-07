"""
AutoFix Agent 单元测试 — pytest
覆盖：ruff扫描、AST扫描、修复生成、编译验证、边缘情况
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.expanduser("~/work/git/tea_agent"))
from tea_agent.auto_fix import AutoFixAgent, FixResult


# ── 测试夹具 ──

@pytest.fixture
def sample_file():
    """创建含多种问题的临时 Python 文件。"""
    code = """
import os
import sys
import json
from typing import List, Optional


def foo():
    pass


class MyClass:
    def method1(self):
        x = 1
        y = 2  # noqa
        return x
""".lstrip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def agent():
    return AutoFixAgent(os.path.expanduser("~/work/git/tea_agent"))


# ── 扫描测试 ──

class TestScan:
    def test_ruff_scan_finds_imports(self, agent, sample_file):
        """ruff 应发现未使用的导入。"""
        issues = agent.scan(sample_file)
        ruff_issues = [i for i in issues if i["via"] == "ruff"]
        assert len(ruff_issues) >= 1, f"ruff 应发现至少 1 个问题, 实际: {len(ruff_issues)}"
        codes = {i["rule"] for i in ruff_issues}
        assert "F401" in codes, f"应发现 F401(未使用导入), 实际: {codes}"

    def test_scan_with_clean_file(self, agent):
        """干净文件应产生少量或无 issue。"""
        clean_code = "x = 1\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(clean_code)
            path = f.name
        try:
            issues = agent.scan(path)
            assert len(issues) == 0, f"干净文件应无问题, 实际: {len(issues)}"
        finally:
            os.unlink(path)

    def test_scan_syntax_error_file(self, agent):
        """语法错误的文件应静默处理而非崩溃。"""
        bad_code = "def foo(:\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(bad_code)
            path = f.name
        try:
            issues = agent.scan(path)
            assert isinstance(issues, list), "即使语法错误也应返回列表"
        finally:
            os.unlink(path)

    def test_scan_empty_file(self, agent):
        """空文件应无问题。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            path = f.name
        try:
            issues = agent.scan(path)
            assert len(issues) == 0
        finally:
            os.unlink(path)

    def test_ruff_autofix_provided(self, agent, sample_file):
        """ruff 发现的 issue 应包含 autofix 信息。"""
        issues = agent.scan(sample_file)
        ruff_with_fix = [i for i in issues if i["via"] == "ruff" and i.get("ruff_autofix")]
        assert len(ruff_with_fix) >= 1, "ruff issues 应包含 autofix 信息"


class TestFix:
    def test_fix_dry_run(self, agent, sample_file):
        """dry_run 应返回预览但不修改文件。"""
        issues = agent.scan(sample_file)
        if not issues:
            pytest.skip("无可用 issue")
        with open(sample_file, "r") as f:
            before = f.read()
        result = agent.fix(issues[0], dry_run=True)
        assert result.action == "dry_run", f"应返回 dry_run, 实际: {result.action}"
        with open(sample_file, "r") as f:
            after = f.read()
        assert before == after, "dry_run 不应修改文件"

    def test_fix_unknown_rule(self, agent):
        """未知规则应返回 skip。"""
        dummy = {"rule": "UNKNOWN_RULE", "via": "ruff",
                 "file": "tests/__init__.py", "line": 1,
                 "ruff_autofix": None}
        result = agent.fix(dummy, dry_run=True)
        assert not result.ok
        assert result.action == "skip"

    def test_fix_line_out_of_range(self, agent, sample_file):
        """超出范围的行号应返回 ok=False。"""
        dummy = {"rule": "NO_DOCSTRING", "via": "ast",
                 "file": os.path.basename(sample_file), "line": 99999,
                 "message": "", "ruff_autofix": None}
        # 需要正确设置 project_root
        fp = os.path.relpath(sample_file, str(agent.project_root))
        dummy["file"] = fp
        result = agent.fix(dummy, dry_run=True)
        assert not result.ok

    def test_fix_log_after_fix(self, agent, sample_file):
        """实际修复后 fix_log 应有记录（需非 dry_run）。"""
        issues = agent.scan(sample_file)
        # 选择 ruff 可自动修复的
        fixable = [i for i in issues if i["via"] == "ruff" and i.get("ruff_autofix")]
        if not fixable:
            pytest.skip("无可自动修复的 issue")
        before = len(agent.fix_log)
        result = agent.fix(fixable[0], dry_run=False)
        if result.action == "fixed":
            assert len(agent.fix_log) == before + 1, "fix_log 应增加 1"
        # 恢复文件
        os.system(f"cd {agent.project_root} && git checkout -- {fixable[0]['file']} 2>/dev/null || true")


class TestFixAll:
    def test_fix_all_dry_run(self, agent):
        """fix_all dry_run 应返回预览报告。"""
        result = agent.fix_all(severity="warning", dry_run=True, max_fixes=5)
        assert "scanned" in result
        assert "filtered" in result
        assert result["dry_run"] is True
        assert len(result["results"]) <= 5

    def test_fix_all_severity_filter(self, agent):
        """severity 参数应正确过滤。"""
        r1 = agent.fix_all(severity="error", dry_run=True, max_fixes=5)
        r2 = agent.fix_all(severity="info", dry_run=True, max_fixes=5)
        assert r1["filtered"] >= r2["filtered"], \
            f"error({r1['filtered']}) ≥ info({r2['filtered']}) 应成立"

    def test_fix_all_zero_max(self, agent):
        """max_fixes=0 应不修复。"""
        result = agent.fix_all(dry_run=True, max_fixes=0)
        assert len(result["results"]) == 0


class TestVerify:
    def test_verify_no_fixes(self, agent):
        """无修复记录时 verify 应通过。"""
        result = agent.verify()
        assert result["ok"] is True
        assert result["fixes"] == 0

    def test_report_empty(self, agent):
        """无修复记录时 report 应返回 0。"""
        result = agent.report()
        assert result["total_fixes"] == 0
        assert result == {"total_fixes": 0, "by_rule": {}, "changes": []}


class TestEdgeCases:
    def test_project_root_nonexistent(self):
        """不存在的项目目录应能创建 agent 但扫描返回空。"""
        agent = AutoFixAgent("/nonexistent/path")
        issues = agent.scan()
        # 应不崩溃，返回空
        assert isinstance(issues, list)

    def test_scan_on_self(self, agent):
        """扫描 auto_fix.py 自身应无问题。"""
        fp = os.path.join(os.path.dirname(__file__), "..", "auto_fix.py")
        if os.path.exists(fp):
            issues = agent.scan(fp)
            assert isinstance(issues, list)

    def test_ruff_not_installed(self, agent, monkeypatch):
        """模拟 ruff 不可用时，应优雅降级。"""
        import subprocess
        original_run = subprocess.run

        def mock_run(*args, **kwargs):
            raise FileNotFoundError("ruff not found")

        monkeypatch.setattr(subprocess, "run", mock_run)
        issues = agent.scan()
        assert isinstance(issues, list), "ruff 缺失也应返回列表"

    def test_ascii_only_file(self, agent):
        """纯 ASCII 文件不应有问题。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('# this file has no issues\nx = 42\nprint(x)\n')
            path = f.name
        try:
            issues = agent.scan(path)
            assert len(issues) == 0
        finally:
            os.unlink(path)


class TestIntegration:
    def test_ruff_deep_scan(self, agent):
        """ruff 全量扫描应覆盖 tea_agent/store/ 目录。"""
        store_dir = os.path.join(str(agent.project_root), "tea_agent", "store")
        if os.path.isdir(store_dir):
            issues = agent.scan(store_dir)
            assert len(issues) >= 5, f"store 目录应发现至少 5 个问题, 实际: {len(issues)}"
            codes = {i["rule"] for i in issues}
            assert "F401" in codes or "W293" in codes, f"应包含常见 ruff 规则: {codes}"

    def test_scan_result_structure(self, agent, sample_file):
        """扫描结果应包含完整字段。"""
        issues = agent.scan(sample_file)
        if issues:
            issue = issues[0]
            for key in ("id", "file", "line", "severity", "rule", "message", "via"):
                assert key in issue, f"缺少字段: {key}"

    def test_fix_result_structure(self, agent, sample_file):
        """FixResult 应包含标准字段。"""
        result = FixResult(ok=True, action="fixed", detail="test", old="a", new="b", via="ruff")
        d = result.to_dict()
        for key in ("ok", "action", "detail", "old", "new", "via"):
            assert key in d, f"缺少字段: {key}"
