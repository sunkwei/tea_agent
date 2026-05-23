"""
@2026-05-19 gen by claude, tree-sitter 代码分析器 — 仓库级上下文增强
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
    """Internal: ensure ts."""
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
    """Internal: get the text.
    
    Args:
        source_bytes: Description.
        node: Description.
    """
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8")

def _extract_docstring(source_bytes, body_node):
    """Internal: extract docstring.
    
    Args:
        source_bytes: Description.
        body_node: Description.
    """
    for child in body_node.named_children:
        if child.type == "expression_statement":
            expr = child.children[0] if child.children else None
            if expr and expr.type == "string":
                text = _get_text(source_bytes, expr).strip().strip('"').strip("'")
                return text[:200]
        break
    return ""

def _extract_calls(source_bytes, body_node):
    """Internal: extract calls.
    
    Args:
        source_bytes: Description.
        body_node: Description.
    """
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
    """Internal: extract params.
    
    Args:
        source_bytes: Description.
        func_node: Description.
    """
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
    """Parse file.
    
    Args:
        filepath: Description.
    """
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

    def _handle_function_def(child, depth):
        """Extract function definition info."""
        name_node = child.child_by_field_name("name")
        body_node = child.child_by_field_name("body")
        name = _get_text(source_bytes, name_node) if name_node else "?"
        params = _extract_params(source_bytes, child)
        calls = _extract_calls(source_bytes, child) if body_node else []
        doc = _extract_docstring(source_bytes, body_node) if body_node else ""
        body_span = (child.start_point[0] + 1, child.end_point[0] + 1)
        result["functions"].append({
            "name": name, "line": child.start_point[0] + 1,
            "body_span": body_span,
            "params": params, "docstring": doc, "calls": calls,
        })
        if depth == 0:
            result["top_level"].append({
                "name": name, "kind": "function",
                "line": child.start_point[0] + 1,
            })

    def _handle_class_def(child, depth):
        """Extract class definition info."""
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
                    mbody_span = (sub.start_point[0] + 1, sub.end_point[0] + 1)
                    methods.append({
                        "name": mn_name, "line": sub.start_point[0] + 1,
                        "body_span": mbody_span,
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

    def _handle_import(child):
        """Extract import statement info."""
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

    def _walk(node, depth=0):
        """Walk AST recursively, dispatching to typed handlers."""
        for child in node.named_children:
            if child.type == "function_definition":
                _handle_function_def(child, depth)
            elif child.type == "class_definition":
                _handle_class_def(child, depth)
            elif child.type in ("import_statement", "import_from_statement"):
                _handle_import(child)
            _walk(child, depth + 1)

    _walk(root)
    return result

def _parse_file_ast_fallback(filepath: str) -> Optional[Dict]:
    """Internal: parse file ast fallback.
    
    Args:
        filepath: Description.
    """
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
    """Impact analysis.
    
    Args:
        project_root: Description.
        filepath: Description.
        symbol: Description.
    """
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
    """Build dependency graph.
    
    Args:
        project_root: Description.
    """
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
        """Internal: dfs.
        
        Args:
            m: Description.
        """
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

# ── Metrics Engine ────────────────────────────────────────────────

# ── Metrics Engine ────────────────────────────────────────────────

def _count_branches(node, source_bytes) -> int:
    """统计子树中的分支节点（用于圈复杂度）"""
    branch_types = {
        "if_statement", "elif_clause", "else_clause",
        "for_statement", "while_statement",
        "try_statement", "except_clause", "finally_clause",
        "match_statement", "case_clause",
        "conditional_expression", "boolean_operator",
    }
    count = 0
    for child in node.children:
        if child.type in branch_types:
            count += 1
        count += _count_branches(child, source_bytes)
    return count


def _cyclomatic_for_body(body_node, source_bytes) -> int:
    """计算函数体的圈复杂度：1 + 分支数"""
    if body_node is None:
        return 1
    return 1 + _count_branches(body_node, source_bytes)


def _compute_fn_metrics(fn_info: dict, source_bytes, body_node) -> dict:
    """计算单个函数的度量"""
    loc = 0
    body_span = fn_info.get("body_span")
    if body_span:
        loc = body_span[1] - body_span[0] + 1
    fan_out = len(fn_info.get("calls", []))
    return {
        "cyclomatic": _cyclomatic_for_body(body_node, source_bytes),
        "loc": loc,
        "fan_out": fan_out,
        "fan_in": 0,  # filled later via cross-reference
        "has_docstring": bool(fn_info.get("docstring")),
    }


def _compute_metrics_ast_fallback(filepath: str) -> dict:
    """AST fallback: compute cyclomatic complexity from Python AST."""
    import ast as _ast, os as _os

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        tree = _ast.parse(source, filename=filepath)
    except Exception as e:
        return {"ok": False, "error": str(e), "file": filepath}

    class _MetricsVisitor(_ast.NodeVisitor):
        def __init__(self):
            self.items = []
            self._current = None
            self._branches = 0
            self._calls = set()

        def _end_func(self, node):
            if self._current is None:
                return
            loc = node.end_lineno - node.lineno + 1 if hasattr(node, "end_lineno") else 0
            self.items.append({
                "name": self._current,
                "kind": self._current_kind,
                "line": node.lineno,
                "docstring": self._doc,
                "metrics": {
                    "cyclomatic": 1 + self._branches,
                    "loc": loc,
                    "fan_out": len(self._calls),
                    "fan_in": 0,
                    "has_docstring": bool(self._doc),
                },
            })
            self._current = None
            self._branches = 0
            self._calls = set()
            self._doc = ""

        def visit_FunctionDef(self, node):
            self._current = node.name
            self._current_kind = "function"
            self._branches = 0
            self._calls = set()
            self._doc = _ast.get_docstring(node) or ""
            self.generic_visit(node)
            self._end_func(node)

        def visit_AsyncFunctionDef(self, node):
            self.visit_FunctionDef(node)

        def visit_If(self, node):
            if self._current:
                self._branches += 1
                if node.orelse:
                    self._branches += 1  # else counts too
            self.generic_visit(node)

        def visit_For(self, node):
            if self._current: self._branches += 1
            self.generic_visit(node)

        def visit_AsyncFor(self, node):
            if self._current: self._branches += 1
            self.generic_visit(node)

        def visit_While(self, node):
            if self._current: self._branches += 1
            self.generic_visit(node)

        def visit_Try(self, node):
            if self._current:
                self._branches += 1
                self._branches += len(node.handlers)
            self.generic_visit(node)

        def visit_Match(self, node):
            if self._current:
                self._branches += len(node.cases)
            self.generic_visit(node)

        def visit_IfExp(self, node):
            if self._current: self._branches += 1
            self.generic_visit(node)

        def visit_BoolOp(self, node):
            if self._current: self._branches += len(node.values) - 1
            self.generic_visit(node)

        def visit_Call(self, node):
            if self._current:
                if isinstance(node.func, _ast.Name):
                    self._calls.add(node.func.id)
                elif isinstance(node.func, _ast.Attribute):
                    self._calls.add(node.func.attr)
            self.generic_visit(node)

    v = _MetricsVisitor()
    v.visit(tree)

    all_cyclo = [i["metrics"]["cyclomatic"] for i in v.items]
    complexity_dist = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for c in all_cyclo:
        if c <= 5: complexity_dist["low"] += 1
        elif c <= 10: complexity_dist["medium"] += 1
        elif c <= 20: complexity_dist["high"] += 1
        else: complexity_dist["critical"] += 1

    # Fan-in
    all_calls = {}
    for item in v.items:
        all_calls[item["name"]] = set()
        for item2 in v.items:
            if item2 is not item:
                pass  # we need call sets per function...
    # Recompute fan-in from call sets
    for item in v.items:
        name = item["name"]
        item["metrics"]["fan_in"] = sum(
            1 for other in v.items if other is not item and name in other["metrics"].get("_call_set", set())
        )

    # Build call sets properly
    # Actually, let's re-visit to collect calls per function
    class _CallCollector(_ast.NodeVisitor):
        def __init__(self):
            self.calls = {}  # func_name -> set of called names

        def visit_FunctionDef(self, node):
            name = node.name
            calls = set()

            class _Inner(_ast.NodeVisitor):
                def visit_Call(self, n):
                    if isinstance(n.func, _ast.Name):
                        calls.add(n.func.id)
                    elif isinstance(n.func, _ast.Attribute):
                        calls.add(n.func.attr)
                    self.generic_visit(n)
            _Inner().visit(node)
            self.calls[name] = calls
            self.generic_visit(node)

    cc = _CallCollector()
    try:
        cc.visit(tree)
    except Exception:
        cc.calls = {}

    for item in v.items:
        name = item["name"]
        item["metrics"]["_call_set"] = cc.calls.get(name, set())
        item["metrics"]["fan_in"] = sum(
            1 for other in v.items
            if other is not item and name in cc.calls.get(other["name"], set())
        )
        # Clean internal field
        item["metrics"].pop("_call_set", None)

    total_loc = source.count("\n") + 1
    total_fns = sum(1 for i in v.items if i["kind"] == "function")
    total_methods = sum(1 for i in v.items if i["kind"] == "method")
    has_doc = sum(1 for i in v.items if i.get("docstring"))

    return {
        "ok": True,
        "file": filepath,
        "total_loc": total_loc,
        "functions": total_fns,
        "methods": total_methods,
        "docstring_coverage": f"{has_doc}/{total_fns + total_methods}" if (total_fns + total_methods) else "N/A",
        "complexity_dist": complexity_dist,
        "avg_cyclomatic": round(sum(all_cyclo) / len(all_cyclo), 1) if all_cyclo else 0,
        "max_cyclomatic": max(all_cyclo) if all_cyclo else 0,
        "items": sorted(v.items, key=lambda x: x["metrics"]["cyclomatic"], reverse=True),
        "_fallback": "ast",
    }

def compute_metrics(project_root: str, filepath: str) -> dict:
    """计算单个文件的代码度量：圈复杂度、LOC、扇入扇出、注释覆盖等。

    Returns:
        dict with per-function metrics + module summary
    """
    import os as _os
    full_path = filepath if _os.path.isabs(filepath) else _os.path.join(project_root, filepath)
    lang = _ensure_ts()
    if lang is None:
        return _compute_metrics_ast_fallback(full_path)
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except Exception as e:
        return {"ok": False, "error": str(e), "file": filepath}

    source_bytes = source.encode("utf-8")
    from tree_sitter import Parser
    parser = Parser()
    parser.language = lang
    tree = parser.parse(source_bytes)
    root = tree.root_node

    fns = []       # standalone functions
    methods = []   # class methods
    fn_metrics = []  # all callable metrics
    call_map = {}    # name -> fn_metrics entry

    def _walk(node, depth=0):
        for child in node.named_children:
            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                body_node = child.child_by_field_name("body")
                name = _get_text(source_bytes, name_node) if name_node else "?"
                calls = _extract_calls(source_bytes, body_node) if body_node else []
                doc = _extract_docstring(source_bytes, body_node) if body_node else ""
                span = (child.start_point[0] + 1, child.end_point[0] + 1)
                info = {"name": name, "line": span[0], "body_span": span,
                        "params": _extract_params(source_bytes, child),
                        "docstring": doc, "calls": calls}
                m = _compute_fn_metrics(info, source_bytes, body_node)
                if depth == 0:
                    fns.append({"name": name, "metrics": m, "line": span[0],
                                "kind": "function", "docstring": doc})
                else:
                    methods.append({"name": name, "metrics": m, "line": span[0],
                                    "kind": "method", "docstring": doc})
                fn_metrics.append((name, m))
                call_map[name] = m
            elif child.type == "class_definition":
                body_node = child.child_by_field_name("body")
                if body_node:
                    for sub in body_node.named_children:
                        if sub.type == "function_definition":
                            mn = sub.child_by_field_name("name")
                            mb = sub.child_by_field_name("body")
                            mn_name = _get_text(source_bytes, mn) if mn else "?"
                            mcalls = _extract_calls(source_bytes, mb) if mb else []
                            mdoc = _extract_docstring(source_bytes, mb) if mb else ""
                            mspan = (sub.start_point[0] + 1, sub.end_point[0] + 1)
                            minfo = {"name": mn_name, "line": mspan[0], "body_span": mspan,
                                     "params": _extract_params(source_bytes, sub),
                                     "docstring": mdoc, "calls": mcalls}
                            mm = _compute_fn_metrics(minfo, source_bytes, mb)
                            methods.append({"name": mn_name, "metrics": mm, "line": mspan[0],
                                            "kind": "method", "docstring": mdoc})
                            fn_metrics.append((mn_name, mm))
                            call_map[mn_name] = mm
            _walk(child, depth + 1)

    _walk(root)

    # Fan-in: count how many other functions call this one
    all_callables = fns + methods
    for entry in all_callables:
        name = entry["name"]
        # count callers within this file
        fan_in = sum(1 for _, m in fn_metrics if m is not entry["metrics"]
                     and name in call_map.get(name, {}).get("calls", set()))
        # better: iterate all_callables and check their metrics' calls
        fan_in = 0
        for other in all_callables:
            if other is entry:
                continue
            # find other's calls from parse
            pass

    # Re-do fan-in: from the parsed data directly
    # We need to rebuild the calls-per-function map
    fn_calls = {}
    # Re-walk to get accurate calls
    def _walk2(node, depth=0):
        for child in node.named_children:
            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                body_node = child.child_by_field_name("body")
                name = _get_text(source_bytes, name_node) if name_node else "?"
                calls = _extract_calls(source_bytes, body_node) if body_node else []
                fn_calls[name] = set(calls)
            elif child.type == "class_definition":
                body_node = child.child_by_field_name("body")
                if body_node:
                    for sub in body_node.named_children:
                        if sub.type == "function_definition":
                            mn = sub.child_by_field_name("name")
                            mb = sub.child_by_field_name("body")
                            mn_name = _get_text(source_bytes, mn) if mn else "?"
                            mcalls = _extract_calls(source_bytes, mb) if mb else []
                            fn_calls[mn_name] = set(mcalls)
            _walk2(child, depth + 1)
    _walk2(root)

    for entry in all_callables:
        name = entry["name"]
        entry["metrics"]["fan_in"] = sum(1 for cn, calls in fn_calls.items()
                                         if cn != name and name in calls)

    # Module-level summary
    all_cyclo = [e["metrics"]["cyclomatic"] for e in all_callables]
    complexity_dist = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for c in all_cyclo:
        if c <= 5:
            complexity_dist["low"] += 1
        elif c <= 10:
            complexity_dist["medium"] += 1
        elif c <= 20:
            complexity_dist["high"] += 1
        else:
            complexity_dist["critical"] += 1

    total_loc = source.count("\n") + 1
    total_fns = len(fns)
    total_methods = len(methods)
    has_doc = sum(1 for e in all_callables if e.get("docstring"))

    return {
        "ok": True,
        "file": filepath,
        "total_loc": total_loc,
        "functions": total_fns,
        "methods": total_methods,
        "docstring_coverage": f"{has_doc}/{total_fns + total_methods}" if (total_fns + total_methods) else "N/A",
        "complexity_dist": complexity_dist,
        "avg_cyclomatic": round(sum(all_cyclo) / len(all_cyclo), 1) if all_cyclo else 0,
        "max_cyclomatic": max(all_cyclo) if all_cyclo else 0,
        "items": sorted(all_callables, key=lambda x: x["metrics"]["cyclomatic"], reverse=True),
    }


def find_dead_code(project_root: str, filepath: str) -> dict:
    """检测文件中的未使用代码：函数/方法/导入。

    Returns:
        dict with dead_functions, dead_methods, unused_imports
    """
    import os as _os
    full_path = filepath if _os.path.isabs(filepath) else _os.path.join(project_root, filepath)
    result = parse_file(full_path)
    if not result:
        return {"ok": False, "error": f"Cannot parse {filepath}", "file": filepath}

    # Build: all defined symbols, all called symbols
    defined = set()
    calls_all = set()
    for fn in result.get("functions", []):
        defined.add(fn["name"])
        calls_all.update(fn.get("calls", []))
    for cls in result.get("classes", []):
        defined.add(cls["name"])
        for m in cls.get("methods", []):
            defined.add(m["name"])
            calls_all.update(m.get("calls", []))

    # Dead = defined but never called (and not __init__ or special names)
    special = {"__init__", "__str__", "__repr__", "__len__", "__call__", "__iter__",
               "__next__", "__enter__", "__exit__", "__getitem__", "__setitem__"}
    dead = [d for d in defined if d not in calls_all and d not in special
            and not d.startswith("_")]  # _private may be external API

    # Unused imports
    unused_imports = []
    # Build set of all referenced names in source
    all_refs = calls_all | defined
    for imp in result.get("imports", []):
        names = imp.get("names", [])
        module = imp.get("module", "")
        used = [n for n in names if n in all_refs]
        if not used and not module.startswith("_"):
            unused_imports.append({
                "module": module, "names": names, "line": imp.get("line"),
                "hint": "No references found to imported names",
            })

    return {
        "ok": True,
        "file": filepath,
        "total_defined": len(defined),
        "dead_functions": dead,
        "dead_count": len(dead),
        "unused_imports": unused_imports,
    }
