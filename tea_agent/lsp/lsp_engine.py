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

# ── Jedi 智能后端 ────────────────────────────────────────

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

def semantic_diagnose(project_root: str, filepath: str) -> Dict:
    """基于 jedi 的语义级诊断 — 检查未定义符号、无法解析的引用等深局问题。

    与 diagnose() 的 ruff lint 不同，此函数深入语义层：
      - 检查引用是否能解析到定义
      - 检查导入模块是否存在
      - 检查函数/类名拼写错误
    不检查代码风格/格式问题。

    Args:
        project_root: 项目根目录
        filepath: 目标 .py 文件

    Returns:
        {"ok": bool, "issues": [...], "total": int, "hint": str}
    """
    if not filepath or not filepath.endswith(".py"):
        return {"ok": True, "issues": [], "total": 0, "hint": "非 Python 文件，跳过"}

    source = _read_file_safe(filepath)
    if source is None:
        return {"ok": False, "error": f"无法读取: {filepath}"}

    try:
        import jedi
        script = jedi.Script(source, path=filepath,
                             project=_get_jedi_project(project_root))

        issues = []
        seen_names = set()

        # 1. 扫描所有引用，检查能否解析
        all_names = script.get_names(all_scopes=True, definitions=True)
        defined = {n.name for n in all_names if n.type in
                   ('function', 'class', 'param', 'statement', 'import')}

        all_refs = script.get_names(all_scopes=True, definitions=False)
        for ref in all_refs:
            name = ref.name
            if name in seen_names or name.startswith('_') or name in defined:
                continue
            # 尝试推断
            try:
                inferred = ref.infer()
                if not inferred:
                    seen_names.add(name)
                    issues.append({
                        "type": "unresolved_reference",
                        "name": name,
                        "line": ref.line,
                        "column": ref.column or 0,
                        "message": f"符号 '{name}' 无法解析到定义，可能是拼写错误或缺少导入",
                    })
            except Exception:
                pass

        # 2. 检查导入
        for name in script.get_names(all_scopes=True):
            if name.type == 'import':
                try:
                    inferred = name.infer()
                    if not inferred:
                        issues.append({
                            "type": "unresolved_import",
                            "name": name.name,
                            "line": name.line,
                            "column": 0,
                            "message": f"导入 '{name.name}' 无法解析",
                        })
                except Exception:
                    pass

        hint = f"发现 {len(issues)} 个语义问题" if issues else "语义检查通过 ✓"
        return {
            "ok": len(issues) == 0,
            "issues": issues[:30],
            "total": len(issues),
            "hint": hint,
        }

    except ImportError:
        return {"ok": False, "error": "jedi 未安装，请运行: pip install jedi"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

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
    """跳转微义 — 基于 jedi"""
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
            "hint": f"记录 {len(items)} 个定义" if items else "未拶到定义",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def hover(project_root: str, filepath: str, line: int, col: int) -> Dict:
    """悬停信情 — 系垈 + docstring"""
    try:
        source = _read_file_safe(filepath)
        if source is None:
            return {"ok": False, "error": f"无法读取文件: {filepath}"}

        import jedi
        script = jedi.Script(source, path=filepath, project=_get_jedi_project(project_root))

        # 荷取当前位置的签名＜帮助
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
        pass

# ── C++ (clangd) 支持 ────────────────────────────────────────

def _check_clangd() -> bool:
    """检查 clangd 是否已安装。"""
    try:
        result = subprocess.run(
            ["clangd", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def cpp_diagnose(project_root: str, filepath: str) -> Dict:
    """C++ 诊断 — 基于 clangd。
    
    Args:
        project_root: 项目根目录
        filepath: 目标 .cpp/.h 文件
    
    Returns:
        {"ok": bool, "diagnostics": [...], "total": int, "hint": str}
    """
    if not filepath or not any(filepath.endswith(ext) for ext in ('.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.hxx')):
        return {"ok": True, "diagnostics": [], "total": 0, "hint": "非 C++ 文件，跳过"}
    
    if not _check_clangd():
        return {"ok": False, "error": "clangd 未安装，请安装 LLVM 工具链"}
    
    try:
        # 使用 clangd 的 --check 模式进行诊断
        # 注意：clangd 需要 compile_commands.json 或 compile_flags.txt
        result = subprocess.run(
            ["clangd", "--check", filepath, f"--path-mapping={project_root}={project_root}"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=project_root
        )
        
        # 解析 clangd 输出
        diagnostics = []
        for line in result.stderr.split('\n'):
            if 'error:' in line or 'warning:' in line:
                # 格式: file:line:col: error: message
                parts = line.split(':', 3)
                if len(parts) >= 4:
                    diag = {
                        "file": parts[0],
                        "line": int(parts[1]) if parts[1].isdigit() else 0,
                        "column": int(parts[2]) if parts[2].isdigit() else 0,
                        "severity": "error" if "error:" in line else "warning",
                        "message": parts[3].strip()
                    }
                    diagnostics.append(diag)
        
        errors = [d for d in diagnostics if d.get("severity") == "error"]
        warnings = [d for d in diagnostics if d.get("severity") == "warning"]
        
        summary = []
        if errors:
            summary.append(f"{len(errors)} 错误")
        if warnings:
            summary.append(f"{len(warnings)} 警告")
        
        return {
            "ok": len(errors) == 0,
            "diagnostics": diagnostics[:20],
            "total": len(diagnostics),
            "errors": len(errors),
            "warnings": len(warnings),
            "hint": f"发现 {', '.join(summary)}" if summary else "无问题 ✓",
        }
    
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "clangd 诊断超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cpp_goto_definition(project_root: str, filepath: str, line: int, col: int) -> Dict:
    """C++ 跳转定义 — 基于 clangd。
    
    注意：需要 clangd 运行在 LSP 服务器模式，这里使用简化实现。
    """
    if not filepath or not any(filepath.endswith(ext) for ext in ('.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.hxx')):
        return {"ok": False, "error": "非 C++ 文件"}
    
    if not _check_clangd():
        return {"ok": False, "error": "clangd 未安装"}
    
    try:
        # 使用 ctags 作为简化实现
        result = subprocess.run(
            ["ctags", "-f", "-", "--fields=+n", "--sort=yes", filepath],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root
        )
        
        if result.returncode != 0:
            return {"ok": False, "error": "ctags 执行失败"}
        
        # 解析 ctags 输出
        definitions = []
        for tag_line in result.stdout.strip().split('\n'):
            if not tag_line or tag_line.startswith('!'):
                continue
            
            parts = tag_line.split('\t')
            if len(parts) >= 3:
                definitions.append({
                    "name": parts[0],
                    "file": parts[1],
                    "pattern": parts[2] if len(parts) > 2 else "",
                })
        
        return {
            "ok": True,
            "definitions": definitions[:10],
            "hint": f"找到 {len(definitions)} 个定义" if definitions else "未找到定义",
        }
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cpp_completion(project_root: str, filepath: str, line: int, col: int) -> Dict:
    """C++ 代码补全 — 基于 clangd。
    
    注意：完整实现需要 clangd LSP 协议，这里使用简化实现。
    """
    if not filepath or not any(filepath.endswith(ext) for ext in ('.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.hxx')):
        return {"ok": False, "error": "非 C++ 文件"}
    
    # 简化实现：使用 ctags 提取当前文件的符号
    try:
        result = subprocess.run(
            ["ctags", "-f", "-", "--fields=+n", "--sort=yes", filepath],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root
        )
        
        if result.returncode != 0:
            return {"ok": False, "error": "ctags 执行失败"}
        
        # 解析 ctags 输出
        completions = []
        for tag_line in result.stdout.strip().split('\n'):
            if not tag_line or tag_line.startswith('!'):
                continue
            
            parts = tag_line.split('\t')
            if len(parts) >= 3:
                completions.append({
                    "name": parts[0],
                    "type": "function" if "f:" in tag_line else "variable",
                })
        
        return {
            "ok": True,
            "completions": completions[:15],
            "hint": f"找到 {len(completions)} 个补全项",
        }
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


def diagnose_auto(project_root: str, filepath: str = None) -> Dict:
    """自动检测语言并运行诊断。"""
    if not filepath:
        return diagnose(project_root)
    
    ext = Path(filepath).suffix.lower()
    if ext in ('.py', '.pyw', '.pyi'):
        return diagnose(project_root, filepath)
    elif ext in ('.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.hxx'):
        return cpp_diagnose(project_root, filepath)
    else:
        return {"ok": True, "diagnostics": [], "total": 0, "hint": f"不支持的文件类型: {ext}"}


def goto_definition_auto(project_root: str, filepath: str, line: int, col: int) -> Dict:
    """自动检测语言并跳转定义。"""
    ext = Path(filepath).suffix.lower()
    if ext in ('.py', '.pyw', '.pyi'):
        return goto_definition(project_root, filepath, line, col)
    elif ext in ('.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.hxx'):
        return cpp_goto_definition(project_root, filepath, line, col)
    else:
        return {"ok": False, "error": f"不支持的文件类型: {ext}"}


def completion_auto(project_root: str, filepath: str, line: int, col: int) -> Dict:
    """自动检测语言并补全。"""
    ext = Path(filepath).suffix.lower()
    if ext in ('.py', '.pyw', '.pyi'):
        return completion(project_root, filepath, line, col)
    elif ext in ('.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.hxx'):
        return cpp_completion(project_root, filepath, line, col)
    else:
        return {"ok": False, "error": f"不支持的文件类型: {ext}"}

        return {"ok": False, "error": str(e)}
