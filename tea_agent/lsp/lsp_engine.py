"""
@2026-05-19 gen by claude, LSP 引擎 — 基于 jedi + ruff 的实时代码智能
提供：诊断(diagnose) / 补全(completion) / 跳转定义(definition) / 悬停(hover) / 引用(references)

依赖: jedi (代码智能), ruff (诊断), tree-sitter (语法树)
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
import logging

logger = logging.getLogger("lsp")

# ── Jedi 智能后端 ────────────────────────────────────────────

def _get_jedi_project(project_root: str):
    """获取 jedi Project 实例"""
    import jedi
    return jedi.Project(project_root)

def _read_file_safe(filepath: str) -> Optional[str]:
    """安全读取文件"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def diagnose(project_root: str, filepath: str = None) -> Dict:
    """运行 ruff 诊断，返回 (ok, diagnostics, error)"""
    try:
        target = filepath or project_root
        # 只检查 Python 文件
        if filepath and not filepath.endswith(".py"):
            target = project_root

        result = subprocess.run(
            ["ruff", "check", "--output-format", "json", target],
            capture_output=True, text=True,
            timeout=30,
            cwd=project_root,
        )

        if result.returncode == 0:
            return {"ok": True, "diagnostics": [], "total": 0, "hint": "无问题 ✓"}

        import json
        diagnostics = json.loads(result.stdout) if result.stdout.strip() else []
        # 按严重程度分组
        errors = [d for d in diagnostics if d.get("fix") is None or d.get("code", "").startswith("F")]
        warnings = [d for d in diagnostics if d.get("fix") is not None and not d.get("code", "").startswith("F")]

        summary = []
        if errors:
            summary.append(f"{len(errors)} 错误")
        if warnings:
            summary.append(f"{len(warnings)} 警告")

        return {
            "ok": True,
            "diagnostics": diagnostics,
            "total": len(diagnostics),
            "errors": len(errors),
            "warnings": len(warnings),
            "hint": f"发现 {', '.join(summary)}" if summary else "无问题",
            "items": [_fmt_diagnostic(d) for d in diagnostics[:20]],  # 最多20条
        }
    except FileNotFoundError:
        return {"ok": False, "error": "ruff 未安装，请运行: pip install ruff"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _fmt_diagnostic(d: Dict) -> str:
    """格式化单条诊断为可读字符串"""
    loc = f"{d.get('filename', '')}:{d.get('location', {}).get('row', '?')}:{d.get('location', {}).get('column', '?')}"
    code = d.get("code", "?")
    msg = d.get("message", "")
    fix = d.get("fix", {})
    fix_hint = f" (可自动修复: {fix.get('message', '')})" if fix else ""
    return f"[{code}] {loc}\n  {msg}{fix_hint}"

def completion(project_root: str, filepath: str, line: int, col: int) -> Dict:
    """代码补全 — 基于 jedi"""
    try:
        source = _read_file_safe(filepath)
        if source is None:
            return {"ok": False, "error": f"无法读取文件: {filepath}"}

        import jedi
        script = jedi.Script(source, path=filepath, project=_get_jedi_project(project_root))
        completions = script.complete(line, col)

        items = []
        for c in completions[:15]:  # 最多15条
            items.append({
                "name": c.name,
                "complete": c.complete,
                "type": c.type,
                "description": c.description[:200] if c.description else "",
                "docstring": c.docstring(raw=True)[:300] if c.docstring(raw=True) else "",
            })

        return {
            "ok": True,
            "completions": items,
            "total": len(completions),
            "hint": f"位置 {line}:{col} 找到 {len(completions)} 条补全",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def goto_definition(project_root: str, filepath: str, line: int, col: int) -> Dict:
    """跳转到定义 — 基于 jedi"""
    try:
        source = _read_file_safe(filepath)
        if source is None:
            return {"ok": False, "error": f"无法读取文件: {filepath}"}

        import jedi
        script = jedi.Script(source, path=filepath, project=_get_jedi_project(project_root))
        definitions = script.goto(line, col)

        items = []
        for d in definitions:
            items.append({
                "name": d.name,
                "type": d.type,
                "module": d.module_name or "",
                "file": str(d.module_path) if d.module_path else "",
                "line": d.line,
                "column": d.column,
                "description": d.description[:300] if d.description else "",
            })

        return {
            "ok": True,
            "definitions": items,
            "hint": f"找到 {len(items)} 个定义" if items else "未找到定义",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def hover(project_root: str, filepath: str, line: int, col: int) -> Dict:
    """悬停信息 — 类型 + docstring"""
    try:
        source = _read_file_safe(filepath)
        if source is None:
            return {"ok": False, "error": f"无法读取文件: {filepath}"}

        import jedi
        script = jedi.Script(source, path=filepath, project=_get_jedi_project(project_root))

        # 获取当前位置的签名/帮助
        signatures = script.get_signatures(line, col)
        definitions = script.infer(line, col)

        sig_info = []
        for sig in signatures:
            sig_info.append({
                "name": sig.name,
                "params": str(sig.params) if sig.params else "",
                "index": sig.index,
            })

        def_info = []
        for d in definitions:
            def_info.append({
                "name": d.name,
                "type": d.type,
                "docstring": d.docstring(raw=True)[:500] if d.docstring(raw=True) else "",
                "module": d.module_name or "",
            })

        return {
            "ok": True,
            "signatures": sig_info,
            "types": def_info,
            "hint": f"{len(sig_info)} 签名, {len(def_info)} 类型推断",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def references(project_root: str, filepath: str, line: int, col: int) -> Dict:
    """查找引用 — 基于 jedi"""
    try:
        source = _read_file_safe(filepath)
        if source is None:
            return {"ok": False, "error": f"无法读取文件: {filepath}"}

        import jedi
        script = jedi.Script(source, path=filepath, project=_get_jedi_project(project_root))
        refs = script.get_references(line, col)

        items = []
        for r in refs[:30]:
            items.append({
                "name": r.name,
                "type": r.type,
                "module": r.module_name or "",
                "file": str(r.module_path) if r.module_path else "",
                "line": r.line,
                "column": r.column,
            })

        return {
            "ok": True,
            "references": items,
            "total": len(refs),
            "hint": f"找到 {len(refs)} 处引用" if refs else "未找到引用",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def collect_context(project_root: str, filepath: str, symbol: str = None, max_files: int = 5) -> Dict:
    """仓库级上下文收集：给定文件/符号，自动拉取相关代码片段。

    策略:
      1. 符号引用 → jedi 查找定义 + 调用者
      2. 同目录 .py 文件 → 类/函数签名摘要
      3. 返回结构化上下文供注入 prompt
    """
    if filepath:
        source = _read_file_safe(filepath)
        if source is None:
            return {"ok": False, "error": f"无法读取文件: {filepath}"}

    results = {"ok": True, "files": [], "symbols": [], "hint": ""}
    scanned = set()

    try:
        import jedi

        # 1. 分析目标文件中的所有顶层符号
        if filepath and filepath.endswith(".py"):
            source = _read_file_safe(filepath)
            script = jedi.Script(source, path=filepath, project=_get_jedi_project(project_root))
            names = script.get_names(all_scopes=True, definitions=True, references=False)

            module_symbols = []
            for n in names:
                if n.type in ("function", "class", "module"):
                    module_symbols.append({
                        "name": n.name, "type": n.type,
                        "line": n.line, "description": n.description[:200] if n.description else "",
                    })
            if module_symbols:
                rel = os.path.relpath(filepath, project_root)
                results["files"].append({
                    "path": rel,
                    "kind": "target",
                    "symbols": module_symbols[:30],
                })

        # 2. 如果指定了符号，收集其定义和引用
        if symbol and filepath:
            source = _read_file_safe(filepath)
            script = jedi.Script(source, path=filepath, project=_get_jedi_project(project_root))
            # 尝试按名称搜索
            for n in script.get_names(all_scopes=True, definitions=True, references=False):
                if n.name == symbol:
                    refs = n.get_references()
                    for r in refs[:10]:
                        if r.module_path and str(r.module_path) not in scanned:
                            scanned.add(str(r.module_path))
                            rel = os.path.relpath(str(r.module_path), project_root)
                            results["symbols"].append({
                                "name": r.name,
                                "file": rel,
                                "line": r.line,
                                "type": r.type,
                            })
                    break

        # 3. 补充同目录的关键文件
        if filepath:
            target_dir = os.path.dirname(filepath)
            py_files = sorted(Path(target_dir).glob("*.py"))
            for pf in py_files[:max_files]:
                rel = os.path.relpath(str(pf), project_root)
                if rel not in [f["path"] for f in results["files"]]:
                    src = _read_file_safe(str(pf))
                    if src:
                        script = jedi.Script(src, path=str(pf), project=_get_jedi_project(project_root))
                        names = script.get_names(all_scopes=True, definitions=True, references=False)
                        syms = [{"name": n.name, "type": n.type, "line": n.line} for n in names
                                if n.type in ("function", "class")][:15]
                        results["files"].append({"path": rel, "kind": "sibling", "symbols": syms})

        results["hint"] = f"收集了 {len(results['files'])} 个文件, {len(results['symbols'])} 个符号引用"
        return results

    except Exception as e:
        return {"ok": False, "error": str(e)}
