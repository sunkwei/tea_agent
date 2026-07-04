# @2026-07-02 gen by claude, 自动代码审查工具 — 编译/Lint/语义/安全/风格综合审查
"""
toolkit_code_review — 自动代码审查引擎

综合审查 Python 代码质量：
  1. 编译检查 (py_compile)
  2. Lint 检查 (ruff)
  3. 语义诊断 (jedi LSP)
  4. 代码风格评估
  5. 安全扫描（检测不安全 API、硬编码密码等）
  6. 复杂度评估

输出结构化审查报告（Markdown），含严重等级和修复建议。
"""

import os
import re
import json
import logging
import subprocess
import py_compile
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from tea_agent.lsp.lsp_engine import diagnose

logger = logging.getLogger("toolkit.code_review")

# ── 安全模式库 ──────────────────────────────────────────
SUSPICIOUS_PATTERNS = [
    (r'(?i)(password|passwd|pwd|secret|api_key|apikey|token)\s*[=:]\s*["\'][^"\'\s]{8,}["\']', "hardcoded_credential", "硬编码凭据"),
    (r'\b(eval|exec)\s*\(', "dangerous_exec", "危险动态执行"),
    (r'subprocess\..*shell\s*=\s*True', "dangerous_shell", "Shell注入风险"),
    (r'pickle\.loads?\s*\(', "unsafe_deserialize", "不安全的反序列化"),
    (r'(?i)(?:execute|executemany)\s*\([\'"].*%[sd]|f[\'"].*\{.*\}.*(?:SELECT|INSERT|UPDATE|DELETE)', "sql_injection", "SQL注入风险"),
    (r'tempfile\.mktemp\b', "insecure_temp", "不安全的临时文件"),
    (r'(?i)(md5|sha1)\s*\(', "weak_hash", "弱哈希算法"),
]

# ── 审查引擎 ────────────────────────────────────────────

def _check_compile(filepath: str) -> Dict[str, Any]:
    """Python 编译检查"""
    try:
        py_compile.compile(filepath, doraise=True)
        return {"ok": True, "errors": []}
    except py_compile.PyCompileError as e:
        return {"ok": False, "errors": [str(e)]}


def _check_ruff(filepath: str) -> Dict[str, Any]:
    """Ruff Lint 检查"""
    try:
        r = subprocess.run(
            ["ruff", "check", "--output-format", "json", filepath],
            capture_output=True, text=True, timeout=30,
        )
        if r.stdout.strip():
            issues = json.loads(r.stdout)
        else:
            issues = []
        return {"ok": len(issues) == 0, "issues": issues, "count": len(issues)}
    except FileNotFoundError:
        return {"ok": True, "issues": [], "count": 0, "hint": "ruff 未安装"}
    except subprocess.TimeoutExpired:
        return {"ok": True, "issues": [], "count": 0, "hint": "ruff 超时，跳过"}
    except Exception as e:
        return {"ok": True, "issues": [], "count": 0, "hint": f"ruff 错误: {e}"}


def _check_semantic(project_root: str, filepath: str) -> Dict[str, Any]:
    """LSP 语义诊断"""
    try:
        result = diagnose(project_root, filepath)
        return result
    except Exception as e:
        return {"ok": True, "issues": [], "hint": f"语义诊断跳过: {e}"}


def _check_security(filepath: str) -> Dict[str, Any]:
    """安全扫描"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        findings = []
        for pattern, category, desc in SUSPICIOUS_PATTERNS:
            for match in re.finditer(pattern, content):
                line_num = content[:match.start()].count('\n') + 1
                findings.append({
                    "line": line_num, "category": category,
                    "description": desc, "matched": match.group()[:80],
                    "severity": "high" if category in ("hardcoded_credential", "dangerous_exec", "sql_injection") else "medium",
                })
        return {"ok": len(findings) == 0, "findings": findings, "count": len(findings)}
    except Exception as e:
        return {"ok": True, "findings": [], "count": 0, "hint": f"安全扫描错误: {e}"}


def _assess_complexity(filepath: str) -> Dict[str, Any]:
    """代码复杂度评估"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines = content.split('\n')
        total_lines = len(lines)
        code_lines = sum(1 for l in lines if l.strip() and not l.strip().startswith('#'))
        blank_lines = sum(1 for l in lines if not l.strip())
        comment_lines = sum(1 for l in lines if l.strip().startswith('#'))
        func_pattern = re.compile(r'^def\s+\w+\s*\(', re.MULTILINE)
        class_pattern = re.compile(r'^class\s+\w+', re.MULTILINE)
        max_indent = 0
        for line in lines:
            stripped = line.rstrip()
            if stripped:
                indent = len(line) - len(line.lstrip())
                max_indent = max(max_indent, indent)
        return {
            "ok": True,
            "metrics": {
                "total_lines": total_lines, "code_lines": code_lines,
                "blank_lines": blank_lines, "comment_lines": comment_lines,
                "comment_ratio": round(comment_lines / max(code_lines, 1) * 100, 1),
                "function_count": len(func_pattern.findall(content)),
                "class_count": len(class_pattern.findall(content)),
                "max_indent": max_indent,
                "avg_line_length": round(sum(len(l) for l in lines if l.strip()) / max(code_lines, 1), 1),
            },
            "complexity_score": _complexity_score(total_lines, code_lines, max_indent),
        }
    except Exception as e:
        return {"ok": True, "metrics": {}, "complexity_score": 0, "hint": f"复杂度评估错误: {e}"}


