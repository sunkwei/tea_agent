# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 运行项目测试套件
import logging

logger = logging.getLogger("toolkit")

def toolkit_run_tests(pattern: str = "test_*.py") -> dict:
    """
    运行项目中的测试文件（通过 pytest，glob 显式展开）。

    Args:
        pattern: 测试文件匹配模式，默认 'test_*.py' 运行所有测试
    """
    logger.info(f"toolkit_run_tests called: pattern={pattern!r}")

    import glob
    import os
    import re
    import subprocess
    import sys

    cwd = os.getcwd()
    # 同时收集当前目录与 tea_agent/tests/ 下的测试文件（subprocess 无 shell，需显式展开 glob）
    test_files = sorted(set(
        glob.glob(pattern) + glob.glob(os.path.join("tea_agent", "tests", pattern))
    ))
    test_files = [t for t in test_files if os.path.exists(t)]

    if not test_files:
        return {"ok": False, "error": f"未找到匹配 '{pattern}' 的测试文件", "cwd": cwd}

    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *test_files, "-q", "--tb=short"],
            capture_output=True, text=True, timeout=300, cwd=cwd,
        )
        output = r.stdout + r.stderr
        m = re.search(r'(\d+)\s+passed', output)
        passed = int(m.group(1)) if m else 0
        m = re.search(r'(\d+)\s+failed', output)
        failed = int(m.group(1)) if m else 0
        # pytest 统计可能是复数 "errors" 也可能是单数 "1 error"
        m = re.search(r'(\d+)\s+error', output)
        errors = int(m.group(1)) if m else 0
        return {
            "ok": r.returncode == 0,
            "total": passed + failed + errors,
            "passed": passed,
            "failed": failed + errors,
            "returncode": r.returncode,
            "output": output[-1500:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "测试超时 (>300s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def meta_toolkit_run_tests() -> dict:
    """Meta toolkit run tests."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_run_tests",
            "description": "运行项目测试套件（python -m pytest）。glob 显式展开当前目录与 tea_agent/tests/ 下的测试文件。返回 passed/failed/errors/total。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "测试文件匹配模式，默认 'test_*.py' 运行所有测试",
                        "default": "test_*.py",
                    }
                },
            },
        },
    }
