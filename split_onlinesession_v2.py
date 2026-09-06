"""onlinesession.py 组件拆分 v2（稳健版）：
- 三个组件各自成文件，携带【完整原始 import 头】（不裁剪，避免缺 import）
- 生成后若可用 ruff 自动清理未用 import (F401)
- 主文件删除三组件类与随迁 helper，顶部 re-export 保持兼容
"""
import ast
import os
import shutil
import subprocess
import sys
import py_compile

os.chdir(os.path.dirname(os.path.abspath(__file__)))
SRC = "tea_agent/onlinesession.py"
PKG_DIR = "tea_agent/session/components"
os.makedirs(PKG_DIR, exist_ok=True)

src = open(SRC, encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

# 1) 全部模块级 import 语句源码行（保序去重）
imp_segs = []
for n in tree.body:
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        seg = ast.get_source_segment(src, n).rstrip()
        if seg not in imp_segs:
            imp_segs.append(seg)
IMPORT_HEAD = "\n".join(imp_segs)

# 2) 类定义区间
def span(cls):
    s = cls.lineno
    if cls.decorator_list:
        s = min(d.lineno for d in cls.decorator_list)
    return s, cls.end_lineno

classes = {}
for n in tree.body:
    if isinstance(n, ast.ClassDef) and n.name in {"APIComponent", "ToolComponent", "SummarizerComponent"}:
        classes[n.name] = (span(n), ast.get_source_segment(src, n))

# 3) 模块级函数（随迁 helper）
defs = {}
for n in tree.body:
    if isinstance(n, ast.FunctionDef):
        defs[n.name] = (n.lineno, n.end_lineno, ast.get_source_segment(src, n))

EXTRA_HELPERS = {"ToolComponent": ["_summarize_json"]}   # 类依赖、需随迁的模块函数
HELPER_EXTRA_IMPORTS = {"_summarize_json": ["import json\n", "from typing import Any\n"]}

HDR_TMPL = '"""{{name}} —— 从 onlinesession.py 拆分（2026-09-06，保持 API 兼容）。"""\n\n'
files = {
    "api.py": ("APIComponent", "APIComponent（LLM API 通信与消息组装组件）"),
    "tool.py": ("ToolComponent", "ToolComponent（工具执行循环组件）"),
    "summarizer.py": ("SummarizerComponent", "SummarizerComponent（会话摘要组件）"),
}

for fname, (clsname, desc) in files.items():
    (s, e), body = classes[clsname]
    parts = [HDR_TMPL.format(name=desc), IMPORT_HEAD, "\n"]
    # logger 定义（组件文件各自持有）
    parts.append('\nlogger = logging.getLogger("session")\n')
    for h in EXTRA_HELPERS.get(clsname, []):
        parts.append("\n" + defs[h][2] + "\n")
    parts.append("\n" + body + "\n")
    with open(os.path.join(PKG_DIR, fname), "w", encoding="utf-8") as f:
        f.write("".join(parts))
    print(f"== {fname}: {clsname} (行 {s}-{e}) 写出")

with open(os.path.join(PKG_DIR, "__init__.py"), "w", encoding="utf-8") as f:
    f.write('"""session 组件包（从 onlinesession.py 拆出）。"""\n'
            "from tea_agent.session.components.api import APIComponent\n"
            "from tea_agent.session.components.tool import ToolComponent\n"
            "from tea_agent.session.components.summarizer import SummarizerComponent\n"
            '\n__all__ = ["APIComponent", "ToolComponent", "SummarizerComponent"]\n')
print("== __init__.py 写出")

# 4) 主文件改造
shutil.copy2(SRC, SRC + ".bak_split2_20260906")
drop = []
for clsname, ((s, e), _body) in classes.items():
    drop.append((s, e))
for clsname, helpers in EXTRA_HELPERS.items():
    for h in helpers:
        drop.append((defs[h][0], defs[h][1]))
for s, e in sorted(drop, reverse=True):
    while s - 2 >= 0 and lines[s - 1].strip() == "":
        s -= 1
    while e < len(lines) and lines[e - 1].strip() == "":
        e += 1
    del lines[s - 1:e]
new_src = "".join(lines)
anchor = "from tea_agent.session.tool_loop_runner import execute_tool_loop\n"
assert anchor in new_src
new_src = new_src.replace(
    anchor,
    anchor + "from tea_agent.session.components import (  # noqa: F401  拆分自本文件，re-export 兼容\n"
    + "    APIComponent,\n    SummarizerComponent,\n    ToolComponent,\n)\n",
    1,
)
with open(SRC, "w", encoding="utf-8") as f:
    f.write(new_src)
print(f"== 主文件: {len(lines)} → {len(new_src.splitlines())} 行")

# 5) 编译 + ruff 清理未用 import（可选）
for f in [SRC, os.path.join(PKG_DIR, "api.py"), os.path.join(PKG_DIR, "tool.py"),
          os.path.join(PKG_DIR, "summarizer.py")]:
    py_compile.compile(f, doraise=True)
print("== py_compile 全部通过")

ruff = shutil.which("ruff")
if ruff:
    for f in [SRC, os.path.join(PKG_DIR, "api.py"), os.path.join(PKG_DIR, "tool.py"),
              os.path.join(PKG_DIR, "summarizer.py")]:
        r = subprocess.run([ruff, "check", "--fix", "--select", "F401", f],
                           capture_output=True, text=True)
        print(f"ruff fix {os.path.basename(f)} RC {r.returncode}: {r.stdout.strip()[-200:]}")
else:
    print("ruff 不可用，跳过清理（未用 import 需后续 ruff check --fix）")