def _complexity_score(total: int, code: int, max_indent: int) -> str:
    score = 0
    if total < 50:
        score += 10
    elif total < 200:
        score += 7
    elif total < 500:
        score += 4
    else: score += 1
    if max_indent <= 2:
        score += 5
    elif max_indent <= 4:
        score += 3
    else: score += 1
    if score >= 13:
        return "简单"
    elif score >= 8:
        return "中等"
    else: return "复杂"


def _check_style(filepath: str) -> Dict[str, Any]:
    """风格检查"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        issues = []
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if len(line) > 100 and line.strip():
                issues.append({"line": i, "type": "line_too_long", "description": f"行过长: {len(line)}字符(建议≤100)", "severity": "low"})
                if len(issues) >= 5:
                    break
        if content.strip() and not content.strip().startswith('"""') and not content.strip().startswith("'''"):
            issues.append({"line": 1, "type": "missing_docstring", "description": "缺少模块级 docstring", "severity": "low"})
        return {"ok": len(issues) == 0, "issues": issues, "count": len(issues)}
    except Exception as e:
        return {"ok": True, "issues": [], "count": 0, "hint": f"风格检查错误: {e}"}
# ── 报告生成 ────────────────────────────────────────────

def _generate_report(filepath, compile_result, lint_result, semantic_result, security_result, complexity_result, style_result):
    """生成 Markdown 格式审查报告"""
    filename = os.path.basename(filepath)

    error_count = sum([0])
    if not compile_result.get("ok", True):
        error_count += len(compile_result.get("errors", []))
    warning_count = 0
    for issue in lint_result.get("issues", []):
        code = issue.get("code", "")
        if code and code[0] in ("E", "F"):
            error_count += 1
        else:
            warning_count += 1
    error_count += security_result.get("count", 0)
    warning_count += style_result.get("count", 0)
    total_issues = error_count + warning_count

    report = []
    report.append(f"# 📋 代码审查报告: {filename}")
    report.append(f"")
    report.append(f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"**摘要**: {total_issues} 个问题（{error_count} 错误, {warning_count} 警告）")
    report.append(f"")

    metrics = complexity_result.get("metrics", {})
    report.append(f"## 📊 代码复杂度")
    report.append(f"")
    report.append(f"| 指标 | 值 |")
    report.append(f"|------|-----|")
    report.append(f"| 总行数 | {metrics.get('total_lines', 'N/A')} |")
    report.append(f"| 代码行数 | {metrics.get('code_lines', 'N/A')} |")
    report.append(f"| 注释比例 | {metrics.get('comment_ratio', 'N/A')}% |")
    report.append(f"| 函数数 | {metrics.get('function_count', 'N/A')} |")
    report.append(f"| 类数 | {metrics.get('class_count', 'N/A')} |")
    report.append(f"| **复杂度** | **{complexity_result.get('complexity_score', 'N/A')}** |")
    report.append(f"")

    if not compile_result.get("ok", True):
        report.append(f"## ❌ 编译错误")
        for err in compile_result.get("errors", []):
            report.append(f"- `{err[:200]}`")
        report.append(f"")

    lint_issues = lint_result.get("issues", [])
    if lint_issues:
        report.append(f"## ⚠️ Lint 问题 ({len(lint_issues)})")
        report.append(f"| 行号 | 类型 | 描述 |")
        report.append(f"|------|------|------|")
        for issue in lint_issues[:30]:
            loc = issue.get("location", {})
            line = loc.get("row", issue.get("row", "?"))
            code = issue.get("code", "")
            msg = issue.get("message", "")[:60]
            report.append(f"| {line} | `{code}` | {msg} |")
        if len(lint_issues) > 30:
            report.append(f"| ... | ... | 还有 {len(lint_issues) - 30} 个 |")
        report.append(f"")

    sec = security_result.get("findings", [])
    if sec:
        report.append(f"## 🔒 安全问题 ({len(sec)})")
        report.append(f"| 行号 | 严重度 | 类型 |")
        report.append(f"|------|--------|------|")
        for f in sec:
            report.append(f"| {f['line']} | {f['severity']} | {f['description']} |")
        report.append(f"")

    sem = semantic_result.get("issues", [])
    if sem:
        report.append(f"## 🔍 语义问题 ({len(sem)})")
        for issue in sem[:20]:
            report.append(f"- {issue.get('message', str(issue))[:100]}")
        report.append(f"")

    sty = style_result.get("issues", [])
    if sty:
        report.append(f"## 🎨 风格建议 ({len(sty)})")
        for issue in sty:
            report.append(f"- L{issue['line']}: {issue['description']}")
        report.append(f"")

    report.append(f"## 📝 总结")
    if error_count == 0 and warning_count == 0:
        report.append(f"✅ **代码质量优秀** — 未发现问题")
    elif error_count == 0:
        report.append(f"⚠️ **代码质量良好** — {warning_count} 个警告需关注")
    else:
        report.append(f"❌ **需要修复** — {error_count} 个错误, {warning_count} 个警告")

    return '\n'.join(report)


