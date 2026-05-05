## llm generated tool func, created Fri May  1 07:47:45 2026
# version: 1.0.4

#!/usr/bin/env python3
"""toolkit_kb -- Markdown 知识库管理工具。"""


def toolkit_kb(action, title="", content="", tags="", category="", query="", brief="", sort="time"):
    import os, re, subprocess
    from pathlib import Path
    from datetime import datetime

# NOTE: 2026-05-04 17:54:53, self-evolved by tea_agent --- toolkit_kb KB_DIR 从 config.paths 读取
    try:
        from tea_agent.config import get_config
        KB_DIR = Path(get_config().paths.kb_dir_abs)
    except Exception:
        KB_DIR = Path(os.environ.get("HOME", "/tmp")) / ".tea_agent" / "kb"
    INDEX_FILE = KB_DIR / "INDEX.md"
    KB_DIR.mkdir(parents=True, exist_ok=True)

    def sanitize(name):
        name = re.sub(r"[/\\:*?\"<>|]", "_", name)
        name = re.sub(r"\s+", "_", name)
        return name[:120]

    def _meta(text, key):
        m = re.search(rf"<!--.*?\b{key}:(\S+).*?-->", text)
        return m.group(1) if m else ""

    def rebuild_index():
        md_files = sorted(KB_DIR.glob("*.md"))
        lines = [
            "# 📚 Knowledge Base Index",
            f"*自动生成，共 {len(md_files)} 篇 — {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n",
        ]
        for f in md_files:
            stat = f.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            size = stat.st_size
            try:
                text = f.read_text(encoding="utf-8")
                first_line = text.split("\n")[0].lstrip("# ").strip() if text else f.stem
                ct = _meta(text, "category")
                tg = _meta(text, "tags")
                bf = _meta(text, "brief")
            except Exception:
                first_line = f.stem; ct = ""; tg = ""; bf = ""
            entry = f"- **[{first_line}]({f.name})** | `{ct}` | {mtime} | {size}B"
            if tg:
                entry += f" | 🏷️ {tg}"
            if bf:
                entry += f" | {bf}"
            lines.append(entry)
        lines.append(f"\n---\n*共 {len(md_files)} 篇*\n")
        INDEX_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if action == "add":
        filename = sanitize(title) + ".md"
        filepath = KB_DIR / filename
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"# {title}\n<!-- created:{now} category:{category} tags:{tags} brief:{brief} -->\n\n"
        filepath.write_text(header + content, encoding="utf-8")
        rebuild_index()
        return f"✅ 已保存: {filepath} ({len(content)} chars)"

    elif action == "update":
        filename = sanitize(title) + ".md"
        filepath = KB_DIR / filename
        if filepath.exists():
            with filepath.open("a", encoding="utf-8") as f:
                f.write("\n" + content)
            rebuild_index()
            return f"✅ 已追加: {filepath} (+{len(content)} chars)"
        else:
            return toolkit_kb("add", title=title, content=content, tags=tags, category=category, brief=brief)

    elif action == "read":
        filename = sanitize(title) + ".md"
        filepath = KB_DIR / filename
        if filepath.exists():
            text = filepath.read_text(encoding="utf-8")
            clean = re.sub(r"<!--.*?-->\n?", "", text)
            return clean
        return f"❌ 未找到: {filename}"

    elif action == "list":
        md_files = list(KB_DIR.glob("*.md"))
        if category:
            filtered = []
            for f in md_files:
                try:
                    text = f.read_text(encoding="utf-8")
                    if f"category:{category}" in text:
                        filtered.append(f)
                except Exception:
                    pass
            md_files = filtered
        if sort == "time":
            md_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        elif sort == "title":
            md_files.sort(key=lambda f: f.stem)
        elif sort == "size":
            md_files.sort(key=lambda f: f.stat().st_size, reverse=True)
        if not md_files:
            return "(空)"
        lines = []
        for f in md_files:
            stat = f.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M")
            size = stat.st_size
            lines.append(f"  {f.stem:<40} {mtime}  {size:>6}B  {f.name}")
        return "\n".join(lines)

    elif action == "search":
        results = []
        try:
            cmd = ["grep", "-r", "-n", "-i", "--include=*.md", query, str(KB_DIR)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.stdout:
                for line in r.stdout.strip().split("\n"):
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        path_part, lineno, content = parts
                        fname = Path(path_part).name
                        results.append((fname, lineno, content.strip()[:120]))
            if tags:
                filtered = []
                tl = [t.strip() for t in tags.split(",")]
                for fname, lineno, content in results:
                    fp = KB_DIR / fname
                    if fp.exists():
                        text = fp.read_text(encoding="utf-8")
                        if any(f"tags:{t}" in text for t in tl):
                            filtered.append((fname, lineno, content))
                results = filtered
        except FileNotFoundError:
            return "❌ grep 不可用"
        if not results:
            return f"🔍 未找到匹配 '{query}' 的文档"
        return f"🔍 '{query}' 匹配 {len(results)} 处:\n" + "\n".join(
            f"  {f}:{l}: {c}" for f, l, c in results[:30]
        )

    elif action == "index":
        rebuild_index()
        return f"✅ 索引已重建: {INDEX_FILE}"

    elif action == "delete":
        filename = sanitize(title) + ".md"
        filepath = KB_DIR / filename
        if filepath.exists():
            filepath.unlink()
            rebuild_index()
            return f"🗑️ 已删除: {filename}"
        return f"❌ 未找到: {filename}"

    elif action == "status":
        md_files = list(KB_DIR.glob("*.md"))
        total_size = sum(f.stat().st_size for f in md_files)
        return f"📚 KB: {len(md_files)} 篇文档, 共 {total_size}B | 路径: {KB_DIR}"

    return f"❌ 未知操作: {action}"


def meta_toolkit_kb() -> dict:
    return {"type": "function", "function": {"name": "toolkit_kb", "description": "Markdown 知识库管理。文档存储在 $HOME/.tea_agent/kb/，所有主题共享。支持 add/update/read/list/search/index/delete/status 操作。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["add", "update", "read", "list", "search", "index", "delete", "status"], "description": "操作类型"}, "title": {"type": "string", "description": "文档标题（用作文件名，add/update/read/delete 时使用）"}, "content": {"type": "string", "description": "[add/update] Markdown 内容，add 时覆盖写入，update 时追加"}, "tags": {"type": "string", "description": "[add/search] 逗号分隔标签。search 时多标签 OR 匹配"}, "category": {"type": "string", "description": "[add/list] 分类，如 memory/reflection/analysis/temp"}, "query": {"type": "string", "description": "[search] grep 搜索关键词"}, "brief": {"type": "string", "description": "[add] 简短摘要，用于索引显示"}, "sort": {"type": "string", "enum": ["time", "title", "size"], "description": "[list] 排序方式，默认 time"}}, "required": ["action"]}}}
