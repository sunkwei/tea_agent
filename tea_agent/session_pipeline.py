"""
会话 Pipeline 模块 — 将对话流程拆分为可配置的步骤。

每个步骤是一个独立函数，按 position 串行执行，返回 dict 自动合并到上下文。
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
    """Pipeline 步骤定义。"""

    name: str
    func: Callable[[dict[str, Any]], dict[str, Any] | None]
    enabled: bool = True
    description: str = ""
    position: int = 0
    critical: bool = False  # 核心步骤失败时 raise 而非吞异常


class SessionPipeline:
    """会话 Pipeline — 管理对话流程的处理步骤链。"""

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
        critical: bool = False,
    ) -> None:
        """注册一个 Pipeline 步骤。同名不可重复注册。"""
        if name in self._steps:
            raise ValueError(f"步骤 '{name}' 已存在")

        step = PipelineStep(
            name=name,
            func=func,
            enabled=enabled,
            description=description,
            position=position,
            critical=critical,
        )

        self._steps[name] = step
        self._step_order.append(name)
        self._step_order.sort(key=lambda n: self._steps[n].position)

    def enable_step(self, name: str) -> None:
        if name in self._steps:
            self._steps[name].enabled = True

    def disable_step(self, name: str) -> None:
        if name in self._steps:
            self._steps[name].enabled = False

    def set_step_position(self, name: str, position: int) -> None:
        if name in self._steps:
            self._steps[name].position = position
            self._step_order.sort(key=lambda n: self._steps[n].position)

    def remove_step(self, name: str) -> None:
        if name in self._steps:
            del self._steps[name]
            self._step_order.remove(name)

    def get_enabled_steps(self) -> list[tuple[str, PipelineStep]]:
        return [
            (name, self._steps[name])
            for name in self._step_order
            if self._steps[name].enabled
        ]

    def execute(
        self,
        context: dict[str, Any],
        stop_at: str | None = None,
        skip_steps: list[str] | None = None,
    ) -> dict[str, Any]:
        """串行执行所有启用的 Pipeline 步骤。"""
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
                if step.critical:
                    logger.error(f"    Critical step {name} failed: {e}", exc_info=True)
                    raise
                logger.warning(f"    Error running step {name}: {e}")
                context.setdefault("_errors", []).append(
                    {
                        "step": name,
                        "error": str(e),
                    }
                )

            if stop_at and name == stop_at:
                break

        logger.debug(f"Execution complete, with content\n{context}\n")
        return context

    def list_steps(self) -> list[dict[str, Any]]:
        """列出所有步骤的状态。"""
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
