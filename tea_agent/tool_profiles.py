"""
工具档位系统 (Tool Profiles) — 按模型上下文窗口自适应裁剪工具暴露量。

背景：工具 JSON Schema 是每次 API 请求都全额携带的固定开销。
当前 57 个 LLM 可见工具 schema ≈ 43KB ≈ 10.8K tokens。对 128K+ 的大窗口
占比 <8%，保留全量能力划算；但对 32K/64K 的小窗口模型会吃掉 1/3 可用空间，
必须按档位裁剪。

设计（对齐会话架构约束）：
  - 档位在「会话启动时」按模型窗口一次性选定，整个会话保持稳定，
    避免工具列表中途收缩破坏 DeepSeek 前缀缓存（工具 schema 顺序跨进程稳定）。
  - 降档不减"最后保底"：exec/file/edit 永远在场（shell 是万能工具）。
  - config.yaml 可显式覆盖：ModelConfig.tool_profile = auto|full|standard|core|minimal|nano
    auto=按 max_context_tokens 推导；显式档位优先。

档位分层（嵌套：nano ⊂ minimal ⊂ core ⊂ standard ⊂ full）：
  full      所有工具（≥200K 窗口，能力优先）
  standard  核心集 + 开发高频集（64K~200K，常规编码 Agent）
  core      编码闭环 + 轻量编排（32K~64K）
  minimal   编码最小可用（16K~32K）
  nano      exec + file + edit 三件套（<16K，最后保底）

窗口推导（max_context_tokens 未知/未配置时保守返回 full——不误伤能力；
因此小窗口模型请显式配置 max_context_tokens 或直接设 tool_profile）：
  ≥200K → full；≥64K → standard；≥32K → core；≥16K → minimal；<16K → nano
"""

from __future__ import annotations

import logging

logger = logging.getLogger("tool_profiles")

__all__ = [
    "PROFILE_NAMES",
    "PROFILE_TOOLS",
    "PROFILE_THRESHOLDS",
    "resolve_tool_profile",
    "filter_tools_by_profile",
    "UNKNOWN_CTX_PROFILE",
]

# ═══ 档位定义 ═══════════════════════════════════════════

# 合法档位名（auto=按窗口推导；其余为显式档位）
PROFILE_NAMES: tuple[str, ...] = ("auto", "full", "standard", "core", "minimal", "nano")

# 窗口未知/未配置（max_context_tokens<=0）时的保守档位：全量，能力优先。
UNKNOWN_CTX_PROFILE = "full"

# 档位阈值表（降序匹配）：(下界, 档位)
PROFILE_THRESHOLDS: list[tuple[int, str]] = [
    (200_000, "full"),
    (64_000, "standard"),
    (32_000, "core"),
    (16_000, "minimal"),
]

# 每个档位的工具白名单。全量档（full）用 None 表示「不过滤」。
# 档位须嵌套：nano ⊂ minimal ⊂ core ⊂ standard，保证升档只加不减。
_PROFILE_TOOLSETS: dict[str, list[str]] = {
    # nano — 最后保底三件套
    "nano": [
        "toolkit_exec",
        "toolkit_file",
        "toolkit_edit",
    ],
    # minimal — 编码最小可用：+ diff（安全编辑）/search（查代码/网络）/question（澄清）
    "minimal": [
        "toolkit_exec",
        "toolkit_file",
        "toolkit_edit",
        "toolkit_diff",
        "toolkit_search",
        "toolkit_question",
    ],
    # core — 编码闭环 + 轻量编排（对齐 onlinesession.CORE_TOOLS 编码子集）
    "core": [
        "toolkit_exec",
        "toolkit_file",
        "toolkit_edit",
        "toolkit_diff",
        "toolkit_search",
        "toolkit_lsp",
        "toolkit_question",
        "toolkit_todo",
        "toolkit_plan",
        "toolkit_memory",
        "toolkit_kb",
        "toolkit_config",
        "toolkit_mode",
    ],
    # standard — 核心集(CORE_TOOLS) + 开发高频集
    "standard": [
        "toolkit_exec",
        "toolkit_file",
        "toolkit_edit",
        "toolkit_diff",
        "toolkit_search",
        "toolkit_lsp",
        "toolkit_question",
        "toolkit_todo",
        "toolkit_plan",
        "toolkit_memory",
        "toolkit_kb",
        "toolkit_config",
        "toolkit_mode",
        "toolkit_subagent",
        "toolkit_subagent_msg",
        "toolkit_save",
        "toolkit_reload",
        "toolkit_rollback",
        "toolkit_list_versions",
        # ── 开发高频工具 ──
        "toolkit_batch_process",
        "toolkit_format_code",
        "toolkit_code_review",
        "toolkit_run_tests",
        "toolkit_build",
        "toolkit_publish_doc",
        "toolkit_task_resume",
        "toolkit_custom_commands",
        "toolkit_self_evolve",
    ],
}

# 冻结为 set，避免运行时被改动（full=None 不过滤）
PROFILE_TOOLS: dict[str, frozenset[str] | None] = {
    name: (frozenset(tools) if name != "full" else None)
    for name, tools in list(_PROFILE_TOOLSETS.items()) + [("full", [])]
}


def resolve_tool_profile(
    max_context_tokens: int | None,
    explicit: str = "auto",
) -> str:
    """解析生效的工具档位。

    Args:
        max_context_tokens: 模型最大上下文 token 数；<=0/None 视为未配置
        explicit: 显式档位（auto=按窗口推导；其余须为 PROFILE_NAMES 合法档位）

    Returns:
        生效档位名（full/standard/core/minimal/nano）
    """
    name = (explicit or "auto").strip().lower()
    if name != "auto":
        if name in PROFILE_NAMES:
            return name
        logger.warning(f"未知 tool_profile={explicit!r}，回退 auto")
        name = "auto"

    ctx = int(max_context_tokens or 0)
    if ctx <= 0:
        # 窗口未知：保守全量（能力优先）。若真为小窗口，请配置 max_context_tokens
        # 或显式 tool_profile，避免误裁。
        logger.debug("max_context_tokens 未配置，tool_profile 保守回退 full")
        return UNKNOWN_CTX_PROFILE

    for lower, profile in PROFILE_THRESHOLDS:
        if ctx >= lower:
            return profile
    return "nano"


def filter_tools_by_profile(
    tools: list[dict],
    profile: str,
) -> list[dict]:
    """按档位过滤工具定义列表。

    Args:
        tools: 全量工具定义（build_tools() 输出）
        profile: 生效档位名（full=不过滤）

    Returns:
        过滤后的工具列表（保持原顺序）
    """
    if not tools:
        return tools
    allowed = PROFILE_TOOLS.get(profile)
    if allowed is None:  # full 或未知档位：不过滤
        return tools
    return [
        t for t in tools
        if t.get("function", {}).get("name") in allowed
    ]
