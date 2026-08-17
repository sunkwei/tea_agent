"""
工具执行 Hook 系统 — 借鉴 DeepSeek Harness Tool Execution Pipeline。

提供两个阶段的可插拔钩子（默认全部放行，保持 Tea Agent "自由奔放" 哲学）：
- pre-execute 瀑布：审批 / 权限 / 沙箱决策（可拒绝执行）
- post-execute 瀑布：结果改写 / 附加上下文注入（additionalContexts）
- 回调异常隔离：单个 hook 抛异常不影响核心执行与其他 hook

用法：
    from tea_agent.tool_hooks import tool_hooks

    @tool_hooks.on_post("toolkit_exec")
    def mask_secrets(tool_name, args, result):
        if isinstance(result, dict) and "stdout" in result:
            result["stdout"] = _mask(result["stdout"])
        return {"result": result}

    @tool_hooks.on_pre("toolkit_file")
    def deny_write(tool_name, args):
        if args.get("action") == "write":
            return {"deny": True, "reason": "写文件被策略拒绝"}
        return True
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("tool_hooks")


class ToolHookRegistry:
    """线程安全的工具 Hook 注册表。

    结构:
        _pre_hooks:  {tool_name: [fn, ...]}   fn(tool_name, args) -> bool | dict
        _post_hooks: {tool_name: [fn, ...]}   fn(tool_name, args, result) -> result | {"result":..., "additional_context":...}
    tool_name 为 "*" 时匹配所有工具（全局钩子）。
    """

    def __init__(self) -> None:
        self._pre_hooks: dict[str, list[Callable]] = {}
        self._post_hooks: dict[str, list[Callable]] = {}
        self._lock = threading.RLock()
        self._additional_contexts: list[dict] = []

    # ── 注册 API ──

    def on_pre(self, tool_name: str | None = None):
        """装饰器：注册 pre-execute 钩子。"""
        def deco(fn: Callable) -> Callable:
            self.register_pre(tool_name, fn)
            return fn
        return deco

    def on_post(self, tool_name: str | None = None):
        """装饰器：注册 post-execute 钩子。"""
        def deco(fn: Callable) -> Callable:
            self.register_post(tool_name, fn)
            return fn
        return deco

    def register_pre(self, tool_name: str | None, fn: Callable) -> None:
        """注册 pre-execute 钩子。

        fn(tool_name, args) -> True 放行；False 或 {"deny": True, "reason": "..."} 拒绝。
        """
        with self._lock:
            self._pre_hooks.setdefault(tool_name or "*", []).append(fn)

    def register_post(self, tool_name: str | None, fn: Callable) -> None:
        """注册 post-execute 钩子。

        fn(tool_name, args, result) -> 新 result（替换）或 {"result":..., "additional_context":...}
        """
        with self._lock:
            self._post_hooks.setdefault(tool_name or "*", []).append(fn)

    def clear(self) -> None:
        """清空全部钩子（测试/重置用）。"""
        with self._lock:
            self._pre_hooks.clear()
            self._post_hooks.clear()
            self._additional_contexts.clear()

    # ── 执行 API ──

    def run_pre(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """pre-execute 瀑布。返回 (allow, reason)。默认放行。

        任一钩子拒绝即整体拒绝；钩子异常被隔离（记录并继续）。
        """
        hooks = list(self._pre_hooks.get("*", [])) + list(self._pre_hooks.get(tool_name, []))
        for fn in hooks:
            try:
                decision = fn(tool_name, args)
                if decision is False:
                    return False, f"pre-hook 拒绝: {getattr(fn, '__name__', fn)}"
                if isinstance(decision, dict) and decision.get("deny"):
                    reason = decision.get("reason") or "被 pre-hook 拒绝"
                    return False, str(reason)
            except Exception as e:  # noqa: BLE001 — 回调异常隔离
                logger.warning("pre-hook %s 异常已隔离: %s", getattr(fn, "__name__", fn), e)
        return True, ""

    def run_post(self, tool_name: str, args: dict, result: Any) -> tuple[Any, list[dict]]:
        """post-execute 瀑布。返回 (final_result, additional_contexts)。

        - 钩子返回 dict 且含 "result" 键 → 替换结果，可附带 "additional_context"
        - 钩子返回其他值 → 直接作为新结果
        - 钩子异常被隔离（记录并继续，保留当前结果）
        """
        final = result
        contexts: list[dict] = []
        hooks = list(self._post_hooks.get("*", [])) + list(self._post_hooks.get(tool_name, []))
        for fn in hooks:
            try:
                out = fn(tool_name, args, final)
                if isinstance(out, dict) and "result" in out:
                    final = out["result"]
                    if out.get("additional_context") is not None:
                        contexts.append(out["additional_context"])
                elif out is not None:
                    final = out
            except Exception as e:  # noqa: BLE001 — 回调异常隔离
                logger.warning("post-hook %s 异常已隔离: %s", getattr(fn, "__name__", fn), e)
        return final, contexts

    def inject_context(self, context: dict) -> None:
        """直接注入附加上下文（供 post-hook 系统外部调用）。"""
        with self._lock:
            self._additional_contexts.append(context)

    def drain_contexts(self) -> list[dict]:
        """取出并清空所有附加上下文（FIFO）。"""
        with self._lock:
            ctxs, self._additional_contexts = self._additional_contexts, []
        return ctxs

    def stats(self) -> dict:
        """当前注册的钩子统计。"""
        with self._lock:
            return {
                "pre_hooks": {k: len(v) for k, v in self._pre_hooks.items()},
                "post_hooks": {k: len(v) for k, v in self._post_hooks.items()},
                "pending_contexts": len(self._additional_contexts),
            }


# 全局单例 — 各会话共享（工具级 hook）
tool_hooks = ToolHookRegistry()
