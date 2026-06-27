"""
轻量 Agent — 用于子任务执行。

核心设计:
  内部使用 LiteSession 做真正的 LLM 调用 + 工具执行。
  无存储、无长期记忆、每次独立执行。

用法:
    from tea_agent.multi_agent import LiteAgent
    
    agent = LiteAgent()
    result = agent.execute_sync("重构 gui.py 添加类型注解")
"""

import logging
from typing import Dict

from tea_agent.litesession import LiteSession

logger = logging.getLogger(__name__)


class LiteAgent:
    """
    轻量 Agent — 基于 LiteSession 实现真正的 LLM 调用。

    每次 execute() 创建一个新的 LiteSession（无状态），
    执行完毕后释放，不保留历史。
    """

    def __init__(self, toolkit=None, max_iterations: int = 20, enable_thinking: bool = False):
        """
        Args:
            toolkit: Toolkit 实例（工具库），None 时自动获取全局实例
            max_iterations: 工具调用最大迭代次数
            enable_thinking: 是否启用 thinking（子任务建议关闭以提速）
        """
        self.max_iterations = max_iterations
        self.enable_thinking = enable_thinking

        # 获取 toolkit
        if toolkit is None:
            from tea_agent import tlk
            toolkit = tlk._toolkit_
        self.toolkit = toolkit

    def execute_sync(self, goal: str, system_prompt: str = "") -> str:
        """
        同步执行子任务（直接调用 LiteSession.chat）。

        Args:
            goal: 子任务描述
            system_prompt: 自定义系统提示（为空使用内置提示）

        Returns:
            AI 最终回复文本
        """
        logger.info(f"🚀 LiteAgent 开始执行: {goal[:80]}...")

        # 获取模型配置
        cfg = self._get_config()
        main_m = cfg.main_model

        # 构建系统提示
        if not system_prompt:
            system_prompt = self._build_system_prompt(goal)

        # 创建 LiteSession（无状态）
        sess = LiteSession(
            toolkit=self.toolkit,
            api_key=str(main_m.api_key or ""),
            api_url=str(main_m.api_url or ""),
            model=str(main_m.model_name or ""),
            system_prompt=system_prompt,
            enable_thinking=self.enable_thinking,
            max_iterations=self.max_iterations,
        )

        # 执行
        result = sess.chat(goal)

        # 提取结果
        assistant = result.get("assistant", "")
        tool_calls = result.get("tool_calls", 0)
        error = result.get("error")

        if error:
            logger.error(f"❌ LiteAgent 失败: {error}")
            return f"[执行失败] {error}"

        logger.info(f"✅ LiteAgent 完成 (工具调用: {tool_calls} 次)")
        return assistant

    def execute_with_context(
        self,
        goal: str,
        context: Dict,
        system_prompt: str = "",
    ) -> str:
        """
        带上下文执行子任务。

        Args:
            goal: 子任务描述
            context: 上下文信息（如前置步骤的结果）
            system_prompt: 自定义系统提示

        Returns:
            AI 最终回复文本
        """
        # 把上下文注入到 goal 前面
        context_parts = []
        for key, value in context.items():
            context_parts.append(f"【{key}】\n{value}")

        if context_parts:
            enriched_goal = (
                "## 前置信息\n"
                + "\n\n".join(context_parts)
                + f"\n\n## 当前任务\n{goal}"
            )
        else:
            enriched_goal = goal

        return self.execute_sync(enriched_goal, system_prompt)

    @staticmethod
    def _get_config():
        """获取全局配置"""
        from tea_agent.config import load_config
        return load_config()

    @staticmethod
    def _build_system_prompt(goal: str) -> str:
        """构建子任务专用系统提示"""
        return f"""你是一个专注的执行 Agent。你的任务是高效完成指定工作。

## 当前子任务
{goal}

## 规则
1. 精准使用工具完成任务，不做多余操作
2. 如果遇到错误，尝试修复一次；仍失败则报告具体错误
3. 完成后返回简明结果摘要
4. 不要主动询问，直接执行
"""
