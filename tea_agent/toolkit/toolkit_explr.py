## llm generated tool func, created Mon May 11 20:34:01 2026
# version: 1.0.1

"""
项目知识库构建与查询工具 — toolkit_explr

在任意项目目录中构建以下索引（存入 .tea_agent_run/）：
  symbol_index.json  — 符号 → 文件:行号 (基于 ctags)
  call_graph.json    — 函数调用图 (基于 AST)
  ctags.json         — 原始 ctags 输出
  call_flow.dot/svg  — 调用流程图 (需 graphviz)
  kb.md              — 人类可读知识库

查询接口: symbol(符号定位), callers(谁调此函数), callees(此函数调谁), module(模块概览)
"""
import ast
import json
import os
import subprocess
import shutil
import time
from collections import defaultdict

_PYTHON_BUILTINS = frozenset({
    'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'breakpoint', 'bytearray', 'bytes',
    'callable', 'chr', 'classmethod', 'compile', 'complex', 'copyright', 'credits',
    'delattr', 'dict', 'dir', 'divmod', 'enumerate', 'eval', 'exec', 'exit', 'filter',
    'float', 'format', 'frozenset', 'getattr', 'globals', 'hasattr', 'hash', 'help',
    'hex', 'id', 'input', 'int', 'isinstance', 'issubclass', 'iter', 'len', 'license',
    'list', 'locals', 'map', 'max', 'memoryview', 'min', 'next', 'object', 'oct',
    'open', 'ord', 'pow', 'print', 'property', 'quit', 'range', 'repr', 'reversed',
    'round', 'set', 'setattr', 'slice', 'sorted', 'staticmethod', 'str', 'sum',
    'super', 'tuple', 'type', 'vars', 'zip', '__import__',
    # 常见方法名（ast.Attribute 产生的 .append .strip .join 等）
    'append', 'strip', 'join', 'split', 'replace', 'format', 'startswith',
    'endswith', 'get', 'items', 'keys', 'values', 'update', 'pop', 'clear',
    'copy', 'read', 'write', 'close', 'seek', 'find', 'index', 'count',
    'remove', 'insert', 'sort', 'reverse', 'extend', 'upper', 'lower',
    'encode', 'decode', 'search', 'match', 'sub', 'group', 'groups',
    'add', 'difference', 'intersection', 'union', 'discard',
    '__init__', '__str__', '__repr__', '__call__', '__len__', '__getitem__',
    '__setitem__', '__delitem__', '__iter__', '__next__', '__enter__', '__exit__',
    '__contains__', '__eq__', '__ne__', '__lt__', '__gt__', '__hash__',
    # Logging 和 traceback 等标准库常用方法
    'info', 'debug', 'warning', 'error', 'critical', 'exception', 'log',
    'print_exc', 'format_exc', 'getLogger', 'basicConfig',
})

import logging
logger = logging.getLogger("toolkit")

_RUN_DIR = ".tea_agent_run"

def _log(msg):
    """Internal: log.
    
    Args:
        msg: Description.
    """
    print(f"[explr] {msg}")

def _build_ctags(directory, run_dir):
    """生成 ctags JSON 索引"""
    ctags_bin = shutil.which("ctags") or shutil.which("ctags-universal")
    if not ctags_bin:
        _log("⚠ ctags 未安装，跳过 ctags 索引")
        return None, {}

    src_dirs = []
    for entry in sorted(os.listdir(directory)):
        epath = os.path.join(directory, entry)
        if os.path.isdir(epath) and not entry.startswith('.') and entry not in ('build', '__pycache__', 'tmp', 'dist'):
            for root, dirs, files in os.walk(epath):
                if any(f.endswith('.py') for f in files):
                    src_dirs.append(epath)
                    break

    if not src_dirs:
        _log("⚠ 未找到 Python 源码目录")
        return None, {}

    _log(f"ctags 扫描: {', '.join(src_dirs)}")
    try:
        result = subprocess.run(
            [ctags_bin, '-R', '--fields=+nKzS', '--python-kinds=+cfmv', '--output-format=json'] + src_dirs,
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=60, cwd=directory
        )
    except Exception as e:
        _log(f"⚠ ctags 执行失败: {e}")
        return None, {}

    lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
    _log(f"ctags: {len(lines)} 条目")

    ctags_path = os.path.join(run_dir, "ctags.json")
    with open(ctags_path, 'w', encoding='utf-8') as f:
        f.write(result.stdout)

    index = {}
    for line in lines:
        try:
            entry = json.loads(line)
            name = entry.get('name', '')
            path = entry.get('path', '')
            line_num = entry.get('line', '')
            kind = entry.get('kind', '')
            if name:
                if name not in index:
                    index[name] = []
                index[name].append({
                    'kind': kind,
                    'path': os.path.relpath(path, directory) if os.path.isabs(path) else path,
                    'line': line_num,
                })
        except json.JSONDecodeError:
            logger.exception("operation failed")


    return ctags_path, index

