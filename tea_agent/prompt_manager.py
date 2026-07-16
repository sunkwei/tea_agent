"""
系统提示词管理器 (SystemPromptManager)

管理多版本系统提示词，支持基于反思和记忆的自动进化。

核心功能：
1. 版本管理：多版本提示词存储、加载、回滚
2. 自动进化：基于反思建议 + 长期记忆，调用 LLM 生成新版本
3. 版本历史：查看所有版本及变更原因
4. 手动设置：支持管理员手动指定提示词内容

工作流程：
    initialize() → 从数据库加载最新活跃版本，无记录时创建默认版本
    evolve()     → 基于反思建议生成新版本
    rollback()   → 回退到指定历史版本
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("SystemPromptManager")

__all__ = [
    "SystemPromptManager",
    "DEFAULT_SYSTEM_PROMPT",
]

# 默认系统提示词模板（当数据库无记录时使用）
DEFAULT_SYSTEM_PROMPT = (
    "你是可自我扩展的智能Agent。"
    "拥有工具库toolkit，可通过toolkit_save(name,meta,pycode)保存新工具、"
    "toolkit_reload()重载获得新能力。"
    "内置工具：toolkit_exec(执行命令)、toolkit_load_file(读文件)、toolkit_save_file(写文件)。\n\n"
    "核心行为：主动分析任务需求，自主创建/优化/组合工具。"
    "工具须为纯Python、可执行、有明确输入输出、通用可复用。"
    "可自由设计单函数/多函数/工具套件等结构。\n\n"
    "上下文感知规则：\n"
    "1. 如果当前是 tea_agent 项目自身（特征：当前目录或父目录存在 tea_agent/agent.py）\n"
    "   → 启用全部自进化能力：可创建工具、修改源码、优化提示词\n"
    "2. 如果是外部项目（非 tea_agent 自身）\n"
    "   → 禁用自进化行为：不创建新工具、不修改源码框架、不优化提示词\n"
    "   → 专注于完成用户的外部任务，仅使用通用文件读写/搜索/编辑工具\n\n"
    "你不断进化，能力无上限。以最有效优雅的方式完成任务并持续增强自身。"
)

class SystemPromptManager:
    """系统提示词版本管理器 — 多版本、自动进化、支持回滚。

    通过数据库持久化存储提示词版本，每次对话使用最新活跃版本。
    可基于反思建议和长期记忆自动生成优化版本。

    Attributes:
        storage: Storage 数据库实例，用于存取提示词版本
        current_prompt: 当前生效的提示词文本
        current_version: 当前版本号字符串
        current_prompt_id: 当前版本的数据库 ID
    """

    EVOLVE_SYSTEM_PROMPT: str = """你是系统提示词优化器。基于以下信息，优化 Agent 的系统提示词：

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

    def __init__(
        self,
        storage: Any,
        cheap_client: Any = None,
        cheap_model: str = "",
    ) -> None:
        """初始化提示词管理器。

        Args:
            storage: Storage 数据库实例（必须已初始化）
            cheap_client: 便宜模型 OpenAI 客户端，用于生成新提示词版本
            cheap_model: 便宜模型名称
        """
        self.storage = storage
        self._cheap_client = cheap_client
        self._cheap_model = cheap_model
        self._current_prompt: str = ""
        self._current_version: str = "0"
        self._current_prompt_id: int = 0
        self._initialized: bool = False

    def initialize(self) -> str:
        """从数据库加载最新活跃提示词。数据库为空时自动插入默认版本 v1。

        Returns:
            当前生效的系统提示词文本
        """
        latest = self.storage.get_latest_system_prompt()
        if latest:
            self._current_prompt = latest["content"]
            self._current_version = latest["version"]
            self._current_prompt_id = latest["id"]
            logger.info(f"加载系统提示词 v{self._current_version} (id={self._current_prompt_id})")
        else:
            self._current_prompt = DEFAULT_SYSTEM_PROMPT
            self._current_version = "1"
            self._current_prompt_id = self.storage.add_system_prompt(
                content=DEFAULT_SYSTEM_PROMPT,
                reason="初始默认版本",
            )
            logger.info(f"创建默认系统提示词 v1 (id={self._current_prompt_id})")

        self._initialized = True
        return self._current_prompt

    @property
    def current_prompt(self) -> str:
        """获取当前生效的系统提示词。未初始化时自动调用 initialize()。"""
        if not self._initialized:
            return self.initialize()
        return self._current_prompt

    @property
    def current_version(self) -> str:
        """当前版本号（如 "1", "2", "3"）。"""
        return self._current_version

    @property
    def current_prompt_id(self) -> int:
        """当前版本的数据库记录 ID。"""
        return self._current_prompt_id

    def reload(self) -> str:
        """从数据库重新加载最新活跃版本（放弃当前内存中的版本）。

        Returns:
            重新加载后的提示词文本
        """
        latest = self.storage.get_latest_system_prompt()
        if latest:
            self._current_prompt = latest["content"]
            self._current_version = latest["version"]
            self._current_prompt_id = latest["id"]
        return self._current_prompt

    def build_evolve_prompt(self, reflection_suggestion: str | None = None) -> list[dict[str, str]]:
        """构建提示词进化用的 LLM prompt，包含当前提示词、反思建议和长期记忆。

        Args:
            reflection_suggestion: 单条反思生成的具体提示词调整建议

        Returns:
            [system_prompt_message, user_prompt_message] 格式的消息列表
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

    def evolve(self, reflection_suggestion: str | None = None) -> int | None:
        """触发提示词进化：调用 LLM 生成新版本并存储到数据库。

        流程：
        1. 构建进化 prompt
        2. 调用 cheap model 生成新提示词
        3. 校验内容有效性（长度 > 20，与当前版本不同）
        4. 存储到数据库并切换到新版本
        5. 标记相关反思为已应用

        Args:
            reflection_suggestion: 反思生成的提示词调整建议

        Returns:
            新提示词的数据库 ID，失败或跳过时返回 None
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
        """回滚到指定历史版本。

        Args:
            version: 目标版本号字符串（如 "2"）

        Returns:
            True 表示回滚成功，False 表示版本不存在或操作失败
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

    def list_versions(self) -> list[dict[str, Any]]:
        """列出所有历史版本（按时间倒序）。

        Returns:
            版本字典列表，每个包含 id/version/content/reason/created_at 等字段
        """
        return self.storage.get_system_prompt_history(limit=50)

    def get_stats(self) -> dict[str, Any]:
        """获取提示词版本统计信息。

        Returns:
            total_versions: 总版本数
            current_version: 当前版本号
            current_id: 当前版本的数据库 ID
        """
        count = self.storage.get_system_prompt_count()
        return {
            "total_versions": count,
            "current_version": self._current_version,
            "current_id": self._current_prompt_id,
        }

    def manual_set(self, content: str, reason: str = "手动设置") -> int:
        """手动设置新提示词版本（跳过 LLM 生成，直接存储）。

        Args:
            content: 新的提示词文本
            reason: 设置原因说明

        Returns:
            新版本的数据库 ID
        """
        new_id = self.storage.add_system_prompt(content=content, reason=reason)
        self._current_prompt = content
        self._current_version = str(int(self._current_version) + 1)
        self._current_prompt_id = new_id
        return new_id
