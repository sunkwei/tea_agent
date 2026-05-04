#!/usr/bin/env python3
"""
MQTT 简易客户端 — PC 终端版，与 tea_agent 通过 MQTT broker 实时交互。

用法:
    python mqtt_client.py <用户名>
    python mqtt_client.py <用户名> --broker mqtt.example.com --port 1883 --prefix tea

交互:
    直接输入文字 + Enter → 发送到 {prefix}/chat/{用户名}
    自动订阅 {prefix}/chat/+ → 接收所有人消息（包括 tea_agent）
    /quit → 退出
"""
import json
import os
import sys
import threading
import time
import uuid
import select

import paho.mqtt.client as mqtt


class MqttPcClient:
    """极简 MQTT 聊天客户端"""

    def __init__(self, username: str, broker_host="localhost", broker_port=1883,
                 topic_prefix="tea"):
        self.username = username.strip()
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic_prefix = topic_prefix

        self.topic_chat_wild = f"{topic_prefix}/chat/+"
        self.topic_chat_pfx = f"{topic_prefix}/chat/"
        self.topic_status = f"{topic_prefix}/status"

        self._ready = threading.Event()
        self._stop = threading.Event()

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    # ── MQTT 回调 ────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(self.topic_chat_wild)
            client.subscribe(self.topic_status)
            self._ready.set()
        else:
            print(f"\n❌ 连接失败 (rc={reason_code})")
            self._ready.set()

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:
            return

        topic = msg.topic

        # ── 状态消息 ──
        if topic == self.topic_status:
            try:
                obj = json.loads(payload)
                who = obj.get("sender", "?")
                status = obj.get("content", "")
                if status == "online":
                    print(f"\r🔵 {who} 上线了")
                elif status == "offline":
                    print(f"\r🔴 {who} 离线了")
                else:
                    print(f"\r📢 {who}: {status}")
            except json.JSONDecodeError:
                print(f"\r📢 {payload}")
            print("> ", end="", flush=True)
            return

        # ── 聊天消息 ──
        if not topic.startswith(self.topic_chat_pfx):
            return

        sender = topic[len(self.topic_chat_pfx):]

        # 解析
        try:
            obj = json.loads(payload)
            if isinstance(obj, dict) and obj.get("sender"):
                sender = obj["sender"]
                content = obj.get("content", payload)
                mtype = obj.get("type", "say")
            else:
                content = payload
                mtype = "say"
        except json.JSONDecodeError:
            content = payload
            mtype = "say"

        if sender == self.username:
            return  # 不回显自己

        # 格式化输出
        emoji = {"say": "💬", "think": "🧠", "system": "📢"}.get(mtype, "💬")
        print(f"\r{emoji} {sender}: {content}")
        print("> ", end="", flush=True)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        print(f"\n⚠️ 与 broker 断开连接")
        self._stop.set()

    # ── 公共方法 ──────────────────────────────────────

    def connect(self, timeout=10) -> bool:
        print(f"🔌 连接 {self.broker_host}:{self.broker_port} …", end="", flush=True)
        self.client.connect_async(self.broker_host, self.broker_port)
        self.client.loop_start()

        if not self._ready.wait(timeout):
            print(f"\n❌ 连接超时 ({timeout}s)")
            return False
        return True

    def send(self, text: str):
        msg = {
            "id": uuid.uuid4().hex[:8],
            "sender": self.username,
            "type": "say",
            "content": text,
            "reply_to": None,
            "ts": time.time(),
        }
        topic = f"{self.topic_chat_pfx}{self.username}"
        self.client.publish(topic, json.dumps(msg, ensure_ascii=False))

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("\n👋 已退出")

    def run(self):
        """交互式主循环"""
        print(f"\r{' '*60}\r", end="")
        print(f"╔{'═'*50}╗")
        print(f"║  ✅ 已连接 MQTT broker                               ║")
        print(f"║  你的名字: {self.username:<42}║")
        print(f"║  Channel:   {self.topic_chat_wild:<42}║")
        print(f"╠{'═'*50}╣")
        print(f"║  直接输入文字 + Enter 发送                            ║")
        print(f"║  /quit → 退出                                       ║")
        print(f"╚{'═'*50}╝")
        print("> ", end="", flush=True)

        try:
            while not self._stop.is_set():
                r, _, _ = select.select([sys.stdin], [], [], 0.5)
                if not r:
                    continue

                line = sys.stdin.readline()
                if not line:
                    break

                line = line.strip()
                if not line:
                    print("> ", end="", flush=True)
                    continue

                if line == "/quit":
                    break

                self.send(line)
                print("> ", end="", flush=True)

        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            self.disconnect()


# ── 入口 ──────────────────────────────────────────────

def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="MQTT 简易客户端 — 与 tea_agent 和其他客户端实时聊天")
    ap.add_argument("username", nargs="?", default=None,
                    help="你的用户名（必填）")
    ap.add_argument("--broker", default="localhost",
                    help="MQTT broker 地址 (默认 localhost)")
    ap.add_argument("--port", type=int, default=1883,
                    help="MQTT broker 端口 (默认 1883)")
    ap.add_argument("--prefix", default="tea",
                    help="Topic 前缀/channel (默认 tea)")
    args = ap.parse_args()

    if not args.username:
        print("用法: python mqtt_client.py <用户名> [--broker HOST] [--port PORT] [--prefix PREFIX]")
        print("示例: python mqtt_client.py alice --broker localhost --prefix tea")
        sys.exit(1)

    client = MqttPcClient(
        username=args.username,
        broker_host=args.broker,
        broker_port=args.port,
        topic_prefix=args.prefix,
    )

    if not client.connect():
        sys.exit(1)

    client.run()


if __name__ == "__main__":
    main()
