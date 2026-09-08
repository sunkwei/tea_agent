"""只读死代码/冗余扫描：找出 tea_agent 核心模块中定义但从未被引用的顶层符号，以及重复定义。"""
import ast, os, sys, collections

ROOT = r"C:\Users\Hetin\work\git\tea_agent"
PKG = os.path.join(ROOT, "tea_agent")

def py_files(base):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "build", "dist", ".git", "node_modules", "egg-info")]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)

# 1) 收集所有文件及其顶层定义、import 名称
all_files = list(py_files(PKG)) + list(py_files(os.path.join(ROOT, "tea_agent_mini")))
# 也加入根目录散落 py / tests / sdk / server 等以便引用计数准确
extra_dirs = [os.path.join(ROOT, d) for d in ("tests", "scripts", "sdk", "demo", "benchmark") if os.path.isdir(os.path.join(ROOT, d))]
extra_dirs += [os.path.join(ROOT, "tea_agent", d) for d in ("tests", "toolkit", "server", "session", "workflow", "multi_agent", "protocol", "lsp", "skills", "channel", "compaction") if os.path.isdir(os.path.join(ROOT, "tea_agent", d))]
for ed in extra_dirs:
    all_files += list(py_files(ed))

module_defs = {}   # (module, name) -> count of defs
all_defined = collections.Counter()
references = collections.Counter()
file_of_def = {}
modpath_of_file = {}
module_defs = collections.Counter()  # (module, name) -> 1

for fp in all_files:
    try:
        src = open(fp, encoding="utf-8", errors="ignore").read()
        tree = ast.parse(src)
    except Exception:
        continue
    rel = os.path.relpath(fp, ROOT).replace("\\", "/").replace("/", ".")
    rel = rel[:-3] if rel.endswith(".py") else rel
    modpath_of_file[fp] = rel
    for node in ast.walk(tree):
        # 记录引用：所有 Name / Attribute 中出现的标识符
        pass
    # 顶层 def/class 收集
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            key = (rel, node.name)
            all_defined[node.name] += 1
            file_of_def.setdefault(node.name, set()).add(fp)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                nm = a.asname or a.name.split(".")[0]
                references[nm] += 1

# 2) 遍历全文统计任何标识符出现（含 attribute 尾名），粗粒度判断死代码
name_occurrences = collections.Counter()
for fp in all_files:
    try:
        src = open(fp, encoding="utf-8", errors="ignore").read()
        tree = ast.parse(src)
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name_occurrences[node.id] += 1
        elif isinstance(node, ast.Attribute):
            name_occurrences[node.attr] += 1
        elif isinstance(node, ast.FunctionDef):
            name_occurrences[node.name] += 1  # 自身定义也算出现
        elif isinstance(node, ast.ClassDef):
            name_occurrences[node.name] += 1

# 3) 输出：核心模块中定义次数>0 但 全库出现次数<=定义次数(=仅自身定义处出现) 的顶层符号
CORE = ["tea_agent.onlinesession", "tea_agent.memory", "tea_agent.basesession", "tea_agent.agent", "tea_agent.litesession",
        "tea_agent.session_pipeline", "tea_agent.agent_pipeline", "tea_agent.agent_background", "tea_agent.reflection",
        "tea_agent.project_memory", "tea_agent.session_memory_component", "tea_agent.cross_topic_summarizer",
        "tea_agent.merge_db", "tea_agent.provider_store", "tea_agent.auto_compact", "tea_agent.scheduler_storage"]
CORE_PREFIX = tuple(c + "." for c in CORE)

print("=== 候选死代码（顶层 def/class，全库除定义处外几乎无引用）===")
for (mod, name), cnt in sorted(all_defined.items()):
    if not (mod in CORE or mod.startswith(CORE_PREFIX)):
        continue
    # 粗判定：全库该名字出现次数 <= 1 且定义处无调用
    occ = name_occurrences.get(name, 0)
    if occ <= 2:  # 只有 def + 可能的 docstring
        print(f"  {mod} :: {name}  (出现 {occ} 次)")

print("\n=== 按模块统计顶层符号数 ===")
for m in sorted(set(m for (m, _) in all_defined if m in CORE or m.startswith(CORE_PREFIX))):
    syms = [n for (mm, n) in all_defined if mm == m]
    print(f"  {m}: {len(syms)} 个顶层符号")
