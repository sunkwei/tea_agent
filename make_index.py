# @2026-05-09 gen by tea_agent, 纯 Python 源码索引器（零外部依赖，替代 ctags）
"""
源码索引器 — 纯 Python 实现，零外部依赖。
扫描项目 Python 文件，提取函数/类/方法/导入/注释标记，生成 JSON 索引。

用法:
  python make_index.py                     # 生成/更新索引
  python make_index.py --watch             # 持续监控文件变化
  python make_index.py --query "function_name"  # 查询符号定义
"""

import os
import re
import json
import time
import ast
from pathlib import Path
from typing import Dict, List, Optional, Set

# ── 配置 ──
PROJECT_ROOT = Path(__file__).resolve().parent
INDEX_DIR = PROJECT_ROOT / ".tea_agent_run" / "index"
INDEX_FILE = INDEX_DIR / "source_index.json"
FILE_INDEX_FILE = INDEX_DIR / "file_index.json"

# 排除的目录
EXCLUDE_DIRS: Set[str] = {
    "__pycache__", ".git", ".tea_agent_run", "build", "dist",
    "*.egg-info", "backup", "dump_*", "tmp", ".vscode", ".idea",
}

# 排除的文件模式
EXCLUDE_PATTERNS = [
    r".*\.bak$", r".*\.bak\.py$", r"^~.*",  # 备份文件
]


def should_skip_path(path: Path) -> bool:
    """判断是否应跳过该路径"""
    parts = path.parts
    for part in parts:
        for exc in EXCLUDE_DIRS:
            if re.match(exc.replace("*", ".*"), part):
                return True
    name = path.name
    for pat in EXCLUDE_PATTERNS:
        if re.match(pat, name):
            return True
    return False


def extract_py_symbols(filepath: Path) -> Dict:
    """使用 AST 和正则提取 Python 文件中的符号"""
    result = {
        "file": str(filepath.relative_to(PROJECT_ROOT)),
        "size": filepath.stat().st_size,
        "mtime": filepath.stat().st_mtime,
        "imports": [],
        "classes": [],
        "functions": [],
        "methods": [],
        "decorators": [],
        "comments": [],  # NOTE/MARK/TODO/FIXME 注释
        "docstring": "",
    }

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
    except Exception:
        return result

    # ── 正则提取注释中的标记 ──
    for match in re.finditer(
        r'(?:^|\n)\s*#\s*(NOTE|MARK|TODO|FIXME|HACK|XXX|WARNING|BUG)[\s:：-]+(.+?)(?:\n|$)',
        source, re.IGNORECASE
    ):
        result["comments"].append({
            "tag": match.group(1).upper(),
            "text": match.group(2).strip(),
            "line": source[:match.start()].count("\n") + 1,
        })

    # ── AST 提取符号 ──
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return result

    # 模块级 docstring
    if (isinstance(tree.body, list) and tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, (ast.Constant, ast.Str))):
        val = tree.body[0].value
        result["docstring"] = (val.value if hasattr(val, 'value') else val.s)[:200]

    for node in ast.walk(tree):
        # 导入
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append({
                    "module": alias.name,
                    "alias": alias.asname,
                    "line": node.lineno,
                })
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                result["imports"].append({
                    "module": f"{mod}.{alias.name}",
                    "alias": alias.asname,
                    "line": node.lineno,
                })

        # 类定义
        elif isinstance(node, ast.ClassDef):
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(f"{base.value.id}.{base.attr}" if hasattr(base.value, 'id') else base.attr)
            cls_info = {
                "name": node.name,
                "bases": bases,
                "line": node.lineno,
                "decorators": [d.id if isinstance(d, ast.Name) else str(getattr(d, 'attr', d)) for d in node.decorator_list],
            }
            result["classes"].append(cls_info)

        # 函数定义（模块级）
        elif isinstance(node, ast.FunctionDef):
            # 判断是否在类内部
            parent = getattr(node, '_parent', None)
            func_info = {
                "name": node.name,
                "line": node.lineno,
                "args": [arg.arg for arg in node.args.args],
                "decorators": [d.id if isinstance(d, ast.Name) else str(getattr(d, 'attr', d)) for d in node.decorator_list],
                "returns": ast.unparse(node.returns) if hasattr(ast, 'unparse') and node.returns else "",
            }
            # 通过 parent 判断层级（简化：通过遍历判断）
            result["functions"].append(func_info)

    return result


