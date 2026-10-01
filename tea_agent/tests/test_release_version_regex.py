"""回归测试: toolkit_release_version 的 pyproject 版本替换正则。

历史缺陷: 旧正则（无行首锚定）会误改 [tool.ruff] 的
target-version = "py310"（"version = ..." 是其子串）→ pyproject.toml 解析失败。
钉住行为契约: 只改 [project] 的 version 行，ruff target-version 原样保留。
"""

import re
from pathlib import Path

PYPROJECT_SAMPLE = """[build-system]
requires = ["setuptools>=61"]

[project]
name = "tea_agent"
version = "0.17.1"

[tool.ruff]
line-length = 150
target-version = "py310"
"""


class TestVersionBumpRegex:
    """regex 只应命中 [project].version 行。"""

    def test_bumps_project_version_only(self):
        new = re.sub(
            r'^version\s*=\s*["\'][^"\']+["\']',
            'version = "0.17.2"',
            PYPROJECT_SAMPLE,
            count=1,
            flags=re.MULTILINE,
        )
        assert 'version = "0.17.2"' in new
        assert 'target-version = "py310"' in new  # 误报现场必须保持原样

    def test_no_anchor_would_break_target_version(self):
        """元验证: 旧正则（无锚定）确实会破坏 target-version —— 证明契约钉得对。"""
        old_regex_result = re.sub(
            r'version\s*=\s*["\'][^"\']+["\']',
            'version = "0.17.2"',
            PYPROJECT_SAMPLE,
        )
        assert 'target-version = "0.17.2"' in old_regex_result  # 旧行为 = 缺陷

    def test_keeps_source_regex_anchored(self):
        """源码中的正则必须带 ^ 锚定 + MULTILINE + count=1（防未来回退）。"""
        src = Path(__file__).parents[2] / "tea_agent" / "toolkit" / "toolkit_release_version.py"
        code = src.read_text(encoding="utf-8")
        needle_anchored = "r'^version\\s*=\\s*[\"\\'][^\"\\']+[\"\\']'"
        needle_flags = "flags=re.MULTILINE"
        assert needle_anchored in code
        assert needle_flags in code
        assert "count=1" in code
