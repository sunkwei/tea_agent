"""共享 LSP 检查：影响分析 + ruff lint 前后对比 + 签名变更检测。

使用方: toolkit_self_evolve, toolkit_edit, toolkit_diff
"""

import os
import re
import json
import tempfile
import subprocess
import logging

logger = logging.getLogger("toolkit")


def run_lsp_check(
    file_path: str,
    symbol: str = None,
    old_code: str = None,
    new_code: str = None,
    cwd: str = None,
) -> dict:
    """Layer 2.5: 影响分析 + ruff lint + 签名对比。非阻塞——异常均静默处理。

    Args:
        file_path: 修改后的文件完整路径
        symbol: 被修改的函数/类名（可选，用于影响分析+签名对比）
        old_code: 修改前的代码片段（用于 lint before + 签名提取）
        new_code: 修改后的代码片段（用于签名提取）
        cwd: 工作目录

    Returns:
        {"impact": {...}|None, "lint_before": int, "lint_after": int, "lint_new": int,
         "sig_changed": bool, "old_sig": str|None, "new_sig": str|None}
    """
    result = {
        "impact": None,
        "lint_before": 0,
        "lint_after": 0,
        "lint_new": 0,
        "sig_changed": False,
        "old_sig": None,
        "new_sig": None,
    }

    cwd = cwd or os.getcwd()

    try:
        if symbol:
            try:
                from tea_agent.lsp.ts_analyzer import impact_analysis
                imp = impact_analysis(cwd, file_path, symbol)
                if imp and imp.get("ok"):
                    result["impact"] = {
                        "callers": len(imp.get("direct_callers", [])),
                        "deps": imp.get("dependencies", []),
                        "risk": imp.get("risk", "unknown"),
                        "hint": imp.get("hint", ""),
                    }
            except Exception:
                pass

        if old_code is not None:
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False
                ) as tf:
                    tf.write(old_code)
                    tmp_b = tf.name
                r = subprocess.run(
                    ["ruff", "check", "--output-format", "json", tmp_b],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    cwd=cwd,
                )
                if r.stdout.strip():
                    result["lint_before"] = len(json.loads(r.stdout))
            except Exception:
                pass
            finally:
                try:
                    os.unlink(tmp_b)
                except Exception:
                    pass

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as tf:
                with open(file_path, encoding="utf-8") as f:
                    tf.write(f.read())
                tmp_a = tf.name
            r = subprocess.run(
                ["ruff", "check", "--output-format", "json", tmp_a],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=cwd,
            )
            if r.stdout.strip():
                result["lint_after"] = len(json.loads(r.stdout))
            result["lint_new"] = max(0, result["lint_after"] - result["lint_before"])
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp_a)
            except Exception:
                pass

        if symbol and old_code is not None and new_code is not None:
            try:
                pat = rf"def\s+{re.escape(symbol)}\s*\([^)]*\)"
                m = re.search(pat, old_code)
                result["old_sig"] = m.group(0).strip() if m else None
                m = re.search(pat, new_code)
                result["new_sig"] = m.group(0).strip() if m else None
                if (
                    result["old_sig"]
                    and result["new_sig"]
                    and result["old_sig"] != result["new_sig"]
                ):
                    result["sig_changed"] = True
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"LSP checks: {e}")

    return result
