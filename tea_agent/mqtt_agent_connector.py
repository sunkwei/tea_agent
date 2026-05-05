#!/usr/bin/env python3
"""
通用 MQTT 连接器 — tea_agent 作为 MQTT client 与外部客户端实时交互。

Topic 约定（沿用 chat_room 验证过的模式）：
  {prefix}/chat/+          — 通配符，订阅所有用户发言
  {prefix}/chat/{who}      — 每个人发布到此 topic
  {prefix}/status          — tea_agent 的 presence（online/offline）

消息格式：
  {"id":"abc123","sender":"谁","type":"say","content":"内容","reply_to":null,"ts":1702900000}

支持两种模式：
  1. 被动模式（默认）：收到消息存入 DB，创建 mqtt_{sender} topic
  2. 主动模式：收到消息自动调用 AI 处理并回复（通过 reply_handler 回调）
"""
import json
import logging
import threading
import time
import uuid
import os
from typing import Optional, Dict, Callable

import paho.mqtt.client as mqtt

logger = logging.getLogger("mqtt_agent_connector")

# ── 常量 ─────────────────────────────────────────────
TOPIC_TITLE_PREFIX = "mqtt_"   # 由此前缀开头的 topic 受保护


class MqttAgentConnector:
    """通用 MQTT 连接器 — 双工通信，支持 1:N 广播和 1:1 定向回复"""

    def __init__(self, broker_host="localhost", broker_port=1883,
                 broker_username="", broker_password="",
                 topic_prefix="tea"):
        """
        Args:
            broker_host: MQTT broker 地址
            broker_port: MQTT broker 端口
            broker_username: broker 认证用户名（空=匿名）
            broker_password: broker 认证口令
            topic_prefix: channel 前缀，如 "tea" → tea/chat/+
        """
        self.uuid_short = uuid.uuid4().hex[:6]
        self.username = f"tea_agent_{self.uuid_short}"
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.broker_username = broker_username
        self.broker_password = broker_password
        self.topic_prefix = topic_prefix

        # MQTT topic 模板
        self.topic_chat_wild = f"{topic_prefix}/chat/+"
        self.topic_chat_pfx = f"{topic_prefix}/chat/"
        self.topic_status = f"{topic_prefix}/status"

        # 内部状态
        self._store = None
        self._reply_handler: Optional[Callable] = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._topic_cache: Dict[str, int] = {}
        self._cache_lock = threading.Lock()
        self._connected = False

    # ── 公共接口 ──────────────────────────────────────

    def set_reply_handler(self, handler: Callable[[str, str, str], Optional[str]]):
        """
        设置自动回复处理器。

        Args:
            handler: async def handler(sender: str, content: str, msg_id: str) -> Optional[str]
                     返回 None 表示不回复，返回字符串则作为回复内容自动发布
        """
        self._reply_handler = handler

    def start(self, store):
        """
        启动后台 MQTT 线程。

        Args:
            store: Storage 实例，用于创建/查找 topic 和写入消息
        """
        self._store = store
        t = threading.Thread(target=self._run, daemon=True, name="mqtt-agent-connector")
        t.start()
        logger.info(f"MQTT 连接器启动 — 身份: {self.username}, topic: {self.topic_chat_wild}")
        return t

    def stop(self):
        """停止后台线程"""
        self._stop_event.set()
        logger.info("MQTT 连接器已请求停止")

    def publish_reply(self, content: str, reply_to: Optional[str] = None,
                      msg_type: str = "say"):
        """
        主动发布消息到 MQTT。

        Args:
            content: 消息内容
            reply_to: 回复目标用户名（None=广播到自己的 channel）
            msg_type: 消息类型 say/think/system
        """
        if not self._connected:
            logger.warning("MQTT 未连接，无法发布消息")
            return

        target = reply_to if reply_to else self.username
        topic = f"{self.topic_chat_pfx}{target}"
        msg = {
            "id": uuid.uuid4().hex[:8],
            "sender": self.username,
            "type": msg_type,
            "content": content,
            "reply_to": reply_to,
            "ts": time.time(),
        }
        self._client.publish(topic, json.dumps(msg, ensure_ascii=False))
        logger.debug(f"MQTT 发布 → {topic}: {content[:50]}...")

    @property
    def is_ready(self) -> bool:
        """连接就绪标志"""
        return self._ready_event.is_set()

    # ── 内部 ──────────────────────────────────────────

    def _connect_client(self):
        """创建并连接 MQTT client"""
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        # Will message — 断线时通知
        client.will_set(self.topic_status, json.dumps({
            "sender": self.username,
            "type": "system",
            "content": "offline",
            "ts": time.time(),
        }), retain=False)

        # 认证
        if self.broker_username:
            client.username_pw_set(self.broker_username, self.broker_password)

        try:
            client.connect(self.broker_host, self.broker_port, keepalive=30)
            return client
        except Exception as e:
            logger.warning(f"MQTT broker 连接失败 ({self.broker_host}:{self.broker_port}): {e}")
            return None

    def _run(self):
