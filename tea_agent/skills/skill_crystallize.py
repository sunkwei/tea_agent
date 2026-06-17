"""
Skill 结晶器 — 从任务执行过程中提取可复用技能。

设计灵感:
  GenericAgent 的 Skill 树系统 — "Don't preload skills, evolve them"
  
工作流程:
  1. 任务完成 → 分析执行轨迹
  2. 提取工具组合 + 执行步骤
  3. 生成 Skill 描述 + 成功条件
  4. 保存到 Skill 库

用法:
    from tea_agent.skills.skill_crystallize import SkillCrystallizer
    
    crystallizer = SkillCrystallizer()
    skill = crystallizer.crystallize(
        task="重构 gui.py 添加类型注解",
        tools_used=["toolkit_file", "toolkit_edit", "toolkit_lsp"],
        rounds=rounds_data,  # 可选：完整的对话轮次
        success=True,
        token_cost=15000,
        time_seconds=120
    )
"""

import json
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict

import logging

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """技能定义"""
    id: str                          # 唯一标识 (基于任务+工具组合的 hash)
    name: str                        # 技能名称
    description: str                 # 技能描述
    category: str                    # 分类: code/search/browser/file/...
    tools: List[str]                 # 使用的工具列表
    steps: List[str]                 # 执行步骤
    success_conditions: List[str]    # 成功条件
    example_task: str                # 示例任务描述
    token_cost: int = 0              # 平均 token 消耗
    time_seconds: float = 0          # 平均耗时
    success_count: int = 1           # 成功次数
    fail_count: int = 0              # 失败次数
    created_at: str = ""             # 创建时间
    last_used: str = ""              # 最后使用时间
    tags: List[str] = None           # 标签
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0
    
    @property
    def confidence(self) -> float:
        """置信度 = 成功率 * 使用频率"""
        if self.success_count < 1:
            return 0.0
        # 基础置信度随成功次数增长
        base = min(1.0, 0.5 + 0.1 * (self.success_count - 1))
        return base * self.success_rate


