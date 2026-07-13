"""
[废弃] Backend Bridge — PySide6+QML 桥接层。

⚠️ 此文件已废弃，保留仅为代码参考。
请使用 tea_agent.gui2 的 Web 界面（Starlette + SSE）替代。
删除日期: 2026-07

在 QML 中以 `backend` 上下文属性暴露以下接口：

属性:
    backend.messages     : list<dict>   — 当前会话消息列表
    backend.topics       : list<dict>   — 主题列表
    backend.statusText   : str          — 状态栏文本

方法 (QML 可调用):
    backend.sendMessage(text)       — 发送用户消息
    backend.loadTopic(topicId)      — 加载指定主题
    backend.newTopic()              — 新建主题
    backend.getTopicsList()         — 获取主题列表
    backend.getMessagesList()       — 获取消息列表
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
from typing import List

from PySide6.QtCore import QObject, Signal, Slot, Property

logger = logging.getLogger(__name__)


class BackendBridge(QObject):
    """QML 后端桥接 — 管理 Agent 会话、消息、主题。"""

    # ── 信号 ──────────────────────────────────────────────
    messagesChanged = Signal()
    thinkUpdated = Signal(str)
    streamUpdated = Signal(str)
    statusChanged = Signal(str)
    topicsChanged = Signal()
    errorOccurred = Signal(str)
    scrollToBottom = Signal()

    def __init__(self, config_path: str | None = None, parent=None):
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
        self._cfg = None
        self._config_path = config_path
        self._lock = threading.Lock()

    # ── 初始化 ────────────────────────────────────────────

    @Slot()
    def initialize(self):
        """初始化后端：加载 Agent 配置、刷新主题列表。"""
        self._update_status("正在初始化...")
        try:
            from tea_agent.config import load_config
            from tea_agent.agent import Agent

            self._cfg = load_config(self._config_path)
            self._agent = Agent()
            self._agent_ready = True

            self._update_status("✅ 就绪")
            self.refresh_topics()
            self._check_task_resume()

            logger.info("Backend initialized successfully")
        except Exception as e:
            logger.error(f"Backend init failed: {e}", exc_info=True)
            self._update_status(f"❌ 初始化失败: {e}")
            self.errorOccurred.emit(str(e))

    def _check_task_resume(self):
        try:
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
        if not text or not text.strip():
            return
        if self._generating:
            self._update_status("⏳ 正在生成中，请等待...")
            return

        text = text.strip()
        self._add_message("user", text)
        self._update_status("🤔 思考中...")
        self._generating = True
        self._think_buffer = ""
        self._stream_buffer = ""

        threading.Thread(target=self._run_agent, args=(text,), daemon=True).start()

    def _run_agent(self, user_text: str):
        """在线程中运行 Agent.chat，通过回调实时更新 UI。

        Agent 的 `_callback` 在流式输出和工具调用时被调用，
        数据类型支持：
          - {"type":"chunk", "content":"..."}    ← LiteSession
          - {"type":"token", "text":"..."}        ← FullSession
          - {"type":"thinking", "text":"..."}     ← 思考过程
          - {"type":"status", "text":"..."}       ← 状态更新
          - {"type":"done", "used_tools":[...]}   ← 完成
        """
        try:
            # ── 注册流式回调 ──────────────────────────────
            def agent_callback(data: dict):
                typ = data.get("type", "")
                if typ in ("token", "chunk"):
                    text = data.get("text") or data.get("content") or ""
                    if text:
                        self._stream_buffer += text
                        self.streamUpdated.emit(self._stream_buffer)
                elif typ == "thinking":
                    text = data.get("text", "")
                    if text:
                        self._think_buffer += text
                        self.thinkUpdated.emit(self._think_buffer)
                elif typ == "status":
                    self._update_status(data.get("text", ""))
                # "done" 在 chat() 返回后统一处理

            self._agent._callback = agent_callback

            # ── 阻塞等待完整回复 ──────────────────────────
            self._agent.chat(
                user_input=user_text,
                topic_id=self._current_topic_id,
            )

            # ── 处理完成结果 ──────────────────────────────
            self._on_agent_done()

        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            self.errorOccurred.emit(f"Agent 错误: {e}")
            self._on_agent_done()

    def _on_agent_done(self):
        """将缓冲区的内容刷新到消息列表，重置生成状态。"""
        if self._think_buffer.strip():
            self._add_message("think", self._think_buffer.strip())
            self._think_buffer = ""

        stream_content = self._stream_buffer.strip()
        if stream_content:
            self._add_message("ai", stream_content)
            self._stream_buffer = ""

        if self._generating:
            self._generating = False
            self._update_status("✅ 就绪")
            self.scrollToBottom.emit()

    def _add_message(self, role: str, content: str):
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
        """刷新主题列表（从配置文件指定的数据库读取）。"""
        try:
            from tea_agent.store import Storage as _Storage
            db_path = str(self._cfg.paths.db_path_abs) if self._cfg and hasattr(self._cfg, 'paths') else None
            store = _Storage(db_path=db_path) if db_path else _Storage()
            topics = store.list_topics()
            self._topics = [
                {"id": t["topic_id"], "title": t.get("title", ""),
                 "updated": str(t.get("last_update_stamp", ""))}
                for t in topics if isinstance(t, dict)
            ]
            self.topicsChanged.emit()
        except Exception as e:
            logger.warning(f"Refresh topics failed: {e}")

    @Slot(result=list)
    def getTopicsList(self):
        """QML 调用：获取当前主题列表。"""
        return list(self._topics)

    @Slot(str)
    def load_topic(self, topic_id: str):
        """加载指定主题的对话历史。"""
        self._update_status(f"📂 加载主题 {topic_id[:8]}...")
        try:
            from tea_agent.store import Storage as _Storage
            db_path = str(self._cfg.paths.db_path_abs) if self._cfg and hasattr(self._cfg, 'paths') else None
            store = _Storage(db_path=db_path) if db_path else _Storage()
            convs = store.get_conversations(topic_id)
            with self._lock:
                self._messages.clear()
                for c in convs:
                    if c.get("user_msg"):
                        self._messages.append({
                            "role": "user",
                            "content": c["user_msg"],
                            "timestamp": str(c.get("stamp", "")),
                        })
                    rounds = c.get("rounds_json_parsed") or []
                    for r in rounds:
                        role = r.get("role", "ai")
                        content = r.get("content", "") or ""
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
        with self._lock:
            self._messages.clear()
            self._current_topic_id = ""
        self.messagesChanged.emit()
        self._update_status("📝 新主题")
        self._add_message("notice", "📝 新对话开始，输入消息吧")

    @Slot()
    def interrupt(self):
        if self._agent and self._generating:
            try:
                if hasattr(self._agent._sess, 'interrupt'):
                    self._agent._sess.interrupt()
                self._generating = False
                self._update_status("⏹ 已中断")
            except Exception as e:
                logger.warning(f"Interrupt failed: {e}")

    # ── QML 可调用的消息获取方法 ──────────────────────────

    @Slot(result=list)
    def getMessagesList(self):
        """QML 调用：获取当前消息列表（线程安全）。"""
        with self._lock:
            return list(self._messages)

    # ── 属性暴露给 QML ────────────────────────────────────

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
        if self._agent:
            try:
                self._agent.close()
            except Exception:
                pass