# NOTE: 2026-05-04 08:56:41, self-evolved by tea_agent --- 每次重连前清除 _ready_event，防止旧的就绪状态导致误判
        RETRY_INTERVAL = 30

        while not self._stop_event.is_set():
            self._ready_event.clear()
            self._connected = False
            client = self._connect_client()
            if client is None:
                logger.info(f"MQTT 将在 {RETRY_INTERVAL}s 后重试...")
                self._stop_event.wait(RETRY_INTERVAL)
                continue

# NOTE: 2026-05-04 08:55:14, self-evolved by tea_agent --- 将 _ready_event.set() 从 _run 移到 _on_connect 订阅完成后，修复时序问题
# NOTE: 2026-05-04 08:56:33, self-evolved by tea_agent --- _run 监控循环等 _ready_event 就绪后再检查连接，避免 on_connect 前的误判
            self._client = client
            client.loop_start()
            # 等待 on_connect 完成订阅（设置 _ready_event）
            if not self._ready_event.wait(timeout=10):
                logger.warning("MQTT on_connect 超时，断开重试")
                client.loop_stop()
                try: client.disconnect()
                except: pass
                continue
            logger.info(f"MQTT 连接就绪 — 身份: {self.username}")

            # 等待断开或停止
            while not self._stop_event.is_set():
                if not client.is_connected():
                    logger.warning("MQTT 连接断开，将重试...")
                    break
                self._stop_event.wait(2)

            self._connected = False
            client.loop_stop()
            try:
                client.disconnect()
            except Exception:
                pass

            if self._stop_event.is_set():
                break

            logger.info(f"MQTT 将在 {RETRY_INTERVAL}s 后重试...")
            self._stop_event.wait(RETRY_INTERVAL)

        self._connected = False
        logger.info("MQTT 连接器线程退出")