def _build_call_graph(directory):
    """用 AST 分析函数调用图"""
    calls = {}
    defs = {}
    classes = {}

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'build', 'dist', '.git', '.tea_agent_run', 'tmp')]
        for fname in files:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, directory)
            try:
                with open(fpath, 'r', encoding='utf-8') as fh:
                    source = fh.read()
                tree = ast.parse(source, filename=relpath)
            except (SyntaxError, UnicodeDecodeError) as e:
                _log(f"⚠ 语法错误: {relpath}: {e}")
                continue

            class CallVisitor(ast.NodeVisitor):
                """CallVisitor class."""
                def visit_FunctionDef(self, node):
                    """Visit FunctionDef.
                    
                    Args:
                        node: Description.
                    """
                    defs[node.name] = {'file': relpath, 'line': node.lineno}
                    called = set()
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            if isinstance(child.func, ast.Name):
                                called.add(child.func.id)
                            elif isinstance(child.func, ast.Attribute):
                                called.add(child.func.attr)
                    if called:
                        calls[node.name] = sorted(called)
                    self.generic_visit(node)

                def visit_AsyncFunctionDef(self, node):
                    """Visit AsyncFunctionDef.
                    
                    Args:
                        node: Description.
                    """
                    self.visit_FunctionDef(node)

                def visit_ClassDef(self, node):
                    """Visit ClassDef.
                    
                    Args:
                        node: Description.
                    """
                    classes[node.name] = {'file': relpath, 'line': node.lineno}
                    self.generic_visit(node)

            CallVisitor().visit(tree)

    _log(f"AST: {len(defs)} 函数, {len(classes)} 类, {sum(len(v) for v in calls.values())} 调用边")
    return calls, defs, classes

def _build_dot_flow(calls, defs, run_dir):
    """生成关键调用流程 DOT 图"""
    dot_bin = shutil.which("dot")
    if not dot_bin:
        return

    callers = defaultdict(list)
    for caller, callees in calls.items():
        for callee in callees:
            callers[callee].append(caller)

    top = sorted(callers.items(), key=lambda x: -len(x[1]))[:30]
    top_names = {n for n, _ in top}

    dot = ['digraph G {', '  rankdir=TB;', '  node [shape=box, style=filled, fillcolor=lightyellow, fontsize=10];']
    for i, (name, clrs) in enumerate(top):
        count = len(clrs)
        color = 'lightsalmon' if count > 20 else 'lightyellow'
        short_name = name[:25] + ('..' if len(name) > 25 else '')
        dot.append(f'  n{i} [label="{short_name}\\n({count} callers)" fillcolor={color}];')

    name_to_id = {n: f"n{i}" for i, (n, _) in enumerate(top)}
    for caller, callees in calls.items():
        if caller not in name_to_id:
            continue
        for callee in callees:
            if callee in name_to_id:
                dot.append(f'  {name_to_id[caller]} -> {name_to_id[callee]};')

    dot.append('}')
    dot_path = os.path.join(run_dir, "call_flow.dot")
    with open(dot_path, 'w') as f:
        f.write('\n'.join(dot))

    svg_path = os.path.join(run_dir, "call_flow.svg")
    subprocess.run([dot_bin, '-Tsvg', dot_path, '-o', svg_path],
                   capture_output=True, timeout=15)
    _log(f"DOT: {dot_path}, {svg_path}")

def _build_kb_md(directory, index, calls, defs, classes, run_dir):
    """生成人类可读知识库 Markdown"""
    now = time.strftime("%Y-%m-%d %H:%M")
    project_name = os.path.basename(os.path.abspath(directory))

    modules = {}
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'build', 'dist', '.git', '.tea_agent_run', 'tmp')]
        for fname in files:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, directory)
            try:
                with open(fpath, 'r', encoding='utf-8') as fh:
                    lines = fh.readlines()
            except Exception:
                continue

            mod_classes = []
            mod_funcs = []
            lines_count = len(lines)
            for line in lines:
                s = line.strip()
                if s.startswith('class '):
                    name = s.split('(')[0].replace('class ', '').strip().rstrip(':')
                    mod_classes.append(name)
                elif s.startswith('def ') and not s.startswith((' ', '\t')):
                    name = s.split('(')[0].replace('def ', '').strip()
                    if not name.startswith('_'):
                        mod_funcs.append(name)

            modules[relpath] = {'classes': mod_classes, 'funcs': mod_funcs, 'lines': lines_count}

    kind_counts = defaultdict(int)
    for entries in index.values():
        for e in entries:
            kind_counts[e['kind']] += 1

    md = f"""# {project_name} 项目知识库

> 自动生成: {now}
> 工具: ctags + AST + graphviz
>
> 符号: {len(index)} 唯一 · 函数: {len(defs)} · 类: {len(classes)} · 调用边: {sum(len(v) for v in calls.values())}

## 符号种类分布

| 种类 | 数量 |
|------|------|
"""
    for kind, count in sorted(kind_counts.items(), key=lambda x: -x[1]):
        md += f"| {kind} | {count} |\n"

    md += f"""
## 模块索引 ({len(modules)} 文件)

| 模块 | 行数 | 类 | 公开函数 |
|------|------|-----|----------|
"""
    for path in sorted(modules.keys()):
        info = modules[path]
        cls_str = ', '.join(info['classes'][:3]) or '—'
        fn_str = ', '.join(info['funcs'][:3]) or '—'
        md += f"| {path} | {info['lines']} | {cls_str} | {fn_str} |\n"

    md += f"""
## Top 20 被调用函数

| 函数 | 文件:行号 | 调用者数 |
|------|-----------|----------|
"""
    callers = defaultdict(list)
    for caller, callees in calls.items():
        for callee in callees:
            callers[callee].append(caller)
    for name, clrs in sorted(callers.items(), key=lambda x: -len(x[1]))[:20]:
        loc = defs.get(name, {})
        fp = loc.get('file', '?')
        ln = loc.get('line', '?')
        md += f"| `{name}` | {fp}:{ln} | {len(clrs)} |\n"

    md += f"""
## 生成文件

| 文件 | 说明 |
|------|------|
| symbol_index.json | 符号→位置索引 |
| call_graph.json | AST 调用图 |
| ctags.json | 原始 ctags 输出 |
| call_flow.dot | Graphviz 调用流程图 |
| call_flow.svg | 调用流程图 SVG |
| kb.md | 本文档 |
"""
    kb_path = os.path.join(run_dir, "kb.md")
    with open(kb_path, 'w', encoding='utf-8') as f:
        f.write(md)
    _log(f"KB: {kb_path} ({len(md):,} chars)")

