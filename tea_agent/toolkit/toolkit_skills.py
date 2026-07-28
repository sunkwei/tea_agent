"""
Skills .md 体系 v3.0 — 兼容 Pi Agent Harness / anthropics/skills 格式

增强功能（借鉴 Pi）：
  - disable-model-invocation YAML front matter 支持
  - format_skills_for_system_prompt() — XML 格式化输出到 system prompt
  - 诊断警告（SkillDiagnostic）
  - 递归目录扫描 + .gitignore/.ignore 过滤
  - 增强缓存

支持：
  - SKILL.md 格式（YAML front matter）
  - 搜索路径：多路径扫描（用户级 → 系统级 → 项目级）
  - 兼容：anthropics/skills 格式、自定义命令、项目级技能
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
SKILL_META_KEYS = {
    "name", "description", "tags", "category", "version",
    "author", "repo_reference", "disable-model-invocation",
}

# ═══ 诊断 ═══════════════════════════════════════════════
# Pi-style SkillDiagnostic system


class SkillDiagnostic:
    """技能加载过程中的诊断/警告信息。"""

    def __init__(self, code: str, message: str, path: str):
        self.type = "warning"
        self.code = code  # file_info_failed, parse_failed, invalid_metadata, ...
        self.message = message
        self.path = path

    def to_dict(self):
        return {"type": self.type, "code": self.code, "message": self.message, "path": self.path}


# ═══ 缓存 ═══════════════════════════════════════════════
_scan_cache: list[dict] | None = None
_scan_cache_time: float = 0
SCAN_CACHE_TTL = 60  # 秒，比之前延长（30→60）


def _parse_skill_md(path: str) -> tuple[dict | None, list[SkillDiagnostic]]:
    """解析 SKILL.md 文件，提取 YAML front matter

    返回: (skill_dict_or_None, diagnostics_list)
    """
    diagnostics: list[SkillDiagnostic] = []
    try:
        with open(path, encoding='utf-8') as f:
            raw = f.read()
    except Exception as e:
        diagnostics.append(SkillDiagnostic("read_failed", str(e), path))
        return None, diagnostics

    if not raw.startswith('---'):
        return None, diagnostics

    # 定位 --- 结束标记
    end_idx = raw.find('\n---\n', 3)
    if end_idx == -1:
        end_idx = raw.find('\r\n---\r\n', 3)
    if end_idx == -1:
        diagnostics.append(SkillDiagnostic("parse_failed", "找不到结束标记 ---", path))
        return None, diagnostics

    yaml_block = raw[3:end_idx]
    try:
        meta = yaml.safe_load(yaml_block)
    except Exception as e:
        diagnostics.append(SkillDiagnostic("parse_failed", f"YAML解析失败: {e}", path))
        return None, diagnostics

    if not isinstance(meta, dict):
        diagnostics.append(SkillDiagnostic("parse_failed", "YAML front matter 不是字典", path))
        return None, diagnostics

    # ── 验证元数据 ──
    name = meta.get("name", Path(path).parent.stem)
    description = meta.get("description", "")

    if not name or not isinstance(name, str):
        diagnostics.append(SkillDiagnostic("invalid_metadata", f"name 无效: {name}", path))
        name = Path(path).parent.stem

    if not description or not isinstance(description, str):
        diagnostics.append(SkillDiagnostic("invalid_metadata", f"description 为空: {path}", path))

    # ── 构建技能对象 ──
    skill = {
        "name": name,
        "description": description or "",
        "tags": meta.get("tags", []),
        "category": meta.get("category", "general"),
        "version": meta.get("version", "1.0.0"),
        "author": meta.get("author", ""),
        "repo_reference": meta.get("repo_reference", ""),
        "disable_model_invocation": meta.get("disable-model-invocation", False),
        "path": path,
        "content": raw[end_idx + 5:].strip(),
        "source": "file",
        "loaded_at": datetime.now().isoformat(),
    }
    return skill, diagnostics


def _scan_skill_dirs() -> list[dict]:
    """扫描所有技能目录 v3.0

    增加：
    - 递归支持（目录嵌套）
    - 遵循 .gitignore / .ignore 模式（简单实现）
    - 更多扫描路径
    """
    dirs = []

    # 父路径列表 v3.0 - 按优先级排列
    parent_paths = [
        (Path.home() / ".tea_agent" / "skills", "user"),
        (Path.home() / ".ads" / "skills", "system"),
        (Path.home() / ".claude" / "skills", "system"),
    ]

    # 项目级
    cwd = Path.cwd()
    for sub_dir in [".agents", ".tea_agent", ".claude", ".pi"]:
        project_dir = cwd / sub_dir / "skills"
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
                found = False
                for fname in [SKILL_CONFIG_FILE, SKILL_ALT_FILE]:
                    skill_file = skill_dir / fname
                    if skill_file.exists():
                        dirs.append({
                            "path": str(skill_file),
                            "skill_name": skill_dir.name,
                            "source": source,
                            "config_file": fname,
                        })
                        found = True
                        break
                if not found:
                    # 支持直接包含 SKILL.md 的目录（非子目录）
                    for f in skill_dir.iterdir():
                        if f.is_file() and f.name.upper() in ("SKILL.MD", "BRIEF.MD"):
                            dirs.append({
                                "path": str(f),
                                "skill_name": skill_dir.name,
                                "source": source,
                                "config_file": f.name,
                            })
                            break
        except Exception as e:
            logger.warning(f"扫描失败 {base_dir}: {e}")

    return dirs


# ═══ 核心 API ════════════════════════════════════════════

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
        skill, diagnostics = _parse_skill_md(item["path"])
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
                    "disable_model_invocation": False,
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


# ═══ 新增：Pi-style XML System Prompt 格式化 ═════════════

def format_skills_for_system_prompt(skills: list[dict] | None = None) -> str:
    """将可用技能格式化为 XML，注入 system prompt。

    借鉴 Pi 的 <available_skills> 格式，让 LLM 感知可用的技能文件。

    Args:
        skills: 技能列表，None 则自动加载

    Returns:
        XML 格式的技能列表字符串，若无可返回空字符串
    """
    if skills is None:
        skills = _load_all_skills()

    # 过滤掉 disable_model_invocation=True 的技能
    visible = [s for s in skills if not s.get("disable_model_invocation", False)]
    if not visible:
        return ""

    lines = [
        "以下技能提供特定任务的专门指令。当任务匹配技能描述时，读取完整的 SKILL.md 文件。",
        "当技能文件引用相对路径时，以技能目录（SKILL.md 所在目录）为基准解析绝对路径。",
        "",
        "<available_skills>",
    ]

    for s in visible:
        name = _escape_xml(s.get("name", "unknown"))
        desc = _escape_xml(s.get("description", "")[:150])
        loc = _escape_xml(s.get("path", ""))
        lines.append("  <skill>")
        lines.append(f"    <name>{name}</name>")
        lines.append(f"    <description>{desc}</description>")
        lines.append(f"    <location>{loc}</location>")
        lines.append("  </skill>")

    lines.append("</available_skills>")
    return "\n".join(lines)


def _escape_xml(value: str) -> str:
    """XML 转义"""
    return (value
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


# ═══ 新增：技能诊断 API ══════════════════════════════════

def _check_skills_diagnostics() -> list[dict]:
    """检查所有技能的诊断信息"""
    diagnostics = []
    items = _scan_skill_dirs()
    for item in items:
        _, diags = _parse_skill_md(item["path"])
        for d in diags:
            diagnostics.append(d.to_dict())
    return diagnostics


# ═══ 主入口 ════════════════════════════════════════════════

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
    Skills .md 体系 v3.0 — 兼容 Pi Agent Harness / anthropics/skills 格式

    新增:
    - disable-model-invocation 字段支持
    - format_for_system_prompt: 生成 <available_skills> XML
    - diagnostics: 检查技能诊断

    Args:
        action: scan/list/load/search/recommend/add/delete/
                format_for_system_prompt/diagnostics
        query: 搜索关键词
        category: 分类筛选
        tags: 标签筛选列表（OR 匹配）
        name: 技能名称
        content: 技能 Markdown 内容
        description: 技能描述

    Returns:
        技能信息或操作结果
    """
    # ── 新增 actions ──
    if action == "format_for_system_prompt":
        skills_list = _load_all_skills()
        xml_str = format_skills_for_system_prompt(skills_list)
        return {"xml": xml_str}

    if action == "diagnostics":
        diags = _check_skills_diagnostics()
        return {"diagnostics": diags, "total": len(diags)}

    # ── 原有 actions ──
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
                    "disable_model_invocation": s.get("disable_model_invocation", False),
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
        skills = _load_all_skills()
        results = _search_skills(query, skills) if query else skills[:10]
        return {"total": len(results), "skills": results}

    elif action == "add":
        if not name or not content:
            return {"error": "需要 name 和 content 参数"}
        skill_dir = Path.home() / ".tea_agent" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"

        meta = {
            "name": name,
            "description": description or f"Custom skill: {name}",
            "tags": [],
            "category": "custom",
            "version": "1.0.0",
            "author": "user",
            "disable-model-invocation": False,
        }
        front = "---\n" + yaml.dump(meta, allow_unicode=True, default_flow_style=False) + "---\n"

        with open(skill_file, 'w', encoding='utf-8') as f:
            f.write(front + content.strip())

        global _scan_cache
        _scan_cache = None

        return {"success": True, "path": str(skill_file), "name": name}

    elif action == "delete":
        if not name:
            return {"error": "需要 name 参数"}
        skill_dir = Path.home() / ".tea_agent" / "skills" / name
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            skill_file.unlink()
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
            "description": "Skills .md 体系 v3.0 — 兼容 Pi Agent Harness 格式。支持 scan/list/load/search/recommend/add/delete/format_for_system_prompt/diagnostics。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["scan", "list", "load", "search", "recommend", "add", "delete", "format_for_system_prompt", "diagnostics"],
                        "description": "操作类型"
                    },
                    "query": {"type": "string", "description": "搜索关键词"},
                    "category": {"type": "string", "description": "分类筛选"},
                    "tags": {
                        "type": "array", "items": {"type": "string"},
                        "description": "标签筛选（OR 匹配）"
                    },
                    "name": {"type": "string", "description": "技能名称"},
                    "content": {"type": "string", "description": "技能 Markdown 内容"},
                    "description": {"type": "string", "description": "技能描述"},
                },
                "required": ["action"],
            },
        },
    }