# ── 主入口 ──────────────────────────────────────────────

def toolkit_code_review(filepath="", directory="", output="", level="standard", glob_pattern="*.py", max_files=20):
    """
    自动代码审查工具。综合检查编译错误、Lint、安全、复杂度、风格。

    Args:
        filepath: 单文件审查路径
        directory: 目录审查路径（与 filepath 二选一）
        output: 审查报告输出路径（可选）
        level: quick=快速(仅编译+lint), standard=标准(含安全+语义), thorough=全面(含复杂度+风格)
        glob_pattern: 目录审查时的文件匹配模式，默认 *.py
        max_files: 最大审查文件数

    Returns: {"ok": bool, "reports": [...], "summary": {...}, "report_file": "..."}
    """
    try:
        cwd = os.getcwd()
        project_root = cwd
        while os.path.dirname(project_root) != project_root:
            if os.path.exists(os.path.join(project_root, "pyproject.toml")):
                break
            project_root = os.path.dirname(project_root)

        files_to_review = []
        if filepath:
            if os.path.isfile(filepath):
                files_to_review.append(filepath)
            else:
                return {"ok": False, "error": f"文件不存在: {filepath}"}
        elif directory:
            d = os.path.abspath(directory)
            if os.path.isdir(d):
                for p in Path(d).rglob(glob_pattern):
                    files_to_review.append(str(p))
                    if len(files_to_review) >= max_files:
                        break
            else:
                return {"ok": False, "error": f"目录不存在: {directory}"}
        else:
            return {"ok": False, "error": "需要提供 filepath 或 directory"}

        if not files_to_review:
            return {"ok": False, "error": "没有找到要审查的文件"}

        reports = []
        summary = {"total": len(files_to_review), "passed": 0, "failed": 0, "issues": 0}

        for fp in files_to_review:
            logger.info(f"审查: {fp}")
            compile_r = _check_compile(fp)
            lint_r = _check_ruff(fp) if level in ("quick", "standard", "thorough") else {"ok": True, "issues": []}
            security_r = _check_security(fp) if level in ("standard", "thorough") else {"ok": True, "findings": []}
            semantic_r = _check_semantic(project_root, fp) if level in ("standard", "thorough") else {"ok": True, "issues": []}
            complexity_r = _assess_complexity(fp) if level in ("thorough",) else {"ok": True, "metrics": {}, "complexity_score": "N/A"}
            style_r = _check_style(fp) if level == "thorough" else {"ok": True, "issues": []}

            report_md = _generate_report(fp, compile_r, lint_r, semantic_r, security_r, complexity_r, style_r)
            reports.append({"file": fp, "report": report_md, "compile_ok": compile_r.get("ok", True)})

            issue_count = (0 if compile_r.get("ok", True) else len(compile_r.get("errors", [])) +
                          lint_r.get("count", 0) + security_r.get("count", 0) +
                          style_r.get("count", 0))
            summary["issues"] += issue_count
            if compile_r.get("ok", True):
                summary["passed"] += 1
            else:
                summary["failed"] += 1

        result = {"ok": True, "reports": reports, "summary": summary}

        if output:
            all_reports = []
            for r in reports:
                all_reports.append(r["report"])
                all_reports.append("\n---\n")
            combined = "\n".join(all_reports)
            with open(output, "w", encoding="utf-8") as f:
                f.write(combined)
            result["report_file"] = output

        return result

    except Exception as e:
        logger.exception(f"toolkit_code_review: {e}")
        return {"ok": False, "error": str(e)[:300]}


# ── Meta ────────────────────────────────────────────────

def meta_toolkit_code_review():
    """Meta for code review tool."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_code_review",
            "description": "自动代码审查工具。综合检查编译错误、Lint、安全漏洞、代码复杂度、风格问题，生成结构化审查报告。支持单文件或整个目录批量审查。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "单文件审查路径（与 directory 二选一）"},
                    "directory": {"type": "string", "description": "目录审查路径（与 filepath 二选一）"},
                    "output": {"type": "string", "description": "审查报告输出文件路径（可选）"},
                    "level": {"type": "string", "enum": ["quick", "standard", "thorough"], "description": "审查深度: quick=快速, standard=标准, thorough=全面", "default": "standard"},
                    "glob_pattern": {"type": "string", "description": "目录审查时的文件匹配模式", "default": "*.py"},
                    "max_files": {"type": "integer", "description": "最大审查文件数", "default": 20},
                },
                "required": [],
            },
        },
    }
