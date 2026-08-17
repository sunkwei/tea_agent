# version: 1.3.0
"""
Agent 后台服务模块

从 agent.py 提取的后台服务启动逻辑：
- 定时任务调度器
- 打断知识闭环 M3/M4: 打断模式后台分析（聚合 → preference 记忆沉淀）
"""

import logging
import threading

logger = logging.getLogger("agent.background")

# M3: 打断模式分析默认配置（可由 config.yaml interruption.* 覆盖）
_INTERRUPT_ANALYZE_INTERVAL_H = 1.0  # 分析周期（小时）
_INTERRUPT_ANALYZE_MIN_COUNT = 2     # 同一工具打断 ≥ 2 次才沉淀
_INTERRUPT_SKILL_MIN_COUNT = 3       # 同一工具打断 ≥ 3 次才生成行为指导 skill
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


def _skill_name_for_tool(tool: str) -> str:
    """工具名 → skill 名：toolkit_exec → interrupt-avoid-exec。"""
    suffix = tool.removeprefix("toolkit_").replace("_", "-")
    return f"interrupt-avoid-{suffix}"


def _default_skills_dir() -> str:
    """用户级 skills 目录（与 toolkit_skills 存储一致）。"""
    import os
    return os.path.join(os.path.expanduser("~"), ".tea_agent", "skills")


def _ensure_interruption_skill(skills_dir: str, tool: str, count: int) -> str | None:
    """M5: 高频打断模式 → 主动生成行为指导 SKILL.md（幂等）。

    当同一工具打断次数达到 skill 阈值时，生成一个让 Agent 在执行
    该类工具链前「先计划、勤汇报、早确认」的被动技能包。
    - 幂等：同名 SKILL.md 已存在则跳过（不覆盖人工/历史修改）
    - 仅生成 skill 文件（被动加载），不修改任何运行逻辑（安全边界）

    Returns:
        SKILL.md 路径；已存在或失败返回 None
    """
    import os

    name = _skill_name_for_tool(tool)
    skill_dir = os.path.join(skills_dir, name)
    skill_file = os.path.join(skill_dir, "SKILL.md")
    if os.path.isfile(skill_file):
        return None  # 幂等：已存在

    description = (
        f"用户在使用 {tool} 时曾多次被打断（{count} 次，打断知识闭环统计）。"
        f"执行涉及 {tool} 的任务前先输出计划摘要并确认方向。"
    )
    front = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "tags: [interruption, behavior, self-evolve]\n"
        "category: self-evolve\n"
        "version: 1.0.0\n"
        "author: tea_agent\n"
        "disable-model-invocation: false\n"
        "---\n"
    )
    body = (
        f"# 打断规避：{tool}\n\n"
        f"## 触发背景\n"
        f"用户在使用 `{tool}` 时被打断 {count} 次（打断知识闭环统计）。"
        f"打断 = 隐式否定信号：该工具路径曾不符合用户预期。\n\n"
        f"## 行为准则\n"
        f"1. 涉及 `{tool}` 的多步骤任务，先输出 2-3 行计划摘要再执行。\n"
        f"2. 每个关键步骤完成后简要汇报进展，避免闷头长链执行。\n"
        f"3. 若执行结果可能不符合预期，先给结论让用户确认再展开细节。\n"
        f"4. 该工具路径曾被多次打断，默认视为需优先确认方向。\n\n"
        f"## 适用场景\n"
        f"- 用户要求使用 {tool} 完成任务时\n"
    )
    try:
        os.makedirs(skill_dir, exist_ok=True)
        with open(skill_file, "w", encoding="utf-8") as f:
            f.write(front + body)
        logger.info(f"[InterruptionKnowledge] 已生成打断规避技能: {name} (count={count})")
        return skill_file
    except Exception:
        logger.exception(f"生成打断规避技能失败: {name}")
        return None


