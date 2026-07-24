"""
微信 iLink Bot 适配器 — Long Polling 模式
==========================================
基于腾讯官方 iLink Bot API（ClawBot 协议）将 tea_agent 接入微信。

原理：
  微信用户 → 微信 App → iLink 服务器 (ilinkai.weixin.qq.com)
                              ↕ HTTP/JSON（长轮询出站连接）
                      WeChatAdapter（本程序）
                              ↕ HTTP
                      tea_agent API (http://127.0.0.1:8282)

✅ 官方协议，合法稳定不封号
✅ 无需公网端口/域名（纯出站连接）
✅ 每个微信用户自动分配独立会话话题
✅ 凭证持久化，重启免扫码
✅ 支持"正在输入"状态

使用方式：
  1. 启动 tea_agent server (tea_agent --port 8282)
  2. 启动微信适配器：

     python -m tea_agent.channel.wechat_adapter
     或：
     tea-agent-wechat --api http://127.0.0.1:8282
"""

import argparse
import base64
import json
import logging
import os
import struct
import threading
import time
import uuid
from pathlib import Path

import httpx

logger = logging.getLogger("wechat_adapter")

# ── 常量 ──
ILINK_BASE = "https://ilinkai.weixin.qq.com"
ILINK_PATH_PREFIX = "/ilink/bot"
DEFAULT_API_BASE = "http://127.0.0.1:8282"
POLL_INTERVAL = 2.0  # 扫码状态轮询间隔（秒）
LONG_POLL_TIMEOUT = 40  # 长轮询客户端超时（秒）
SEND_TIMEOUT = 15  # 发送消息超时（秒）
MAX_REPLY_LEN = 4000  # 微信单条消息最大长度

# 凭证存储路径
CRED_DIR = str(Path.home() / ".tea_agent" / "wechat")
CRED_FILE = os.path.join(CRED_DIR, "credentials.json")
SESSIONS_FILE = os.path.join(CRED_DIR, "wechat_sessions.json")


# ════════════════════════════════════════════════════════════════
#  工具函数
# ════════════════════════════════════════════════════════════════

def _generate_uin() -> str:
    """生成 X-WECHAT-UIN 头：随机 4 字节 → uint32 → 十进制字符串 → base64。"""
    rand_uint32 = struct.unpack("<I", os.urandom(4))[0]
    return base64.b64encode(str(rand_uint32).encode()).decode()


def _make_headers(bot_token: str = "") -> dict:
    """构造通用请求头。"""
    headers = {
        "Content-Type": "application/json",
    }
    if bot_token:
        headers["AuthorizationType"] = "ilink_bot_token"
        headers["Authorization"] = f"Bearer {bot_token}"
        headers["X-WECHAT-UIN"] = _generate_uin()
    return headers


def _base_info() -> dict:
    """构造基础信息体。"""
    return {"base_info": {"channel_version": "2.0.0"}}


def _load_json(path: str) -> dict:
    """从 JSON 文件加载数据。"""
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"加载文件失败 {path}: {e}")
    return {}


def _save_json(path: str, data: dict):
    """保存数据到 JSON 文件。"""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存文件失败 {path}: {e}")


# ════════════════════════════════════════════════════════════════
#  WeChatAdapter
# ════════════════════════════════════════════════════════════════

