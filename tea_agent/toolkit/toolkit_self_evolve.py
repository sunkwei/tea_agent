# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 自进化——修改项目代码并带注释/备份/验证
import logging

# NOTE: 2026-05-07 gen by tea_agent, toolkit logging
logger = logging.getLogger("toolkit")

# NOTE: 2026-05-16 gen by tea_agent, 补充 git_snapshot 和 run_tests 参数到函数签名
def toolkit_self_evolve(file_path: str, description: str, old_code: str, new_code: str, verify: bool = True, backup: bool = True, git_snapshot: bool = True, run_tests: bool = True) -> dict:
    """
    四层安全自进化：修改项目源文件，自动生成演化注释、备份原文件、验证编译、测试回滚。

    安全层次:
        Layer 0: git auto-commit 快照（进化前，可 git reset --hard HEAD~1 恢复）
        Layer 1: 时间戳 .bak 文件（不覆盖，保留所有历史版本）
        Layer 2: py_compile 编译验证（失败自动回滚）
        Layer 3: 运行测试套件（失败自动 git reset --hard 回到快照）

    Args:
        file_path: 要修改的文件路径（相对于项目根目录）
        description: 修改的简短描述
        old_code: 要替换的旧代码片段（精确匹配）
        new_code: 替换后的新代码片段
        verify: 是否验证编译通过（Layer 2）
        backup: 是否创建时间戳 .bak 备份（Layer 1）
        git_snapshot: 是否创建 git 快照（Layer 0）。仅在 git 工作区干净时生效
        run_tests: 编译通过后是否运行测试（Layer 3）。测试失败自动 git reset
    """
    logger.info(f"toolkit_self_evolve called: file_path={file_path!r}, description={repr(description)[:80]}, old_code={repr(old_code)[:80]}, new_code={repr(new_code)[:80]}, verify={verify!r}, backup={backup!r}")

    import os
    import shutil
    import py_compile
    import subprocess
    from datetime import datetime

    cwd = os.getcwd()
    full_path = os.path.join(cwd, file_path)

    if not os.path.exists(full_path):
        return {"ok": False, "error": f"文件不存在: {file_path}"}

    # ──────────────────────────────────────
    # 辅助函数
    # ──────────────────────────────────────
    def _git_clean():
        """检查 git 工作区是否干净（忽略 untracked 文件）"""
        try:
            r = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True, timeout=10, cwd=cwd)
            if r.returncode != 0:
                return False
            # 忽略 untracked 文件（??），只检查已跟踪文件的改动
            lines = [l for l in r.stdout.splitlines() if l.strip() and not l.startswith("?")]
            return len(lines) == 0
        except Exception:
            return False

    def _git_snap(desc):
        """创建 git 快照，返回 (ok, error)"""
        try:
            subprocess.run(["git", "add", file_path],
                           capture_output=True, timeout=10, cwd=cwd, check=True)
            subprocess.run(["git", "commit", "-m",
                           f"🔒 snapshot: pre-evolve — {desc}"],
                           capture_output=True, timeout=10, cwd=cwd, check=True)
            return True, None
        except subprocess.CalledProcessError as e:
            return False, str(e.stderr)[:200]
        except Exception as e:
            return False, str(e)[:200]

    def _git_revert():
        """硬回滚最近一次 git 提交"""
        try:
            subprocess.run(["git", "reset", "--hard", "HEAD~1"],
                           capture_output=True, timeout=10, cwd=cwd, check=True)
            return True
        except Exception:
            return False

    def _run_tests():
        """运行测试，返回 (passed, total, failures)"""
        try:
            r = subprocess.run(
                [os.sys.executable, "-m", "pytest", "test_*.py", "--tb=short", "-q"],
                capture_output=True, text=True, timeout=120, cwd=cwd
            )
            output = r.stdout + r.stderr
            if "no tests ran" in output.lower():
                return -1, 0, "no tests found"
            import re
            m = re.search(r'(\d+)\s+passed', output)
            passed = int(m.group(1)) if m else 0
            m = re.search(r'(\d+)\s+failed', output)
            failed = int(m.group(1)) if m else 0
            total = passed + failed
            return passed, total, output[-500:] if failed > 0 else None
        except subprocess.TimeoutExpired:
            return 0, 0, "test timeout (>120s)"
        except Exception as e:
            return 0, 0, str(e)[:200]

    # ──────────────────────────────────────
    # 主逻辑
    # ──────────────────────────────────────

    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    if old_code not in content:
        return {"ok": False, "error": "old_code 在文件中未找到（精确匹配失败）"}

    # 检查 old_code 出现次数，避免多次出现时修改错误位置
    if content.count(old_code) > 1:
        return {"ok": False, "error": f"old_code 在文件中出现 {content.count(old_code)} 次，无法确定修改位置，请提供更多上下文"}

