# @2026-04-30 gen by deepseek-v4-pro, SystemPromptManager: 多版本系统提示词管理—基于反思/记忆自动进化，每次使用最新版本
"""
系统提示词管理器 (SystemPromptManager)

管理多版本系统提示词：
- 从数据库加载最新活跃版本
- 基于反思建议 + 长期记忆自动生成新版本
- 每次对话使用最新版本
- 支持版本回滚
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("SystemPromptManager")

# 默认系统提示词模板（当数据库无记录时使用）
DEFAULT_SYSTEM_PROMPT = (
    "你是可自我扩展的智能Agent。"
    "拥有工具库toolkit，可通过toolkit_save(name,meta,pycode)保存新工具、"
    "toolkit_reload()重载获得新能力。"
    "内置工具：toolkit_exec(执行命令)、toolkit_load_file(读文件)、toolkit_save_file(写文件)。\n\n"
    "核心行为：主动分析任务需求，自主创建/优化/组合工具。"
    "工具须为纯Python、可执行、有明确输入输出、通用可复用。"
    "可自由设计单函数/多函数/工具套件等结构。\n\n"
    "你不断进化，能力无上限。以最有效优雅的方式完成任务并持续增强自身。"
)


class SystemPromptManager:
    """系统提示词版本管理器"""

    EVOLVE_SYSTEM_PROMPT = """你是系统提示词优化器。基于以下信息，优化 Agent 的系统提示词：

优化原则：
1. 保留原有核心能力定义（工具创建、自进化等）
2. 根据反思建议补充缺失的指引
3. 根据长期记忆中的教训增加约束或技巧
4. 保持精简，不超过 500 字
5. 用中文

输入信息：
- 当前提示词
- 最近的反思建议
- 相关的长期记忆

输出：优化后的完整系统提示词。直接输出提示词文本，不要加引号或其他装饰。"""

    def __init__(self, storage, cheap_client=None, cheap_model: str = ""):
        """
        Args:
            storage: Storage 实例
            cheap_client: 便宜模型客户端（用于生成新提示词）
            cheap_model: 便宜模型名称
        """
        self.storage = storage
        self._cheap_client = cheap_client
        self._cheap_model = cheap_model
        self._current_prompt: str = ""
        self._current_version: str = "0"
        self._current_prompt_id: int = 0
        self._initialized = False

    def initialize(self) -> str:
        """
        初始化：从数据库加载最新活跃提示词。
        如果数据库为空，自动插入默认版本 v1。

        Returns:
            当前生效的系统提示词
        """
        latest = self.storage.get_latest_system_prompt()
        if latest:
            self._current_prompt = latest["content"]
            self._current_version = latest["version"]
            self._current_prompt_id = latest["id"]
            logger.info(f"加载系统提示词 v{self._current_version} (id={self._current_prompt_id})")
        else:
            # 首次运行，插入默认版本
            self._current_prompt = DEFAULT_SYSTEM_PROMPT
            self._current_version = "1"
            self._current_prompt_id = self.storage.add_system_prompt(
                content=DEFAULT_SYSTEM_PROMPT,
                reason="初始默认版本"
            )
            logger.info(f"创建默认系统提示词 v1 (id={self._current_prompt_id})")

        self._initialized = True
        return self._current_prompt

    @property
    def current_prompt(self) -> str:
        """获取当前生效的系统提示词"""
        if not self._initialized:
            return self.initialize()
        return self._current_prompt

    @property
    def current_version(self) -> str:
        return self._current_version

    @property
    def current_prompt_id(self) -> int:
        return self._current_prompt_id

    def reload(self) -> str:
        """重新从数据库加载最新活跃版本"""
        latest = self.storage.get_latest_system_prompt()
        if latest:
            self._current_prompt = latest["content"]
            self._current_version = latest["version"]
            self._current_prompt_id = latest["id"]
        return self._current_prompt

    def build_evolve_prompt(self, reflection_suggestion: Optional[str] = None) -> List[Dict]:
        """
        构建提示词进化 prompt。

        Args:
            reflection_suggestion: 反思生成的具体提示词建议

        Returns:
            API 消息列表
        """
        # 收集最近的反思建议
        suggestions = []
        if reflection_suggestion:
            suggestions.append(f"反思建议: {reflection_suggestion}")

        # 收集最近的未应用反思
        recent_reflections = self.storage.get_recent_reflections(limit=5)
        for ref in recent_reflections:
            import json
            ref_suggestions = ref.get("suggestions", "[]")
            if isinstance(ref_suggestions, str):
                try:
                    ref_suggestions = json.loads(ref_suggestions)
                except json.JSONDecodeError:
                    ref_suggestions = []
            for s in ref_suggestions:
                suggestions.append(f"反思建议: {s}")

        # 收集相关的长期记忆（指令类）
        instructions = self.storage.get_instructions()
        memory_text = ""
        if instructions:
            memory_text = "相关长期记忆:\n" + "\n".join(
                f"- [{m['category']}] {m['content']}" for m in instructions[:10]
            )

        user_content = f"""当前提示词：