def _check_index_stale(directory, run_dir):
    """检查索引是否比源码文件旧。
    
    对比索引文件 mtime 与最近改动的 Python 源文件 mtime。
    如果任何源文件比索引新，返回 True（索引过期）。
    """
    idx_mtime = os.path.getmtime(os.path.join(run_dir, "symbol_index.json"))
    # 扫描 Python 源文件，找最新 mtime
    max_src_mtime = 0
    for root, dirs, files in os.walk(directory):
        # 跳过隐藏目录和虚拟环境
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'node_modules', 'venv', 'build', 'dist', '.git')]
        for f in files:
            if f.endswith('.py'):
                mtime = os.path.getmtime(os.path.join(root, f))
                if mtime > max_src_mtime:
                    max_src_mtime = mtime
    return max_src_mtime > idx_mtime


def _action_build(directory, force):
    """Internal: action build.
    
    Args:
        directory: Description.
        force: Description.
    """
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        return f"❌ 目录不存在: {directory}"

    run_dir = os.path.join(directory, _RUN_DIR)
    os.makedirs(run_dir, exist_ok=True)

    kb_path = os.path.join(run_dir, "kb.md")
    sym_path = os.path.join(run_dir, "symbol_index.json")
    if not force and os.path.exists(kb_path) and os.path.exists(sym_path):
        age = time.time() - os.path.getmtime(kb_path)
        if age < 3600:
            # 新鲜度检查：索引是否比源码旧
            stale = _check_index_stale(directory, run_dir)
            if not stale:
                return f"✅ 知识库已存在 (更新于 {age/60:.0f} 分钟前)，使用 force=true 强制重建"
            else:
                _log("⚠ 检测到源码变更，自动重建索引")

    _log(f"🏗 构建项目知识库: {directory}")
    t0 = time.time()

    _, index = _build_ctags(directory, run_dir)
    calls, defs, classes = _build_call_graph(directory)

    if not index and defs:
        for name, info in defs.items():
            index[name] = [{'kind': 'function', 'path': info['file'], 'line': info['line']}]
        for name, info in classes.items():
            if name not in index:
                index[name] = [{'kind': 'class', 'path': info['file'], 'line': info['line']}]
            else:
                index[name].append({'kind': 'class', 'path': info['file'], 'line': info['line']})
        _log(f"ctags 回退: AST {len(index)} 符号作为索引")

    cg_path = os.path.join(run_dir, "call_graph.json")
    with open(cg_path, 'w', encoding='utf-8') as f:
        json.dump({'functions': defs, 'classes': classes, 'calls': calls}, f, indent=2, ensure_ascii=False)

    idx_path = os.path.join(run_dir, "symbol_index.json")
    with open(idx_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    _build_dot_flow(calls, defs, run_dir)
    _build_kb_md(directory, index, calls, defs, classes, run_dir)

    # Build SymbolIndex (SQLite + TF-IDF 向量)
    try:
        from tea_agent.lsp.symbol_index import SymbolIndex
        si = SymbolIndex(directory)
        si.build_index(force=True)
        si.build_vector_index()
        si.close()
        _log(f"SymbolIndex: {si.get_symbol_count()} 符号已索引 (SQLite)")
    except Exception as e:
        _log(f"SymbolIndex 构建跳过: {e}")

    elapsed = time.time() - t0
    summary = (
        f"✅ 知识库构建完成 ({elapsed:.1f}s)\n"
        f"  📁 {run_dir}/\n"
        f"  🏷  {len(index)} 符号 · {len(defs)} 函数 · {len(classes)} 类\n"
        f"  🔗 {sum(len(v) for v in calls.values())} 调用边\n"
        f"  📄 kb.md / symbol_index.json / call_graph.json"
    )
    return summary

def _action_query(directory, symbol, query_type):
    """Internal: action query.
    
    Args:
        directory: Description.
        symbol: Description.
        query_type: Description.
    """
    directory = os.path.abspath(directory)
    run_dir = os.path.join(directory, _RUN_DIR)

    idx_path = os.path.join(run_dir, "symbol_index.json")
    cg_path = os.path.join(run_dir, "call_graph.json")

    if query_type == 'module':
        kb_path = os.path.join(run_dir, "kb.md")
        if os.path.exists(kb_path):
            with open(kb_path, 'r', encoding='utf-8') as f:
                content = f.read()
            in_table = False
            lines = []
            for line in content.split('\n'):
                if '## 模块索引' in line:
                    in_table = True
                    continue
                if in_table and line.startswith('## '):
                    break
                if in_table:
                    lines.append(line)
            return '\n'.join(lines[:50])
        return "❌ 无知识库，请先 build"

    if not symbol:
        return "❌ query 需要 symbol 参数"

    if query_type == 'symbol':
        if not os.path.exists(idx_path):
            return "❌ 无索引，请先 build"
        with open(idx_path, 'r', encoding='utf-8') as f:
            index = json.load(f)

        if symbol in index:
            entries = index[symbol]
            parts = [f"## `{symbol}` ({len(entries)} 处定义)"]
            for e in entries[:10]:
                parts.append(f"- [{e['kind']}] `{e['path']}:{e['line']}`")
            return '\n'.join(parts)
        else:
            matches = [k for k in index if symbol.lower() in k.lower()]
            if matches:
                if len(matches) == 1:
                    return _action_query(directory, matches[0], 'symbol')
                return f"未找到 `{symbol}`，相关: {', '.join(f'`{m}`' for m in matches[:15])}"
            return f"❌ 未找到 `{symbol}`"

    if not os.path.exists(cg_path):
        return "❌ 无调用图，请先 build"
    with open(cg_path, 'r', encoding='utf-8') as f:
        cg = json.load(f)

    calls = cg.get('calls', {})
    defs = cg.get('functions', {})

    if query_type == 'semantic':
        try:
            from tea_agent.lsp.symbol_index import SymbolIndex
            si = SymbolIndex(directory)
            results = si.search_natural(symbol, top_k=10)
            si.close()
            if not results:
                return f"Semantic search no results: {symbol}"
            parts = [f"## Semantic search: {symbol}"]
            for r in results:
                p = r.get('parent', '')
                name = f'{p}.{r["name"]}' if p else r['name']
                parts.append(f"- [sim={r['similarity']:.3f}] {name} ({r['file_path']}:{r['line']})")
            return chr(10).join(parts)
        except Exception as e:
            return f"Semantic search failed: {e}"

    if query_type == 'callers':
        callers = defaultdict(list)
        for caller, callees in calls.items():
            for callee in callees:
                callers[callee].append(caller)
        if symbol in callers:
            project_callers = [c for c in callers[symbol] if c not in _PYTHON_BUILTINS]
            builtin_count = len(callers[symbol]) - len(project_callers)
            parts = [f"## `{symbol}` 被 {len(project_callers)} 个项目函数调用" +
                     (f" (+{builtin_count} 内置)" if builtin_count > 0 else "") + ":"]
            if not project_callers:
                parts.append("_(无项目内调用者)_")
            for c in sorted(project_callers)[:30]:
                loc = defs.get(c, {}).get('file', '?')
                ln = defs.get(c, {}).get('line', '?')
                parts.append(f"- `{c}` ({loc}:{ln})")
            return '\n'.join(parts)
        return f"❌ `{symbol}` 无调用者记录"

    if query_type == 'callees':
        if symbol in calls:
            project_callees = [c for c in calls[symbol] if c not in _PYTHON_BUILTINS]
            builtin_count = len(calls[symbol]) - len(project_callees)
            parts = [f"## `{symbol}` 调用 {len(project_callees)} 个项目函数" +
                     (f" (+{builtin_count} 内置)" if builtin_count > 0 else "") + ":"]
            if not project_callees:
                parts.append("_(无项目内调用)_")
            for c in sorted(project_callees)[:30]:
                loc = defs.get(c, {}).get('file', '?')
                ln = defs.get(c, {}).get('line', '?')
                parts.append(f"- `{c}` ({loc}:{ln})")
            return '\n'.join(parts)
        return f"❌ `{symbol}` 无被调用记录"

    return "❌ 未知 query_type"

def _action_generate_docs(directory):
    """生成结构化项目文档（codegen-doc 风格）。

    生成 docs/ 目录下的：
      - API参考.md    — 所有模块的公开 API
      - 模块概览.md   — 模块职责与依赖关系
      - 调用图分析.md — Top 调用者和被调用者
      - 架构总览.md   — 项目级架构摘要

    Args:
        directory: 项目根目录

    Returns:
        结果摘要
    """
    directory = os.path.abspath(directory)
    run_dir = os.path.join(directory, _RUN_DIR)
    cg_path = os.path.join(run_dir, "call_graph.json")
    idx_path = os.path.join(run_dir, "symbol_index.json")

    # 若知识库不存在，先构建
    if not os.path.exists(cg_path) or not os.path.exists(idx_path):
        _log("知识库不存在，先自动构建...")
        _action_build(directory, force=True)

    # 加载数据
    with open(cg_path, 'r', encoding='utf-8') as f:
        cg = json.load(f)
    calls = cg.get('calls', {})
    defs = cg.get('functions', {})
    classes = cg.get('classes', {})

    if os.path.exists(idx_path):
        with open(idx_path, 'r', encoding='utf-8') as f:
            index = json.load(f)
    else:
        index = {}

    # 输出目录
    doc_dir = os.path.join(directory, "docs")
    os.makedirs(doc_dir, exist_ok=True)
    now = time.strftime("%Y-%m-%d %H:%M")
    project_name = os.path.basename(directory)

    # ── 1. API参考.md ──
    _log("生成 API参考.md ...")
    api_lines = [
        f"# {project_name} API 参考",
        "",
        f"> 自动生成: {now}  |  函数: {len(defs)}  |  类: {len(classes)}  |  符号: {len(index)}",
        "",
    ]

    # 按模块分组
    module_api = defaultdict(lambda: {"classes": [], "funcs": []})
    for sym, entries in index.items():
        for e in entries:
            path = e.get('path', '')
            kind = e.get('kind', '')
            line = e.get('line', '')
            module = os.path.dirname(path) or "root"
            if 'class' in kind or kind == 'member':
                module_api[module]["classes"].append((sym, path, line, kind))
            else:
                module_api[module]["funcs"].append((sym, path, line, kind))

    for module in sorted(module_api.keys()):
        info = module_api[module]
        cls_list = info["classes"]
        fn_list = info["funcs"]

        if not cls_list and not fn_list:
            continue

        api_lines.append(f"## 模块 `{module}`")
        api_lines.append("")

        # 类
        if cls_list:
            api_lines.append("### 类")
            api_lines.append("")
            api_lines.append("| 类名 | 文件:行号 | 类型 |")
            api_lines.append("|------|----------|------|")
            seen = set()
            for name, path, line, kind in sorted(cls_list):
                dedup_key = (name, path, line)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                api_lines.append(f"| `{name}` | `{path}:{line}` | {kind} |")
            api_lines.append("")

        # 函数
        if fn_list:
            api_lines.append("### 函数")
            api_lines.append("")
            api_lines.append("| 函数名 | 文件:行号 | 类型 |")
            api_lines.append("|--------|----------|------|")
            seen = set()
            for name, path, line, kind in sorted(fn_list):
                dedup_key = (name, path, line)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                api_lines.append(f"| `{name}` | `{path}:{line}` | {kind} |")
            api_lines.append("")

        # 限制条目数避免文档过肥
        if len(api_lines) > 2000:
            break

    with open(os.path.join(doc_dir, "API参考.md"), 'w', encoding='utf-8') as f:
        f.write('\n'.join(api_lines))

    # ── 2. 模块概览.md ──
    _log("生成 模块概览.md ...")
    mod_lines = [
        f"# {project_name} 模块概览",
        "",
        f"> 自动生成: {now}",
        "",
    ]
    # 收集模块级统计
    mod_stats = defaultdict(lambda: {"lines": 0, "funcs": 0, "classes": 0, "imports": set()})
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'build', 'dist', '.git', '.tea_agent_run', 'tmp', 'docs')]
        for fname in files:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, directory).replace('\\', '/')
            try:
                with open(fpath, 'r', encoding='utf-8') as fh:
                    src = fh.readlines()
            except Exception:
                continue
            mod_stats[relpath]["lines"] = len(src)
            for line in src:
                s = line.strip()
                if s.startswith('class '):
                    mod_stats[relpath]["classes"] += 1
                elif s.startswith('def ') and not s.startswith((' ', '\t')):
                    mod_stats[relpath]["funcs"] += 1
                elif s.startswith(('import ', 'from ')):
                    mod_stats[relpath]["imports"].add(s)

    mod_lines.append("| 模块 | 行数 | 类 | 函数 | 导入 |")
    mod_lines.append("|------|:----:|:---:|:----:|------|")
    for mp in sorted(mod_stats.keys()):
        s = mod_stats[mp]
        imps = ', '.join(sorted(s["imports"])[:3]) or "—"
        mod_lines.append(f"| `{mp}` | {s['lines']} | {s['classes']} | {s['funcs']} | {imps[:60]} |")

    mod_lines.append("")
    with open(os.path.join(doc_dir, "模块概览.md"), 'w', encoding='utf-8') as f:
        f.write('\n'.join(mod_lines))

    # ── 3. 调用图分析.md ──
    _log("生成 调用图分析.md ...")
    callers_map = defaultdict(list)
    for caller, callees in calls.items():
        for callee in callees:
            callers_map[callee].append(caller)

    call_lines = [
        f"# {project_name} 调用图分析",
        "",
        f"> 自动生成: {now}  |  调用边: {sum(len(v) for v in calls.values())}",
        "",
        "## Top 20 被调用最多",
        "",
        "| 函数 | 调用者数 | 文件:行号 |",
        "|------|:--------:|----------|",
    ]
    top_callees = sorted(callers_map.items(), key=lambda x: -len(x[1]))[:20]
    for name, clrs in top_callees:
        loc = defs.get(name, {})
        fp = loc.get('file', '?')
        ln = loc.get('line', '?')
        call_lines.append(f"| `{name}` | {len(clrs)} | `{fp}:{ln}` |")

    call_lines.append("")
    call_lines.append("## Top 20 最活跃调用者")
    call_lines.append("")
    call_lines.append("| 函数 | 调用次数 | 文件:行号 |")
    call_lines.append("|------|:--------:|----------|")
    top_callers = sorted(calls.items(), key=lambda x: -len(x[1]))[:20]
    for name, callees in top_callers:
        loc = defs.get(name, {})
        fp = loc.get('file', '?')
        ln = loc.get('line', '?')
        call_lines.append(f"| `{name}` | {len(callees)} | `{fp}:{ln}` |")

    call_lines.append("")
    with open(os.path.join(doc_dir, "调用图分析.md"), 'w', encoding='utf-8') as f:
        f.write('\n'.join(call_lines))

    # ── 4. 架构总览.md ──
    _log("生成 架构总览.md ...")
    arch_lines = [
        f"# {project_name} 架构总览",
        "",
        f"> 自动生成: {now}",
        "",
        f"## 项目规模",
        "",
        f"| 指标 | 数值 |",
        f"|------|:----:|",
        f"| Python 模块 | {len(mod_stats)} |",
        f"| 函数定义 | {len(defs)} |",
        f"| 类定义 | {len(classes)} |",
        f"| 符号总数 | {len(index)} |",
        f"| 调用边 | {sum(len(v) for v in calls.values())} |",
        "",
        "## 入口点",
        "",
    ]

    # 找入口点：定义了但很少被调用的顶层函数
    entry_points = []
    for name in defs:
        caller_count = len(callers_map.get(name, []))
        callee_count = len(calls.get(name, []))
        if caller_count <= 1 and callee_count >= 3:
            entry_points.append((name, callee_count, caller_count))
    for name, cc, cr in sorted(entry_points, key=lambda x: -x[1])[:10]:
        loc = defs.get(name, {})
        arch_lines.append(f"- **`{name}`** → 调用 {cc} 个函数，被 {cr} 个调用 (`{loc.get('file','?')}:{loc.get('line','?')}`)")

    arch_lines.append("")
    arch_lines.append("## 生成文档")
    arch_lines.append("")
    arch_lines.append("| 文档 | 说明 |")
    arch_lines.append("|------|------|")
    arch_lines.append("| [API参考.md](API参考.md) | 所有模块的公开 API 索引 |")
    arch_lines.append("| [模块概览.md](模块概览.md) | 模块职责与依赖关系 |")
    arch_lines.append("| [调用图分析.md](调用图分析.md) | Top 调用关系分析 |")
    arch_lines.append("| [架构总览.md](架构总览.md) | 本文档 |")
    arch_lines.append("")

    with open(os.path.join(doc_dir, "架构总览.md"), 'w', encoding='utf-8') as f:
        f.write('\n'.join(arch_lines))

    file_count = 4
    return (
        f"✅ 项目文档已生成 ({file_count} 文件)\n"
        f"  📁 {doc_dir}/\n"
        f"  📄 API参考.md — {len(defs)} 函数 + {len(classes)} 类\n"
        f"  📄 模块概览.md — {len(mod_stats)} 模块\n"
        f"  📄 调用图分析.md — {sum(len(v) for v in calls.values())} 调用边\n"
        f"  📄 架构总览.md — 入口点 {len(entry_points)} 个"
    )


