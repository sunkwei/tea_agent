"""invariants — 运行时不变式注册表（借鉴 DeepSeek Harness 的 invariants 子系统）。

AGENTS.md 里的「不可妥协不变式」此前只是文档约定，靠 review 时的记忆维持，
改错了要到线上才暴露。这里把它们升级为**可安装的运行时断言**：

- 每个不变式 = 一个纯函数检查器，挂在明确的检查点 ``where`` 上
- :meth:`InvariantRegistry.run` 旁路观测：返回违例清单，**永不抛异常**，
  不改写主流程控制流（与 AGENTS.md「旁路代码不得改写控制流」一致）
- :meth:`InvariantRegistry.enforce` 严格模式：违例抛 :class:`InvariantFailure`
  （测试 / 自检用）

设计约束：

- 检查器必须是纯函数（不碰 DB、不改状态、不读时钟），违例只由入参决定
- 检查器签名统一 ``(**ctx) -> str | None``：返回 ``None`` 表示通过，返回
  字符串即违例详情；多余关键字由 ``**_`` 吸收，同一 ctx 可喂多个检查器
- 检查器自身异常按违例处理 —— 宁可 fail-open 也不能静默放过真违例
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger("invariants")

CheckFn = Callable[..., "str | None"]


@dataclass(frozen=True)
class InvariantViolation:
    """一条不变式违例。"""

    invariant: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.invariant}] @{self.where}: {self.detail}"


class InvariantFailure(RuntimeError):  # noqa: N818 — 命名对齐 dsh invariants 术语
    """严格模式下的不变式违例（:meth:`InvariantRegistry.enforce` 抛出）。"""

    def __init__(self, violations: list[InvariantViolation]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(str(v) for v in self.violations) or "invariant failure")


@dataclass(frozen=True)
class Invariant:
    """一个已注册的不变式。"""

    name: str
    where: str
    check: CheckFn
    description: str = ""


class InvariantRegistry:
    """不变式注册表：``name`` 唯一，按 ``where`` 分检查点。

    同名 ``install`` 为幂等覆盖（便于测试替换检查器），执行顺序按 name 排序，
    保证判定**确定性**（呼应 AGENTS.md 工具列表顺序稳定的约束）。
    """

    def __init__(self) -> None:
        self._items: dict[str, Invariant] = {}

    def install(self, name: str, where: str, check: CheckFn, description: str = "") -> Invariant:
        """注册（或覆盖）一个不变式检查器。"""
        inv = Invariant(name=name, where=where, check=check, description=description)
        self._items[name] = inv
        return inv

    def uninstall(self, name: str) -> bool:
        """移除不变式，返回是否真的移除了。"""
        return self._items.pop(name, None) is not None

    def names(self, where: str | None = None) -> tuple[str, ...]:
        """已注册不变式名（确定性排序；可按检查点过滤）。"""
        return tuple(sorted(n for n, it in self._items.items() if where is None or it.where == where))

    def clear(self) -> None:
        """清空（测试隔离用）。"""
        self._items.clear()

    def run(self, where: str, /, **ctx) -> list[InvariantViolation]:
        """执行 ``where`` 检查点的全部不变式，返回违例清单。**永不抛异常**。"""
        out: list[InvariantViolation] = []
        for name in self.names(where):
            inv = self._items[name]
            try:
                detail = inv.check(**ctx)
            except Exception as e:  # noqa: BLE001 — 检查器自身异常按违例处理
                out.append(InvariantViolation(name, where, f"检查器异常: {e.__class__.__name__}: {e}"))
                continue
            if detail:
                out.append(InvariantViolation(name, where, str(detail)))
        return out

    def enforce(self, where: str, /, **ctx) -> None:
        """严格模式：违例抛 :class:`InvariantFailure`。"""
        violations = self.run(where, **ctx)
        if violations:
            raise InvariantFailure(violations)


# 全局注册表：各模块在 import 时安装自己的不变式（见 tool_shield / tlk）
registry = InvariantRegistry()

__all__ = [
    "CheckFn",
    "Invariant",
    "InvariantFailure",
    "InvariantRegistry",
    "InvariantViolation",
    "registry",
]