class WeChatAdapter:
    """微信 iLink Bot 适配器。

    通过微信官方 iLink Bot API 将 tea_agent 接入微信。
    使用 Long Polling 模式接收消息，无需公网端口。

    特性：
    - 扫码登录 + 凭证持久化（重启免扫码）
    - 长轮询接收消息（35s 挂起）
    - 自动显示"正在输入"状态
    - 每个微信用户独立 tea_agent 话题
    - 会话超时自动创建新话题
    - 支持 /commands 命令
    """

    def __init__(
        self,
        api_base_url: str = DEFAULT_API_BASE,
        session_timeout: int = 1800,
        bot_token: str = "",
        base_url: str = ILINK_BASE,
    ):
        """
        Args:
            api_base_url: tea_agent HTTP API 地址
            session_timeout: 会话超时秒数 (默认 1800 = 30 分钟)
            bot_token: 已有的 Bot Token（空则需扫码登录）
            base_url: iLink API 基地址
        """
        self._api_base = api_base_url.rstrip("/")
        self._session_timeout = session_timeout
        self._base_url = base_url.rstrip("/")

        # ── 认证状态 ──
        self._bot_token = bot_token
        self._ilink_bot_id = ""
        self._ilink_user_id = ""

        # ── 消息游标（长轮询） ──
        self._get_updates_buf = ""

        # ── 会话管理 ──
        self._sessions = _load_json(SESSIONS_FILE)  # {wx_user_id: topic_id}
        self._last_active: dict[str, float] = {}  # {wx_user_id: timestamp}

        # ── typing_ticket 缓存 ──
        self._typing_tickets: dict[str, str] = {}  # {wx_user_id: ticket}

        # ── 运行控制 ──
        self._running = False
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._http_client = httpx.Client(timeout=httpx.Timeout(60.0))

    # ──────────────────────────────────────────────
    #  属性
    # ──────────────────────────────────────────────

    @property
    def is_logged_in(self) -> bool:
        return bool(self._bot_token)

    @property
    def bot_token(self) -> str:
        return self._bot_token

    # ──────────────────────────────────────────────
    #  凭证持久化
    # ──────────────────────────────────────────────

    def _load_credentials(self) -> bool:
        """从本地加载已保存的凭证，成功返回 True。"""
        data = _load_json(CRED_FILE)
        token = data.get("bot_token", "")
        if token:
            self._bot_token = token
            self._ilink_bot_id = data.get("ilink_bot_id", "")
            self._ilink_user_id = data.get("ilink_user_id", "")
            self._get_updates_buf = data.get("get_updates_buf", "")
            logger.info("✅ 已从本地加载凭证，跳过扫码")
            return True
        return False

    def _save_credentials(self):
        """保存凭证到本地。"""
        data = {
            "bot_token": self._bot_token,
            "ilink_bot_id": self._ilink_bot_id,
            "ilink_user_id": self._ilink_user_id,
            "get_updates_buf": self._get_updates_buf,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _save_json(CRED_FILE, data)
        logger.info("💾 凭证已保存到 %s", CRED_FILE)

    def _clear_credentials(self):
        """清除本地凭证（会话过期时）。"""
        self._bot_token = ""
        self._ilink_bot_id = ""
        self._ilink_user_id = ""
        self._get_updates_buf = ""
        self._typing_tickets.clear()
        try:
            if os.path.isfile(CRED_FILE):
                os.remove(CRED_FILE)
                logger.info("🧹 已清除过期凭证")
        except Exception as e:
            logger.warning(f"清除凭证失败: {e}")

    # ──────────────────────────────────────────────
    #  扫码登录
    # ──────────────────────────────────────────────

    def login(self, force: bool = False) -> bool:
        """扫码登录微信 Bot。

        Args:
            force: True=强制重新登录（忽略已有凭证）

        Returns:
            bool: 是否登录成功
        """
        if not force and self._load_credentials():
            return True

        print("=" * 52)
        print("  🔐  微信 Bot 登录")
        print("=" * 52)

        # 1. 获取二维码
        try:
            qr_resp = self._http_client.get(
                f"{self._base_url}{ILINK_PATH_PREFIX}/get_bot_qrcode",
                params={"bot_type": "3"},
                headers=_make_headers(),
            )
            qr_resp.raise_for_status()
            qr_data = qr_resp.json()
        except Exception as e:
            logger.error(f"获取二维码失败: {e}")
            print(f"❌ 获取二维码失败: {e}")
            return False

        qrcode_key = qr_data.get("qrcode", "")
        qrcode_url = qr_data.get("qrcode_img_content", "")

        if not qrcode_key or not qrcode_url:
            logger.error(f"二维码数据异常: {qr_data}")
            print("❌ 二维码数据异常")
            return False

        print("\n📱 请使用微信扫描以下二维码：")
        print(f"  {qrcode_url}")
        print("\n⏳ 等待扫码...（每 2 秒轮询）")
        print("   🔴 按 Ctrl+C 取消\n")

        # 尝试用 terminal 显示二维码图片（如果可用）
        self._display_qrcode(qrcode_url)

        # 2. 轮询扫码状态
        start_time = time.time()
        while not self._stop_event.is_set():
            try:
                status_resp = self._http_client.get(
                    f"{self._base_url}{ILINK_PATH_PREFIX}/get_qrcode_status",
                    params={"qrcode": qrcode_key},
                    headers=_make_headers(),
                )
                status_resp.raise_for_status()
                status_data = status_resp.json()
            except Exception as e:
                logger.warning(f"轮询扫码状态失败: {e}")
                time.sleep(POLL_INTERVAL)
                continue

            status = status_data.get("status", "")

            if status == "wait":
                # 等待扫描
                elapsed = int(time.time() - start_time)
                if elapsed % 6 == 0:  # 每 6 秒提示一次
                    print(f"  ⏳ 等待扫码... ({elapsed}s)")
            elif status == "scaned":
                print("  ✅ 已扫描！请在手机上确认登录")
            elif status == "confirmed":
                # 登录成功！
                self._bot_token = status_data.get("bot_token", "")
                self._ilink_bot_id = status_data.get("ilink_bot_id", "")
                self._ilink_user_id = status_data.get("ilink_user_id", "")
                returned_baseurl = status_data.get("baseurl", "")
                if returned_baseurl:
                    self._base_url = returned_baseurl

                if not self._bot_token:
                    logger.error("登录成功但未获取到 bot_token")
                    print("❌ 登录失败：未获取到 bot_token")
                    return False

                self._save_credentials()
                print("\n🎉  登录成功！")
                print(f"  🤖 Bot ID: {self._ilink_bot_id}")
                print(f"  👤 User ID: {self._ilink_user_id}")
                print(f"  🌐 Base URL: {self._base_url}")
                return True
            elif status == "expired":
                print("  ⏰ 二维码已过期，请重新运行")
                return False
            else:
                logger.debug(f"未知状态: {status}")

            if time.time() - start_time > 180:
                print("  ⏰ 登录超时（3 分钟）")
                return False

            time.sleep(POLL_INTERVAL)

        return False

    @staticmethod
    def _display_qrcode(url: str):
        """尝试用终端显示二维码。"""
        try:
            # 尝试使用 qr 库显示
            import io

            import qrcode
            from PIL import Image

            resp = httpx.get(url, timeout=10)
            Image.open(io.BytesIO(resp.content))
            # 在终端显示 ASCII 二维码（如果 qrcode 库可用）
            qr = qrcode.QRCode()
            qr.add_data(url)
            qr.print_ascii(invert=True)
            return
        except ImportError:
            pass
        except Exception:
            pass

        # 尝试使用 qrterminal
        try:
            import qrterm
            qrterm.generate(url, small=True)
        except ImportError:
            pass

    # ──────────────────────────────────────────────
    #  消息收发 - 核心循环
    # ──────────────────────────────────────────────

    def _poll_loop(self):
        """长轮询消息循环（在独立线程中运行）。"""
        logger.info("📡 开始长轮询消息...")

        while self._running and not self._stop_event.is_set():
            if not self._bot_token:
                logger.error("未登录，停止轮询")
                break

            try:
                payload = {
                    "get_updates_buf": self._get_updates_buf,
                    **_base_info(),
                }

                resp = self._http_client.post(
                    f"{self._base_url}{ILINK_PATH_PREFIX}/getupdates",
                    json=payload,
                    headers=_make_headers(self._bot_token),
                    timeout=LONG_POLL_TIMEOUT + 5,
                )

                # HTTP 4xx/5xx 处理
                if resp.status_code == 401:
                    logger.warning("Token 无效或已过期，需重新登录")
                    self._clear_credentials()
                    break
                elif resp.status_code >= 500:
                    logger.warning(f"服务端错误 HTTP {resp.status_code}，等待重试...")
                    time.sleep(5)
                    continue

                resp.raise_for_status()
                data = resp.json()

            except httpx.TimeoutException:
                # 长轮询超时是正常的（35s 后服务器无消息）
                continue
            except httpx.RequestError as e:
                logger.warning(f"网络错误: {e}")
                time.sleep(3)
                continue
            except Exception as e:
                logger.warning(f"轮询异常: {e}")
                time.sleep(3)
                continue

            # 检查会话过期
            ret = data.get("ret", 0)
            if ret == -14 or data.get("errcode") == -14:
                logger.warning("⚠️ 会话已过期（errcode -14），清除凭证")
                self._clear_credentials()
                break

            # 更新游标
            new_buf = data.get("get_updates_buf", "")
            if new_buf:
                self._get_updates_buf = new_buf
                # 持久化游标
                self._save_credentials()

            # 处理消息
            msgs = data.get("msgs", [])
            for msg in msgs:
                try:
                    self._handle_incoming(msg)
                except Exception as e:
                    logger.exception(f"处理消息异常: {e}")

        logger.info("📡 消息轮询已停止")

    def _handle_incoming(self, msg: dict):
        """处理单条入站消息。

        消息结构（文本消息示例）：
        {
            "from_user_id": "wx_xxx",
            "to_user_id": "",
            "msg_id": "msg_xxx",
            "message_type": 1,      # 1=用户消息, 2=Bot消息
            "message_state": 1,     # 1=完整消息
            "context_token": "ct_xxx",
            "item_list": [
                {"type": 1, "text_item": {"text": "你好"}}
            ],
            "send_time": 1234567890,
        }
        """
        # 跳过 Bot 自己的消息
        msg_type = msg.get("message_type", 0)
        if msg_type == 2:
            return

        from_user = msg.get("from_user_id", "")
        context_token = msg.get("context_token", "")
        msg.get("send_time", 0)

        if not from_user or not context_token:
            logger.warning("消息缺少 from_user_id 或 context_token")
            return

        # 提取文本内容
        text = ""
        item_list = msg.get("item_list", [])
        for item in item_list:
            if item.get("type") == 1 and "text_item" in item:
                text = item["text_item"].get("text", "")
                break

        if not text:
            logger.info(f"[{from_user}] 收到非文本消息（跳过）")
            return

        # 检查是否是命令
        if text.startswith("/"):
            self._handle_command(from_user, context_token, text)
            return

        logger.info(f"📩 [{from_user[:12]}...]: {text[:80]}")

        # 发送"正在输入"状态
        self._send_typing(from_user, context_token)

        # 调用 tea_agent API
        reply = self._call_tea_agent(from_user, text)

        # 发送回复
        if reply:
            self._send_message(from_user, context_token, reply)

    def _handle_command(self, user_id: str, context_token: str, cmd_text: str):
        """处理以 / 开头的命令。"""
        parts = cmd_text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        parts[1] if len(parts) > 1 else ""

        if cmd == "/start" or cmd == "/help":
            reply = (
                "🤖 *Tea Agent - 微信助手*\n\n"
                "已连接到 AI 助手，直接发送消息即可对话。\n\n"
                "📋 *命令*\n"
                "/start - 显示此帮助\n"
                "/new - 开始新话题\n"
                "/topic - 查看当前话题\n"
                "/about - 关于\n\n"
                "💬 发送任意消息开始对话。"
            )
        elif cmd == "/new":
            # 清除话题映射
            uid_key = str(user_id)
            old_topic = self._sessions.get(uid_key, "")
            if uid_key in self._sessions:
                del self._sessions[uid_key]
                _save_json(SESSIONS_FILE, self._sessions)
            if uid_key in self._last_active:
                del self._last_active[uid_key]
            reply = "✅ 已创建新话题"
            if old_topic:
                reply += "（旧话题已归档）"
        elif cmd == "/topic":
            uid_key = str(user_id)
            current_id = self._sessions.get(uid_key, "")
            reply = f"📌 当前话题 ID: `{current_id[:16]}...`" if current_id else "📌 暂无活跃话题，发送消息将自动创建。"
        elif cmd == "/about":
            reply = (
                "ℹ️ *Tea Agent 微信助手*\n\n"
                "基于腾讯官方 iLink Bot API 实现，"
                "合法稳定不封号。\n\n"
                "*架构*\n"
                "微信 → iLink 服务器 → WeChatAdapter → tea_agent AI\n\n"
                "*能力*\n"
                "• 文本对话\n"
                "• 多话题隔离\n"
                "• 凭证持久化\n"
                "• 长轮询实时消息"
            )
        else:
            reply = f"❌ 未知命令: {cmd}\n使用 /help 查看可用命令。"

        self._send_message(user_id, context_token, reply)

    # ──────────────────────────────────────────────
    #  发送消息 / Typing
    # ──────────────────────────────────────────────

    def _send_typing(self, user_id: str, context_token: str, status: int = 1):
        """发送"正在输入"状态。

        需要两步：
        1. 获取 typing_ticket（按用户缓存，有效期约 24h）
        2. 发送 typing 状态

        Args:
            user_id: 微信用户 ID
            context_token: 上下文 token
            status: 1=开始, 2=停止
        """
        if status == 2:
            # 停止 typing：直接发
            ticket = self._typing_tickets.get(user_id, "")
            if not ticket:
                return
            try:
                payload = {
                    "ilink_user_id": user_id,
                    "typing_ticket": ticket,
                    "status": 2,
                    **_base_info(),
                }
                self._http_client.post(
                    f"{self._base_url}{ILINK_PATH_PREFIX}/sendtyping",
                    json=payload,
                    headers=_make_headers(self._bot_token),
                    timeout=SEND_TIMEOUT,
                )
            except Exception:
                pass
            return

        # status == 1: 先获取 ticket
        ticket = self._typing_tickets.get(user_id, "")
        if not ticket:
            try:
                config_payload = {
                    "ilink_user_id": user_id,
                    "context_token": context_token,
                    **_base_info(),
                }
                config_resp = self._http_client.post(
                    f"{self._base_url}{ILINK_PATH_PREFIX}/getconfig",
                    json=config_payload,
                    headers=_make_headers(self._bot_token),
                    timeout=SEND_TIMEOUT,
                )
                config_resp.raise_for_status()
                config_data = config_resp.json()
                ticket = config_data.get("typing_ticket", "")
                if ticket:
                    self._typing_tickets[user_id] = ticket
            except Exception as e:
                logger.warning(f"获取 typing_ticket 失败: {e}")
                return

        if not ticket:
            return

        # 发送 typing 状态
        try:
            payload = {
                "ilink_user_id": user_id,
                "typing_ticket": ticket,
                "status": 1,
                **_base_info(),
            }
            self._http_client.post(
                f"{self._base_url}{ILINK_PATH_PREFIX}/sendtyping",
                json=payload,
                headers=_make_headers(self._bot_token),
                timeout=SEND_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"发送 typing 状态失败: {e}")

    def _send_message(self, to_user: str, context_token: str, text: str):
        """发送文本消息给微信用户。

        Args:
            to_user: 目标用户 ID
            context_token: 上下文 token
            text: 消息文本
        """
        if not text:
            return

        # 消息分段（微信单条消息有限制）
        max_len = MAX_REPLY_LEN
        segments = []
        if len(text) <= max_len:
            segments = [text]
        else:
            for i in range(0, len(text), max_len):
                chunk = text[i:i + max_len]
                if i > 0:
                    chunk = f"📎 (续 {i // max_len + 1})\n\n{chunk}"
                segments.append(chunk)

        for segment in segments:
            try:
                payload = {
                    "msg": {
                        "from_user_id": "",
                        "to_user_id": to_user,
                        "client_id": f"ta-{uuid.uuid4().hex[:16]}",
                        "message_type": 2,
                        "message_state": 2,
                        "context_token": context_token,
                        "item_list": [
                            {"type": 1, "text_item": {"text": segment}}
                        ],
                    },
                    **_base_info(),
                }

                resp = self._http_client.post(
                    f"{self._base_url}{ILINK_PATH_PREFIX}/sendmessage",
                    json=payload,
                    headers=_make_headers(self._bot_token),
                    timeout=SEND_TIMEOUT,
                )

                if resp.status_code == 401:
                    logger.warning("发送消息时 Token 失效")
                    self._clear_credentials()
                    break

                resp.raise_for_status()
                result = resp.json()
                ret = result.get("ret", 0)
                if ret != 0:
                    logger.warning(f"发送消息返回异常 ret={ret}: {result}")

                logger.info(f"📤 [{to_user[:12]}...]: {segment[:60]}...")

            except httpx.RequestError as e:
                logger.error(f"发送消息网络错误: {e}")
                break
            except Exception as e:
                logger.error(f"发送消息异常: {e}")
                break

        # 停止 typing 状态
        self._send_typing(to_user, context_token, status=2)

    # ──────────────────────────────────────────────
    #  tea_agent API 调用
    # ──────────────────────────────────────────────

    def _get_or_create_topic(self, wx_user_id: str) -> str:
        """获取或创建微信用户对应的 tea_agent 话题。

        策略：
        1. 优先从持久化 sessions 中读取话题映射
        2. 检查会话是否超时（超时则创建新话题）
        3. 若不存在，调用 API 创建新话题
        """
        uid_key = str(wx_user_id)
        topic_id = self._sessions.get(uid_key, "")
        now = time.time()

        # 检查超时
        last_active = self._last_active.get(uid_key, 0)
        if topic_id and last_active > 0 and (now - last_active) > self._session_timeout:
            logger.info(f"用户 {wx_user_id[:12]}... 会话超时，创建新话题")
            topic_id = ""

        # 需要创建新话题
        if not topic_id:
            try:
                resp = httpx.post(
                    f"{self._api_base}/v1/sessions",
                    json={"title": f"微信用户 {wx_user_id[:12]}..."},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                topic_id = data.get("id", "")
                if topic_id:
                    self._sessions[uid_key] = topic_id
                    _save_json(SESSIONS_FILE, self._sessions)
                    logger.info(f"创建话题 {topic_id[:12]} 用于微信用户 {wx_user_id[:12]}...")
            except httpx.RequestError as e:
                logger.warning(f"创建话题失败 (连接错误): {e}")
            except Exception as e:
                logger.warning(f"创建话题失败: {e}")

        return topic_id

    def _call_tea_agent(self, wx_user_id: str, message: str) -> str:
        """向 tea_agent API 发送消息并获取回复。

        Args:
            wx_user_id: 微信用户 ID
            message: 用户消息文本

        Returns:
            str: AI 回复文本
        """
        topic_id = self._get_or_create_topic(wx_user_id)

        payload = {
            "model": "default",
            "messages": [{"role": "user", "content": message}],
            "stream": False,
        }
        if topic_id:
            payload["topic_id"] = topic_id

        try:
            resp = httpx.post(
                f"{self._api_base}/v1/chat/completions",
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()

            choices = data.get("choices", [])
            reply = choices[0].get("message", {}).get("content", "") if choices else data.get("text", "") or str(data)

            if not reply:
                reply = "（无回复）"

            self._last_active[str(wx_user_id)] = time.time()
            return reply

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            detail = e.response.text[:200]
            logger.error(f"API 请求失败 (HTTP {status}): {detail}")
            if status == 503:
                return (
                    "⚠️ tea_agent 服务未就绪\n\n"
                    "请确认 tea_agent server 正在运行且模型已配置。\n"
                    "启动方式: `tea_agent`"
                )
            return f"❌ 服务器错误 (HTTP {status})"
        except httpx.TimeoutException:
            logger.error("API 请求超时")
            return "⏳ 请求超时，tea_agent 处理时间过长，请稍后重试。"
        except httpx.RequestError as e:
            logger.error(f"无法连接到 tea_agent API: {e}")
            return (
                "🔌 无法连接到 tea_agent\n\n"
                f"请确认服务器已启动。\n"
                f"当前 API: {self._api_base}\n"
                f"启动方式: `tea_agent`"
            )
        except Exception as e:
            logger.exception(f"调用 API 异常: {e}")
            return f"❌ 内部错误: {type(e).__name__}"

    # ──────────────────────────────────────────────
    #  API 辅助方法（用于命令）
    # ──────────────────────────────────────────────

    def _api_get(self, path: str, timeout: int = 10) -> dict | None:
        try:
            resp = httpx.get(f"{self._api_base}{path}", timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"API GET {path} 失败: {e}")
            return None

    def _api_post(self, path: str, json_data: dict | None = None, timeout: int = 10) -> dict | None:
        try:
            resp = httpx.post(f"{self._api_base}{path}", json=json_data or {}, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"API POST {path} 失败: {e}")
            return None

    # ──────────────────────────────────────────────
    #  启动 / 停止
    # ──────────────────────────────────────────────

    def start(self):
        """启动 WeChat Bot（同步阻塞）。"""
        # 登录
        if not self.is_logged_in and not self.login():
            print("❌ 登录失败，退出")
            return

        print("=" * 52)
        print("  🤖  Tea Agent 微信 Bot")
        print("  📡  模式: Long Polling (出站连接，无需公网)")
        print(f"  🔗  API: {self._api_base}")
        print(f"  📋  活跃会话: {len(self._sessions)}")
        print("=" * 52)

        self._running = True
        self._stop_event.clear()

        # 启动轮询线程
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

        print("  ✅ 已就绪，等待消息...")
        print("  ⏹️  Ctrl+C 停止")
        print("=" * 52)

        try:
            # 主线程保持运行
            while self._running:
                time.sleep(1)

                # 检查 token 是否有效
                if not self._bot_token:
                    logger.warning("Token 已失效，尝试重新登录...")
                    print("\n🔄 Token 已失效，尝试重新登录...")
                    if self.login(force=True):
                        # 重新启动轮询
                        self._poll_thread = threading.Thread(
                            target=self._poll_loop, daemon=True
                        )
                        self._poll_thread.start()
                    else:
                        print("❌ 重新登录失败")
                        break

        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            logger.exception(f"运行异常: {e}")
        finally:
            self._running = False

    def stop(self):
        """优雅停止 Bot。"""
        self._running = False
        self._stop_event.set()
        print("\n🛑 Bot 正在停止...")

        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5)

        self._http_client.close()
        print("🛑 Bot 已停止。")


# ════════════════════════════════════════════════════════════════
#  CLI 入口
# ════════════════════════════════════════════════════════════════

def run_wechat_bot():
    """CLI 入口：启动微信 Bot 适配器。"""
    parser = argparse.ArgumentParser(
        description="Tea Agent 微信 Bot — Long Polling 模式 (无需公网端口)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""使用示例：
  tea-agent-wechat
  tea-agent-wechat --api http://127.0.0.1:8282
  tea-agent-wechat --api http://192.168.1.100:8282 --debug
        """,
    )
    parser.add_argument(
        "--api",
        default=os.environ.get("TEA_AGENT_API_URL", DEFAULT_API_BASE),
        help=f"tea_agent API 地址 (默认: {DEFAULT_API_BASE})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("WECHAT_SESSION_TIMEOUT", "1800")),
        help="会话超时秒数 (默认: 1800 = 30 分钟)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("WECHAT_BOT_TOKEN", ""),
        help="已有 Bot Token（跳过扫码）",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试日志",
    )

    args = parser.parse_args()

    # ── 日志配置 ──
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.debug:
        for name in ["httpx", "httpcore", "urllib3"]:
            logging.getLogger(name).setLevel(logging.WARNING)

    # ── 启动 ──
    adapter = WeChatAdapter(
        api_base_url=args.api,
        session_timeout=args.timeout,
        bot_token=args.token,
    )
    try:
        adapter.start()
    except KeyboardInterrupt:
        adapter.stop()


if __name__ == "__main__":
    run_wechat_bot()