def _action_status(directory):
    """Internal: action status.
    
    Args:
        directory: Description.
    """
    directory = os.path.abspath(directory)
    run_dir = os.path.join(directory, _RUN_DIR)
    if not os.path.isdir(run_dir):
        return f"❌ {_RUN_DIR}/ 不存在，请先 build"

    files = sorted(os.listdir(run_dir))
    lines = [f"📁 {run_dir}/ ({len(files)} 文件)"]
    total = 0
    for fname in files:
        fpath = os.path.join(run_dir, fname)
        size = os.path.getsize(fpath)
        total += size
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fpath)))
        lines.append(f"  {fname:25s} {size:>10,} bytes  [{mtime}]")

    idx_path = os.path.join(run_dir, "symbol_index.json")
    cg_path = os.path.join(run_dir, "call_graph.json")
    if os.path.exists(idx_path):
        with open(idx_path, 'r', encoding='utf-8') as f:
            index = json.load(f)
        lines.append(f"\n🏷 {len(index)} 符号")
    if os.path.exists(cg_path):
        with open(cg_path, 'r', encoding='utf-8') as f:
            cg = json.load(f)
        lines.append(f"🔗 {len(cg.get('calls', {}))} 函数有调用关系, {sum(len(v) for v in cg.get('calls', {}).values())} 调用边")

    lines.append(f"\n💾 总计 {total:,} bytes")
    return '\n'.join(lines)

