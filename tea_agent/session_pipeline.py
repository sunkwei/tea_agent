"""
会话 Pipeline 模块 — 将对话流程拆分为可配置的步骤。

设计思路：
- 每个步骤是一个独立的函数/方法，通过名称标识
- 步骤可以启用/禁用、重新排序、动态插入
- Pipeline 按配置顺序串行执行启用的步骤
- 每个步骤返回 dict，自动合并到上下文

适用场景：
- 对话前预处理（注入记忆、OS 信息）
- 对话后处理（摘要、评估、技能结晶）
- 自定义插件扩展
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("session_pipeline")

__all__ = [
    "PipelineStep",
    "SessionPipeline",
]


@dataclass
class PipelineStep:
    """Pipeline 步骤定义 — 描述一个可执行的对话处理步骤。

    Attributes:
        name:       步骤名称（唯一标识符）
        func:       执行函数，签名接受 (context: dict) -> dict
        enabled:    是否启用，禁用的步骤在 execute 中被跳过
        description: 步骤的功能描述（用于文档和调试）
        position:   执行顺序编号，越小越先执行
    """
    name: str
    func: Callable[[dict[str, Any]], dict[str, Any] | None]
    enabled: bool = True
    description: str = ""
    position: int = 0


class SessionPipeline:
    """会话 Pipeline 管理器 — 管理对话流程的处理步骤链。

    功能：
    - 注册/移除步骤
    - 启用/禁用步骤
    - 重新排序步骤
    - 按顺序执行所有启用的步骤

    用法:
        pipeline = SessionPipeline()
        pipeline.register_step("inject_memory", my_func, position=10)
        result = pipeline.execute({"user_input": "你好"})
    """

    def __init__(self) -> None:
        """初始化空的 Pipeline。"""
        self._steps: dict[str, PipelineStep] = {}
        self._step_order: list[str] = []

    def register_step(
        self,
        name: str,
        func: Callable[[dict[str, Any]], dict[str, Any] | None],
        enabled: bool = True,
        description: str = "",
        position: int = 0,
    ) -> None:
        """注册一个 Pipeline 步骤。

        Args:
            name: 步骤名称（唯一标识符，不可重复注册）
            func: 执行函数，签名为 (context: dict) -> dict | None
            enabled: 是否启用
            description: 步骤描述信息
            position: 执行顺序编号（越小越先执行）

        Raises:
            ValueError: 如果 name 已存在

        注意：
            position 相同的情况下，先注册的先执行。
            注册后所有步骤按 position 升序排列。
        """
        if name in self._steps:
            raise ValueError(f"步骤 '{name}' 已存在")

        step = PipelineStep(
            name=name,
            func=func,
            enabled=enabled,
            description=description,
            position=position,
        )

        self._steps[name] = step
        self._step_order.append(name)
        self._step_order.sort(key=lambda n: self._steps[n].position)

    def enable_step(self, name: str) -> None:
        """启用指定步骤。

        Args:
            name: 步骤名称。如果不存在则静默忽略。
        """
        if name in self._steps:
            self._steps[name].enabled = True

    def disable_step(self, name: str) -> None:
        """禁用指定步骤（跳过执行）。

        Args:
            name: 步骤名称。如果不存在则静默忽略。
        """
        if name in self._steps:
            self._steps[name].enabled = False

    def set_step_position(self, name: str, position: int) -> None:
        """重新设置步骤的执行顺序编号。

        Args:
            name: 步骤名称
            position: 新的顺序编号
        """
        if name in self._steps:
            self._steps[name].position = position
            self._step_order.sort(key=lambda n: self._steps[n].position)

    def remove_step(self, name: str) -> None:
        """从 Pipeline 中移除指定步骤。

        Args:
            name: 要移除的步骤名称

        Raises:
            ValueError: 如果 name 不存在
        """
        if name in self._steps:
            del self._steps[name]
            self._step_order.remove(name)

    def get_enabled_steps(self) -> list[tuple[str, PipelineStep]]:
        """获取所有启用的步骤，按执行顺序排列。

        Returns:
            (name, step) 元组列表，按 position 升序
        """
        return [
            (name, self._steps[name]) for name in self._step_order
            if self._steps[name].enabled
        ]

    def execute(
        self,
        context: dict[str, Any],
        stop_at: str | None = None,
        skip_steps: list[str] | None = None,
    ) -> dict[str, Any]:
        """串行执行 Pipeline 中的所有启用步骤。

        执行流程：
        1. 遍历所有启用的步骤（按 position 排序）
        2. 跳过 skip_steps 中指定的步骤
        3. 执行步骤函数，将返回的 dict 合并到 context
        4. 如果步骤抛出异常，记录错误到 context["_errors"]
        5. 如果到达 stop_at 步骤，执行后停止

        Args:
            context: 上下文字典，传递给每个步骤并在步骤间共享
            stop_at: 执行到此步骤后停止（该步骤本身会执行）
            skip_steps: 临时跳过的步骤名称列表

        Returns:
            更新后的上下文字典（所有步骤的返回被合并到此字典）
        """
        skip_steps = skip_steps or []

        logger.debug(f"Executing session pipe with context:\n{context}")
        for i, (name, step) in enumerate(self.get_enabled_steps()):
            logger.debug(f"  Step {i}: {name}")
            if name in skip_steps:
                continue

            try:
                logger.debug(f"    Running step {name}, context: {context}")
                result = step.func(context)
                if isinstance(result, dict):
                    context.update(result)
            except Exception as e:
                logger.warning(f"    Error running step {name}: {e}")
                context.setdefault("_errors", []).append({
                    "step": name,
                    "error": str(e),
                })

            if stop_at and name == stop_at:
                break

        logger.debug(f"Execution complete, with content\n{context}\n")
        return context

    def list_steps(self) -> list[dict[str, Any]]:
        """列出所有步骤的状态信息。

        Returns:
            步骤状态字典列表，每个字典包含：
            - name: 步骤名称
            - enabled: 是否启用
            - position: 执行顺序
            - description: 步骤描述
            - disabled: （仅禁用的步骤）标记为 True
        """
        enabled_steps = [
            {
                "name": name,
                "enabled": step.enabled,
                "position": step.position,
                "description": step.description,
            }
            for name, step in self.get_enabled_steps()
        ]
        disabled_steps = [
            {
                "name": name,
                "enabled": step.enabled,
                "position": step.position,
                "description": step.description,
                "disabled": True,
            }
            for name, step in self._steps.items()
            if not step.enabled
        ]
        return enabled_steps + disabled_steps
