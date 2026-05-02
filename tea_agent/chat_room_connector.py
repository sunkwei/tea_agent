#!/usr/bin/env python3
"""
chat_room 消息中继 — 将 MQTT 聊天广场的消息接入 tea_agent
启动一个后台线程，连接 MQTT broker，将收到的消息路由到对应 topic。

topic 标题规则（不可被摘要修改）：
  对所有来自 {who} 的消息，存入标题为 'chat_room_{who}' 的 topic
"""
import json
import logging
import threading
import time
import uuid
import os
from typing import Optional, Dict

import paho.mqtt.client as mqtt

logger = logging.getLogger("chat_room_connector")

# ── MQTT 话题常量（与 chat_room 项目一致）────────────────
TOPIC_REGISTER_REQ  = "chatroom/register/request"
TOPIC_REGISTER_RESP = "chatroom/register/response"
TOPIC_CHAT_WILD     = "chatroom/chat/+"
TOPIC_CHAT_PFX      = "chatroom/chat/"
TOPIC_SYSTEM        = "chatroom/system"
TOPIC_PRESENCE_PFX  = "chatroom/presence/"

TOPIC_TITLE_PREFIX  = "chat_room_"   # 由此前缀开头的 topic 标题受保护


class ChatRoomConnector:
    """MQTT 聊天广场 → tea_agent 消息路由"""

    def __init__(self, broker_host="localhost", broker_port=1883):
        self.username = f"tea_agent_{uuid.uuid4().hex[:6]}"
        self.broker_host = broker_host
        self.broker_port = broker_port
        self._store = None                # 由 start() 注入
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        # topic 缓存: {sender_name: topic_id}
        self._topic_cache: Dict[str, int] = {}
        self._cache_lock = threading.Lock()

    # ── 公共接口 ──────────────────────────────────────

    def start(self, store):
        """
        启动后台线程。

        Args:
            store: Storage 实例，用于创建/查找 topic 和写入消息
        """
        self._store = store
        t = threading.Thread(target=self._run, daemon=True, name="chatroom-connector")
        t.start()
        logger.info(f"chat_room 连接器启动 — 身份: {self.username}")
        return t

    def stop(self):
        """停止后台线程"""
        self._stop_event.set()
        logger.info("chat_room 连接器已请求停止")

    # ── 内部 ──────────────────────────────────────────

    def _run(self):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        # LWT 遗嘱
        client.will_set(f"{TOPIC_PRESENCE_PFX}{self.username}", "offline", retain=False)

        try:
            client.connect(self.broker_host, self.broker_port, keepalive=30)
        except Exception as e:
            logger.error(f"chat_room 连接 broker 失败: {e}")
            self._ready_event.set()  # 不阻塞主线程
            return

        client.loop_start()
        self._ready_event.set()

        # 等待停止信号
        self._stop_event.wait()

        client.loop_stop()
        client.disconnect()
        logger.info("chat_room 连接器已关闭")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            # 注册
            client.publish(TOPIC_REGISTER_REQ, self.username)
            # 订阅所有聊天消息
            client.subscribe(TOPIC_CHAT_WILD)
            # 发送上线 presence
            client.publish(f"{TOPIC_PRESENCE_PFX}{self.username}", "online")
            logger.info(f"chat_room 已连接 broker，订阅 {TOPIC_CHAT_WILD}")
        else:
            logger.warning(f"chat_room broker 连接失败 rc={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning(f"chat_room 与 broker 断开 (rc={reason_code})")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:
            return

        # 只处理聊天消息
        if not topic.startswith(TOPIC_CHAT_PFX):
            return

        sender = topic[len(TOPIC_CHAT_PFX):]
        if sender == self.username:
            return  # 跳过自己

        # 尝试解析 JSON 消息
        content = payload
        try:
            msg_obj = json.loads(payload)
            if isinstance(msg_obj, dict):
                mtype = msg_obj.get("type", "")
                # 跳过非发言类消息
                if mtype in ("join", "leave", "system", "error", "history"):
                    return
                content = msg_obj.get("content", payload)
                sender = msg_obj.get("sender", sender)
        except (json.JSONDecodeError, TypeError):
            pass  # 纯文本消息

        if not content.strip():
            return

        self._route_message(sender, content)

    def _route_message(self, sender: str, content: str):
        """将消息存入对应 topic"""
        if self._store is None:
            return

        tid = self._get_or_create_topic(sender)
        if tid < 0:
            return

        try:
            # 作为 user_msg 存入（AI 回复留空），标记为非函数调用
            self._store.save_msg(tid, content, "", False)
            logger.info(f"chat_room → topic chat_room_{sender}: {content[:50]}...")
        except Exception as e:
            logger.error(f"chat_room 写入 DB 失败 (sender={sender}): {e}")

    def _get_or_create_topic(self, sender: str) -> int:
        """查找或创建标题为 'chat_room_{sender}' 的 topic"""
        with self._cache_lock:
            if sender in self._topic_cache:
                return self._topic_cache[sender]

        title = f"{TOPIC_TITLE_PREFIX}{sender}"

        # 在已有 topic 中搜索
        try:
            topics = self._store.list_topics()
            for t in topics:
                if t.get("title") == title:
                    with self._cache_lock:
                        self._topic_cache[sender] = t["topic_id"]
                    return t["topic_id"]
        except Exception as e:
            logger.warning(f"chat_room 搜索 topic 失败: {e}")

        # 不存在则创建
        try:
            tid = self._store.create_topic(title)
            with self._cache_lock:
                self._topic_cache[sender] = tid
            logger.info(f"chat_room 新建 topic: {title} (id={tid})")
            return tid
        except Exception as e:
            logger.error(f"chat_room 创建 topic 失败 ({title}): {e}")
            return -1


# ── 模块级单例 ────────────────────────────────────────

_connector: Optional[ChatRoomConnector] = None
_connector_started = False


def start(store) -> Optional[ChatRoomConnector]:
    """
    启动 chat_room 连接器（幂等，多次调用不会创建重复线程）。

    Args:
        store: Storage 实例

    Returns:
        ChatRoomConnector 或 None（broker 不可用时）
    """
    global _connector, _connector_started
    if _connector_started:
        return _connector

    broker_host = os.environ.get("MQTT_BROKER", "localhost")
    broker_port = int(os.environ.get("MQTT_PORT", "1883"))

    _connector = ChatRoomConnector(broker_host, broker_port)
    _connector.start(store)
    _connector_started = True
    return _connector


def stop():
    """停止连接器"""
    global _connector
    if _connector:
        _connector.stop()
        _connector = None


def is_chat_room_topic(title: str) -> bool:
    """判断 topic 标题是否属于 chat_room（受保护，不可被摘要修改）"""
    return title.startswith(TOPIC_TITLE_PREFIX)