# NOTE: 2026-05-04 08:55:29, self-evolved by tea_agent --- _on_connect 中设置 _ready_event 和 _connected，确保订阅完成后再标就绪
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            # 订阅所有聊天消息
            client.subscribe(self.topic_chat_wild)
            # 发布上线通知
            client.publish(self.topic_status, json.dumps({
                "sender": self.username,
                "type": "system",
                "content": "online",
                "ts": time.time(),
            }))
            self._connected = True
            self._ready_event.set()
            logger.info(f"MQTT 已连接 broker，订阅 {self.topic_chat_wild}")
        else:
            logger.warning(f"MQTT broker 连接失败 rc={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning(f"MQTT 与 broker 断开 (rc={reason_code})")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload_str = msg.payload.decode("utf-8", errors="replace")
        except Exception:
            return

        # 只处理聊天消息
        if not topic.startswith(self.topic_chat_pfx):
            return

        # 提取发送者
        sender = topic[len(self.topic_chat_pfx):]
        if sender == self.username:
            return  # 跳过自己

        # 解析消息
        content = payload_str
        msg_id = ""
        msg_type = "say"

        try:
            msg_obj = json.loads(payload_str)
            if isinstance(msg_obj, dict):
                if msg_obj.get("sender") == self.username:
                    return
                msg_type = msg_obj.get("type", "say")
                if msg_type in ("join", "leave", "system", "error"):
                    return  # 跳过非发言类消息
                content = msg_obj.get("content", payload_str)
                msg_id = msg_obj.get("id", "")
                sender = msg_obj.get("sender", sender)
        except (json.JSONDecodeError, TypeError):
            pass  # 纯文本消息

        if not content.strip():
            return

        # ── 存入 DB ──
        self._route_message(sender, content)

        # ── 自动回复（如果有 handler）──
        if self._reply_handler:
            try:
                reply = self._reply_handler(sender, content, msg_id)
                if reply:
                    self.publish_reply(reply, reply_to=sender)
            except Exception as e:
                logger.error(f"MQTT 自动回复失败 (sender={sender}): {e}")

    def _route_message(self, sender: str, content: str):
        """将消息存入对应 topic"""
        if self._store is None:
            return

        tid = self._get_or_create_topic(sender)
        if tid < 0:
            return

        try:
            self._store.save_msg(tid, content, "", False)
            logger.debug(f"MQTT → topic mqtt_{sender}: {content[:50]}...")
        except Exception as e:
            logger.error(f"MQTT 写入 DB 失败 (sender={sender}): {e}")

    def _get_or_create_topic(self, sender: str) -> int:
        """查找或创建标题为 'mqtt_{sender}' 的 topic"""
        with self._cache_lock:
            if sender in self._topic_cache:
                return self._topic_cache[sender]

        title = f"{TOPIC_TITLE_PREFIX}{sender}"

        try:
            topics = self._store.list_topics()
            for t in topics:
                if t.get("title") == title:
                    with self._cache_lock:
                        self._topic_cache[sender] = t["topic_id"]
                    return t["topic_id"]
        except Exception as e:
            logger.warning(f"MQTT 搜索 topic 失败: {e}")

        try:
            tid = self._store.create_topic(title)
            with self._cache_lock:
                self._topic_cache[sender] = tid
            logger.info(f"MQTT 新建 topic: {title} (id={tid})")
            return tid
        except Exception as e:
            logger.error(f"MQTT 创建 topic 失败 ({title}): {e}")
            return -1


# ── 模块级单例 ────────────────────────────────────────

_connector: Optional[MqttAgentConnector] = None
_connector_started = False


def start(store) -> Optional[MqttAgentConnector]:
    """
    启动 MQTT 连接器（幂等，从 config.yaml 读取配置）。

    Args:
        store: Storage 实例

    Returns:
        MqttAgentConnector 或 None（未启用或启动失败时）
    """
    global _connector, _connector_started
    if _connector_started:
        return _connector

    from tea_agent.config import get_config
    cfg = get_config()
    mqtt_cfg = cfg.mqtt

    if not mqtt_cfg.enabled:
        logger.info("MQTT 未启用（config.yaml 中 mqtt.enabled=false）")
        return None

    _connector = MqttAgentConnector(
        broker_host=mqtt_cfg.broker_host,
        broker_port=mqtt_cfg.broker_port,
        broker_username=mqtt_cfg.username,
        broker_password=mqtt_cfg.password,
        topic_prefix=mqtt_cfg.topic_prefix,
    )
    _connector.start(store)
    _connector_started = True
    return _connector


def stop():
    """停止 MQTT 连接器"""
    global _connector
    if _connector:
        _connector.stop()
        _connector = None


def is_mqtt_topic(title: str) -> bool:
    """判断 topic 标题是否属于 MQTT（受保护，不可被摘要修改）"""
    return title.startswith(TOPIC_TITLE_PREFIX)


def get_connector() -> Optional[MqttAgentConnector]:
    """获取当前连接器实例"""
    return _connector