def analyze_interruptions(
    storage=None,
    days: int = 7,
    min_count: int = _INTERRUPT_ANALYZE_MIN_COUNT,
    skill_min_count: int | None = None,
    skills_dir: str | None = None,
) -> list[str]:
    """M3/M5: 聚合打断模式 → 沉淀 preference 记忆 + 生成行为指导 skill。

    查询已分类（classified）的打断事件，按 tool_name 聚合，两级处理：
    - 同一工具打断 ≥ min_count 次 → 写入 preference 记忆（tags=interruption,tool:<name>）
    - 同一工具打断 ≥ skill_min_count 次 → 主动生成「打断规避」SKILL.md（M5，闭环最后一公里）
    两者均幂等（已有记忆/已有同名 skill 则跳过），只产出偏好，不自动改 prompt。

    Args:
        storage: Storage 实例；None 时用全局单例
        days: 统计窗口（天），仅用于提示文案
        min_count: 记忆沉淀阈值
        skill_min_count: skill 生成阈值；None 时读配置（默认 3）
        skills_dir: skill 输出目录；None 时用 ~/.tea_agent/skills

    Returns:
        list[str]: 本次新写入的记忆内容 / 生成的 skill 路径（幂等时为空列表）
    """
    try:
        from tea_agent.store import get_storage
        if storage is None:
            storage = get_storage()
        if skill_min_count is None:
            skill_min_count = int(_get_icfg().get("skill_min_count", _INTERRUPT_SKILL_MIN_COUNT))
        if skills_dir is None:
            skills_dir = _default_skills_dir()

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
            # M3: 幂等去重——已有该工具的打断偏好记忆则跳过
            existing = storage.memories.search_memories(
                category="preference", tags=[f"tool:{tool}"], limit=5
            )
            if not existing:
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

            # M5: 持续高频（≥ skill 阈值）→ 主动生成行为指导 skill
            if cnt >= skill_min_count:
                path = _ensure_interruption_skill(skills_dir, tool, cnt)
                if path:
                    name = _skill_name_for_tool(tool)
                    # 记录 skill 生成事件（可追踪，幂等由 SKILL.md 存在性保证）
                    storage.memories.add_memory(
                        content=(
                            f"[打断规避技能] 已自动生成技能 {name}（tool={tool}, count={cnt}），"
                            f"后续涉及 {tool} 的任务将按技能准则先计划、勤汇报、早确认。"
                        ),
                        category="preference",
                        priority=1,
                        importance=3,
                        tags=f"interruption,skill:{name}",
                    )
                    written.append(f"[skill] {path}")
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

    # dispose 静止态：stop_event 供外部优雅停止（kill → await done）
    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                from tea_agent.store import get_storage

                _cleanup_old_events(get_storage())
                icfg = _get_icfg()
                analyze_interruptions(
                    days=7,
                    min_count=int(icfg.get("min_count", _INTERRUPT_ANALYZE_MIN_COUNT)),
                    skill_min_count=int(icfg.get("skill_min_count", _INTERRUPT_SKILL_MIN_COUNT)),
                )
            except Exception:
                logger.exception("interruption analyzer iteration failed")
            # 可中断睡眠：stop_event 置位时立即退出，不等待剩余间隔
            stop_event.wait(max(0.1, interval_h) * 3600)

    try:
        t = threading.Thread(target=_loop, name="interruption-analyzer", daemon=True)
        t.stop = stop_event.set  # type: ignore[attr-defined]  # 停止句柄
        t.stopped = stop_event.is_set  # type: ignore[attr-defined]  # 静止态查询
        t.start()
        logger.info(f"打断模式分析线程已启动 (interval={interval_h}h)")
        return t
    except Exception as e:
        logger.debug(f"打断模式分析线程启动失败: {e}")
        return None


def stop_interruption_analyzer(thread: threading.Thread | None, timeout: float = 5.0) -> bool:
    """停止后台分析线程并等待其到达静止态（dispose 语义）。

    防御模式：Dispose must reach quiescence, not just request it。
    kill → await done：先置位 stop_event，再 join 等待线程退出；
    超时返回 False（不阻塞调用方）。

    Args:
        thread: start_interruption_analyzer 返回的线程
        timeout: 最大等待秒数

    Returns:
        线程是否已到达静止态（退出）
    """
    if thread is None or not thread.is_alive():
        return True
    try:
        stop = getattr(thread, "stop", None)
        if callable(stop):
            stop()
        thread.join(timeout=timeout)
        return not thread.is_alive()
    except Exception:
        logger.exception("stop_interruption_analyzer failed")
        return False
