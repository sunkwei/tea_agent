"""
@2026-07-07 gen by tea_agent, 后台服务启动 + 退出清理模块
从 gui.py 提取：Dream/Scheduler 启动 + 桌面通知 + 窗口关闭清理
"""

import tkinter as tk
import threading
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("main_db_gui")


class ServiceManager:
    """后台服务管理器：Dream、Scheduler 启动 + 退出清理 + 桌面通知"""

    def __init__(self, gui):
        self.gui = gui

    # ── Dream 潜意识引擎 ──────────────────
    # NOTE: 2026-06-19 gen by tea_agent, App启动自动启动Dream潜意识引擎
    def start_dream(self):
        """启动Dream潜意识引擎后台线程，每小时循环一次"""
        import os
        # 确保 cwd 为项目根目录，使 _is_tea_agent_cwd() 检查通过
        _proj_root = str(Path(__file__).resolve().parent.parent.parent)
        try:
            os.chdir(_proj_root)
        except Exception:
            pass
        try:
            from tea_agent.toolkit.toolkit_subconscious import toolkit_subconscious
            result = toolkit_subconscious("start")
            status = result.get("status", "unknown")
            if status == "rejected":
                logger.warning(f"Dream 未自动启动: {result.get('reason')}, cwd={os.getcwd()}")
            elif status == "already_running":
                logger.info(f"Dream 已在运行中 (pid={result.get('pid')})")
            else:
                logger.info(f"Dream 自动启动成功: {status}")
        except Exception as e:
            logger.warning(f"Dream 自动启动失败: {e}")

    # ── 定时任务调度器 ──────────────────
    # NOTE: 2026-05-16 gen by tea_agent, App启动自动启动定时任务调度器
    def start_scheduler(self):
        """启动定时任务调度器后台线程，每分钟检查一次"""
        try:
            from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
            result = toolkit_scheduler("start")
            status = result.get("status", "unknown")
            if status == "already_running":
                logger.info(f"定时任务调度器已在运行中 (pid={result.get('pid')})")
            else:
                logger.info(f"定时任务调度器自动启动成功: {status}")
        except Exception as e:
            logger.warning(f"定时任务调度器自动启动失败: {e}")

    # ── 退出清理 ──────────────────
    # NOTE: 2026-05-05, self-evolved by tea_agent --- 退出时正常关闭数据库：WAL checkpoint
    # NOTE: 2026-05-15 13:07:16, self-evolved by tea_agent --- _on_closing 添加托盘图标清理逻辑
    def on_closing(self):
        """窗口关闭时的清理流程"""
        self.gui._update_status("⏳ 正在清理资源...")
        # NOTE: 2026-05-18 gen by tea_agent, 退出时停止托盘图标
        try:
            self.gui.tray.stop()
            logger.info("托盘图标已停止")
        except Exception as e:
            logger.warning(f"停止托盘图标失败: {e}")
        # NOTE: 2026-06-19 gen by tea_agent, 退出时停止Dream线程
        try:
            from tea_agent.toolkit.toolkit_subconscious import toolkit_subconscious
            toolkit_subconscious("stop")
            logger.info("Dream 已停止")
        except Exception as e:
            logger.warning(f"停止 Dream 失败: {e}")
        # NOTE: 2026-05-16 gen by tea_agent, 退出时停止定时任务调度器
        try:
            from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
            toolkit_scheduler("stop")
            logger.info("定时任务调度器已停止")
        except Exception as e:
            logger.warning(f"停止定时任务调度器失败: {e}")
        try:
            self.gui.db.close()
            self.gui._update_status("✅ 数据库已正常关闭")
        except Exception as e:
            logger.warning(f"关闭数据库失败: {e}")
        self.gui.root.destroy()

    # ── 桌面通知 ──────────────────
    # NOTE: 2026-05-02 09:06:48, self-evolved by tea_agent --- 添加 _notify_completion 方法
    # NOTE: 2026-05-06 09:50:18, 修正通知格式
    def notify_completion(self, ai_msg: Optional[str] = None, user_msg: Optional[str] = None):
        """LLM 任务完成后发送桌面通知。通知内容: TeaAgent: {user_msg} + {ai_msg}。
        委托给 toolkit_notify（跨平台兼容：Windows/macOS/Linux）。"""
        # 构建通知消息
        if user_msg and ai_msg:
            u = user_msg.strip()
            a = ai_msg.strip()
            if len(u) > 20:
                u = u[:20] + "..."
            if len(a) > 40:
                a = a[:40] + "..."
            notification_msg = f"TeaAgent: {u} + {a}"
        elif ai_msg:
            notification_msg = ai_msg.strip()
            if len(notification_msg) > 60:
                notification_msg = notification_msg[:60] + "..."
            notification_msg = f"TeaAgent: {notification_msg}"
        else:
            notification_msg = "TeaAgent: AI 任务已完成"

        try:
            from tea_agent.toolkit.toolkit_notify import toolkit_notify
            toolkit_notify("TeaAgent", notification_msg, urgency="normal", duration=5000)
        except Exception:
            pass  # 通知失败不影响主流程