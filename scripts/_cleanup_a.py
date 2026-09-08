"""A 类冗余清理（一次性）：.bak 备份 + compaction 空包 + 5 个确认死函数。含自验证与 git 记录。"""
import ast, os, subprocess, sys

ROOT = r"C:\Users\Hetin\work\git\tea_agent"
PKG = os.path.join(ROOT, "tea_agent")

SKIP_DIRS = {"__pycache__", ".git", "build", "dist", "node_modules", ".egg-info", ".tea_agent_run", "_pt", "_pt_run"}
report = {"bak_removed": [], "dead_funcs": [], "compaction": [], "errors": []}

# ---------- 1. 删除 .bak 系列（含 .bak 后缀及 *.bak.* / *.bak_*） ----------
for base in [ROOT, PKG]:
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith("_pt")]
        for fn in filenames:
            if fn.endswith(".bak") or ".bak." in fn or ".bak_" in fn or fn.endswith(".bak.py"):
                fp = os.path.join(dirpath, fn)
                try:
                    os.remove(fp)
                    report["bak_removed"].append(os.path.relpath(fp, ROOT))
                except OSError as e:
                    report["errors"].append(f"del {fp}: {e}")

# ---------- 2. 删除 compaction 空包 ----------
comp = os.path.join(PKG, "compaction")
if os.path.isdir(comp):
    for fn in os.listdir(comp):
        fp = os.path.join(comp, fn)
        if fn.endswith(".py"):
            try:
                os.remove(fp)
                report["compaction"].append(os.path.relpath(fp, ROOT))
            except OSError as e:
                report["errors"].append(f"del {fp}: {e}")
    try:
        os.rmdir(comp)
        report["compaction"].append("tea_agent/compaction/ (dir removed)")
    except OSError as e:
        report["errors"].append(f"rmdir {comp}: {e}")

# ---------- 3. 删除 5 个确认死函数（AST 精确行区间） ----------
# (文件相对路径, [要删的顶层符号名])
DEAD = {
    "tea_agent/auto_compact.py": ["generate_branch_summary", "AutoCompactStep", "unregister_post_compact_hook"],
    "tea_agent/providers.py": ["switch_provider"],
    "tea_agent/config.py": ["set_active_config_path"],
}

def find_top_level_nodes(src, names):
    """返回 {name: (start_lineno, end_lineno)} 顶层节点区间（1-based，含装饰器）。"""
    tree = ast.parse(src)
    result = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in names:
                start = node.lineno
                # 包含装饰器
                if node.decorator_list:
                    start = min(d.lineno for d in node.decorator_list)
                end = getattr(node, "end_lineno", node.lineno)
                result[node.name] = (start, end)
    return result

for rel, names in DEAD.items():
    fp = os.path.join(ROOT, rel.replace("/", os.sep))
    try:
        src = open(fp, encoding="utf-8").read()
        lines = src.splitlines(keepends=True)
        ranges = find_top_level_nodes(src, names)
        missing = [n for n in names if n not in ranges]
        if missing:
            report["errors"].append(f"{rel}: 未找到 {missing}")
            continue
        # 标记删除行（去重、从大到小删）
        drop = set()
        for name, (s, e) in ranges.items():
            # 删除节点主体行 + 节点后紧跟的注释行/空行（保留至多 1 个空行分隔）
            drop.update(range(s, e + 1))
            nxt = e  # 已含 end
            while nxt < len(lines) - 1:
                stripped = lines[nxt].strip()
                if stripped == "":
                    nxt += 1
                elif stripped.startswith("#"):
                    drop.add(nxt)
                    nxt += 1
                else:
                    break
            report["dead_funcs"].append(f"{rel}:{s} {name} (行 {s}-{e})")
        new_lines = [l for i, l in enumerate(lines, 1) if i not in drop]
        # 清理可能的连续 3+ 空行
        out, blank = [], 0
        for l in new_lines:
            if l.strip() == "":
                blank += 1
                if blank <= 2:
                    out.append(l)
            else:
                blank = 0
                out.append(l)
        # 验证语法
        try:
            ast.parse("".join(out))
        except SyntaxError as e:
            report["errors"].append(f"{rel}: 删除后语法错误 {e} — 已跳过写入")
            continue
        open(fp, "w", encoding="utf-8").write("".join(out))
    except Exception as e:
        report["errors"].append(f"{rel}: {e}")

# ---------- 4. 输出报告 ----------
print(f"已删除 .bak 文件: {len(report['bak_removed'])} 个")
print(f"已删除 compaction 条目: {len(report['compaction'])}")
print(f"已删除死函数: {len(report['dead_funcs'])}")
for d in report["dead_funcs"]:
    print("   ", d)
if report["errors"]:
    print("\n⚠️ 错误:")
    for e in report["errors"]:
        print("  ", e)
else:
    print("\n✅ 无错误")

# 写入 git 删除清单供提交
with open(os.path.join(ROOT, "_cleanup_a_list.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(sorted(report["bak_removed"])))
print(f"\n总删除文件数: {len(report['bak_removed']) + len(report['compaction'])}")
