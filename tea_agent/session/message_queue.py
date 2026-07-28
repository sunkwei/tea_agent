"""
Steering/Follow-up 消息队列系统 — 借鉴 Pi Agent Harness

功能：
  - Steering Queue：用户在当前工具批次执行期间发送的消息，在下一批次前注入
  - Follow-up Queue：用户排队等待的消息，在所有工作完成后投递
  - 两种投递模式：one-at-a-time（一次一条）或 all（一次全部）
  - 线程安全，支持并发读写

使用场景：
  用户在 Agent 执行工具时可以继续输入新指令，无需等待当前轮次完成。

用法：
    from session.message_queue import MessageQueue

    queue = MessageQueue(mode="one-at-a-time")

    # 用户输入新消息（在 agent 执行期间）
    queue.push_steering("帮我优化这个函数")
    queue.push_followup("完成后总结一下")

    # Agent 轮次间检查
    steering = queue.get_steering()  # 获取待处理的 steering 消息
    followup = queue.get_followup()  # 获取待处理的 follow-up 消息
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger("session.message_queue")


class QueueMode(str, Enum):
    """消息投递模式。"""
    ONE_AT_A_TIME = "one-at-a-time"  # 逐条投递
    ALL = "all"                      # 批量投递


class MessageType(str, Enum):
    """消息类型。"""
    STEERING = "steering"   # 插入性消息（在工具批次间注入）
    FOLLOWUP = "followup"   # 后续消息（在所有工作完成后投递）


@dataclass
class QueuedMessage:
    """队列中的一条消息。"""
    id: str
    type: MessageType
    content: str
    timestamp: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class MessageQueue:
    """线程安全的 Steering/Follow-up 消息队列。

    属性：
        mode: 投递模式
        steering_queue: 插入性消息队列
        followup_queue: 后续消息队列
        on_message: 新消息回调
    """

    def __init__(
        self,
        mode: str = "one-at-a-time",
        on_message: Callable[[QueuedMessage], None] | None = None,
    ):
        """
        Args:
            mode: one-at-a-time 或 all
            on_message: 新消息回调函数（可选）
        """
        self.mode = mode
        self.on_message = on_message
        self._steering_queue: list[QueuedMessage] = []
        self._followup_queue: list[QueuedMessage] = []
        self._lock = threading.Lock()
        self._message_id_counter = 0

    def _next_id(self) -> str:
        """生成递增消息 ID。"""
        self._message_id_counter += 1
        return f"msg_{self._message_id_counter}_{datetime.now().strftime('%H%M%S')}"

    # ── 推送 ──────────────────────────────────────────────

    def push_steering(self, content: str, **metadata) -> QueuedMessage:
        """推送一条 steering 消息。

        Steering 消息在下一轮工具执行前注入到对话中。
        """
        msg = QueuedMessage(
            id=self._next_id(),
            type=MessageType.STEERING,
            content=content,
            timestamp=datetime.now().isoformat(),
            metadata=metadata,
        )
        with self._lock:
            self._steering_queue.append(msg)

        logger.info(f"📨 Steering 入队: [{msg.id}] {content[:80]}...")
        if self.on_message:
            try:
                self.on_message(msg)
            except Exception as e:
                logger.warning(f"on_message 回调失败: {e}")

        return msg

    def push_followup(self, content: str, **metadata) -> QueuedMessage:
        """推送一条 follow-up 消息。

        Follow-up 消息在 Agent 完成所有工作后投递。
        """
        msg = QueuedMessage(
            id=self._next_id(),
            type=MessageType.FOLLOWUP,
            content=content,
            timestamp=datetime.now().isoformat(),
            metadata=metadata,
        )
        with self._lock:
            self._followup_queue.append(msg)

        logger.info(f"📨 Follow-up 入队: [{msg.id}] {content[:80]}...")
        if self.on_message:
            try:
                self.on_message(msg)
            except Exception as e:
                logger.warning(f"on_message 回调失败: {e}")

        return msg

    def push(self, content: str, msg_type: str = "steering", **metadata) -> QueuedMessage:
        """通用推送接口。

        Args:
            content: 消息内容
            msg_type: "steering" 或 "followup"
            metadata: 附加元数据
        """
        if msg_type == "followup":
            return self.push_followup(content, **metadata)
        return self.push_steering(content, **metadata)

    # ── 消费 ──────────────────────────────────────────────

    def get_steering(self) -> list[QueuedMessage]:
        """获取所有待处理的 steering 消息。

        根据 mode 决定返回一条还是全部。
        """
        with self._lock:
            if not self._steering_queue:
                return []

            if self.mode == QueueMode.ONE_AT_A_TIME:
                return [self._steering_queue.pop(0)]
            else:
                messages = list(self._steering_queue)
                self._steering_queue.clear()
                return messages

    def get_followup(self) -> list[QueuedMessage]:
        """获取所有待处理的 follow-up 消息。"""
        with self._lock:
            if not self._followup_queue:
                return []
            messages = list(self._followup_queue)
            self._followup_queue.clear()
            return messages

    def get_all_pending(self) -> dict:
        """获取所有待处理消息。

        Returns:
            {"steering": [...], "followup": [...]}
        """
        with self._lock:
            return {
                "steering": list(self._steering_queue),
                "followup": list(self._followup_queue),
            }

    # ── 状态查询 ──────────────────────────────────────────

    @property
    def has_steering(self) -> bool:
        """是否有待处理的 steering 消息。"""
        with self._lock:
            return len(self._steering_queue) > 0

    @property
    def has_followup(self) -> bool:
        """是否有待处理的 follow-up 消息。"""
        with self._lock:
            return len(self._followup_queue) > 0

    @property
    def has_pending(self) -> bool:
        """是否有任何待处理消息。"""
        with self._lock:
            return len(self._steering_queue) > 0 or len(self._followup_queue) > 0

    @property
    def steering_count(self) -> int:
        with self._lock:
            return len(self._steering_queue)

    @property
    def followup_count(self) -> int:
        with self._lock:
            return len(self._followup_queue)

    # ── 管理 ──────────────────────────────────────────────

    def clear(self):
        """清空所有队列。"""
        with self._lock:
            self._steering_queue.clear()
            self._followup_queue.clear()
        logger.info("🧹 消息队列已清空")

    def set_mode(self, mode: str):
        """设置投递模式。"""
        if mode not in ("one-at-a-time", "all"):
            raise ValueError(f"无效模式: {mode}")
        self.mode = mode
        logger.info(f"📋 消息队列模式切换为: {mode}")

    def to_dict(self) -> dict:
        """导出队列状态。"""
        with self._lock:
            return {
                "mode": self.mode,
                "steering": [m.to_dict() for m in self._steering_queue],
                "followup": [m.to_dict() for m in self._followup_queue],
                "total_pending": len(self._steering_queue) + len(self._followup_queue),
            }


# ═══ Session 集成辅助 ═══════════════════════════════════

def create_message_queue(session) -> MessageQueue:
    """为 session 创建并挂载消息队列。

    在 session.context 上添加 message_queue 属性。

    Args:
        session: OnlineToolSession 实例

    Returns:
        创建的 MessageQueue 实例
    """
    if hasattr(session.context, 'message_queue'):
        return session.context.message_queue

    queue = MessageQueue(
        mode=getattr(session.context, 'queue_mode', 'one-at-a-time'),
    )
    session.context.message_queue = queue
    logger.info("📋 消息队列已挂载到 session.context")
    return queue


def inject_queued_messages(messages: list, session) -> list:
    """将队列中的消息注入到消息列表中。

    在构建 API 消息时调用此函数，将队列中的 steering 消息插入。

    Args:
        messages: 当前 API 消息列表
        session: OnlineToolSession 实例

    Returns:
        注入后的消息列表
    """
    queue = getattr(session.context, 'message_queue', None)
    if not queue or not queue.has_steering:
        return messages

    steering = queue.get_steering()
    if not steering:
        return messages

    # 在最后一条消息前插入 steering 消息
    inserted = list(messages)
    for msg in steering:
        inserted.append({
            "role": "user",
            "content": f"[即时指令] {msg.content}",
        })
        logger.info(f"📨 注入 steering 消息: {msg.content[:80]}...")

    return inserted


def check_followup_messages(session) -> list:
    """检查是否有 follow-up 消息待处理。

    在工具循环结束后调用，返回待处理的 follow-up 消息列表。

    Args:
        session: OnlineToolSession 实例

    Returns:
        follow-up 消息内容列表
    """
    queue = getattr(session.context, 'message_queue', None)
    if not queue:
        return []

    followup = queue.get_followup()
    if not followup:
        return []

    contents = [{
        "role": "user",
        "content": f"[后续任务] {msg.content}",
        "metadata": msg.metadata,
    } for msg in followup]

    logger.info(f"📨 投递 {len(followup)} 条 follow-up 消息")
    return contents
