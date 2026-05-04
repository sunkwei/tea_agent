"""
Skill 管理系统 — tea_agent 的模块化能力框架

Skill = Tool集合 + 领域Prompt + 激活规则

设计要点：
- Skill 是比 Tool 高一层的能力抽象
- 每个 Skill 包含一组相关工具 + 领域指令
- 按需激活，减少 token 消耗
- 内置 Skill 放在 tea_agent/skills/，用户自定义 Skill 放在 ~/.tea_agent/skills/

用法：
    mgr = SkillManager.get_instance()
    mgr.discover_skills()
    mgr.activate_skill("desktop_automation")
    tools = mgr.get_active_tools(all_meta_map)  # 过滤后的工具列表
    prompt = mgr.get_active_prompt()             # 注入的领域指令
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple

logger = logging.getLogger("SkillManager")

# 始终激活的核心工具（不归属于任何 Skill，永远可用）
CORE_TOOLS = {
    "toolkit_skill",  # Skill 管理工具必须始终可用
    "toolkit_save",
    "toolkit_reload", 
    "toolkit_rollback",
    "toolkit_list_versions",
}


class Skill:
    """单个 Skill 的数据结构"""

    def __init__(self, manifest: dict, source_dir: str):
        self.name: str = manifest.get("name", "")
        self.version: str = manifest.get("version", "1.0.0")
        self.description: str = manifest.get("description", "")
        self.tools: List[str] = manifest.get("tools", [])
        self.prompt_inject: str = manifest.get("prompt_inject", "")
        self.activation: str = manifest.get("activation", "auto")  # auto | manual
        self.dependencies: List[str] = manifest.get("dependencies", [])
        self.trigger_words: List[str] = manifest.get("trigger_words", [])
        self.source_dir: str = source_dir
        self.active: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tool_count": len(self.tools),
            "tools": self.tools,
            "activation": self.activation,
            "active": self.active,
            "trigger_words": self.trigger_words,
        }


class SkillManager:
    """
    Skill 管理器（单例模式）。

    职责：
    - 发现和加载 Skill
    - 激活/停用 Skill
    - 提供工具过滤（仅返回激活 Skill 包含的工具 + 核心工具）
    - 收集并返回领域 Prompt 片段
    - 基于用户输入自动激活相关 Skill
    """

    _instance: Optional["SkillManager"] = None

    @classmethod
    def get_instance(cls) -> "SkillManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """重置单例（测试用）"""
        cls._instance = None

    def __init__(self):
        if SkillManager._instance is not None:
            return  # 单例
        SkillManager._instance = self

        self.skills: Dict[str, Skill] = {}
        self._discovered = False

        # 内置 Skill 目录
        self._builtin_dir = str(Path(__file__).parent)
# NOTE: 2026-05-04 17:55:07, self-evolved by tea_agent --- skills _user_dir 从 config.paths 读取
        # 用户 Skill 目录（从 config 读取，支持多 agent 隔离）
        try:
            from tea_agent.config import get_config
            self._user_dir = get_config().paths.skills_dir_abs
        except Exception:
            self._user_dir = str(Path.home() / ".tea_agent" / "skills")

    # ─── 发现与加载 ─────────────────────────────────

    def discover_skills(self, force: bool = False) -> List[str]:
        """
        扫描内置和用户 Skill 目录，发现所有可用 Skill。

        Args:
            force: 强制重新扫描（即使已扫描过）

        Returns:
            发现的 Skill 名称列表
        """
        if self._discovered and not force:
            return list(self.skills.keys())

        self.skills.clear()

        # 1. 内置 Skill
        self._scan_directory(self._builtin_dir, source="builtin")

        # 2. 用户自定义 Skill
        if os.path.isdir(self._user_dir):
            self._scan_directory(self._user_dir, source="user")

        self._discovered = True
        logger.info(f"Skill 发现完成: {len(self.skills)} 个 — {list(self.skills.keys())}")
        return list(self.skills.keys())

    def _scan_directory(self, dirpath: str, source: str):
        """扫描目录下的所有 Skill 子目录"""
        if not os.path.isdir(dirpath):
            return

        for entry in sorted(os.listdir(dirpath)):
            full_path = os.path.join(dirpath, entry)
            if not os.path.isdir(full_path):
                continue

            init_file = os.path.join(full_path, "__init__.py")
            if not os.path.isfile(init_file):
                continue

            try:
                manifest = self._load_manifest(init_file)
                if manifest and manifest.get("name"):
                    name = manifest["name"]
                    skill = Skill(manifest, full_path)
                    # 用户 Skill 覆盖同名的内置 Skill
                    if name in self.skills and source == "user":
                        logger.info(f"用户 Skill '{name}' 覆盖内置版本")
                    self.skills[name] = skill
                    logger.debug(f"发现 Skill [{source}]: {name} ({len(skill.tools)} tools)")
            except Exception as e:
                logger.warning(f"加载 Skill 失败: {entry} — {e}")

    @staticmethod
    def _load_manifest(init_file: str) -> Optional[dict]:
        """从 __init__.py 中安全加载 SKILL_MANIFEST 字典"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("skill_manifest", init_file)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, "SKILL_MANIFEST", None)

    # ─── 激活/停用 ─────────────────────────────────

    def activate_skill(self, name: str) -> bool:
        """激活指定 Skill"""
        if name not in self.skills:
            logger.warning(f"Skill '{name}' 不存在")
            return False
        self.skills[name].active = True
        logger.info(f"Skill 已激活: {name} ({len(self.skills[name].tools)} tools)")
        return True

    def deactivate_skill(self, name: str) -> bool:
        """停用指定 Skill"""
        if name not in self.skills:
            return False
        self.skills[name].active = False
        logger.info(f"Skill 已停用: {name}")
        return True

    def toggle_skill(self, name: str) -> Optional[bool]:
        """切换 Skill 激活状态，返回新状态"""
        if name not in self.skills:
            return None
        self.skills[name].active = not self.skills[name].active
        return self.skills[name].active

    def activate_all(self):
        """激活所有 Skill"""
        for s in self.skills.values():
            s.active = True
        logger.info("所有 Skill 已激活")

    def deactivate_all(self):
        """停用所有 Skill（核心工具不受影响）"""
        for s in self.skills.values():
            s.active = False
        logger.info("所有 Skill 已停用")

    # ─── 工具过滤 ──────────────────────────────────

    def is_tool_active(self, tool_name: str) -> bool:
        """检查工具是否当前激活"""
        # 核心工具始终激活
        if tool_name in CORE_TOOLS:
            return True

        # 检查是否有激活的 Skill 包含此工具
        for skill in self.skills.values():
            if skill.active and tool_name in skill.tools:
                return True
        return False

    def get_active_tool_names(self) -> Set[str]:
        """获取当前激活的所有工具名称"""
        active = set(CORE_TOOLS)
        for skill in self.skills.values():
            if skill.active:
                active.update(skill.tools)
        return active

    def get_active_tools_meta(self, all_meta_map: Dict[str, dict]) -> List[dict]:
        """
        从所有工具的元数据中，筛选出当前激活的工具元数据。

        Args:
            all_meta_map: {tool_name: meta_dict} — 全部工具的元数据

        Returns:
            当前激活的工具元数据列表（API 格式）
        """
        active_names = self.get_active_tool_names()
        result = []
        for name in sorted(active_names):
            if name in all_meta_map:
                result.append(all_meta_map[name])
        return result

    # ─── Prompt 构建 ───────────────────────────────

    def get_active_prompt(self) -> str:
        """
        收集所有激活 Skill 的领域 prompt 片段。

        Returns:
            注入到 system prompt 的技能描述文本
        """
        fragments = []
        for skill in self.skills.values():
            if skill.active and skill.prompt_inject:
                fragments.append(f"## Skill: {skill.name}\n{skill.prompt_inject.strip()}")

        if not fragments:
            return ""

        return "\n\n".join(fragments)

    def get_skill_summary(self) -> str:
        """生成激活 Skill 的简短摘要（用于 system prompt 头部）"""
        active_skills = [s for s in self.skills.values() if s.active]
        if not active_skills:
            return ""

        lines = []
        for s in active_skills:
            tool_list = ", ".join(s.tools[:5])
            if len(s.tools) > 5:
                tool_list += f" 等{len(s.tools)}个"
            lines.append(f"  [{s.name}]: {tool_list}")

        summary = "当前激活的技能 (Skill):\n" + "\n".join(lines)
        return summary

    # ─── 自动激活 ──────────────────────────────────

    def auto_activate(self, user_input: str) -> List[str]:
        """
        基于用户输入关键词，自动激活相关 Skill。

        规则：
        - 遍历所有 Skill 的 trigger_words
        - 匹配用户输入中出现的触发词
        - 自动激活匹配的 Skill

        Args:
            user_input: 用户输入文本

        Returns:
            被自动激活的 Skill 名称列表
        """
        activated = []
        user_lower = user_input.lower()

        for skill in self.skills.values():
            if skill.activation != "auto":
                continue
            if skill.active:
                continue  # 已激活

            # 检查触发词
            for tw in skill.trigger_words:
                if tw.lower() in user_lower:
                    skill.active = True
                    activated.append(skill.name)
                    logger.info(f"自动激活 Skill '{skill.name}' (触发词: '{tw}')")
                    break

        if activated:
            logger.info(f"自动激活了 {len(activated)} 个 Skill: {activated}")
        return activated

    # ─── 查询 ─────────────────────────────────────

    def list_skills(self) -> List[dict]:
        """列出所有 Skill（含状态）"""
        return [s.to_dict() for s in self.skills.values()]

    def get_skill(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def get_active_skill_names(self) -> List[str]:
        return [s.name for s in self.skills.values() if s.active]

    def get_status(self) -> dict:
        """获取当前 Skill 系统状态"""
        total = len(self.skills)
        active = len(self.get_active_skill_names())
        return {
            "total_skills": total,
            "active_skills": active,
            "core_tools": len(CORE_TOOLS),
            "active_tools": len(self.get_active_tool_names()),
            "skills": self.list_skills(),
        }
