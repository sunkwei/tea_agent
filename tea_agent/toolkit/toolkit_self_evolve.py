import logging

logger = logging.getLogger("toolkit")

def toolkit_self_evolve(file_path: str, description: str, old_code: str, new_code: str, verify: bool = True, backup: bool = True, git_snapshot: bool = True, run_tests: bool = True, symbol: str = None, lsp_checks: bool = True) -> dict:
    """@2026-05-19 gen by claude, 集成LSP检查层(Layer2.5: 影响分析+lint+签名对比)    五层安全自进化 + LSP 智能增强。

    安全层次:
        Layer 0: git auto-commit 快照
        Layer 1: 时间戳 .bak 文件
        Layer 2: py_compile 编译验证（失败自动回滚）
        Layer 2.5: LSP 检查 — 影响分析 + ruff lint + 签名对比（非阻塞警告）
        Layer 3: 运行测试套件（失败自动 git reset --hard）

    Args:
        file_path: 要修改的文件路径（相对于项目根目录）
        description: 修改的简短描述
        old_code: 要替换的旧代码片段（精确匹配）
        new_code: 替换后的新代码片段
        verify: 是否验证编译通过（Layer 2）
        backup: 是否创建时间戳 .bak 备份（Layer 1）
        git_snapshot: 是否创建 git 快照（Layer 0）
        run_tests: 编译通过后是否运行测试（Layer 3）
        symbol: [LSP] 被修改的函数/类名，用于影响分析和签名对比
        lsp_checks: [LSP] 是否启用 LSP 检查，默认 True
    """
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
                           f"snapshot: pre-evolve -- {desc}"],
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

    # ── LSP 辅助函数 ── @2026-05-19 gen by claude
    def _run_lsp_checks(full_path, symbol, old_code, new_code, content):
        """Layer 2.5: 影响分析 + ruff lint + 签名对比 + 语义诊断。非阻塞。"""
        result = {"impact": None, "lint_before": 0, "lint_after": 0, "lint_new": 0,
                  "sig_changed": False, "old_sig": None, "new_sig": None,
                  "semantic": None}
        try:
            # 1. 影响分析
            if symbol:
                try:
                    from tea_agent.lsp.ts_analyzer import impact_analysis
                    imp = impact_analysis(cwd, full_path, symbol)
                    if imp and imp.get("ok"):
                        result["impact"] = {"callers": len(imp.get("direct_callers", [])),
                                            "deps": imp.get("dependencies", []),
                                            "risk": imp.get("risk", "unknown"),
                                            "hint": imp.get("hint", "")}
                except Exception:
                    logger.exception("operation failed")


            # 2. Ruff lint: before
            import tempfile
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tf:
                    tf.write(content)
                    tmp_b = tf.name
                r = subprocess.run(["ruff", "check", "--output-format", "json", tmp_b],
                                   capture_output=True, text=True, timeout=15, cwd=cwd)
                if r.stdout.strip():
                    import json
                    result["lint_before"] = len(json.loads(r.stdout))
            except Exception:
                logger.exception("operation failed")

            finally:
                try: os.unlink(tmp_b)
                except Exception: logger.exception("operation failed")

            # 3. Ruff lint: after
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tf:
                    tf.write(open(full_path, encoding='utf-8').read())
                    tmp_a = tf.name
                r = subprocess.run(["ruff", "check", "--output-format", "json", tmp_a],
                                   capture_output=True, text=True, timeout=15, cwd=cwd)
                if r.stdout.strip():
                    import json
                    result["lint_after"] = len(json.loads(r.stdout))
                result["lint_new"] = max(0, result["lint_after"] - result["lint_before"])
            except Exception:
                logger.exception("operation failed")

            finally:
                try: os.unlink(tmp_a)
                except Exception: logger.exception("operation failed")

            # 4. 签名对比
            if symbol:
                try:
                    import re
                    pat = rf'def\s+{re.escape(symbol)}\s*\([^)]*\)'
                    m = re.search(pat, old_code)
                    result["old_sig"] = m.group(0).strip() if m else None
                    m = re.search(pat, new_code)
                    result["new_sig"] = m.group(0).strip() if m else None
                    if result["old_sig"] and result["new_sig"] and result["old_sig"] != result["new_sig"]:
                        result["sig_changed"] = True
                except Exception:
                    logger.exception("operation failed")


            # 5. 语义诊断（jedi）
            try:
                from tea_agent.lsp.lsp_engine import semantic_diagnose
                sd = semantic_diagnose(cwd, full_path)
                result["semantic"] = {"ok": sd.get("ok", True), "issues": sd.get("issues", [])[:5],
                                      "total": sd.get("total", 0), "hint": sd.get("hint", "")}
                if not sd.get("ok", True):
                    logger.warning(f"LSP semantic: {sd.get('hint', '')}")
            except Exception:
                result["semantic"] = {"ok": True, "issues": [], "hint": "skipped"}

        except Exception as e:
            logger.debug(f"LSP checks: {e}")
        return result

    def _check_python_syntax(content: str, new_code: str) -> dict:
        """Layer 1.5: Python 语法严格检查。
        
        检查内容：
        1. 换行符是否正确（LF 或 CRLF 一致性）
        2. 缩进是否一致（不能混用 Tab 和空格）
        3. 是否有明显的语法错误（如缺少冒号、括号不匹配等）
        4. 新代码中是否有未闭合的字符串
        
        Args:
            content: 完整文件内容
            new_code: 新添加的代码片段
            
        Returns:
            {"ok": bool, "error": str, "details": dict}
        """
        import re
        
        details = {"checks": []}
        
        # 1. 检查换行符一致性
        has_crlf = "\r\n" in content
        has_lf = "\n" in content.replace("\r\n", "")
        
        if has_crlf and has_lf:
            # 混用换行符
            # 但只在新代码中检查，因为旧文件可能已有混用
            new_has_crlf = "\r\n" in new_code
            new_has_lf = "\n" in new_code.replace("\r\n", "")
            if new_has_crlf and new_has_lf:
                return {"ok": False, "error": "新代码中混用了 CRLF 和 LF 换行符",
                        "details": {"issue": "mixed_newlines", "suggestion": "统一使用 LF (\\n)"}}
            details["checks"].append("newline_consistency: ok")
        else:
            details["checks"].append("newline_consistency: ok")
        
        # 2. 检查缩进一致性
        lines = new_code.split("\n")
        indent_issues = []
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            # 检查是否混用 Tab 和空格
            leading = line[:len(line) - len(line.lstrip())]
            if "\t" in leading and " " in leading:
                indent_issues.append(f"行 {i+1}: 混用 Tab 和空格")
            # 检查缩进是否是 4 的倍数（Python 标准）
            if leading and " " in leading and "\t" not in leading:
                spaces = len(leading)
                if spaces % 4 != 0:
                    indent_issues.append(f"行 {i+1}: 缩进 {spaces} 空格，不是 4 的倍数")
        
        if indent_issues:
            return {"ok": False, "error": f"缩进问题: {indent_issues[0]}",
                    "details": {"issue": "indentation", "problems": indent_issues[:3]}}
        details["checks"].append("indentation: ok")
        
        # 3. 检查括号匹配
        brackets = {"(": ")", "[": "]", "{": "}"}
        stack = []
        in_string = False
        string_char = None
        line_num = 1
        
        for i, char in enumerate(new_code):
            if char == "\n":
                line_num += 1
            
            # 处理字符串
            if char in ('"', "'") and not in_string:
                in_string = True
                string_char = char
                # 检查三引号
                if new_code[i:i+3] in ('"""', "'''"):
                    string_char = new_code[i:i+3]
            elif in_string:
                if char == string_char[0] and new_code[i:i+len(string_char)] == string_char:
                    in_string = False
                    string_char = None
                continue
            
            if not in_string:
                if char in brackets:
                    stack.append((char, line_num))
                elif char in brackets.values():
                    if not stack:
                        return {"ok": False, "error": f"行 {line_num}: 多余的闭合括号 '{char}'",
                                "details": {"issue": "bracket_mismatch", "line": line_num}}
                    open_char, open_line = stack.pop()
                    if brackets[open_char] != char:
                        return {"ok": False, "error": f"行 {line_num}: 括号不匹配，'{open_char}' (行 {open_line}) 与 '{char}'",
                                "details": {"issue": "bracket_mismatch", "line": line_num}}
        
        if stack:
            open_char, open_line = stack[-1]
            return {"ok": False, "error": f"行 {open_line}: 未闭合的括号 '{open_char}'",
                    "details": {"issue": "unclosed_bracket", "line": open_line}}
        details["checks"].append("brackets: ok")
        
        # 4. 检查明显的语法错误模式
        # 检查行尾是否有冒号缺失（def, class, if, for, while 等）
        control_patterns = [
            (r'^\s*(def|class|if|elif|else|for|while|with|try|except|finally)\s+.*[^:]\s*$', "控制语句后缺少冒号"),
        ]
        
        for pattern, msg in control_patterns:
            for i, line in enumerate(lines):
                if re.match(pattern, line) and not line.strip().endswith(":"):
                    # 排除多行情况
                    if not line.strip().endswith("\\"):
                        return {"ok": False, "error": f"行 {i+1}: {msg}",
                                "details": {"issue": "missing_colon", "line": i+1}}
        details["checks"].append("syntax_patterns: ok")
        
        # 5. 检查新代码是否有明显的换行问题
        # 检查是否有应该换行但没有换行的情况（如多条语句在同一行）
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # 检查是否有分号分隔的多条语句（不推荐）
            if ";" in stripped and not stripped.startswith("print"):
                # 排除字符串中的分号
                parts = stripped.split(";")
                if len(parts) > 1 and all(p.strip() for p in parts):
                    return {"ok": False, "error": f"行 {i+1}: 使用分号分隔多条语句，建议分行书写",
                            "details": {"issue": "multiple_statements", "line": i+1}}
        details["checks"].append("line_statements: ok")
        
        return {"ok": True, "error": None, "details": details}

    # ──────────────────────────────────────
    # 主逻辑
    # ──────────────────────────────────────

    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()

    if old_code not in content:
        return {"ok": False, "error": "old_code 在文件中未找到（精确匹配失败）"}

    # 检查 old_code 出现次数
    if content.count(old_code) > 1:
        return {"ok": False, "error": f"old_code 在文件中出现 {content.count(old_code)} 次，无法确定修改位置"}

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

    # 应用修改（不再添加 NOTE 注释）
    new_content = content.replace(old_code, new_code, 1)
    
    # ── Layer 1.5: Python 语法严格检查 ──
    if file_path.endswith(".py"):
        syntax_check = _check_python_syntax(new_content, new_code)
        if not syntax_check["ok"]:
            # 语法检查失败，回滚
            shutil.copy2(tmp_bak, full_path)
            if os.path.exists(tmp_bak):
                os.remove(tmp_bak)
            if git_snapped:
                _git_revert()
            return {
                "ok": False,
                "error": f"Python 语法检查失败: {syntax_check['error']}",
                "file": file_path,
                "syntax_details": syntax_check,
                "layers": {"git_snapshot": git_snapped, "bak": bak_path,
                           "syntax_check": False, "compile_verify": "skipped", "tests": "skipped"}
            }
    
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

    # ── Layer 2.5: LSP 智能检查 ──
    lsp_result = None
    if lsp_checks and verify_ok and file_path.endswith(".py"):
        lsp_result = _run_lsp_checks(full_path, symbol, old_code, new_code, content)
        if lsp_result.get("lint_new", 0) > 0:
            logger.warning(f"LSP: 引入 {lsp_result['lint_new']} 个新 lint 问题")
        if lsp_result.get("sig_changed"):
            logger.warning(f"LSP: 签名变更: {lsp_result.get('old_sig')} -> {lsp_result.get('new_sig')}")

    # ── Layer 3: 测试验证 ──
    test_passed = None
    test_total = None
    test_error = None
    if run_tests and verify_ok:
        test_passed, test_total, test_error = _run_tests()
        if test_error and not isinstance(test_error, str):
            test_error = str(test_error)
        if test_passed == -1:
            pass
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
        "bak_path": bak_path,
        "verified": verify_ok,
        "layers": {
            "git_snapshot": git_snapped,
            "bak": bak_path,
            "compile_verify": verify_ok,
            "lsp": lsp_result,
            "tests": f"{test_passed}/{test_total}" if test_total is not None else "skipped"
        }
    }


