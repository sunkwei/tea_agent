"""onlinesession.py 组件拆分脚本（一次性）：
  APIComponent        → tea_agent/session/components/api.py
  ToolComponent       → tea_agent/session/components/tool.py   (+ _summarize_json)
  SummarizerComponent → tea_agent/session/components/summarizer.py
主文件保留全部顶层函数与 OnlineToolSession，顶部 re-export 组件保持向后兼容。
"""
import ast
import os
import shutil

os.chdir(os.path.dirname(os.path.abspath(__file__)))
SRC = "tea_agent/onlinesession.py"
PKG_DIR = "tea_agent/session/components"
os.makedirs(PKG_DIR, exist_ok=True)

src = open(SRC, encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

# ── 1) 收集模块级 import 语句（源码行）───────────────────────────
import_stmts: list[tuple[ast.Import | ast.ImportFrom, list[str], str]] = []
for n in tree.body:
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        al = [a.asname or a.name.split(".")[-1] for a in n.names]
        import_stmts.append((n, al, ast.get_source_segment(src, n) or ""))

def needed_import_block(need: set[str]) -> list[str]:
    """按别名需求重建 import 语句（同语句按需裁剪）。"""
    out = []
    for n, al, seg in import_stmts:
        keep = [(a, idx) for idx, a in enumerate(n.names) if (a.asname or a.name.split(".")[-1]) in need]
        if not keep:
            continue
        if isinstance(n, ast.Import):
            names = ", ".join(
                (a.name if not a.asname else f"{a.name} as {a.asname}") for a, _ in keep
            )
            out.append(f"import {names}")
        else:
            names = ", ".join(
                (a.name if not a.asname else f"{a.name} as {a.asname}") for a, _ in keep
            )
            mod = n.module or ""
            out.append(f"from {mod} import {names}")
    return out

# ── 2) 类定义区间（含 decorator）─────────────────────────────────
def class_span(cls: ast.ClassDef) -> tuple[int, int]:
    start = cls.lineno
    if cls.decorator_list:
        start = min(d.lineno for d in cls.decorator_list)
    return start, cls.end_lineno

comps = {}
for n in tree.body:
    if isinstance(n, ast.ClassDef) and n.name in {
        "APIComponent", "ToolComponent", "SummarizerComponent",
    }:
        s, e = class_span(n)
        comps[n.name] = (n, s, e, ast.get_source_segment(src, n) or "")

# 模块级赋值名（logger / 常量），供组件文件复制
mod_assign = {}
for n in tree.body:
    if isinstance(n, ast.Assign):
        for tg in n.targets:
            if isinstance(tg, ast.Name):
                mod_assign[tg.id] = ast.get_source_segment(src, n) or ""
    elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
        mod_assign[n.target.id] = ast.get_source_segment(src, n) or ""

def class_global_refs(cls: ast.ClassDef) -> set[str]:
    local = set()
    for n in ast.walk(cls):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(n.name)
        if isinstance(n, ast.arg):
            local.add(n.arg)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            local.add(n.id)
    used = set()
    for n in ast.walk(cls):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in local:
            used.add(n.id)
    return used

# 模块级函数/类定义名（排除当前类自身）
mod_def = {}
for n in tree.body:
    if isinstance(n, (ast.ClassDef, ast.FunctionDef)):
        mod_def[n.name] = (n.lineno, n.end_lineno, ast.get_source_segment(src, n) or "")
    elif isinstance(n, (ast.AsyncFunctionDef,)):
        mod_def[n.name] = (n.lineno, n.end_lineno, ast.get_source_segment(src, n) or "")

def helper_func(name: str) -> str:
    """取模块级函数源码（供 tool.py 内嵌 _summarize_json）。"""
    return mod_def[name][2]

# ── 3) 组件文件装配 ──────────────────────────────────────────────
EXTRA_HELPERS = {"ToolComponent": ["_summarize_json"]}   # 类依赖的模块函数
EXTRA_CONSTS = {"ToolComponent": ["logger"], "SummarizerComponent": ["logger"]}

HDR = '"""{desc} —— 从 onlinesession.py 拆分（2026-09-06，保持 API 兼容）。"""\n\n'
file_plan = {
    "api.py": ("APIComponent（API 调用与消息组装组件）", "APIComponent"),
    "tool.py": ("ToolComponent（工具执行循环组件）", "ToolComponent"),
    "summarizer.py": ("SummarizerComponent（会话摘要组件）", "SummarizerComponent"),
}

for fname, (desc, clsname) in file_plan.items():
    cls, s, e, body = comps[clsname]
    used = class_global_refs(cls)
    # 排除将内嵌的 helper/常量（避免重复 import）
    helpers = EXTRA_HELPERS.get(clsname, [])
    consts = EXTRA_CONSTS.get(clsname, [])
    need_imports = used - set(mod_def) - set(consts)
    need_imports = {x for x in need_imports if x not in helpers}

    parts = [HDR.format(desc=desc)]
    imp = needed_import_block(need_imports)
    parts.append("\n".join(imp))
    parts.append("\n")
    for h in helpers:
        parts.append("\n" + helper_func(h) + "\n")
    for c in consts:
        parts.append("\n" + mod_assign[c] + "\n")
    parts.append("\n" + body + "\n")
    with open(os.path.join(PKG_DIR, fname), "w", encoding="utf-8") as f:
        f.write("".join(parts))
    print(f"== {fname}: {clsname} (行 {s}-{e}) 写出, imports={sorted(need_imports)}")

# 组件包 __init__（re-export，保持 from ...components import X 可用）
with open(os.path.join(PKG_DIR, "__init__.py"), "w", encoding="utf-8") as f:
    f.write('"""session 组件包（从 onlinesession.py 拆出）。"""\n'
            "from tea_agent.session.components.api import APIComponent\n"
            "from tea_agent.session.components.tool import ToolComponent\n"
            "from tea_agent.session.components.summarizer import SummarizerComponent\n"
            "\n__all__ = [\"APIComponent\", \"ToolComponent\", \"SummarizerComponent\"]\n")
print("== __init__.py 写出")

# ── 4) 主文件改造：删除组件类与随迁 helper，顶部补 import ──────
shutil.copy2(SRC, SRC + ".bak_split_20260906")
drop_spans = sorted([(comps[n][1], comps[n][2]) for n in comps], reverse=True)
# 随迁 helper：_summarize_json 若被 ToolComponent 使用则从主文件移除
helper_spans = []
for h in EXTRA_HELPERS.get("ToolComponent", []):
    if h in mod_def and h.startswith("_"):
        helper_spans.append((mod_def[h][0], mod_def[h][1]))

for s, e in sorted(drop_spans + helper_spans, reverse=True):
    # 向两端吸收相邻空行/注释，避免残留空块
    while s - 2 >= 0 and lines[s - 1].strip() == "":
        s -= 1
    while e < len(lines) and lines[e - 1].strip() == "":
        e += 1
    del lines[s - 1 : e]

new_src = "".join(lines)
# 在第一个 import 组后插入组件 re-export
anchor = "from tea_agent.session.tool_loop_runner import execute_tool_loop\n"
assert anchor in new_src, "anchor import 未找到"
new_src = new_src.replace(
    anchor,
    anchor
    + "from tea_agent.session.components import (  # noqa: F401  (从 onlinesession.py 拆出，保持向后兼容)\n"
    + "    APIComponent,\n"
    + "    SummarizerComponent,\n"
    + "    ToolComponent,\n"
    + ")\n",
    1,
)
with open(SRC, "w", encoding="utf-8") as f:
    f.write(new_src)
print(f"== 主文件改造完成：{len(lines)} → {len(new_src.splitlines())} 行")

# ── 5) 编译验证 ─────────────────────────────────────────────────
import py_compile
for f in [SRC, os.path.join(PKG_DIR, "api.py"), os.path.join(PKG_DIR, "tool.py"),
          os.path.join(PKG_DIR, "summarizer.py"), os.path.join(PKG_DIR, "__init__.py")]:
    py_compile.compile(f, doraise=True)
print("== py_compile 全部通过")