def build_index(root: Optional[Path] = None, force: bool = False) -> Dict:
    """构建完整源码索引。

    Args:
        root: 项目根目录，默认 PROJECT_ROOT
        force: 是否强制重建（忽略 mtime）

    Returns:
        {"files": {...}, "symbols": {...}, "stats": {...}}
    """
    root = root or PROJECT_ROOT
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # 加载已有索引
    old_index = {}
    if not force and INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                old_index = json.load(f)
        except Exception:
            pass

    old_files = old_index.get("files", {})
    files = {}
    symbols = {"classes": {}, "functions": {}, "tags": {}}

    total = 0
    updated = 0
    scanned = 0

    for filepath in root.rglob("*.py"):
        if should_skip_path(filepath):
            continue
        rel = str(filepath.relative_to(root))
        scanned += 1

        # 增量：mtime 未变则复用
        mtime = filepath.stat().st_mtime
        if not force and rel in old_files:
            old_entry = old_files[rel]
            if old_entry.get("mtime") == mtime:
                files[rel] = old_entry
                # 恢复符号索引
                for cls_name, cls_files in old_index.get("symbols", {}).get("classes", {}).items():
                    if rel in cls_files:
                        symbols["classes"].setdefault(cls_name, []).append(rel)
                for func_name, func_files in old_index.get("symbols", {}).get("functions", {}).items():
                    if rel in func_files:
                        symbols["functions"].setdefault(func_name, []).append(rel)
                continue

        # 解析文件
        info = extract_py_symbols(filepath)
        files[rel] = {
            "size": info["size"],
            "mtime": info["mtime"],
            "imports_count": len(info["imports"]),
            "classes": [c["name"] for c in info["classes"]],
            "functions": [f["name"] for f in info["functions"]],
            "comments_count": len(info["comments"]),
            "docstring": info["docstring"][:200],
        }

        # 构建符号索引
        for cls in info["classes"]:
            symbols["classes"].setdefault(cls["name"], []).append(rel)
        for func in info["functions"]:
            symbols["functions"].setdefault(func["name"], []).append(rel)
        for comment in info["comments"]:
            tag = comment["tag"]
            symbols["tags"].setdefault(tag, []).append({
                "file": rel,
                "line": comment["line"],
                "text": comment["text"],
            })

        updated += 1
        total += 1

    # 加上未变化的文件
    total = len(files)

    index = {
        "version": "1.0",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root),
        "stats": {
            "total_files": total,
            "scanned": scanned,
            "updated": updated,
            "total_classes": sum(len(v) for v in symbols["classes"].values()),
            "total_functions": sum(len(v) for v in symbols["functions"].values()),
            "total_tags": sum(len(v) for v in symbols["tags"].values()),
        },
        "files": files,
        "symbols": symbols,
    }

    # 写入索引
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    # 写入简化文件索引
    file_list = []
    for rel_path, info in sorted(files.items()):
        file_list.append({
            "path": rel_path,
            "size": info["size"],
            "classes": info["classes"],
            "functions": info["functions"],
            "docstring": info.get("docstring", ""),
        })
    with open(FILE_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(file_list, f, ensure_ascii=False, indent=2)

    return index


def query_index(name: str, kind: str = "all") -> List[Dict]:
    """查询符号定义位置。

    Args:
        name: 符号名（支持模糊匹配）
        kind: 类型过滤 (all/class/function/tag)
    """
    if not INDEX_FILE.exists():
        print("索引不存在，请先运行 build_index()")
        return []

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        index = json.load(f)

    results = []
    symbols = index.get("symbols", {})

    if kind in ("all", "class"):
        for cls_name, files in symbols.get("classes", {}).items():
            if name.lower() in cls_name.lower():
                for f in files:
                    results.append({"kind": "class", "name": cls_name, "file": f})

    if kind in ("all", "function"):
        for func_name, files in symbols.get("functions", {}).items():
            if name.lower() in func_name.lower():
                for f in files:
                    results.append({"kind": "function", "name": func_name, "file": f})

    if kind in ("all", "tag"):
        for tag, entries in symbols.get("tags", {}).items():
            if name.lower() in tag.lower():
                for entry in entries:
                    results.append({"kind": f"tag:{tag}", "name": entry["text"],
                                   "file": entry["file"], "line": entry["line"]})

    return results


# ── CLI ──
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--query":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        kind = sys.argv[3] if len(sys.argv) > 3 else "all"
        results = query_index(name, kind)
# NOTE: 2026-05-09 19:47:06, self-evolved by tea_agent --- 修复 make_index.py 嵌套 f-string 语法错误（Python 3.11 不支持）
        for r in results:
            line_info = f":{r['line']}" if 'line' in r else ''
            print(f"[{r['kind']}] {r['name']} → {r['file']}{line_info}")
    elif len(sys.argv) > 1 and sys.argv[1] == "--watch":
        print("🔍 监控模式：文件变化时自动重建索引 (Ctrl+C 停止)")
        last_mtimes = {}
        try:
            while True:
                changed = False
                for f in Path(".").rglob("*.py"):
                    if should_skip_path(f):
                        continue
                    mtime = f.stat().st_mtime
                    rel = str(f)
                    if rel in last_mtimes and last_mtimes[rel] != mtime:
                        changed = True
                        break
                    last_mtimes[rel] = mtime
                if changed:
                    print(f"\n🔄 {time.strftime('%H:%M:%S')} 重建索引...")
                    idx = build_index(force=True)
                    print(f"  ✅ {idx['stats']['total_files']} 文件, "
                          f"{idx['stats']['total_classes']} 类, "
                          f"{idx['stats']['total_functions']} 函数")
                time.sleep(3)
        except KeyboardInterrupt:
            print("\n👋 停止监控")
    else:
        idx = build_index(force="--force" in sys.argv)
        print(f"✅ 索引已生成: {INDEX_FILE}")
        print(f"   📁 {idx['stats']['total_files']} 个文件")
        print(f"   🏷️  {idx['stats']['total_classes']} 个类")
        print(f"   🔧 {idx['stats']['total_functions']} 个函数")
        print(f"   💬 {idx['stats']['total_tags']} 个注释标记")
