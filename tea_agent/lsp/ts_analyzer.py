"""tree-sitter 代码分析器 — 仓库级上下文增强

提供：精确 AST 解析 / 影响分析 / 依赖图 / 跨文件引用
"""

import os, ast as py_ast, logging
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Optional

logger = logging.getLogger("ts_analyzer")

_TS_LANG = None
_TS_LANG_LOADED = False


def _ensure_ts():
    global _TS_LANG, _TS_LANG_LOADED
    if _TS_LANG_LOADED:
        return _TS_LANG
    _TS_LANG_LOADED = True
    try:
        from tree_sitter import Language
        import tree_sitter_python as tsp
        _TS_LANG = Language(tsp.language())
        return _TS_LANG
    except ImportError:
        logger.warning("tree-sitter 未安装，回退到 Python AST")
        return None
    except Exception as e:
        logger.warning(f"tree-sitter 加载失败: {e}")
        return None


def _get_text(source_bytes, node):
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8")


def _extract_docstring(source_bytes, body_node):
    for child in body_node.named_children:
        if child.type == "expression_statement":
            expr = child.children[0] if child.children else None
            if expr and expr.type == "string":
                text = _get_text(source_bytes, expr).strip().strip('"').strip("'")
                return text[:200]
        break
    return ""


def _extract_calls(source_bytes, body_node):
    calls = set()
    stack = [body_node]
    while stack:
        node = stack.pop()
        if node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                if func_node.type == "identifier":
                    calls.add(_get_text(source_bytes, func_node))
                elif func_node.type == "attribute":
                    for c in func_node.children:
                        if c.type == "identifier":
                            calls.add(_get_text(source_bytes, c))
        for child in node.children:
            stack.append(child)
    return sorted(calls)


def _extract_params(source_bytes, func_node):
    params_node = func_node.child_by_field_name("parameters")
    if not params_node:
        return []
    params = []
    for child in params_node.named_children:
        if child.type in ("identifier", "typed_parameter", "default_parameter",
                          "list_splat_pattern", "dictionary_splat_pattern",
                          "typed_default_parameter"):
            for c in child.children:
                if c.type == "identifier":
                    params.append(_get_text(source_bytes, c))
                    break
    return params


def parse_file(filepath: str) -> Optional[Dict]:
    """解析 Python 源码文件为结构化 AST 信息。"""
    lang = _ensure_ts()
    if lang is None:
        return _parse_file_ast_fallback(filepath)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except Exception:
        return None

    from tree_sitter import Parser
    parser = Parser()
    parser.language = lang
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    result = {"file": filepath, "functions": [], "classes": [], "imports": [], "top_level": []}

    def _walk(node, depth=0):
        for child in node.named_children:
            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                body_node = child.child_by_field_name("body")
                name = _get_text(source_bytes, name_node) if name_node else "?"
                params = _extract_params(source_bytes, child)
                calls = _extract_calls(source_bytes, child) if body_node else []
                doc = _extract_docstring(source_bytes, body_node) if body_node else ""
                result["functions"].append({
                    "name": name, "line": child.start_point[0] + 1,
                    "params": params, "docstring": doc, "calls": calls,
                })
                if depth == 0:
                    result["top_level"].append({
                        "name": name, "kind": "function",
                        "line": child.start_point[0] + 1,
                    })
            elif child.type == "class_definition":
                name_node = child.child_by_field_name("name")
                body_node = child.child_by_field_name("body")
                name = _get_text(source_bytes, name_node) if name_node else "?"
                bases = []
                for s in child.children:
                    if s.type == "argument_list":
                        for arg in s.named_children:
                            bases.append(_get_text(source_bytes, arg))
                doc = _extract_docstring(source_bytes, body_node) if body_node else ""
                methods = []
                if body_node:
                    for sub in body_node.named_children:
                        if sub.type == "function_definition":
                            mn = sub.child_by_field_name("name")
                            mb = sub.child_by_field_name("body")
                            mn_name = _get_text(source_bytes, mn) if mn else "?"
                            mparams = _extract_params(source_bytes, sub)
                            mcalls = _extract_calls(source_bytes, sub) if mb else []
                            mdoc = _extract_docstring(source_bytes, mb) if mb else ""
                            methods.append({
                                "name": mn_name, "line": sub.start_point[0] + 1,
                                "params": mparams, "docstring": mdoc, "calls": mcalls,
                            })
                result["classes"].append({
                    "name": name, "line": child.start_point[0] + 1,
                    "methods": methods, "bases": bases,
                })
                if depth == 0:
                    result["top_level"].append({
                        "name": name, "kind": "class",
                        "line": child.start_point[0] + 1,
                    })
            elif child.type in ("import_statement", "import_from_statement"):
                module = ""
                names = []
                for c in child.named_children:
                    if c.type == "dotted_name":
                        if not module:
                            module = _get_text(source_bytes, c)
                        else:
                            names.append(_get_text(source_bytes, c))
                    elif c.type == "aliased_import":
                        for ac in c.named_children:
                            if ac.type == "dotted_name":
                                if not module:
                                    module = _get_text(source_bytes, ac)
                                else:
                                    names.append(_get_text(source_bytes, ac))
                result["imports"].append({
                    "module": module, "names": names,
                    "line": child.start_point[0] + 1,
                })
            _walk(child, depth + 1)

    _walk(root)
    return result