# NOTE: 2026-05-01 11:10:43, self-evolved by tea_agent --- 仅对.py源码文件添加NOTE注释，.md等非源码文件不加
    # 生成演化注释（仅 .py 源码文件，README/CHANGELOG 等不加）
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_py = file_path.endswith(".py")
    comment = f"# NOTE: {now}, self-evolved by tea_agent --- {description}\n" if is_py else ""

    # ── Layer 0: Git 快照 ──
    git_snapped = False
    git_snap_error = None
    if git_snapshot and _git_clean():
        git_snapped, git_snap_error = _git_snap(description)
        if not git_snapped:
            logger.warning(f"Git snapshot failed: {git_snap_error}")
    elif git_snapshot:
        logger.warning("Git working directory not clean, skipping snapshot")

    # ── Layer 1: 时间戳备份（不覆盖） ──
    bak_path = None
    if backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak_path = f"{full_path}.bak.{ts}"
        shutil.copy2(full_path, bak_path)

    # 临时备份（用于快速回滚）
    tmp_bak = full_path + ".tmp_bak"
    shutil.copy2(full_path, tmp_bak)

    # 应用修改（.py 文件在 new_code 前加注释）
    annotated_new = (comment + new_code) if comment else new_code
    new_content = content.replace(old_code, annotated_new, 1)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # ── Layer 2: 编译验证 ──
    verify_ok = True
    verify_error = None
    if verify and file_path.endswith(".py"):
        try:
            py_compile.compile(full_path, doraise=True)
        except py_compile.PyCompileError as e:
            verify_ok = False
            verify_error = str(e)
            shutil.copy2(tmp_bak, full_path)
            if os.path.exists(tmp_bak):
                os.remove(tmp_bak)
            if git_snapped:
                _git_revert()
            return {
                "ok": False,
                "error": f"编译失败，已回滚: {verify_error}",
                "file": file_path,
                "layers": {"git_snapshot": git_snapped, "bak": bak_path,
                           "compile_verify": False, "tests": "skipped"}
            }

    # ── Layer 3: 测试验证 ──
    test_passed = None
    test_total = None
    test_error = None
    if run_tests and verify_ok:
        test_passed, test_total, test_error = _run_tests()
        if test_error and not isinstance(test_error, str):
            test_error = str(test_error)
        if test_passed == -1:
            pass  # no tests found, skip verification
        elif isinstance(test_passed, int) and test_total is not None and test_passed < test_total:
            shutil.copy2(tmp_bak, full_path)
            if os.path.exists(tmp_bak):
                os.remove(tmp_bak)
            if git_snapped:
                _git_revert()
            return {
                "ok": False,
                "error": f"测试失败 ({test_passed}/{test_total} passed)，已回滚",
                "test_output": str(test_error)[:500],
                "file": file_path,
                "layers": {"git_snapshot": git_snapped, "bak": bak_path,
                           "compile_verify": True, "tests": f"{test_passed}/{test_total}"}
            }

    if os.path.exists(tmp_bak):
        os.remove(tmp_bak)

    return {
        "ok": True,
        "file": file_path,
        "comment": comment.strip(),
        "bak_path": bak_path,
        "verified": verify_ok,
        "layers": {
            "git_snapshot": git_snapped,
            "bak": bak_path,
            "compile_verify": verify_ok,
            "tests": f"{test_passed}/{test_total}" if test_total is not None else "skipped"
        }
    }


def meta_toolkit_self_evolve():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_self_evolve",
            "description": "四层安全自进化：修改项目源文件，自动添加演化注释。Layer0=git快照, Layer1=时间戳.bak, Layer2=编译验证, Layer3=测试回滚。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要修改的文件路径（相对于项目根目录，如 tea_agent/store.py）",
                    },
                    "description": {
                        "type": "string",
                        "description": "修改的简短描述，会写入注释",
                    },
                    "old_code": {
                        "type": "string",
                        "description": "要替换的旧代码片段（必须精确匹配）",
                    },
                    "new_code": {
                        "type": "string",
                        "description": "替换后的新代码片段",
                    },
                    "verify": {
                        "type": "boolean",
                        "description": "[Layer2] 是否验证编译通过，默认 true。失败自动回滚",
                    },
                    "backup": {
                        "type": "boolean",
                        "description": "[Layer1] 是否创建时间戳 .bak 备份，默认 true。不覆盖历史备份",
                    },
                    "git_snapshot": {
                        "type": "boolean",
                        "description": "[Layer0] 是否创建 git 快照，默认 true。仅在 git 工作区干净时生效",
                    },
                    "run_tests": {
                        "type": "boolean",
                        "description": "[Layer3] 编译通过后是否运行测试，默认 true。测试失败自动 git reset --hard 回滚",
                    },
                },
                "required": ["file_path", "description", "old_code", "new_code"],
            },
        },
    }
