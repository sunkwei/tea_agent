"""
Skills .md 体系 — 兼容 anthropics/skills 格式 v2.0

支持：
  - SKILL.md 格式（YAML front matter）
  - 搜索路径：~/.tea/skills/<skill>/SKILL.md
  - 兼容：anthropics/skills 格式、自定义命令、项目级技能
Args:
    action: scan/list/load/recommend/add/delete
    query: 搜索关键词
    category: 分类筛选

v2.0 新增：
  - 多路径扫描：用户级 → 系统级 → anthropics → 项目级
  - 支持 SKILL.md 和 BRIEF.md 两种命名
  - 路径级别优先级：user > project > system
  - 同名技能去重（project 覆盖 user）
  - 缓存加速：扫描结果缓存 30 秒
  - 兼容 ~/.agents/skills/ 和 ~/.claude/skills/ 目录
"""

import contextlib
import logging
import time
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger("toolkit.skills")

# 技能配置文件命名
SKILL_CONFIG_FILE = "SKILL.md"
SKILL_ALT_FILE = "BRIEF.md"
SHORT_NAME_LIMIT = 40
DESC_LIMIT = 120

# 有效 meta 字段
SKILL_META_KEYS = {"name", "description", "tags", "category", "version", "author", "repo_reference"}

# ── 缓存 ────────────────────────────────────────────
_scan_cache: dict | None = None
_scan_cache_time: float = 0
SCAN_CACHE_TTL = 30  # 秒


def _parse_skill_md(path: str) -> dict | None:
    """解析 SKILL.md 文件，提取 YAML front matter"""
    try:
        with open(path, encoding='utf-8') as f:
            raw = f.read()
        if not raw.startswith('---'):
            return None

        # 定位 --- 结束标记
        end_idx = raw.find('\n---\n', 3)
        if end_idx == -1:
            end_idx = raw.find('\r\n---\r\n', 3)
        if end_idx == -1:
            return None

        yaml_block = raw[3:end_idx]
        meta = yaml.safe_load(yaml_block)

        if not isinstance(meta, dict):
            return None

        # 构建技能对象
        skill = {
            "name": meta.get("name", Path(path).parent.stem),
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "category": meta.get("category", "general"),
            "version": meta.get("version", "1.0.0"),
            "author": meta.get("author", ""),
            "repo_reference": meta.get("repo_reference", ""),
            "path": path,
            "content": raw[end_idx + 5:].strip(),
            "source": "file",
            "loaded_at": datetime.now().isoformat(),
        }
        return skill
    except Exception as e:
        logger.warning(f"解析 SKILL.md 失败 {path}: {e}")
        return None