def _extract_arch_context(directory, symbol=None):
    """提取项目或符号的架构上下文，辅助自进化决策"""
    directory = os.path.abspath(directory)
    run_dir = os.path.join(directory, _RUN_DIR)
    cg_path = os.path.join(run_dir, "call_graph.json")
    
    if not os.path.exists(cg_path):
        return "❌ 无调用图索引，请先 build"
        
    with open(cg_path, 'r', encoding='utf-8') as f:
        cg = json.load(f)
        
    calls = cg.get('calls', {})
    defs = cg.get('functions', {})
    classes = cg.get('classes', {})
    
    # 1. 项目级上下文
    if not symbol:
        lines = ["## 项目架构概览"]
        lines.append(f"- **函数定义**: {len(defs)} | **类定义**: {len(classes)} | **调用边**: {sum(len(v) for v in calls.values())}")
        
        entry_points = [c for c in calls if len(calls[c]) > 3 and c not in {callee for callees in calls.values() for callee in callees}]
        if entry_points:
            lines.append(f"\n### 🚪 疑似入口函数 (调用多且少被调用)")
            for ep in sorted(entry_points)[:5]:
                lines.append(f"- `{ep}`")
        return "\n".join(lines)

    # 2. 符号级上下文
    info = defs.get(symbol, classes.get(symbol))
    if not info:
        return f"❌ 未找到符号 `{symbol}` 的架构信息"
        
    lines = [f"## 🏛️ 架构上下文: `{symbol}`"]
    lines.append(f"- **类型**: {'📦 Class' if symbol in classes else '⚡ Function'}")
    lines.append(f"- **位置**: `{info['file']}:{info['line']}`")
    
    if symbol in calls:
        callees = [c for c in calls[symbol] if c not in _PYTHON_BUILTINS]
        if callees:
            lines.append(f"- **👇 依赖内部组件 ({len(callees)})**: `{', '.join(callees[:8])}`")
    
    callers = [c for c, callees in calls.items() if symbol in callees]
    if callers:
        lines.append(f"- **👆 被外部调用 ({len(callers)})**: `{', '.join(sorted(callers)[:8])}`")
        
    return "\n".join(lines)

