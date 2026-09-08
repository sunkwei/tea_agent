"""只读死代码/冗余扫描 v2：核心模块顶层符号定义 vs 全库引用计数。"""
import ast, os, collections

ROOT = r"C:\Users\Hetin\work\git\tea_agent"
PKG = os.path.join(ROOT, "tea_agent")

def py_files(base):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "build", "dist", ".git", "node_modules", ".egg-info", ".tea_agent_run")]
        for fn in filenames:
            if fn.endswith(".py") and not fn.endswith(".bak.py"):
                yield os.path.join(dirpath, fn)

bases = [PKG, os.path.join(ROOT, "tea_agent_mini")]
for d in ("tests", "scripts", "sdk", "demo", "benchmark", "deploy"):
    p = os.path.join(ROOT, d)
    if os.path.isdir(p):
        bases.append(p)
for d in ("tests", "toolkit", "server", "session", "workflow", "multi_agent", "protocol", "lsp", "skills", "channel", "compaction", "evaluation", "demo", "scripts", "sdk"):
    p = os.path.join(PKG, d)
    if os.path.isdir(p):
        bases.append(p)

all_files = []
for b in bases:
    all_files += list(py_files(b))
all_files = list(set(all_files))

def relmod(fp):
    rel = os.path.relpath(fp, ROOT).replace("\\", "/")
    rel = rel[:-3] if rel.endswith(".py") else rel
    return rel.replace("/", ".")

name_occ = collections.Counter()       # 标识符出现次数（含定义处）
def_symbols = collections.defaultdict(list)  # mod -> [(name, kind, lineno)]

for fp in all_files:
    try:
        src = open(fp, encoding="utf-8", errors="ignore").read()
        tree = ast.parse(src)
    except Exception as e:
        print(f"[parse-error] {fp}: {e}")
        continue
    mod = relmod(fp)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name_occ[node.id] += 1
        elif isinstance(node, ast.Attribute):
            name_occ[node.attr] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name_occ[node.name] += 1
        elif isinstance(node, ast.ClassDef):
            name_occ[node.name] += 1
        elif isinstance(node, ast.arg):
            name_occ[node.arg] += 1
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            def_symbols[mod].append((node.name, type(node).__name__, node.lineno))

CORE_MODS = [
    "tea_agent/onlinesession", "tea_agent/memory", "tea_agent/basesession",
    "tea_agent/agent", "tea_agent/litesession", "tea_agent/session_pipeline",
    "tea_agent/agent_pipeline", "tea_agent/agent_background", "tea_agent/reflection",
    "tea_agent/project_memory", "tea_agent/session_memory_component",
    "tea_agent/cross_topic_summarizer", "tea_agent/merge_db",
    "tea_agent/provider_store", "tea_agent/auto_compact", "tea_agent/scheduler_storage",
    "tea_agent/model_manager", "tea_agent/model_config", "tea_agent/providers",
    "tea_agent/config", "tea_agent/tlk",
]
# 用模块相对路径的 . 表示
def path_of(mod):
    return mod.replace("/", ".")

print("=== 核心模块：可能死代码的顶层符号（全库出现 <=2 次 ≈ 仅定义处） ===")
for mod in CORE_MODS:
    p = path_of(mod)
    syms = def_symbols.get(mod) or def_symbols.get(p)
    if not syms:
        continue
    for name, kind, ln in sorted(syms, key=lambda x: x[2]):
        if name.startswith("_"):
            continue
        occ = name_occ.get(name, 0)
        if occ <= 2:
            print(f"  {mod}:{ln}  {kind:12s} {name}   (全库出现 {occ} 次)")

print("\n=== 每个核心模块顶层符号数量 ===")
for mod in CORE_MODS:
    syms = def_symbols.get(mod) or def_symbols.get(path_of(mod))
    print(f"  {mod}: {len(syms) if syms else 0} 个顶层符号")

# 附加：整库 .bak 文件统计
print("\n=== 整库 .bak 文件（冗余候选） ===")
bak = []
for b in bases:
    for dirpath, _, fns in os.walk(b):
        for fn in fns:
            if fn.endswith(".bak") or ".bak." in fn or fn.endswith(".bak.py") or ".bak_" in fn:
                fp = os.path.join(dirpath, fn)
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    sz = 0
                bak.append((fp, sz))
for fp, sz in sorted(bak, key=lambda x: -x[1]):
    print(f"  {os.path.relpath(fp, ROOT)}  ({sz} B)")
print(f"  --- 共 {len(bak)} 个备份文件 ---")
