"""
Skill 注册中心 — 管理、索引、推荐技能。

功能:
  - 注册/更新/删除技能
  - 按关键词/分类/标签搜索
  - 推荐相关技能 (基于任务描述)
  - 维护全局索引

用法:
    from tea_agent.skills import SkillRegistry
    
    registry = SkillRegistry()
    
    # 推荐技能
    skills = registry.recommend("帮我给 cli.py 添加类型注解")
    # 返回: [Skill(name="代码 类型注解 cli.py", confidence=0.85), ...]
    
    # 搜索技能
    skills = registry.search("浏览器 自动化")
    
    # 获取所有技能
    all_skills = registry.list_all()
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

import logging

logger = logging.getLogger(__name__)


class SkillRegistry:
    """技能注册中心"""
    
    def __init__(self, skills_dir: Optional[str] = None):
        """
        Args:
            skills_dir: 技能存储目录，默认 ~/.tea_agent/skills/
        """
        if skills_dir is None:
            skills_dir = str(Path.home() / ".tea_agent" / "skills")
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        
        # 索引文件
        self.index_path = self.skills_dir / "skill_index.json"
        self.index = self._load_index()
    
    def _load_index(self) -> Dict:
        """加载索引"""
        if self.index_path.exists():
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载索引失败: {e}")
        
        return {
            "version": 1,
            "updated_at": "",
            "skills": {},  # skill_id -> metadata
            "by_category": {},  # category -> [skill_ids]
            "by_tag": {},  # tag -> [skill_ids]
            "by_tool": {},  # tool -> [skill_ids]
        }
    
    def _save_index(self):
        """保存索引"""
        self.index["updated_at"] = datetime.now().isoformat()
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)
        logger.debug("💾 索引已保存")
    
    def register(self, skill) -> bool:
        """
        注册技能。
        
        Args:
            skill: Skill 对象或字典
            
        Returns:
            是否成功注册
        """
        from .skill_crystallize import Skill
        
        # 如果是字典，转换为 Skill 对象
        if isinstance(skill, dict):
            skill = Skill(**skill)
        
        # 检查是否已存在（更新成功次数）
        existing = self.get_skill(skill.id)
        if existing:
            if skill.success_count > 0:
                existing.success_count += skill.success_count
            if skill.fail_count > 0:
                existing.fail_count += skill.fail_count
            existing.last_used = datetime.now().isoformat()
            skill = existing
            logger.info(f"🔄 更新技能: {skill.name} (成功次数: {existing.success_count})")
        else:
            logger.info(f"✨ 注册新技能: {skill.name}")
        
        # 保存技能文件
        from .skill_crystallize import SkillCrystallizer
        crystallizer = SkillCrystallizer(skills_dir=str(self.skills_dir))
        crystallizer.save_skill(skill)
        
        # 更新索引
        self.index["skills"][skill.id] = {
            "name": skill.name,
            "category": skill.category,
            "tags": skill.tags,
            "tools": skill.tools,
            "confidence": skill.confidence,
            "success_count": skill.success_count,
            "created_at": skill.created_at,
        }
        
        # 更新分类索引
        if skill.category not in self.index["by_category"]:
            self.index["by_category"][skill.category] = []
        if skill.id not in self.index["by_category"][skill.category]:
            self.index["by_category"][skill.category].append(skill.id)
        
        # 更新标签索引
        for tag in skill.tags:
            if tag not in self.index["by_tag"]:
                self.index["by_tag"][tag] = []
            if skill.id not in self.index["by_tag"][tag]:
                self.index["by_tag"][tag].append(skill.id)
        
        # 更新工具索引
        for tool in skill.tools:
            if tool not in self.index["by_tool"]:
                self.index["by_tool"][tool] = []
            if skill.id not in self.index["by_tool"][tool]:
                self.index["by_tool"][tool].append(skill.id)
        
        self._save_index()
        return True
    
    def get_skill(self, skill_id: str):
        """获取单个技能"""
        from .skill_crystallize import SkillCrystallizer
        
        # 从索引检查
        if skill_id not in self.index["skills"]:
            return None
        
        # 加载完整技能
        crystallizer = SkillCrystallizer(skills_dir=str(self.skills_dir))
        return crystallizer.load_skill(skill_id)
    
    def list_all(self):
        """列出所有技能"""
        from .skill_crystallize import SkillCrystallizer
        
        crystallizer = SkillCrystallizer(skills_dir=str(self.skills_dir))
        return crystallizer.list_skills()
    
    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        tools: Optional[List[str]] = None,
        min_confidence: float = 0.0,
    ):
        """
        搜索技能。
        
        Args:
            query: 搜索关键词
            category: 分类过滤
            tags: 标签过滤 (OR 匹配)
            tools: 工具过滤 (AND 匹配)
            min_confidence: 最低置信度
            
        Returns:
            匹配的技能列表
        """
        from .skill_crystallize import SkillCrystallizer
        
        # 获取候选 ID
        candidate_ids = set(self.index["skills"].keys())
        
        # 分类过滤
        if category and category in self.index["by_category"]:
            candidate_ids &= set(self.index["by_category"][category])
        elif category:
            candidate_ids = set()
        
        # 标签过滤 (OR)
        if tags:
            tag_ids = set()
            for tag in tags:
                if tag in self.index["by_tag"]:
                    tag_ids |= set(self.index["by_tag"][tag])
            candidate_ids &= tag_ids
        
        # 工具过滤 (AND)
        if tools:
            tool_ids = set(self.index["by_tool"].get(tools[0], []))
            for tool in tools[1:]:
                tool_ids &= set(self.index["by_tool"].get(tool, []))
            candidate_ids &= tool_ids
        
        # 加载并过滤
        crystallizer = SkillCrystallizer(skills_dir=str(self.skills_dir))
        results = []
        
        for skill_id in candidate_ids:
            skill = crystallizer.load_skill(skill_id)
            if not skill:
                continue
            
            # 置信度过滤
            if skill.confidence < min_confidence:
                continue
            
            # 关键词过滤
            if query:
                if not self._match_query(skill, query):
                    continue
            
            results.append(skill)
        
        # 按置信度排序
        results.sort(key=lambda s: s.confidence, reverse=True)
        return results
    
    def recommend(self, task: str, top_k: int = 3):
        """
        根据任务描述推荐相关技能。
        
        Args:
            task: 任务描述
            top_k: 返回数量
            
        Returns:
            推荐的技能列表，按相关性排序
        """
        # 提取任务特征
        task_features = self._extract_task_features(task)
        
        # 搜索候选技能
        candidates = self.search(
            query=task,
            tags=task_features.get("tags", []),
            tools=task_features.get("tools", []),
        )
        
        # 如果候选不足，放宽搜索
        if len(candidates) < top_k:
            more = self.search(query=task)
            for s in more:
                if s.id not in [c.id for c in candidates]:
                    candidates.append(s)
        
        # 按相关性评分排序
        scored = []
        for skill in candidates:
            score = self._score_relevance(skill, task, task_features)
            scored.append((skill, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return [skill for skill, _ in scored[:top_k]]
    
    def _extract_task_features(self, task: str) -> Dict:
        """提取任务特征"""
        features = {
            "tags": [],
            "tools": [],
            "keywords": [],
        }
        
        task_lower = task.lower()
        
        # 提取可能的工具
        tool_keywords = {
            "toolkit_file": ["文件", "file", "read", "write", "读", "写"],
            "toolkit_edit": ["编辑", "edit", "修改", "replace", "替换"],
            "toolkit_search": ["搜索", "search", "查找", "find"],
            "toolkit_lsp": ["lsp", "类型", "type", "定义", "definition"],
            "toolkit_browser_tab": ["浏览器", "browser", "web", "网页"],
            "toolkit_screenshot": ["截图", "screenshot", "屏幕"],
            "toolkit_exec": ["执行", "exec", "命令", "command", "运行"],
            "toolkit_run_tests": ["测试", "test", "pytest"],
        }
        
        for tool, keywords in tool_keywords.items():
            if any(kw in task_lower for kw in keywords):
                features["tools"].append(tool)
        
        # 提取标签
        tag_keywords = {
            "python": ["python", ".py"],
            "重构": ["重构", "refactor"],
            "测试": ["test", "测试"],
            "文档": ["doc", "文档"],
            "类型": ["type", "类型"],
            "修复": ["fix", "修复", "bug"],
            "优化": ["optimize", "优化"],
            "新增": ["add", "新增", "创建"],
        }
        
        for tag, keywords in tag_keywords.items():
            if any(kw in task_lower for kw in keywords):
                features["tags"].append(tag)
        
        # 提取关键词
        words = re.findall(r'\w+', task_lower)
        features["keywords"] = words[:10]
        
        return features
    
    def _match_query(self, skill, query: str) -> bool:
        """检查技能是否匹配查询"""
        query_lower = query.lower()
        
        # 检查名称
        if query_lower in skill.name.lower():
            return True
        
        # 检查描述
        if query_lower in skill.description.lower():
            return True
        
        # 检查示例任务
        if query_lower in skill.example_task.lower():
            return True
        
        # 检查标签
        for tag in skill.tags:
            if query_lower in tag.lower():
                return True
        
        return False
    
    def _score_relevance(self, skill, task: str, features: Dict) -> float:
        """计算技能与任务的相关性评分"""
        score = 0.0
        
        # 基础分：置信度
        score += skill.confidence * 50
        
        # 标签匹配
        for tag in skill.tags:
            if tag in features.get("tags", []):
                score += 20
        
        # 工具匹配
        for tool in skill.tools:
            if tool in features.get("tools", []):
                score += 15
        
        # 关键词匹配
        task_words = set(features.get("keywords", []))
        skill_words = set(skill.name.lower().split())
        overlap = task_words & skill_words
        score += len(overlap) * 5
        
        return score
    
    def remove_skill(self, skill_id: str) -> bool:
        """删除技能"""
        if skill_id not in self.index["skills"]:
            return False
        
        # 删除文件
        skill_path = self.skills_dir / f"{skill_id}.json"
        if skill_path.exists():
            skill_path.unlink()
        
        # 从索引删除
        skill_meta = self.index["skills"].pop(skill_id)
        
        # 从分类索引删除
        cat = skill_meta.get("category", "")
        if cat in self.index["by_category"]:
            self.index["by_category"][cat] = [
                sid for sid in self.index["by_category"][cat] if sid != skill_id
            ]
        
        # 从标签索引删除
        for tag in skill_meta.get("tags", []):
            if tag in self.index["by_tag"]:
                self.index["by_tag"][tag] = [
                    sid for sid in self.index["by_tag"][tag] if sid != skill_id
                ]
        
        # 从工具索引删除
        for tool in skill_meta.get("tools", []):
            if tool in self.index["by_tool"]:
                self.index["by_tool"][tool] = [
                    sid for sid in self.index["by_tool"][tool] if sid != skill_id
                ]
        
        self._save_index()
        logger.info(f"🗑️ 删除技能: {skill_id}")
        return True
    
    def stats(self) -> Dict:
        """获取统计信息"""
        return {
            "total_skills": len(self.index["skills"]),
            "categories": list(self.index["by_category"].keys()),
            "tags": list(self.index["by_tag"].keys()),
            "tools": list(self.index["by_tool"].keys()),
            "updated_at": self.index.get("updated_at", ""),
        }
