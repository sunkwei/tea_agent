"""
Skill 树系统 — 自动结晶任务经验为可复用技能。

核心理念:
  每次成功完成任务 → 自动提取 Skill → 形成个人技能树
  下次遇到类似任务 → 自动推荐 → 降低 token 消耗

用法:
    from tea_agent.skills import SkillRegistry, SkillCrystallizer
    
    # 结晶新技能
    crystallizer = SkillCrystallizer()
    skill = crystallizer.crystallize(task="重构 gui.py 添加类型注解", 
                                     tools_used=["toolkit_file", "toolkit_edit", "toolkit_lsp"],
                                     result="成功添加了 45 个函数的类型注解")
    
    # 注册到技能库
    registry = SkillRegistry()
    registry.register(skill)
    
    # 推荐相关技能
    skills = registry.recommend("帮我给 cli.py 添加类型提示")
"""

from .skill_registry import SkillRegistry
from .skill_crystallize import SkillCrystallizer

__all__ = ["SkillRegistry", "SkillCrystallizer"]
