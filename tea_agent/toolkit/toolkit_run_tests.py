# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 运行项目测试套件
def toolkit_run_tests(pattern: str = "test_*.py") -> dict:
    """
    运行项目中的测试文件。
    
    Args:
        pattern: 测试文件匹配模式，默认 'test_*.py' 运行所有测试
    """
    import subprocess
    import sys
    from pathlib import Path

    cwd = Path.cwd()
    test_files = sorted(cwd.glob(pattern))

    if not test_files:
        return {"ok": False, "error": f"未找到匹配 '{pattern}' 的测试文件", "cwd": str(cwd)}

    results = {}
    passed = 0
    failed = 0

    for tf in test_files:
        try:
            r = subprocess.run(
                [sys.executable, str(tf)],
                capture_output=True, text=True, timeout=60, cwd=str(cwd)
            )
            ok = r.returncode == 0
            if ok:
                passed += 1
            else:
                failed += 1
            results[tf.name] = {
                "ok": ok,
                "exit_code": r.returncode,
                "stdout": r.stdout[-1000:] if len(r.stdout) > 1000 else r.stdout,
                "stderr": r.stderr[-500:] if len(r.stderr) > 500 else r.stderr,
            }
        except subprocess.TimeoutExpired:
            failed += 1
            results[tf.name] = {"ok": False, "error": "超时 (>60s)"}
        except Exception as e:
            failed += 1
            results[tf.name] = {"ok": False, "error": str(e)}

    return {
        "ok": failed == 0,
        "total": len(test_files),
        "passed": passed,
        "failed": failed,
        "files": results,
    }


def meta_toolkit_run_tests():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_run_tests",
            "description": "运行项目测试文件（默认 test_*.py），返回通过/失败统计和每项详情。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "测试文件 glob 模式，默认 'test_*.py'",
                    },
                },
                "required": [],
            },
        },
    }