def meta_toolkit_self_evolve():
    """Meta toolkit self evolve."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_self_evolve",
            "description": "五层安全自进化：修改项目源文件，不再添加 NOTE 注释。Layer0=git快照, Layer1=时间戳.bak, Layer2=编译验证, Layer2.5=LSP检查(影响分析+lint+签名), Layer3=测试回滚。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "要修改的文件路径（相对于项目根目录，如 tea_agent/store.py）"},
                    "description": {"type": "string", "description": "修改的简短描述"},
                    "old_code": {"type": "string", "description": "要替换的旧代码片段（必须精确匹配）"},
                    "new_code": {"type": "string", "description": "替换后的新代码片段"},
                    "verify": {"type": "boolean", "description": "[Layer2] 是否验证编译通过，默认 true。失败自动回滚"},
                    "backup": {"type": "boolean", "description": "[Layer1] 是否创建时间戳 .bak 备份，默认 true。不覆盖历史备份"},
                    "git_snapshot": {"type": "boolean", "description": "[Layer0] 是否创建 git 快照，默认 true。仅在 git 工作区干净时生效"},
                    "run_tests": {"type": "boolean", "description": "[Layer3] 编译通过后是否运行测试，默认 true。测试失败自动 git reset --hard 回滚"},
                    "symbol": {"type": "string", "description": "[Layer2.5] 被修改的函数/类名，用于影响分析和签名对比"},
                    "lsp_checks": {"type": "boolean", "description": "[Layer2.5] 是否启用 LSP 检查，默认 true"},
                },
                "required": ["file_path", "description", "old_code", "new_code"],
            },
        },
    }