class SkillCrystallizer:
    """技能结晶器"""
    
    # 工具到分类的映射
    TOOL_CATEGORIES = {
        "toolkit_file": "file",
        "toolkit_save_file": "file",
        "toolkit_edit": "code",
        "toolkit_diff": "code",
        "toolkit_self_evolve": "code",
        "toolkit_search": "search",
        "toolkit_lsp": "code",
        "toolkit_explr": "knowledge",
        "toolkit_exec": "system",
        "toolkit_browser_tab": "browser",
        "toolkit_screenshot": "browser",
        "toolkit_ocr": "browser",
        "toolkit_input": "browser",
        "toolkit_js_fetch": "browser",
        "toolkit_pkg": "system",
        "toolkit_build": "system",
        "toolkit_format_code": "code",
        "toolkit_run_tests": "test",
        "toolkit_memory": "memory",
        "toolkit_kb": "knowledge",
    }
    
    def __init__(self, skills_dir: Optional[str] = None):
        """
        Args:
            skills_dir: 技能存储目录，默认 ~/.tea_agent/skills/
        """
        if skills_dir is None:
            skills_dir = str(Path.home() / ".tea_agent" / "skills")
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
    
    def crystallize(
        self,
        task: str,
        tools_used: List[str],
        rounds: Optional[List[Dict]] = None,
        success: bool = True,
        token_cost: int = 0,
        time_seconds: float = 0,
        force_name: Optional[str] = None,
    ) -> Skill:
        """
        从任务执行结果中结晶出技能。
        
        Args:
            task: 任务描述
            tools_used: 使用的工具列表
            rounds: 对话轮次数据 (可选)
            success: 任务是否成功
            token_cost: token 消耗
            time_seconds: 耗时
            force_name: 强制指定技能名称 (可选)
            
        Returns:
            结晶出的 Skill 对象
        """
        # 1. 生成唯一 ID
        skill_id = self._generate_id(task, tools_used)
        
        # 2. 推断分类
        category = self._infer_category(tools_used)
        
        # 3. 提取步骤
        steps = self._extract_steps(rounds, tools_used)
        
        # 4. 生成名称和描述
        name = force_name or self._generate_name(task, category)
        description = self._generate_description(task, steps, tools_used)
        
        # 5. 生成成功条件
        success_conditions = self._extract_success_conditions(rounds, task)
        
        # 6. 提取标签
        tags = self._extract_tags(task, tools_used)
        
        skill = Skill(
            id=skill_id,
            name=name,
            description=description,
            category=category,
            tools=tools_used,
            steps=steps,
            success_conditions=success_conditions,
            example_task=task,
            token_cost=token_cost,
            time_seconds=time_seconds,
            success_count=1 if success else 0,
            fail_count=0 if success else 1,
            tags=tags,
        )
        
        logger.info(f"✨ 结晶新技能: {skill.name} (id={skill.id[:8]})")
        return skill
    
    def _generate_id(self, task: str, tools: List[str]) -> str:
        """生成基于任务+工具的唯一 ID"""
        # 对任务进行标准化处理
        normalized = re.sub(r'[^\w\s]', '', task.lower()).strip()
        normalized = re.sub(r'\s+', '_', normalized)
        
        # 组合工具名
        tools_str = '+'.join(sorted(tools))
        
        # 生成 hash
        content = f"{normalized}:{tools_str}"
        hash_val = hashlib.md5(content.encode()).hexdigest()[:12]
        
        return f"{normalized[:30]}_{hash_val}"
    
    def _infer_category(self, tools: List[str]) -> str:
        """从工具列表推断分类"""
        categories = []
        for tool in tools:
            cat = self.TOOL_CATEGORIES.get(tool, "other")
            categories.append(cat)
        
        # 返回出现最多的分类
        if not categories:
            return "general"
        
        from collections import Counter
        counter = Counter(categories)
        return counter.most_common(1)[0][0]
    
    def _extract_steps(self, rounds: Optional[List[Dict]], tools: List[str]) -> List[str]:
        """从对话轮次中提取执行步骤"""
        steps = []
        
        if rounds:
            for round_data in rounds:
                role = round_data.get("role", "")
                content = round_data.get("content", "")
                tool_calls = round_data.get("tool_calls", [])
                
                if role == "assistant" and content:
                    # 提取 AI 的意图描述
                    intent = self._extract_intent(content)
                    if intent:
                        steps.append(intent)
                
                if tool_calls:
                    for tc in tool_calls:
                        func_name = tc.get("function", {}).get("name", "")
                        if func_name:
                            steps.append(f"调用 {func_name}")
        
        if not steps:
            # 从工具列表生成基本步骤
            steps = [f"使用 {tool}" for tool in tools[:5]]
        
        return steps
    
    def _extract_intent(self, content: str) -> Optional[str]:
        """从 AI 回复中提取意图"""
        # 简单启发式：找第一行描述性内容
        lines = content.strip().split('\n')
        for line in lines:
            line = line.strip()
            # 跳过空行和纯符号行
            if not line or line.startswith('#') or line.startswith('```'):
                continue
            # 跳过太短或太长的行
            if len(line) < 5 or len(line) > 100:
                continue
            return line
        return None
    
    def _generate_name(self, task: str, category: str) -> str:
        """生成技能名称"""
        # 简单处理：取任务前 20 个字符
        name = task[:30].strip()
        # 移除特殊字符
        name = re.sub(r'[^\w\s\u4e00-\u9fff]', '', name)
        # 添加分类前缀
        prefix_map = {
            "code": "代码",
            "file": "文件",
            "search": "搜索",
            "browser": "浏览器",
            "system": "系统",
            "test": "测试",
            "memory": "记忆",
            "knowledge": "知识",
            "general": "通用",
        }
        prefix = prefix_map.get(category, "")
        if prefix and not name.startswith(prefix):
            name = f"{prefix} {name}"
        return name
    
    def _generate_description(self, task: str, steps: List[str], tools: List[str]) -> str:
        """生成技能描述"""
        desc_parts = [task]
        
        if steps:
            desc_parts.append(f"步骤: {len(steps)} 步")
        
        if tools:
            tool_names = [t.replace('toolkit_', '') for t in tools[:3]]
            desc_parts.append(f"工具: {', '.join(tool_names)}")
        
        return ' | '.join(desc_parts)
    
    def _extract_success_conditions(self, rounds: Optional[List[Dict]], task: str) -> List[str]:
        """提取成功条件"""
        conditions = []
        
        # 从任务描述推断
        if "重构" in task or "refactor" in task.lower():
            conditions.append("代码重构后测试通过")
        if "修复" in task or "fix" in task.lower():
            conditions.append("问题已修复")
        if "测试" in task or "test" in task.lower():
            conditions.append("测试用例通过")
        if "文档" in task or "doc" in task.lower():
            conditions.append("文档已生成")
        
        # 从轮次中提取成功信号
        if rounds:
            last_round = rounds[-1] if rounds else {}
            content = last_round.get("content", "")
            if "成功" in content or "完成" in content or "success" in content.lower():
                conditions.append("任务执行完成")
        
        # 默认条件
        if not conditions:
            conditions = ["任务执行完成", "无错误产生"]
        
        return conditions
    
    def _extract_tags(self, task: str, tools: List[str]) -> List[str]:
        """提取标签"""
        tags = []
        
        # 从任务提取关键词
        task_lower = task.lower()
        tag_keywords = {
            "python": ["python", ".py"],
            "重构": ["重构", "refactor", "重写"],
            "测试": ["test", "测试", "验证"],
            "文档": ["doc", "文档", "readme"],
            "类型": ["type", "类型", "类型注解"],
            "修复": ["fix", "修复", "bug", "问题"],
            "优化": ["optimize", "优化", "性能"],
            "新增": ["add", "新增", "添加", "创建"],
            "删除": ["delete", "删除", "移除"],
            "浏览器": ["browser", "浏览器", "web"],
        }
        
        for tag, keywords in tag_keywords.items():
            if any(kw in task_lower for kw in keywords):
                tags.append(tag)
        
        # 从工具提取标签
        for tool in tools:
            if "browser" in tool or "screenshot" in tool:
                if "浏览器" not in tags:
                    tags.append("浏览器")
            if "test" in tool:
                if "测试" not in tags:
                    tags.append("测试")
        
        return tags[:5]  # 最多 5 个标签
    
    def save_skill(self, skill: Skill) -> str:
        """保存技能到文件"""
        skill_path = self.skills_dir / f"{skill.id}.json"
        with open(skill_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(skill), f, ensure_ascii=False, indent=2)
        
        logger.debug(f"💾 保存技能: {skill_path}")
        return str(skill_path)
    
    def load_skill(self, skill_id: str) -> Optional[Skill]:
        """加载技能"""
        skill_path = self.skills_dir / f"{skill_id}.json"
        if not skill_path.exists():
            return None
        
        with open(skill_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return Skill(**data)
    
    def list_skills(self) -> List[Skill]:
        """列出所有技能"""
        skills = []
        for path in self.skills_dir.glob("*.json"):
            try:
                skill = self.load_skill(path.stem)
                if skill:
                    skills.append(skill)
            except Exception as e:
                logger.warning(f"加载技能失败: {path}, {e}")
        return skills
