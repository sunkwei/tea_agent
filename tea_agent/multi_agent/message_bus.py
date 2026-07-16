"""
MessageBus — 跨 Agent 发布/订阅消息队列。

核心设计:
  - 基于主题 (Topic) 的发布/订阅模式（区别于点对点 messaging）
  - 每个 Agent 可以订阅多个主题
  - 发布消息时自动分发给所有订阅者
  - 消息持久化（可选）
  - 构建于 toolkit_subagent_msg 之上

与 toolkit_subagent_msg 的关系:
  toolkit_subagent_msg = Agent-to-Agent 点对点
  MessageBus         = Topic-based Pub/Sub（一对多广播）

用法:
    from tea_agent.multi_agent import MessageBus

    bus = MessageBus()
    bus.subscribe("agent-A", "task:update")
    bus.subscribe("agent-B", "task:update")
    bus.subscribe("agent-B", "task:result")

    bus.publish("task:update", {"status": "running"}, sender="coordinator")
    bus.publish("task:result", {"score": 0.95}, sender="agent-A")

    # 查看主题订阅者
    print(bus.topic_subscribers("task:update"))  # ["agent-A", "agent-B"]

    # 获取 agent-B 的消息
    msgs = bus.consume("agent-B")
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class Message:
    """消息封装。"""

    def __init__(
        self,
        topic: str,
        payload: Any,
        sender: str = "",
        priority: MessagePriority = MessagePriority.NORMAL,
        message_id: str = "",
    ):
        self.id = message_id or f"msg_{int(time.time() * 1000000)}_{id(self)}"
        self.topic = topic
        self.payload = payload
        self.sender = sender
        self.priority = priority
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "payload": self.payload if isinstance(self.payload, (str, int, float, bool, list, dict)) else str(self.payload),
            "sender": self.sender,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return f"<Message topic={self.topic!r} from={self.sender!r}>"


class MessageBus:
    """
    跨 Agent 发布/订阅消息总线。

    线程安全。支持多主题、多订阅者、优先级排序、广播/单播。
    """

    def __init__(self, persist: bool = False):
        """
        Args:
            persist: 是否将消息持久化到数据库（默认 False）
        """
        self._lock = threading.RLock()

        # 主题 → 订阅者列表
        self._subscriptions: dict[str, set[str]] = {}

        # 订阅者 → 消息队列
        self._mailboxes: dict[str, list[Message]] = {}

        # 主题 → 最近消息（方便新订阅者获取上下文）
        self._topic_last_message: dict[str, Message] = {}

        # 消息历史（全量，用于追踪）
        self._history: list[Message] = []
        self._max_history = 1000

        self._persist = persist

        # 回调钩子
        self._on_publish_hooks: list[Callable] = []

    # ── 订阅管理 ────────────────────────────────────

    def subscribe(self, agent_id: str, topic: str) -> bool:
        """Agent 订阅一个主题。"""
        with self._lock:
            if topic not in self._subscriptions:
                self._subscriptions[topic] = set()
            self._subscriptions[topic].add(agent_id)

            # 确保有邮箱
            if agent_id not in self._mailboxes:
                self._mailboxes[agent_id] = []

            logger.debug(f"📡 {agent_id} 订阅了 {topic!r}")
            return True

    def unsubscribe(self, agent_id: str, topic: str) -> bool:
        """Agent 取消订阅。"""
        with self._lock:
            if topic in self._subscriptions and agent_id in self._subscriptions[topic]:
                self._subscriptions[topic].discard(agent_id)
                logger.debug(f"🔇 {agent_id} 取消订阅 {topic!r}")
                return True
            return False

    def unsubscribe_all(self, agent_id: str) -> int:
        """Agent 取消所有订阅。返回取消的主题数。"""
        with self._lock:
            count = 0
            for topic in list(self._subscriptions.keys()):
                if agent_id in self._subscriptions[topic]:
                    self._subscriptions[topic].discard(agent_id)
                    count += 1
            return count

    def topic_subscribers(self, topic: str) -> list[str]:
        """获取某主题的所有订阅者。"""
        with self._lock:
            return list(self._subscriptions.get(topic, set()))

    def subscriptions(self, agent_id: str) -> list[str]:
        """获取某 Agent 订阅的所有主题。"""
        with self._lock:
            return [
                topic for topic, subscribers in self._subscriptions.items()
                if agent_id in subscribers
            ]

    # ── 发布 ────────────────────────────────────────

    def publish(
        self,
        topic: str,
        payload: Any,
        sender: str = "",
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> list[str]:
        """
        发布消息到主题。

        Returns:
            实际接收到的 agent_id 列表
        """
        msg = Message(
            topic=topic,
            payload=payload,
            sender=sender,
            priority=priority,
        )

        with self._lock:
            # 记录最后消息
            self._topic_last_message[topic] = msg

            # 加入历史
            self._history.append(msg)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

            # 分发给订阅者
            recipients = list(self._subscriptions.get(topic, set()))
            for agent_id in recipients:
                if agent_id not in self._mailboxes:
                    self._mailboxes[agent_id] = []
                self._mailboxes[agent_id].append(msg)

            # 持久化
            if self._persist:
                self._persist_message(msg, recipients)

        # 回调
        for hook in self._on_publish_hooks:
            try:
                hook(msg, recipients)
            except Exception as e:
                logger.warning(f"publish hook 失败: {e}")

        logger.debug(f"📤 [{topic}] {sender} → {len(recipients)} 个订阅者: {recipients}")
        return recipients

    def publish_many(self, messages: list[tuple[str, Any, str]], topic: str = "") -> int:
        """
        批量发布消息。

        Args:
            messages: [(topic, payload, sender), ...] 或 [(payload,), ...]（使用默认 topic）
            topic: 默认主题（如果 messages 元组不含 topic）

        Returns:
            发布消息数
        """
        count = 0
        for msg in messages:
            if len(msg) == 3:
                t, p, s = msg
            elif len(msg) == 2:
                t, p = msg
                s = ""
            else:
                p = msg[0]
                t = topic
                s = ""

            target_topic = t or topic
            if target_topic:
                self.publish(target_topic, p, sender=s)
                count += 1
        return count

    # ── 消费 ────────────────────────────────────────

    def consume(self, agent_id: str, max_messages: int = 0) -> list[dict]:
        """
        消费（拉取并移除）某 Agent 的消息。

        Args:
            agent_id: Agent ID
            max_messages: 0=全部

        Returns:
            消息 dict 列表
        """
        with self._lock:
            queue = self._mailboxes.get(agent_id, [])
            if max_messages > 0:
                batch = queue[:max_messages]
                self._mailboxes[agent_id] = queue[max_messages:]
            else:
                batch = queue
                self._mailboxes[agent_id] = []
            return [m.to_dict() for m in batch]

    def peek(self, agent_id: str, limit: int = 10) -> list[dict]:
        """查看消息但不消费。"""
        with self._lock:
            queue = self._mailboxes.get(agent_id, [])
            return [m.to_dict() for m in queue[:limit]]

    def count_messages(self, agent_id: str) -> int:
        """查看队列中等待的消息数。"""
        with self._lock:
            return len(self._mailboxes.get(agent_id, []))

    # ── 广播 ────────────────────────────────────────

    def broadcast(self, payload: Any, sender: str = "") -> int:
        """
        广播给所有有订阅的 Agent。

        Returns:
            接收 agent 数
        """
        with self._lock:
            all_agents = set()
            for subscribers in self._subscriptions.values():
                all_agents.update(subscribers)

            for agent_id in all_agents:
                self.publish("broadcast", payload, sender=sender)

            return len(all_agents)

    # ── 主题管理 ────────────────────────────────────

    def topics(self) -> list[str]:
        """列出所有活跃主题。"""
        with self._lock:
            return list(self._subscriptions.keys())

    def topic_stats(self) -> dict:
        """各主题统计。"""
        with self._lock:
            return {
                topic: {
                    "subscribers": len(subs),
                    "subscriber_list": list(subs),
                }
                for topic, subs in self._subscriptions.items()
            }

    def last_message(self, topic: str) -> dict | None:
        """获取某主题的最后一条消息。"""
        with self._lock:
            msg = self._topic_last_message.get(topic)
            return msg.to_dict() if msg else None

    # ── 系统 ────────────────────────────────────────

    def register_agent(self, agent_id: str) -> bool:
        """注册一个新 Agent（初始化邮箱）。"""
        with self._lock:
            if agent_id not in self._mailboxes:
                self._mailboxes[agent_id] = []
                return True
            return False

    def unregister_agent(self, agent_id: str) -> int:
        """注销 Agent，清理所有订阅和消息。"""
        with self._lock:
            # 取消所有订阅
            count = self.unsubscribe_all(agent_id)
            # 清理邮箱
            self._mailboxes.pop(agent_id, None)
            logger.debug(f"🗑️ Agent {agent_id} 已注销，{count} 个订阅已清理")
            return count

    def add_publish_hook(self, hook: Callable):
        """添加发布后回调。"""
        self._on_publish_hooks.append(hook)

    def clear(self):
        """清空所有消息和订阅。"""
        with self._lock:
            self._subscriptions.clear()
            self._mailboxes.clear()
            self._topic_last_message.clear()
            self._history.clear()
            logger.info("🧹 MessageBus 已清空")

    def status(self) -> dict:
        """总线状态快照。"""
        with self._lock:
            total_mailbox = sum(len(q) for q in self._mailboxes.values())
            return {
                "topics": len(self._subscriptions),
                "subscribers": sum(len(s) for s in self._subscriptions.values()),
                "agents": len(self._mailboxes),
                "pending_messages": total_mailbox,
                "history_size": len(self._history),
                "persist": self._persist,
            }

    def _persist_message(self, msg: Message, recipients: list[str]):
        """持久化消息（预留接口）。"""
        try:
            # 可选：写入数据库
            pass
        except Exception as e:
            logger.warning(f"持久化消息失败: {e}")


# ── 全局单例实例 ────────────────────────────────

_default_bus: MessageBus | None = None
_bus_lock = threading.Lock()


def get_message_bus() -> MessageBus:
    """获取全局消息总线（单例）。"""
    global _default_bus
    if _default_bus is None:
        with _bus_lock:
            if _default_bus is None:
                _default_bus = MessageBus()
    return _default_bus


def reset_message_bus():
    """重置消息总线（测试用）。"""
    global _default_bus
    with _bus_lock:
        _default_bus = None
