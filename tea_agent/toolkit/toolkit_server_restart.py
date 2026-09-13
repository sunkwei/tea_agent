# version: 1.0.0
"""
toolkit_server_restart — 让 Agent 在对话进行中安全地重启 server。

场景：server 需要自我更新（改了代码/配置）时，Agent 不必让用户手动重启；
本工具会安排一次「无感重启」——当前回合正常回答完，再换新进程。

两种模式：
    defer（默认）  优雅重启：置 draining（新回合改为排队）→ 等当前回合结束
                   （上限 wait_seconds）→ 旧进程退出释放端口 → 拉起新进程
                   （就绪探测 /health）。用户体感：这条答完，服务瞬间换成新的。
    immediate      立即重启：不等待在途回合，**当前回合会被切断**（仅供
                   卡死/失控等必须立刻重启的场景）。

配套保障（均在 server 侧实现，本工具只是触发器）：
    - 重启前登记在途快照（turn_snapshot），进程意外死亡时已产出内容可恢复；
    - 排队消息落盘（state._persist_queues），重启后由 restore_queues 还原；
    - 新进程启动时 rebuild_buffers 重建缓冲区，前端可续读。

输入：
    mode:         defer | immediate（默认 defer）
    wait_seconds: defer 模式下等待在途回合的上限秒数（默认 300）
    reason:       重启原因（仅记录，便于排查）

返回：
    {'ok': True, 'mode': ..., 'message': ..., 'wait_seconds': ...}
    或 {'ok': False, 'error': ...}
"""

import logging

logger = logging.getLogger("toolkit")


def toolkit_server_restart(mode: str = "defer", wait_seconds: float = 300,
                           reason: str = "") -> dict:
    """安排一次 server 重启（默认等当前回合结束后执行）。

    Args:
        mode: "defer"（优雅，等当前回合结束）或 "immediate"（立即，会切断回合）。
        wait_seconds: defer 模式下等待在途回合的上限秒数。
        reason: 重启原因（记录到日志，便于事后排查）。

    Returns:
        {'ok': True, ...} 表示已安排；{'ok': False, 'error': ...} 表示未安排。
    """
    mode_norm = (mode or "defer").strip().lower()
    logger.info("toolkit_server_restart called: mode=%r wait=%r reason=%r",
                mode_norm, wait_seconds, (reason or "")[:120])

    if mode_norm not in ("defer", "immediate"):
        return {"ok": False,
                "error": f"mode 仅支持 defer|immediate，收到 {mode!r}"}

    try:
        from tea_agent.server.server import restart_server
    except ImportError as e:
        return {"ok": False,
                "error": f"当前不在 server 进程中（server 模块不可用）：{e}"}

    try:
        wait = float(wait_seconds)
    except (TypeError, ValueError):
        wait = 300.0
    wait = max(0.0, wait)

    graceful = mode_norm == "defer"
    try:
        result = restart_server(graceful=graceful, wait_seconds=wait)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("server restart failed: %s", e)
        return {"ok": False, "error": f"重启失败：{e}"}

    if not result.get("ok"):
        # 常见：Server not running / Restart already in progress（幂等拒绝）
        return {"ok": False, "error": result.get("error", "restart rejected")}

    if graceful:
        note = ("已安排优雅重启：当前回合会正常回答完，随后自动换新进程。"
                "期间新消息会排队，不会丢失。")
    else:
        note = "已触发立即重启：当前回合可能被切断，前端将在服务恢复后续读。"
    if reason:
        note += f"（原因：{reason}）"

    return {"ok": True, "mode": mode_norm, "message": note,
            "wait_seconds": wait,
            "inflight_turns": result.get("inflight_turns"),
            "server_message": result.get("message", "")}


def meta_toolkit_server_restart() -> dict:
    """工具元描述（OpenAI function schema）。"""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_server_restart",
            "description": (
                "重启 tea_agent server（无感重启）。适用于：修改了 server 代码/配置后需要生效，"
                "或服务异常需要恢复。默认 mode=defer：等当前回合正常回答完再换新进程，"
                "新消息排队不丢失，用户几乎无感。仅当服务卡死/失控时才用 mode=immediate"
                "（会切断当前回合）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["defer", "immediate"],
                        "description": "defer=等当前回合结束再重启（默认，无感）；immediate=立即重启（会切断当前回合）",
                        "default": "defer",
                    },
                    "wait_seconds": {
                        "type": "number",
                        "description": "defer 模式下等待在途回合的上限秒数，默认 300",
                        "default": 300,
                    },
                    "reason": {
                        "type": "string",
                        "description": "重启原因（仅记录，便于排查），如「应用新配置」",
                    },
                },
                "required": [],
            },
        },
    }
