# version: 1.3.0
"""
Agent 后台服务模块

从 agent.py 提取的后台服务启动逻辑：
- 定时任务调度器
- 打断知识闭环 M3/M4: 打断模式后台分析（聚合 → preference 记忆沉淀）
"""

import logging
import threading
import time

logger = logging.getLogger("agent.background")

# M3: 打断模式分析默认配置（可由 config.yaml interruption.* 覆盖）
_INTERRUPT_ANALYZE_INTERVAL_H = 1.0  # 分析周期（小时）
_INTERRUPT_ANALYZE_MIN_COUNT = 2     # 同一工具打断 ≥ 2 次才沉淀
_INTERRUPT_KEEP_DAYS = 30            # 事件保留天数（超期清理）


def _get_icfg() -> dict:
    """读取 interruption.* 配置（失败返回空 dict 走默认值）。"""
    try:
        from tea_agent.config import get_config

        return get_config().interruption or {}
    except Exception:
        return {}


def start_scheduler() -> bool:
    """启动定时任务调度器 daemon 线程。

    Returns:
        是否成功启动
    """
    try:
        from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
        toolkit_scheduler("start")
        # M3/M4: 同时启动打断模式后台分析（daemon 线程，不阻塞）
        start_interruption_analyzer()
        return True
    except Exception as e:
        logger.debug(f"定时任务调度器启动跳过: {e}")
    return False


def analyze_interruptions(storage=None, days: int = 7, min_count: int = _INTERRUPT_ANALYZE_MIN_COUNT) -> list[str]:
    """M3: 聚合打断模式并沉淀为 preference 记忆。

    查询已分类（classified）的打断事件，按 tool_name 聚合：
    - 同一工具打断 ≥ min_count 次 → 写入 preference 记忆（tags=interruption,tool:<name>）
    - 幂等：已有同类记忆（tags 含 tool:<name>）则跳过，不重复沉淀
    - 只产出偏好记忆，不自动修改 prompt（符合自进化安全边界）

    Args:
        storage: Storage 实例；None 时用全局单例
        days: 统计窗口（天），仅用于提示文案
        min_count: 沉淀阈值

    Returns:
        list[str]: 本次新写入的记忆内容（幂等时为空列表）
    """
    try:
        from tea_agent.store import get_storage
        if storage is None:
            storage = get_storage()
        evs = storage.query_interruptions(status="classified")
        if not evs:
            return []
        # 按 tool_name 聚合
        tool_counts: dict[str, int] = {}
        for ev in evs:
            tool = (ev.get("tool_name") or "").strip()
            if tool:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1

        written: list[str] = []
        for tool, cnt in sorted(tool_counts.items(), key=lambda x: -x[1]):
            if cnt < min_count:
                continue
            # 幂等去重：已有该工具的打断偏好记忆则跳过
            existing = storage.memories.search_memories(
                category="preference", tags=[f"tool:{tool}"], limit=5
            )
            if existing:
                continue
            content = (
                f"[打断模式] 用户在使用工具 {tool} 时被打断 {cnt} 次（近 {days} 天）。"
                f"这暗示涉及 {tool} 的工具链路径可能不符合用户预期，"
                f"建议优先确认方向或直接给出结论，避免长链路执行。"
            )
            storage.memories.add_memory(
                content=content,
                category="preference",
                priority=2,
                importance=3,
                tags=f"interruption,tool:{tool}",
            )
            written.append(content)
            logger.info(f"[InterruptionKnowledge] 沉淀打断模式记忆: tool={tool}, count={cnt}")
        return written
    except Exception:
        logger.exception("analyze_interruptions failed")
        return []


def _cleanup_old_events(storage) -> None:
    """M4: 清理超过保留期的旧打断事件（幂等，失败仅记日志）。"""
    keep_days = int(_get_icfg().get("keep_days", _INTERRUPT_KEEP_DAYS))
    try:
        deleted = storage.interruptions.cleanup_old_events(keep_days=keep_days)
        if deleted:
            logger.info(f"[InterruptionKnowledge] 清理过期打断事件 {deleted} 条 (keep_days={keep_days})")
    except Exception:
        logger.exception("cleanup old interruption events failed")


def start_interruption_analyzer(
    interval_h: float | None = None,
) -> threading.Thread | None:
    """启动打断模式后台分析 daemon 线程（M3/M4）。

    每 interval_h 小时运行一次：先清理过期事件，再 analyze_interruptions()。
    仅对已分类事件聚合，失败仅记日志不冒泡。
    M4: interval_h 默认从配置 interruption.analyze_interval_h 读取。

    Args:
        interval_h: 分析间隔（小时）；None 时读配置（默认 1h）

    Returns:
        启动的线程对象；失败返回 None
    """
    if interval_h is None:
        try:
            interval_h = float(_get_icfg().get("analyze_interval_h", _INTERRUPT_ANALYZE_INTERVAL_H))
        except Exception:
            interval_h = _INTERRUPT_ANALYZE_INTERVAL_H

    def _loop():
        while True:
            try:
                from tea_agent.store import get_storage

                _cleanup_old_events(get_storage())
                analyze_interruptions(days=7, min_count=_INTERRUPT_ANALYZE_MIN_COUNT)
            except Exception:
                logger.exception("interruption analyzer iteration failed")
            time.sleep(max(0.1, interval_h) * 3600)

    try:
        t = threading.Thread(target=_loop, name="interruption-analyzer", daemon=True)
        t.start()
        logger.info(f"打断模式分析线程已启动 (interval={interval_h}h)")
        return t
    except Exception as e:
        logger.debug(f"打断模式分析线程启动失败: {e}")
        return None