def _parse_file_ast_fallback(filepath: str) -> Optional[Dict]:
    """回退方案：使用 Python 标准库 ast 模块解析文件。"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = py_ast.parse(source, filename=filepath)
    except Exception:
        return None

    result = {"file": filepath, "functions": [], "classes": [], "imports": [], "top_level": []}

    for node in py_ast.iter_child_nodes(tree):
        if isinstance(node, py_ast.FunctionDef):
            calls = set()
            for child in py_ast.walk(node):
                if isinstance(child, py_ast.Call):
                    if isinstance(child.func, py_ast.Name):
                        calls.add(child.func.id)
                    elif isinstance(child.func, py_ast.Attribute):
                        calls.add(child.func.attr)
            doc = py_ast.get_docstring(node) or ""
            params = [arg.arg for arg in node.args.args]
            result["functions"].append({
                "name": node.name, "line": node.lineno,
                "params": params, "docstring": doc[:200], "calls": sorted(calls),
            })
            result["top_level"].append({"name": node.name, "kind": "function", "line": node.lineno})
        elif isinstance(node, py_ast.ClassDef):
            bases = [py_ast.unparse(b) for b in node.bases]
            methods = []
            for sub in node.body:
                if isinstance(sub, py_ast.FunctionDef):
                    mcalls = set()
                    for child in py_ast.walk(sub):
                        if isinstance(child, py_ast.Call):
                            if isinstance(child.func, py_ast.Name):
                                mcalls.add(child.func.id)
                            elif isinstance(child.func, py_ast.Attribute):
                                mcalls.add(child.func.attr)
                    mdoc = py_ast.get_docstring(sub) or ""
                    mparams = [arg.arg for arg in sub.args.args]
                    methods.append({
                        "name": sub.name, "line": sub.lineno,
                        "params": mparams, "docstring": mdoc[:200],
                        "calls": sorted(mcalls),
                    })
            result["classes"].append({
                "name": node.name, "line": node.lineno,
                "methods": methods, "bases": bases,
            })
            result["top_level"].append({"name": node.name, "kind": "class", "line": node.lineno})
        elif isinstance(node, py_ast.Import):
            for alias in node.names:
                result["imports"].append({
                    "module": alias.name, "names": [alias.asname or alias.name],
                    "line": node.lineno,
                })
        elif isinstance(node, py_ast.ImportFrom):
            result["imports"].append({
                "module": node.module or "",
                "names": [a.asname or a.name for a in node.names],
                "line": node.lineno,
            })

    return result


def impact_analysis(project_root: str, filepath: str, symbol: str) -> Dict:
    """分析修改某符号会影响的调用链，评估风险等级。"""
    parsed = parse_file(filepath)
    if not parsed:
        return {"ok": False, "error": f"无法解析: {filepath}"}

    target_def = None
    for f in parsed["functions"]:
        if f["name"] == symbol:
            target_def = {"file": filepath, "line": f["line"], "type": "function",
                          "calls": f.get("calls", [])}
            break
    if not target_def:
        for c in parsed["classes"]:
            if c["name"] == symbol:
                target_def = {"file": filepath, "line": c["line"], "type": "class", "calls": []}
                for m in c.get("methods", []):
                    target_def["calls"].extend(m.get("calls", []))
                break
    if not target_def:
        return {"ok": False, "error": f"未找到符号: {symbol}", "symbol": symbol}

    direct_callers = []
    all_calls = defaultdict(list)

    py_files = list(Path(project_root).rglob("*.py"))
    for pf in py_files:
        pf_str = str(pf)
        if any(s in pf_str for s in (".tea_agent_run", "__pycache__", ".git", "build", "dist")):
            continue
        if pf_str == filepath:
            continue
        pf_parsed = parse_file(pf_str)
        if not pf_parsed:
            continue
        for f_item in pf_parsed["functions"]:
            for call in f_item.get("calls", []):
                all_calls[call].append({
                    "file": pf_str, "line": f_item["line"], "name": f_item["name"],
                })
        for c_item in pf_parsed["classes"]:
            for m_item in c_item.get("methods", []):
                for call in m_item.get("calls", []):
                    all_calls[call].append({
                        "file": pf_str, "line": m_item["line"],
                        "name": f"{c_item['name']}.{m_item['name']}",
                    })

    direct_callers = all_calls.get(symbol, [])

    indirect = set()
    seen = {symbol}
    for caller in direct_callers[:5]:
        cn = caller["name"]
        if cn in seen:
            continue
        seen.add(cn)
        for cc in all_calls.get(cn, []):
            indirect.add((cc["file"], cc["line"], cc["name"]))

    indirect_callers = [{"file": f, "line": l, "name": n} for f, l, n in indirect]

    same_file = []
    for f_item in parsed["functions"]:
        if f_item["name"] != symbol:
            same_file.append({"name": f_item["name"], "kind": "function", "line": f_item["line"]})
    for c_item in parsed["classes"]:
        if c_item["name"] != symbol:
            same_file.append({"name": c_item["name"], "kind": "class", "line": c_item["line"]})

    risk = "high" if len(direct_callers) > 10 else ("medium" if len(direct_callers) > 3 else "low")

    hint_parts = [f"直接调用者: {len(direct_callers)}"]
    if indirect_callers:
        hint_parts.append(f"间接调用者: {len(indirect_callers)}")
    if target_def.get("calls"):
        hint_parts.append(f"依赖: {', '.join(target_def['calls'][:5])}")
    hint_parts.append(f"风险: {risk}")

    return {
        "ok": True, "symbol": symbol,
        "definition": {"file": target_def["file"], "line": target_def["line"], "type": target_def["type"]},
        "direct_callers": direct_callers, "indirect_callers": indirect_callers,
        "callees": target_def.get("calls", []), "same_file_symbols": same_file,
        "risk_level": risk, "hint": " | ".join(hint_parts),
    }


def build_dependency_graph(project_root: str) -> Dict:
    """构建模块依赖关系图，检测循环依赖和孤立模块。"""
    graph = defaultdict(lambda: {"imports": [], "imported_by": [], "symbols": []})
    py_files = list(Path(project_root).rglob("*.py"))

    for pf in py_files:
        pf_str = str(pf)
        if any(s in pf_str for s in (".tea_agent_run", "__pycache__", ".git", "build", "dist")):
            continue
        rel = os.path.relpath(pf_str, project_root).replace("\\", "/")
        mod = rel.replace("/", ".").replace(".py", "")
        if mod.startswith("test"):
            continue
        parsed = parse_file(pf_str)
        if not parsed:
            continue
        for imp in parsed.get("imports", []):
            m = imp.get("module", "")
            if m:
                graph[mod]["imports"].append(m)
                if m != mod:
                    graph[m]["imported_by"].append(mod)
        for tl in parsed.get("top_level", []):
            graph[mod]["symbols"].append(tl["name"])

    circular = []
    visited = set()
    path = []

    def _dfs(m):
        if m in path:
            cycle_start = path.index(m)
            circular.append(path[cycle_start:] + [m])
            return
        if m in visited:
            return
        visited.add(m)
        path.append(m)
        for imp in graph[m]["imports"]:
            _dfs(imp)
        path.pop()

    for m in list(graph.keys())[:50]:
        _dfs(m)

    orphans = [m for m, g in graph.items() if not g["imported_by"] and not g["imports"]]

    limited = {}
    for k, v in list(graph.items())[:100]:
        limited[k] = {
            "imports": v["imports"][:10],
            "imported_by": v["imported_by"][:10],
            "symbols": v["symbols"][:10],
        }

    return {
        "ok": True, "modules": limited,
        "circular": circular[:10], "orphans": orphans[:20],
        "hint": f"{len(graph)} 模块, {len(circular)} 循环依赖, {len(orphans)} 孤立模块",
    }