---
{self._current_prompt}
---

{chr(10).join(suggestions) if suggestions else '(无新的反思建议)'}

{memory_text}

请输出优化后的完整系统提示词。"""

        return [
            {"role": "system", "content": self.EVOLVE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

    def evolve(self, reflection_suggestion: Optional[str] = None) -> Optional[int]:
        """
        触发提示词进化：调用 LLM 生成新版本，存储到数据库。

        Args:
            reflection_suggestion: 反思生成的提示词调整建议

        Returns:
            新提示词 ID，失败返回 None
        """
        if not self._cheap_client:
            logger.info("无便宜模型客户端，跳过提示词进化")
            return None

        messages = self.build_evolve_prompt(reflection_suggestion)

        try:
            response = self._cheap_client.chat.completions.create(
                model=self._cheap_model,
                messages=messages,
                temperature=0.3,
                max_tokens=2000,
                extra_body={"thinking": {"type": "disabled"}},
            )
            new_prompt = response.choices[0].message.content or ""

            if not new_prompt or len(new_prompt.strip()) < 20:
                logger.warning("提示词进化结果太短，跳过")
                return None

            new_prompt = new_prompt.strip()

            # 如果和当前版本一模一样，跳过
            if new_prompt == self._current_prompt:
                logger.info("新提示词与当前版本相同，跳过")
                return None

            # 存储新版本
            reason_parts = []
            if reflection_suggestion:
                reason_parts.append(f"反思建议: {reflection_suggestion[:200]}")
            reason = "; ".join(reason_parts) if reason_parts else "基于反思和记忆自动进化"

            new_id = self.storage.add_system_prompt(
                content=new_prompt,
                reason=reason,
            )

            # 切换到新版本
            self._current_prompt = new_prompt
            self._current_version = str(int(self._current_version) + 1)
            self._current_prompt_id = new_id

            # 标记相关反思为已应用
            recent_reflections = self.storage.get_recent_reflections(limit=5)
            for ref in recent_reflections:
                self.storage.mark_reflection_applied(ref["id"])

            logger.info(f"系统提示词进化完成: v{self._current_version} (id={new_id}), reason={reason[:100]}")
            return new_id

        except Exception as e:
            logger.warning(f"提示词进化失败: {e}")
            return None

    def rollback(self, version: str) -> bool:
        """
        回滚到指定版本。

        Args:
            version: 版本号（如 "2"）

        Returns:
            是否成功
        """
        history = self.storage.get_system_prompt_history(limit=100)
        target = None
        for h in history:
            if h["version"] == version:
                target = h
                break

        if not target:
            logger.warning(f"版本 {version} 不存在")
            return False

        if not self.storage.rollback_system_prompt(target["id"]):
            return False

        self._current_prompt = target["content"]
        self._current_version = version
        self._current_prompt_id = target["id"]
        logger.info(f"系统提示词回滚到 v{version}")
        return True

    def list_versions(self) -> List[Dict]:
        """列出所有版本"""
        return self.storage.get_system_prompt_history(limit=50)

    def get_stats(self) -> Dict:
        """获取统计"""
        count = self.storage.get_system_prompt_count()
        return {
            "total_versions": count,
            "current_version": self._current_version,
            "current_id": self._current_prompt_id,
        }

    def manual_set(self, content: str, reason: str = "手动设置") -> int:
        """手动设置新提示词版本"""
        new_id = self.storage.add_system_prompt(content=content, reason=reason)
        self._current_prompt = content
        self._current_version = str(int(self._current_version) + 1)
        self._current_prompt_id = new_id
        return new_id
