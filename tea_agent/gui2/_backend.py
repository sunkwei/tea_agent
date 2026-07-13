"""
Backend Bridge — Python↔QML 桥接层。

在 QML 中以 `backend` 上下文属性暴露以下接口：

属性:
    backend.messages     : list<dict>   — 当前会话消息列表
    backend.topics       : list<dict>   — 主题列表
    backend.currentTopic : str          — 当前主题 ID
    backend.statusText   : str          — 状态栏文本

方法 (QML 可调用):
    backend.sendMessage(text)       — 发送用户消息
    backend.loadTopic(topicId)      — 加载指定主题
    backend.newTopic()              — 新建主题
    backend.interrupt()             — 中断生成

信号 (QML 可连接):
    backend.messagesChanged()       — 消息列表更新
    backend.thinkUpdated(text)      — 思考过程流式更新
    backend.streamUpdated(text)     — 回复流式更新
    backend.statusChanged(text)     — 状态变更
    backend.topicsChanged()         — 主题列表变更
    backend.errorOccurred(msg)      — 错误通知
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal, Slot, Property

logger = logging.getLogger(__name__)


class BackendBridge(QObject):
    """QML 后端桥接 — 管理 Agent 会话、消息、主题。

    使用 QObject 信号/槽机制，所有与 QML 的交互都是线程安全的。
    """

    # ── 信号 ──────────────────────────────────────────────
    messagesChanged = Signal()          # 消息列表变化
    thinkUpdated = Signal(str)          # 思考过程流式文本
    streamUpdated = Signal(str)         # AI 回复流式文本
    statusChanged = Signal(str)         # 状态栏文本
    topicsChanged = Signal()            # 主题列表变化
    errorOccurred = Signal(str)         # 错误信息
    scrollToBottom = Signal()           # 通知 QML 滚动到底部

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: List[dict] = []
        self._topics: List[dict] = []
        self._current_topic_id: str = ""
        self._status_text: str = "就绪"
        self._agent = None
        self._agent_ready = False
        self._generating = False
        self._think_buffer = ""
        self._stream_buffer = ""

        # _lock 用于跨线程保护消息列表
        self._lock = threading.Lock()

    # ── 初始化 ────────────────────────────────────────────

    @Slot()
    def initialize(self):
        """初始化后端：加载 Agent 配置、刷新主题列表。"""
        self._update_status("正在初始化...")
        try:
            # 延迟导入，避免 QML 加载时阻塞
            from tea_agent.config import load_config
            from tea_agent.agent import Agent

            # 加载配置（load_config 自动处理 _active_config_path）
            self._cfg = load_config()

            # 创建 Agent
            self._agent = Agent()
            self._agent_ready = True

            self._update_status("✅ 就绪")
            self.refresh_topics()

            # 检查 TODO 恢复
            self._check_task_resume()

            logger.info("Backend initialized successfully")
        except Exception as e:
            logger.error(f"Backend init failed: {e}", exc_info=True)
            self._update_status(f"❌ 初始化失败: {e}")
            self.errorOccurred.emit(str(e))

    def _check_task_resume(self):
        """检查是否有未完成的任务需要恢复提示。"""
        try:
            from tea_agent._gui._markdown import _chat_to_markdown
            # 简单的恢复提示
            notice = (
                "💡 欢迎使用 Tea Agent Qt 界面！\n\n"
                "输入消息开始对话，或从左侧选择历史主题继续。"
            )
            self._add_message("notice", notice)
        except Exception:
            pass

    # ── 消息管理 ──────────────────────────────────────────

    @Slot(str)
    def send_message(self, text: str):
        """发送用户消息。"""
        if not text or not text.strip():
            return
        if self._generating:
            self._update_status("⏳ 正在生成中，请等待...")
            return

        text = text.strip()
        self._add_message("user", text)
        self.statusChanged.emit("🤔 思考中...")
        self._generating = True
        self._think_buffer = ""
        self._stream_buffer = ""

        # 在后台线程运行 Agent 推理
        threading.Thread(target=self._run_agent, args=(text,), daemon=True).start()

    def _run_agent(self, user_text: str):
        """在后台线程运行 Agent。"""
        try:
            response = self._agent.run(
                user_text,
                on_think=lambda t: self._on_think(t),
                on_stream=lambda s: self._on_stream(s),
                on_tool=lambda t: self._on_tool(t),
            )
            self._on_agent_done(response)
        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            self.errorOccurred.emit(f"Agent 错误: {e}")
            self._on_agent_done(f"<p style='color:red'>⚠️ 错误: {e}</p>")

    def _on_think(self, text: str):
        """思考过程回调（可在任何线程调用）。"""
        self._think_buffer += text
        self.thinkUpdated.emit(self._think_buffer)

    def _on_stream(self, text: str):
        """流式文本回调。"""
        self._stream_buffer += text
        self.streamUpdated.emit(self._stream_buffer)

    def _on_tool(self, tool_info: dict):
        """工具调用回调。"""
        # 将工具调用信息格式化为工具消息
        name = tool_info.get("name", "unknown")
        params = tool_info.get("params", {})
        status = tool_info.get("status", "running")
        icon = "⚡" if status == "running" else ("✅" if status == "success" else "❌")

        content = f"🔧 调用工具：{name}\n参数：\n{params}"
        if status != "running":
            content += f"\n{icon} 结果：{tool_info.get('result', '')}"

        with self._lock:
            self._messages.append({
                "role": "tool",
                "content": content,
                "timestamp": self._now_ts(),
            })

        self.messagesChanged.emit()
        self.scrollToBottom.emit()

    def _on_agent_done(self, final_text: str):
        """Agent 生成完成。"""
        # 先 flush 思考缓冲
        if self._think_buffer.strip():
            self._add_message("think", self._think_buffer.strip())
            self._think_buffer = ""

        # 添加 AI 回复
        if self._stream_buffer.strip() or final_text:
            content = self._stream_buffer.strip() or final_text
            self._add_message("ai", content)
            self._stream_buffer = ""

        self._generating = False
        self._update_status("✅ 就绪")
        self.scrollToBottom.emit()

    def _add_message(self, role: str, content: str):
        """线程安全地添加消息。"""
        with self._lock:
            self._messages.append({
                "role": role,
                "content": content,
                "timestamp": self._now_ts(),
            })
        self.messagesChanged.emit()

    # ── 主题管理 ──────────────────────────────────────────

    @Slot()
    def refresh_topics(self):
        """刷新主题列表。"""
        try:
            from tea_agent.store import Storage as _Storage
            store = _Storage()
            topics = store.list_topics()
            self._topics = [
                {
                    "id": t["topic_id"],
                    "title": t.get("title", ""),
                    "updated": str(t.get("last_update_stamp", "")),
                }
                for t in topics if isinstance(t, dict)
            ]
            self.topicsChanged.emit()
        except Exception as e:
            logger.warning(f"Refresh topics failed: {e}")

    @Slot(str)
    def load_topic(self, topic_id: str):
        """加载指定主题的对话历史。"""
        self._update_status(f"📂 加载主题 {topic_id[:8]}...")
        try:
            from tea_agent.store import Storage as _Storage
            store = _Storage()
            convs = store.get_conversations(topic_id)
            # convs: list of dicts with {id, topic_id, user_msg, ai_msg, stamp, rounds_json_parsed}
            with self._lock:
                self._messages.clear()
                for c in convs:
                    # 用户消息
                    if c.get("user_msg"):
                        self._messages.append({
                            "role": "user",
                            "content": c["user_msg"],
                            "timestamp": str(c.get("stamp", "")),
                        })
                    # 工具调用轮次（如果有）
                    rounds = c.get("rounds_json_parsed") or []
                    for r in rounds:
                        role = r.get("role", "ai")
                        content = r.get("content", "") or ""
                        # 如果有 tool_calls，格式化显示
                        tool_calls = r.get("tool_calls") or []
                        tc_text = ""
                        for tc in tool_calls:
                            fn = tc.get("function", {})
                            tc_text += f"🔧 调用工具：{fn.get('name', 'unknown')}\n参数：{fn.get('arguments', {})}\n\n"
                        if tc_text:
                            self._messages.append({
                                "role": "tool",
                                "content": tc_text.strip(),
                                "timestamp": "",
                            })
                        if content.strip():
                            self._messages.append({
                                "role": "ai" if role == "assistant" else role,
                                "content": content,
                                "timestamp": "",
                            })
                    # AI 回复（如果没有工具调用轮次）
                    ai_msg = c.get("ai_msg", "") or ""
                    if ai_msg.strip() and not any(
                        r.get("role") == "assistant" and r.get("content") == ai_msg
                        for r in rounds
                    ):
                        self._messages.append({
                            "role": "ai",
                            "content": ai_msg,
                            "timestamp": str(c.get("stamp", "")),
                        })
            self._current_topic_id = topic_id
            self.messagesChanged.emit()
            self._update_status(f"📂 已加载 {len(convs)} 轮对话")
            self.scrollToBottom.emit()
        except Exception as e:
            logger.error(f"Load topic {topic_id} failed: {e}")
            self.errorOccurred.emit(f"加载主题失败: {e}")
            self._update_status("❌ 加载失败")

    @Slot()
    def new_topic(self):
        """新建空白主题。"""
        with self._lock:
            self._messages.clear()
            self._current_topic_id = ""
        self.messagesChanged.emit()
        self._update_status("📝 新主题")
        self._add_message("notice", "📝 新对话开始，输入消息吧")

    @Slot()
    def interrupt(self):
        """中断当前生成。"""
        if self._agent and self._generating:
            try:
                self._agent.interrupt()
                self._generating = False
                self._update_status("⏹ 已中断")
            except Exception as e:
                logger.warning(f"Interrupt failed: {e}")

    # ── 属性暴露给 QML ────────────────────────────────────

    @Slot(result=list)
    def get_messages(self) -> list:
        """返回当前消息列表（QML 可调用）。"""
        with self._lock:
            return list(self._messages)

    messages = Property(list, get_messages, notify=messagesChanged)

    @Slot(result=list)
    def get_topics(self) -> list:
        return list(self._topics)

    topics = Property(list, get_topics, notify=topicsChanged)

    # ── 状态 ──────────────────────────────────────────────

    def _update_status(self, text: str):
        self._status_text = text
        self.statusChanged.emit(text)

    @Slot(result=str)
    def get_status(self) -> str:
        return self._status_text

    statusText = Property(str, get_status, notify=statusChanged)

    @Slot(result=bool)
    def is_generating(self) -> bool:
        return self._generating

    generating = Property(bool, is_generating, notify=statusChanged)

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _now_ts() -> str:
        return datetime.now().strftime("%H:%M:%S")

    @Slot()
    def cleanup(self):
        """清理资源。"""
        if self._agent:
            try:
                self._agent.close()
            except Exception:
                pass