def _scan_skill_dirs() -> list[dict]:
    """扫描所有技能目录 v2.0
      - ~/.tea_agent/skills/<skill>/SKILL.md   (user, 读写)
      - ~/.tea_agent/skills/<skill>/SKILL.md   (user, 不删除)
      - ~/.ads/skills/<skill>/SKILL.md          (系统级)
      - ~/.claude/skills/<skill>/SKILL.md       (anthropics/skills 兼容)
      - .agents/skills/<skill>/SKILL.md         项目级
      - .tea_agent/skills/<skill>/SKILL.md      项目级
      - .claude/skills/<skill>/SKILL.md         项目级
    支持 BRIEF.md 和 SKILL.md 两种命名
    """
    dirs = []

    # 父路径列表 v2.0 - 按优先级排列
    parent_paths = [
        (Path.home() / ".tea_agent" / "skills", "user"),
        (Path.home() / ".ads" / "skills", "system"),
        (Path.home() / ".claude" / "skills", "system"),
    ]

    # 项目级
    cwd = Path.cwd()
    for sub_dir in [".agents", ".tea_agent", ".claude"]:
        project_dir = (cwd / sub_dir / "skills")
        parent_paths.append((project_dir, "project"))

    # 扫描+去重
    seen = set()
    for base_dir, source in parent_paths:
        if not base_dir.exists():
            continue
        try:
            for skill_dir in sorted(base_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                # 同名去重
                if skill_dir.name in seen:
                    continue
                seen.add(skill_dir.name)
                # 查找 SKILL.md 或 BRIEF.md
                for fname in [SKILL_CONFIG_FILE, SKILL_ALT_FILE]:
                    skill_file = skill_dir / fname
                    if skill_file.exists():
                        dirs.append({
                            "path": str(skill_file),
                            "skill_name": skill_dir.name,
                            "source": source,
                            "config_file": fname,
                        })
                        break
        except Exception as e:
            logger.warning(f"扫描失败 {base_dir}: {e}")

    return dirs


# ── 核心 API ────────────────────────────────────────────

def _load_all_skills(force_refresh: bool = False) -> list[dict]:
    """加载所有技能"""
    global _scan_cache, _scan_cache_time
    now = time.time()
    if force_refresh:
        _scan_cache = None
    if _scan_cache and (now - _scan_cache_time) < SCAN_CACHE_TTL:
        return _scan_cache

    items = _scan_skill_dirs()
    skills = []
    for item in items:
        skill = _parse_skill_md(item["path"])
        if skill:
            skill["source"] = item["source"]
            skills.append(skill)
        else:
            # 即使没有 front matter，也作为纯文本技能加载
            try:
                with open(item["path"], encoding='utf-8') as f:
                    content = f.read().strip()
                skills.append({
                    "name": item["skill_name"],
                    "description": content[:DESC_LIMIT] if content else "",
                    "tags": [],
                    "category": "general",
                    "version": "1.0.0",
                    "author": "",
                    "repo_reference": "",
                    "path": item["path"],
                    "content": content,
                    "source": item["source"],
                    "loaded_at": datetime.now().isoformat(),
                })
            except Exception:
                pass

    _scan_cache = skills
    _scan_cache_time = now
    return skills


def _search_skills(query: str = "", skills: list[dict] | None = None,
                   category: str = "", tags: list[str] | None = None) -> list[dict]:
    """搜索技能"""
    if skills is None:
        skills = _load_all_skills()

    results = []
    q = query.lower().strip()

    for s in skills:
        # 分类过滤
        if category and s.get("category", "") != category:
            continue
        # 标签过滤 (OR)
        if tags:
            skill_tags = {t.lower() for t in s.get("tags", [])}
            if not any(t.lower() in skill_tags for t in tags):
                continue
        # 关键词搜索
        if q:
            search_target = f"{s.get('name','')} {s.get('description','')} {''.join(s.get('tags',[]))}"
            if q not in search_target.lower():
                continue
        results.append(s)

    return results


def toolkit_skills(
    action: str = "list",
    query: str = "",
    category: str = "",
    tags: list[str] | None = None,
    name: str = "",
    content: str = "",
    description: str = "",
) -> dict:
    """
    Skills .md 体系 — 兼容 anthropics/skills 格式 v2.0

    支持 SKILL.md（YAML front matter），多路径扫描，按需加载。

    Args:
        action: scan/list/load/search/recommend/add/delete
        query: 搜索关键词
        category: 分类筛选（general/code/test/doc/browser/...）
        tags: 标签筛选列表（OR 匹配）
        name: [load/add/delete] 技能名称
        content: [add] 技能 Markdown 内容
        description: [add] 技能描述

    Returns:
        技能信息或操作结果
    """
    if action == "scan":
        skills = _load_all_skills(force_refresh=True)
        return {"total": len(skills), "skills": skills}

    elif action == "list":
        skills = _load_all_skills()
        return {
            "total": len(skills),
            "skills": [
                {
                    "name": s["name"],
                    "description": s["description"][:60],
                    "category": s.get("category", "general"),
                    "tags": s.get("tags", []),
                    "source": s.get("source", ""),
                    "path": s.get("path", ""),
                }
                for s in skills
            ],
        }

    elif action == "load":
        if not name:
            return {"error": "需要 name 参数"}
        skills = _load_all_skills()
        for s in skills:
            if s["name"] == name:
                return {"skill": s}
        return {"error": f"未找到技能: {name}"}

    elif action == "search":
        skills = _load_all_skills()
        results = _search_skills(query, skills, category, tags)
        return {"total": len(results), "skills": results}

    elif action == "recommend":
        """根据当前工具上下文推荐技能"""
        skills = _load_all_skills()
        results = _search_skills(query, skills) if query else skills[:10]
        return {"total": len(results), "skills": results}

    elif action == "add":
        """添加自定义技能"""
        if not name or not content:
            return {"error": "需要 name 和 content 参数"}
        skill_dir = Path.home() / ".tea_agent" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"

        # 构建 YAML front matter
        meta = {
            "name": name,
            "description": description or f"Custom skill: {name}",
            "tags": [],
            "category": "custom",
            "version": "1.0.0",
            "author": "user",
        }
        front = "---\n" + yaml.dump(meta, allow_unicode=True, default_flow_style=False) + "---\n"

        with open(skill_file, 'w', encoding='utf-8') as f:
            f.write(front + content.strip())

        # 清除缓存
        global _scan_cache
        _scan_cache = None

        return {"success": True, "path": str(skill_file), "name": name}

    elif action == "delete":
        """删除技能"""
        if not name:
            return {"error": "需要 name 参数"}
        skill_dir = Path.home() / ".tea_agent" / "skills" / name
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            skill_file.unlink()
            # 如果目录空了就删除
            with contextlib.suppress(OSError):
                skill_dir.rmdir()
            _scan_cache = None
            return {"success": True, "name": name}
        return {"error": f"未找到技能: {name}"}

    return {"error": f"未知操作: {action}"}


# ── Meta for toolkit registration ──────────────────────

def meta_toolkit_skills() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_skills",
            "description": "Skills .md 体系 — 兼容 anthropics/skills 格式。支持 scan/list/load/search/recommend/add/delete，多路径扫描（~/.tea_agent/ ~/.claude/ ~/.agents/ 项目级），YAML front matter。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["scan", "list", "load", "search", "recommend", "add", "delete"],
                        "description": "scan/list/load/search/recommend/add/delete"
                    },
                    "query": {"type": "string", "description": "搜索关键词"},
                    "category": {"type": "string", "description": "分类筛选: general/code/test/doc/browser/..."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "标签筛选（OR 匹配）"},
                    "name": {"type": "string", "description": "技能名称"},
                    "content": {"type": "string", "description": "技能 Markdown 内容"},
                    "description": {"type": "string", "description": "技能描述"},
                },
                "required": ["action"],
            },
        },
    }
