"""工具风险分级 + 审批闸门 + 审计接线（A2/A3 安全底座）。

对齐 DeepSeek Harness 工具执行流水线：
    pre-execute 瀑布(审批/权限/沙箱) → guards → approval(缺失=拒绝) → execute → post-execute

三档模式（config security.approval_mode 或环境变量 TEA_APPROVAL_MODE）：
- **off**（默认）  : 全部放行，仅审计高风险动作（保持 Tea Agent「自由奔放」哲学）
- **advisory**     : 全部放行，但对需审批的动作打标 `approval: required`（可观测、不阻断）
- **enforce**      : 高风险动作**缺失审批即拒绝**（一次性 token / 持久授权名单 / 环境变量）

授权来源（enforce 模式，任一命中即放行）：
1. 环境变量 ``TEA_APPROVAL_TOKEN`` 非空
2. ``<项目>/.tea_agent_run/approval_token`` 文件非空
3. ``<项目>/.tea_agent_run/approval_allow.json`` 名单包含该工具名
4. 运行时调用 ``toolkit_approve(action='grant', tool='toolkit_exec')``

与其他模块的关系：
- 审计（tea_agent.audit_log）：所有高风险动作 pre/post 双记录，hash 链防篡改
- hook 系统（tea_agent.tool_hooks）：本模块以 pre/post hook 形式挂载，
  覆盖 lite 与 online 两条工具执行路径，无需改动会话代码
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("tea_agent.approval")

__all__ = [
    "RISK_LEVELS",
    "approval_mode",
    "classify_risk",
    "install_builtin_hooks",
    "make_pre_hook",
    "make_post_hook",
    "grant",
    "revoke",
    "grants",
    "is_granted",
    "approval_status",
]

RISK_LEVELS: dict[str, int] = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# enforce 模式下需要审批的最低风险档（默认 high）
_DEFAULT_REQUIRE_AT = "high"

# 需审批工具自身豁免（否则无法完成授权动作）
_EXEMPT_TOOLS = {"toolkit_approve", "toolkit_audit_log"}

_MODE_ENV = "TEA_APPROVAL_MODE"
_TOKEN_ENV = "TEA_APPROVAL_TOKEN"
_VALID_MODES = ("off", "advisory", "enforce")

# 高风险工具集合（含动作级细分见 classify_risk）
_CRITICAL_TOOLS = {"toolkit_sudo_gui", "toolkit_self_evolve"}
_HIGH_TOOLS = {
    "toolkit_save", "toolkit_rollback", "toolkit_prompt_evolve", "toolkit_reload",
    "toolkit_config", "toolkit_send_email", "toolkit_scheduler",
    "toolkit_remote_agent", "toolkit_subagent",
}
_MEDIUM_TOOLS = {
    "toolkit_edit", "toolkit_diff", "toolkit_batch_process", "toolkit_format_code",
    "toolkit_pkg", "toolkit_mcp", "toolkit_fork_session", "toolkit_topic_prompt",
    "toolkit_build", "toolkit_release_version",
}

# 写盘类动作（按 args 判定）
_WRITE_ACTIONS = {"write", "append", "apply", "replace", "format", "set", "delete", "forget"}


def _run_dir() -> str | None:
    """项目运行目录（必要时创建）；不可用时回退 None。"""
    try:
        from tea_agent.storage_scope import project_run_dir

        return project_run_dir()
    except Exception:  # noqa: BLE001
        return None


def approval_mode() -> str:
    """解析审批模式：环境变量 > config security.approval_mode > off（默认）。"""
    env = os.environ.get(_MODE_ENV, "").strip().lower()
    if env in _VALID_MODES:
        return env
    try:
        from tea_agent.config import get_config

        cfg = get_config()
        raw = getattr(cfg, "security", None)
        val = None
        if isinstance(raw, dict):
            val = raw.get("approval_mode")
        elif raw is not None:
            val = getattr(raw, "approval_mode", None)
        if isinstance(val, str) and val.strip().lower() in _VALID_MODES:
            return val.strip().lower()
    except Exception:  # noqa: BLE001 — 配置不可用时保持默认
        pass
    return "off"


def _require_at() -> str:
    """enforce 模式的审批阈值档（默认 high）。"""
    try:
        from tea_agent.config import get_config

        raw = getattr(get_config(), "security", None)
        val = None
        if isinstance(raw, dict):
            val = raw.get("approval_require_at")
        elif raw is not None:
            val = getattr(raw, "approval_require_at", None)
        if isinstance(val, str) and val.strip().lower() in RISK_LEVELS:
            return val.strip().lower()
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_REQUIRE_AT


# ── 风险分级 ──────────────────────────────────────────────────────

def classify_risk(tool_name: str, args: dict | None = None) -> tuple[str | None, str]:
    """对工具调用做确定性风险分级。

    Args:
        tool_name: 工具名（toolkit_* 前缀）
        args: 调用参数

    Returns:
        (level, reason)：level ∈ {None, 'low', 'medium', 'high', 'critical'}
        level 为 None 表示无需审计、无需审批
    """
    args = args or {}
    name = (tool_name or "").strip()
    if name in _EXEMPT_TOOLS:
        return None, "豁免工具"

    if name in _CRITICAL_TOOLS:
        return "critical", "可修改自身代码/提升权限"

    if name == "toolkit_exec":
        app = str(args.get("app", "")).lower()
        # 破坏性命令检测须覆盖 app 本身：仅扫描 args 会漏判 `rm -rf /`
        # （args=['-rf','/'] 拼出 "-rf /"，匹配不到 "rm -rf /" 标记）
        joined = (app + " " + " ".join(str(a) for a in (args.get("args") or [])))[:200].lower()
        denied_markers = ("rm -rf /", "mkfs", "dd if=", ":(){:", "format c:", "del /f /s /q c:")
        if any(m in joined for m in denied_markers):
            return "critical", "疑似破坏性命令"
        if app in ("sudo", "su", "pkexec", "shutdown", "reboot") or "sudo" in app:
            return "critical", "提权/系统级命令"
        if app in ("git", "pip", "npm", "python", "python3", "pytest", "docker") or args.get("action") == "batch":
            return "high", "执行系统命令（可变更文件系统/环境）"
        return "medium", "执行外部程序"

    if name == "toolkit_file":
        action = str(args.get("action", "read")).lower()
        if action in _WRITE_ACTIONS:
            return "medium", f"写入文件（action={action}）"
        return None, "只读操作"

    if name in _HIGH_TOOLS:
        return "high", "变更工具/配置/对外发送"
    if name in _MEDIUM_TOOLS:
        action = str(args.get("action", "")).lower()
        if name in ("toolkit_batch_process", "toolkit_diff", "toolkit_format_code", "toolkit_pkg") \
                and action and action not in _WRITE_ACTIONS and action not in ("apply", "format", "install", "ensure", "lint", "compile"):
            return "low", f"低风险子动作（action={action}）"
        return "medium", "可能修改工作区"

    return None, "常规工具"


# ── 授权管理 ──────────────────────────────────────────────────────

def _allow_path() -> str | None:
    d = _run_dir()
    return os.path.join(d, "approval_allow.json") if d else None


def grants() -> dict:
    """读取持久授权名单（结构：{'tools': [...], 'note': str}）。"""
    path = _allow_path()
    if not path or not os.path.exists(path):
        return {"tools": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("tools"), list):
            return data
        if isinstance(data, list):
            return {"tools": data}
    except (OSError, ValueError):
        logger.debug("approval: 授权名单读取失败")
    return {"tools": []}


def _write_grants(data: dict) -> bool:
    path = _allow_path()
    if not path:
        return False
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        logger.debug("approval: 授权名单写入失败")
        return False


def grant(tool: str, note: str = "") -> dict:
    """持久授权某工具（enforce 模式下放行）。"""
    tool = (tool or "").strip()
    if not tool.startswith("toolkit_"):
        return {"ok": False, "error": "工具名须以 toolkit_ 开头"}
    data = grants()
    tools = set(data.get("tools") or [])
    tools.add(tool)
    data["tools"] = sorted(tools)
    if note:
        data["note"] = note
    ok = _write_grants(data)
    return {"ok": ok, "tool": tool, "grants": data["tools"]}


def revoke(tool: str) -> dict:
    """撤销某工具的持久授权。"""
    data = grants()
    tools = [t for t in (data.get("tools") or []) if t != tool]
    data["tools"] = tools
    ok = _write_grants(data)
    return {"ok": ok, "tool": tool, "grants": tools}


def _has_token() -> bool:
    """一次性/会话级审批 token 是否有效。"""
    if os.environ.get(_TOKEN_ENV, "").strip():
        return True
    d = _run_dir()
    if not d:
        return False
    try:
        with open(os.path.join(d, "approval_token"), encoding="utf-8") as f:
            return bool(f.read().strip())
    except OSError:
        return False


def is_granted(tool_name: str) -> bool:
    """该工具是否已被授权（token 或名单）。"""
    if _has_token():
        return True
    return tool_name in set(grants().get("tools") or [])


def approval_status() -> dict:
    """审批闸门当前状态（供 toolkit_audit_log / 诊断使用）。"""
    d = _run_dir()
    return {
        "mode": approval_mode(),
        "require_at": _require_at(),
        "token_present": _has_token(),
        "grants": grants().get("tools", []),
        "allow_file": _allow_path() if d else None,
        "env_mode": os.environ.get(_MODE_ENV, ""),
    }


# ── Hook 实现 ─────────────────────────────────────────────────────

def _audit(event: str, tool: str, phase: str = "", status: str = "",
           detail: Any = None, **extra: Any) -> None:
    """审计写入（失败静默，绝不阻断工具执行）。"""
    try:
        from tea_agent.audit_log import audit_log

        audit_log.record(event, tool=tool, phase=phase, status=status, detail=detail, **extra)
    except Exception as e:  # noqa: BLE001 — 审计不可用不得影响主流程
        logger.debug("audit 写入跳过: %s", e)


def make_pre_hook():
    """构造 pre-execute 钩子：风险分级 → 审计 → （enforce 时）审批决策。

    Returns:
        fn(tool_name, args) -> True | {'deny': True, 'reason': str}
    """
    def _pre(tool_name: str, args: dict):
        level, reason = classify_risk(tool_name, args)
        if level is None:
            return True

        mode = approval_mode()
        granted = is_granted(tool_name)
        require_at = RISK_LEVELS.get(_require_at(), 3)
        needs_approval = RISK_LEVELS.get(level, 0) >= require_at

        # 审计 pre 阶段（含审批决策痕迹）
        _audit(
            "tool/call", tool_name, phase="pre", status="pending",
            detail={"risk": level, "reason": reason, "mode": mode,
                    "args_preview": args, "granted": granted},
        )

        if mode != "enforce" or not needs_approval or granted:
            return True

        deny_reason = (
            f"⛔ 高风险工具需审批（risk={level}, mode=enforce）: {tool_name}\n"
            f"原因: {reason}\n"
            f"授权方式（任一）:\n"
            f"  1) 设置环境变量 {_TOKEN_ENV}=<任意非空值>\n"
            f"  2) 创建文件 .tea_agent_run/approval_token（非空内容）\n"
            f"  3) 调用 toolkit_approve(action='grant', tool='{tool_name}') 持久授权\n"
            f"  4) 临时放行: 设置 {_MODE_ENV}=advisory"
        )
        _audit("approval/deny", tool_name, phase="pre", status="denied",
               detail={"risk": level, "reason": reason, "mode": mode})
        logger.warning("approval denied: tool=%s risk=%s", tool_name, level)
        return {"deny": True, "reason": deny_reason}

    return _pre


def make_post_hook():
    """构造 post-execute 钩子：记录结果状态与耗时（若结果内提供）。"""
    def _post(tool_name: str, args: dict, result: Any):
        level, reason = classify_risk(tool_name, args)
        if level is None:
            return None

        status = "unknown"
        duration = None
        if isinstance(result, dict):
            if result.get("error") or result.get("ok") is False:
                status = "error"
            elif result.get("ok") is True:
                status = "ok"
            duration = result.get("duration_ms")
        elif isinstance(result, str):
            status = "error" if result.startswith(("错误", "工具执行错误", "⛔")) else "ok"

        _audit("tool/result", tool_name, phase="post", status=status,
               detail={"risk": level, "args_preview": args}, duration_ms=duration)
        return None

    return _post


def install_builtin_hooks(registry) -> bool:
    """把审批+审计钩子挂到给定 hook registry（幂等）。

    Args:
        registry: tea_agent.tool_hooks.ToolHookRegistry 实例

    Returns:
        本次是否新安装
    """
    if registry is None:
        return False
    if getattr(registry, "_builtin_installed", False):
        return False
    registry.register_pre("*", make_pre_hook())
    registry.register_post("*", make_post_hook())
    try:
        registry._builtin_installed = True
    except Exception:  # noqa: BLE001
        return False
    logger.debug("approval: 内建审批+审计钩子已挂载 (mode=%s)", approval_mode())
    return True