# @2026-05-19 gen by claude, 影响分析 — 基于 tree-sitter 的仓库级上下文
def _action_impact(directory, symbol, filepath=None):
    """影响分析：修改 symbol 会影响哪些代码？"""
    from tea_agent.lsp.ts_analyzer import impact_analysis
    directory = os.path.abspath(directory)

    # 如果没提供 filepath，尝试从索引中查找
    if not filepath:
        run_dir = os.path.join(directory, _RUN_DIR)
        idx_path = os.path.join(run_dir, "symbol_index.json")
        if os.path.exists(idx_path):
            with open(idx_path, 'r', encoding='utf-8') as f:
                index = json.load(f)
            if symbol in index:
                entries = index[symbol]
                filepath = os.path.join(directory, entries[0]['path'])
            else:
                # 模糊匹配
                matches = [k for k in index if symbol.lower() in k.lower()]
                if len(matches) == 1:
                    symbol = matches[0]
                    filepath = os.path.join(directory, index[symbol][0]['path'])

    if not filepath or not os.path.isfile(filepath):
        return f"❌ 无法定位符号 `{symbol}` 的文件，请提供 filepath 参数"

    result = impact_analysis(directory, filepath, symbol)
    if not result.get("ok"):
        return f"❌ {result.get('error', '分析失败')}"

    lines = [f"## 💥 影响分析: `{symbol}`"]
    lines.append(f"- **定义位置**: `{result['definition']['file']}:{result['definition']['line']}`")
    lines.append(f"- **类型**: `{result['definition']['type']}`")
    lines.append(f"- **风险等级**: **{result['risk_level'].upper()}**")
    lines.append(f"")

    # 同文件其他符号
    same_file = result.get("same_file_symbols", [])
    if same_file:
        lines.append(f"### 📄 同文件其他符号 ({len(same_file)})")
        for s in same_file[:8]:
            lines.append(f"- `{s['name']}` ({s['kind']}:{s['line']})")
        lines.append(f"")

    # 直接调用者
    callers = result.get("direct_callers", [])
    if callers:
        lines.append(f"### 👆 直接调用者 ({len(callers)})")
        for c in callers[:15]:
            fname = os.path.relpath(c['file'], directory) if c.get('file') else '?'
            lines.append(f"- `{c.get('name', '?')}` → `{fname}:{c.get('line', '?')}`")
        lines.append(f"")

    # 间接调用者
    indirect = result.get("indirect_callers", [])
    if indirect:
        lines.append(f"### 🔄 间接影响 ({len(indirect)})")
        for c in indirect[:10]:
            fname = os.path.relpath(c['file'], directory) if c.get('file') else '?'
            lines.append(f"- `{c.get('name', '?')}` → `{fname}:{c.get('line', '?')}`")
        lines.append(f"")

    # 它调用了谁
    callees = result.get("callees", [])
    if callees:
        lines.append(f"### 👇 它依赖 ({len(callees)})")
        lines.append(f"`{', '.join(callees[:12])}`")
        lines.append(f"")

    lines.append(f"---\n> {result.get('hint', '')}")
    return '\n'.join(lines)

