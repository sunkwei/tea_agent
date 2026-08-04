"""
上下文片段系统 (Context Fragments) — 借鉴 OpenAI Codex Context Fragments 架构

核心思想：将动态上下文拆分为独立片段（时间/预算/模式/AGENTS.md/环境），
按需组装注入 system prompt，取代"单一巨型提示词"的静态做法。

与 Codex (codex-rs/core/src/context/*.rs) 的对应关系：
  CurrentTimeReminder         → current_time 片段
  TokenBudgetRemainingContext → token_budget 片段
  RolloutBudgetContext        → session_budget 片段
  UserInstructions            → agents_md 片段
  EnvironmentContext          → environment 片段

用法：
    from tea_agent.context_fragments import (
        assemble_fragments, register_fragment, get_fragment, list_fragments
    )

    # 1. 使用内置片段（自动组装）
    text = assemble_fragments(context)

    # 2. 自定义片段（注册工厂函数，返回 ContextFragment 或 None）
    register_fragment("my_fragment", lambda ctx: ContextFragment(name="my", body="..."))

    # 3. 追加到 system prompt 尾部即可
    system_prompt = system_prompt + "\\n\\n" + text

设计原则（对齐 Codex）：
- 片段按需注入：工厂返回 None 表示当前不适用
- 片段可独立启用/禁用：assemble_fragments(exclude=...) / names=...
- 有字节预算：max_chars 防止片段无限膨胀
- 失败隔离：单个片段异常不影响整体组装
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("context_fragments")

__all__ = [
    "ContextFragment",
    "register_fragment",
    "unregister_fragment",
    "get_fragment",
    "list_fragments",
    "assemble_fragments",
    "clear_fragments",
    "DEFAULT_FRAGMENT_ORDER",
]

# 默认片段组装顺序（小权重在前，weight 越小越靠前）
DEFAULT_FRAGMENT_ORDER = [
    "session_budget",
    "token_budget",
    "current_time",
    "session_mode",
    "environment",
    "agents_md",
]


@dataclass
class ContextFragment:
    """单个上下文片段。

    Attributes:
        name: 片段唯一名称
        body: 片段内容
        role: 注入角色（system/developer/user），预留兼容
        markers: XML 标签对，如 ("<token_budget>\\n", "\\n</token_budget>")
        enabled: 是否启用
        weight: 组装顺序权重（越小越靠前）
    """

    name: str
    body: str
    role: str = "system"
    markers: tuple[str, str] = ("", "")
    enabled: bool = True
    weight: int = 10

    def render(self) -> str:
        """渲染为文本（带 XML 标记）。"""
        if not self.body:
            return ""
        open_tag, close_tag = self.markers
        if open_tag:
            return f"{open_tag}{self.body}{close_tag}"
        return self.body


# ═══ 片段注册表 ═════════════════════════════════════════

# name → factory(context) -> ContextFragment | None
_FRAGMENT_REGISTRY: dict[str, Callable[[Any], ContextFragment | None]] = {}


def register_fragment(
    name: str,
    factory: Callable[[Any], ContextFragment | None],
) -> None:
    """注册片段工厂。

    Args:
        name: 片段名称（唯一）
        factory: 工厂函数，接收 context，返回 ContextFragment 或 None（不适用时）
    """
    _FRAGMENT_REGISTRY[name] = factory
    logger.debug(f"片段已注册: {name}")


def unregister_fragment(name: str) -> None:
    """注销片段。"""
    _FRAGMENT_REGISTRY.pop(name, None)


def clear_fragments() -> None:
    """清空所有自定义片段（保留内置片段）。"""
    builtin = set(DEFAULT_FRAGMENT_ORDER)
    for name in list(_FRAGMENT_REGISTRY.keys()):
        if name not in builtin:
            _FRAGMENT_REGISTRY.pop(name, None)


def get_fragment(name: str, context: Any) -> ContextFragment | None:
    """获取单个片段的渲染实例。

    Args:
        name: 片段名称
        context: SessionContext

    Returns:
        ContextFragment 或 None（未注册/不适用）
    """
    factory = _FRAGMENT_REGISTRY.get(name)
    if factory is None:
        return None
    try:
        frag = factory(context)
        return frag if frag is not None and frag.enabled else None
    except Exception as e:
        logger.debug(f"片段 {name} 生成失败: {e}")
        return None


def list_fragments() -> list[str]:
    """列出所有已注册片段名称。"""
    return list(_FRAGMENT_REGISTRY.keys())


# ═══ 内置片段 ═══════════════════════════════════════════

def _estimate_context_tokens(context: Any) -> int:
    """估算当前上下文 token 用量（消息 + tools 定义 + 已注入富化文本）。

    修正 S1：此前仅基于 context.messages 估算，漏掉了：
    - tools 定义（78 个工具 JSON Schema，实测约 14K tokens）
    - system prompt 富化部分（OS 信息、记忆注入等）
    导致 token_budget 报警显著低估实际请求用量。
    """
    total = 0
    try:
        from tea_agent.session.history_builder import estimate_messages_tokens, estimate_tokens

        # 1. 消息本体
        msgs = getattr(context, "messages", None) or []
        total += estimate_messages_tokens(msgs)
    except Exception:
        return 0

    # 2. tools 定义（每次请求都会携带全部工具 JSON Schema）
    try:
        toolkit = getattr(context, "toolkit", None)
        meta_map = getattr(toolkit, "meta_map", None) if toolkit else None
        if meta_map:
            import json as _json

            tools_json = _json.dumps(list(meta_map.values()), ensure_ascii=False, default=str)
            total += estimate_tokens(tools_json)
    except Exception:
        pass

    # 3. system prompt 富化注入（OS 信息 / 记忆文本等已注入片段）
    try:
        for attr in ("_injected_os_info_text", "_injected_memories_text"):
            txt = getattr(context, attr, "") or ""
            if txt:
                total += estimate_tokens(txt)
    except Exception:
        pass

    return total


def _get_max_tokens(context: Any) -> int:
    """获取模型最大上下文 token 数（0=未知）。"""
    max_tokens = getattr(context, "max_context_tokens", 0) or 0
    if max_tokens > 0:
        return int(max_tokens)
    # 从配置回退：模型名映射
    try:
        from tea_agent.auto_compact import get_max_context_tokens

        return int(get_max_context_tokens(getattr(context, "config", None)))
    except Exception:
        return 0


def _frag_session_budget(context: Any) -> ContextFragment | None:
    """会话预算片段 — 告知模型当前会话已消耗的轮次/工具调用量。"""
    rounds = getattr(context, "_rounds_collector", None)
    n_rounds = len(rounds) if rounds else 0
    if n_rounds <= 0:
        return None
    return ContextFragment(
        name="session_budget",
        body=f"本次会话已进行 {n_rounds} 轮工具交互。",
        markers=("<session_budget>\n", "\n</session_budget>"),
        weight=1,
    )


def _frag_token_budget(context: Any) -> ContextFragment | None:
    """Token 预算片段（核心）— 让模型感知剩余空间，自主决策。

    对应 Codex TokenBudgetRemainingContext：当模型知道自己还剩多少
    token 时，才能主动选择"继续干活 / 先总结 / 请求压缩"。
    """
    used = _estimate_context_tokens(context)
    max_tokens = _get_max_tokens(context)

    if max_tokens > 0:
        remaining = max(0, max_tokens - used)
        pct = min(100.0, used / max_tokens * 100.0)
        if remaining <= 0:
            body = (
                f"⚠️ 上下文已用尽（{used}/{max_tokens} token）。"
                "请立即总结关键决策，并要求用户允许压缩历史后继续。"
            )
        elif remaining < max_tokens * 0.15:
            body = (
                f"⚠️ 上下文剩余不足 15%（已用 {used}/{max_tokens} token，"
                f"剩余 {remaining}）。建议先总结已完成的工作，再继续。"
            )
        else:
            body = (
                f"当前上下文已用约 {used}/{max_tokens} token"
                f"（{pct:.0f}%，剩余约 {remaining}）。"
                "当剩余空间不足时，请主动总结并提示压缩。"
            )
    else:
        body = f"当前上下文已用约 {used} token（模型窗口未知，按需节制使用）。"

    return ContextFragment(
        name="token_budget",
        body=body,
        markers=("<token_budget>\n", "\n</token_budget>"),
        weight=2,
    )


def _frag_current_time(context: Any) -> ContextFragment | None:
    """当前时间片段 — 对应 Codex CurrentTimeReminder。"""
    try:
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return ContextFragment(
            name="current_time",
            body=f"当前时间: {now}",
            markers=("<current_time>\n", "\n</current_time>"),
            weight=3,
        )
    except Exception:
        return None


def _frag_session_mode(context: Any) -> ContextFragment | None:
    """会话模式片段 — 告知模型当前运行模式。"""
    mode = getattr(context, "_current_mode", "") or ""
    interface = getattr(context, "interface_type", "") or ""
    parts = []
    if mode:
        parts.append(f"运行模式: {mode}")
    if interface:
        parts.append(f"界面: {interface}")
    if not parts:
        return None
    return ContextFragment(
        name="session_mode",
        body="\n".join(parts),
        markers=("<session_mode>\n", "\n</session_mode>"),
        weight=4,
    )


def _frag_environment(context: Any) -> ContextFragment | None:
    """环境信息片段 — 复用已有 OS 注入（避免重复）。"""
    os_text = getattr(context, "_injected_os_info_text", "") or ""
    if not os_text:
        return None
    return ContextFragment(
        name="environment",
        body=os_text,
        markers=("<environment>\n", "\n</environment>"),
        weight=5,
    )


def _frag_agents_md(context: Any) -> ContextFragment | None:
    """AGENTS.md 分层指令片段 — 对应 Codex UserInstructions。

    从项目根到 cwd 收集 AGENTS.md + 用户级 ~/.tea_agent/AGENTS.md，
    带字节预算截断（默认 16KB）。
    """
    try:
        from tea_agent.agents_md_loader import load_agents_md

        loaded = load_agents_md(max_bytes=16 * 1024)
        text = loaded.text if loaded else ""
        if not text:
            return None
        return ContextFragment(
            name="agents_md",
            body=f"[项目指令 AGENTS.md]\n{text}",
            markers=("<agents_md>\n", "\n</agents_md>"),
            weight=6,
        )
    except Exception as e:
        logger.debug(f"AGENTS.md 片段加载失败: {e}")
        return None


# ═══ 注册内置片段 ═══════════════════════════════════════

def _init_builtin_fragments() -> None:
    """注册内置片段（幂等）。"""
    builtin = {
        "session_budget": _frag_session_budget,
        "token_budget": _frag_token_budget,
        "current_time": _frag_current_time,
        "session_mode": _frag_session_mode,
        "environment": _frag_environment,
        "agents_md": _frag_agents_md,
    }
    for name, factory in builtin.items():
        if name not in _FRAGMENT_REGISTRY:
            _FRAGMENT_REGISTRY[name] = factory


_init_builtin_fragments()


# ═══ 组装器 ═════════════════════════════════════════════

def assemble_fragments(
    context: Any,
    names: list[str] | None = None,
    exclude: list[str] | None = None,
    max_chars: int = 24 * 1024,
    header: str = "[系统状态 — 由 tea_agent 自动注入，供参考]",
) -> str:
    """组装启用中的片段为一段文本（追加到 system prompt 尾部）。

    Args:
        context: SessionContext
        names: 指定要组装的片段（None=全部已注册）
        exclude: 排除的片段名
        max_chars: 组装结果最大字符数（字节预算）
        header: 块头注释

    Returns:
        组装后的文本（无片段时返回空串）
    """
    exclude = set(exclude or [])
    candidates = names or list(_FRAGMENT_REGISTRY.keys())

    fragments: list[ContextFragment] = []
    for name in candidates:
        if name in exclude:
            continue
        frag = get_fragment(name, context)
        if frag is not None:
            fragments.append(frag)

    if not fragments:
        return ""

    # 按 weight 排序
    fragments.sort(key=lambda f: f.weight)

    # 组装 + 字节预算
    parts: list[str] = []
    total = 0
    for frag in fragments:
        rendered = frag.render()
        if not rendered:
            continue
        if total + len(rendered) > max_chars:
            logger.debug(f"片段预算耗尽，跳过 {frag.name}")
            break
        parts.append(rendered)
        total += len(rendered)

    if not parts:
        return ""

    return "\n\n".join([header] + parts)
