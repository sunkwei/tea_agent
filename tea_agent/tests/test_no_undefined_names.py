"""静态回归：包内不得存在未定义名（ruff F821）。

背景：2026-09-20 的 master 合并（b3e5ebf）在 ``onlinesession.py`` 中丢掉了
decode_speed 那套采样闭包的定义（``_monotonic`` / ``_now`` / ``_sample``），
却留下三处调用 —— 语法合法、``compile()`` 通过、ruff 的默认规则也不报，
直到第一次真实对话才在流消费循环里抛 ``NameError: name '_now' is not defined``
（服务器直接 500 / 对话中断）。

这类「删了定义、留了调用」的合并事故，只有未定义名检查能静态拦住。
用项目既有的 linter（ruff）而非另写 AST 检查：口径与 ``ruff check`` 完全一致，
且 ``--select F821`` 不受仓库其它 lint 债务影响。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = "tea_agent"

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="需要 ruff（项目 dev 依赖）；缺失时跳过而非把 CI 变红",
)


def test_package_has_no_undefined_names():
    """全包 F821 检查：任何未定义名（含合并丢定义留下的调用）都必须为零。"""
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--select", "F821",
         "--output-format", "concise", TARGET],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # ruff 退出码：0=无发现，1=有发现，2=用法/内部错误。把 2 也当失败暴露出来，
    # 否则 ruff 参数漂移会让这条防线静默失效（比没有测试更糟）。
    assert proc.returncode in (0, 1), (
        f"ruff 调用失败（returncode={proc.returncode}）—— 本防线失效，需要修测试:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    findings = [
        line for line in proc.stdout.splitlines()
        if ": F821 " in line or line.endswith("F821")
    ]
    assert not findings, "存在未定义名（会在运行时抛 NameError）:\n" + "\n".join(findings)