# @2026-05-19 gen by claude, 模块依赖图分析
def _action_deps(directory):
    """构建项目模块依赖图，检测循环依赖和孤立模块"""
    from tea_agent.lsp.ts_analyzer import build_dependency_graph
    directory = os.path.abspath(directory)
    result = build_dependency_graph(directory)

    if not result.get("ok"):
        return f"❌ 依赖分析失败"

    lines = [f"## 📊 模块依赖图"]
    lines.append(f"- **模块数**: {len(result['modules'])}")
    lines.append(f"")

    circular = result.get("circular", [])
    if circular:
        lines.append(f"### ⚠️ 循环依赖 ({len(circular)})")
        for cycle in circular[:5]:
            lines.append(f"- {' → '.join(cycle)}")
        lines.append(f"")

    orphans = result.get("orphans", [])
    if orphans:
        lines.append(f"### 🏝️ 孤立模块 ({len(orphans)})")
        for o in orphans[:10]:
            lines.append(f"- `{o}`")
        lines.append(f"")

    # Top importers
    top = sorted(result["modules"].items(),
                 key=lambda x: len(x[1].get("imported_by", [])),
                 reverse=True)[:10]
    if top:
        lines.append(f"### 📌 最被依赖的模块 (Top 10)")
        for mod, info in top:
            importers = info.get("imported_by", [])
            if importers:
                lines.append(f"- `{mod}` ← {len(importers)} 处引用: `{', '.join(importers[:3])}`")
        lines.append(f"")

    lines.append(f"---\n> {result.get('hint', '')}")
    return '\n'.join(lines)

def toolkit_explr(action="build", directory=".", symbol=None, query_type="symbol", force="false", filepath=None):
    """Toolkit explr.
    
    Args:
        action: Description.
        directory: Description.
        symbol: Description.
        query_type: Description.
        force: Description.
        filepath: Description.
    """
    logger.info(f"toolkit_explr called: action={action!r}, directory={repr(directory)[:80]}, symbol={symbol!r}, query_type={query_type!r}, force={force!r}")
    """Toolkit explr.
    
    Args:
        action: Description.
        directory: Description.
        symbol: Description.
        query_type: Description.
        force: Description.
        filepath: Description.
    """
    logger.info(f"toolkit_explr called: action={action!r}, directory={repr(directory)[:80]}, symbol={symbol!r}, query_type={query_type!r}, force={force!r}")
    force_bool = force in ("true", "True", "1")
    if action == "build":
        return _action_build(directory, force_bool)
    elif action == "generate_docs":
        return _action_generate_docs(directory)
    elif action == "query":
        if query_type == "arch_context":
            return _extract_arch_context(directory, symbol)
        if query_type == "impact":
            return _action_impact(directory, symbol, filepath)
        if query_type == "deps":
            return _action_deps(directory)
        return _action_query(directory, symbol, query_type)
    elif action == "status":
        return _action_status(directory)
    else:
        return f"❌ 未知 action: {action}"

# @2026-05-19 gen by claude, 新增 impact(影响分析) / deps(依赖图) 查询类型 + filepath 参数
def meta_toolkit_explr() -> dict:
    """Meta toolkit explr."""
    return {"type": "function", "function": {"name": "toolkit_explr", "description": "项目知识库构建与查询。action=build 构建符号索引+AST调用图+流程图+kb.md；action=generate_docs 生成结构化项目文档到docs/；action=query 查询符号位置/调用者/被调用者/影响分析/依赖图；action=status 查看知识库状态。默认存储于当前目录 .tea_agent_run/。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["build", "generate_docs", "query", "status"], "description": "build=构建项目知识库, generate_docs=生成结构化文档, query=查询符号/调用关系/影响/依赖, status=查看知识库状态"}, "directory": {"type": "string", "description": "项目目录，默认当前目录", "default": "."}, "symbol": {"type": "string", "description": "[query] 要查询的符号名"}, "query_type": {"type": "string", "enum": ["symbol", "callers", "callees", "module", "semantic", "arch_context", "impact", "deps"], "description": "[query] 查询类型：symbol=符号定位, callers=谁调此函数, callees=此函数调谁, module=模块概览, arch_context=架构上下文, impact=影响分析, deps=模块依赖图", "default": "symbol"}, "force": {"type": "string", "enum": ["true", "false"], "description": "[build] true=强制重建，忽略已有索引", "default": "false"}, "filepath": {"type": "string", "description": "[impact] 符号所在的文件路径"}}, "required": ["action"]}}}
