"""
Telegram Bot Adapter - Long Polling 模式
========================================
通过 Telegram Bot API 将 tea_agent 接入手机/桌面端。

原理：
  用户 → Telegram → (Long Polling 出站连接) → Telegram API 服务器
       ↓  (bot 收到消息后通过本地 HTTP 调用 tea_agent)
  tea_agent API (http://127.0.0.1:8282/v1/chat/completions)
       ↓  (回复发回 Telegram)
  用户 ← Telegram ← Bot

✅ 无需公网端口/域名
✅ 每个 Telegram 用户自动分配独立会话话题
✅ 支持长消息自动分段
✅ 会话持久化（重启后恢复）

使用方式：
  1. 在 @BotFather 创建 Bot，获取 TOKEN
  2. 启动 tea_agent server (tea_agent --port 8282)
  3. 启动 Telegram 适配器：

     export TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
     python -m tea_agent.channel.telegram_adapter

     或：

     tea-agent-telegram --token 123456:ABC-DEF... --api http://127.0.0.1:8282
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger("telegram_adapter")

SESSION_FILE = str(Path.home() / ".tea_agent" / "telegram_sessions.json")


def _load_sessions() -> dict:
    try:
        if os.path.isfile(SESSION_FILE):
            with open(SESSION_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"加载会话映射失败: {e}")
    return {}


def _save_sessions(sessions: dict):
    try:
        Path(SESSION_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存会话映射失败: {e}")


class TelegramAdapter:
    """Telegram Bot 适配器（Long Polling 模式）。

    通过 telegram bot 的 getUpdates 长轮询接收消息，
    转发到 tea_agent HTTP API，返回回复给用户。

    特性：
    - 无需公网端口（出站连接）
    - 自动管理话题会话（每个 Telegram 用户独立话题）
    - 长消息分段发送（Telegram 单条 4096 字符限制）
    - 会话持久化到 ~/.tea_agent/telegram_sessions.json
    """

    def __init__(
        self,
        bot_token: str,
        api_base_url: str = "http://127.0.0.1:8282",
        session_timeout: int = 1800,
    ):
        """
        Args:
            bot_token: Telegram Bot Token (从 @BotFather 获取)
            api_base_url: tea_agent HTTP API 地址
            session_timeout: 会话超时秒数 (默认 1800 = 30 分钟)
        """
        self._bot_token = bot_token
        self._api_base = api_base_url.rstrip("/")
        self._session_timeout = session_timeout
        self._sessions = _load_sessions()
        self._last_active: dict[int, float] = {}
        self._running = False

    # ── HTTP 调用 tea_agent ──

    def _get_or_create_topic(self, user_id: int) -> str:
        """获取或创建用户的 topic_id。

        策略：
        1. 优先从持久化 sessions 中读取
        2. 检查会话是否超时（超时则创建新话题）
        3. 若不存在或超时，调用 API 创建新话题
        """
        uid = str(user_id)
        topic_id = self._sessions.get(uid, "")
        now = time.time()

        # 检查超时
        last_active = self._last_active.get(user_id, 0)
        if topic_id and last_active > 0 and (now - last_active) > self._session_timeout:
            logger.info(f"User {user_id} 会话超时，创建新话题")
            topic_id = ""

        # 需要创建新话题
        if not topic_id:
            try:
                resp = httpx.post(
                    f"{self._api_base}/v1/sessions",
                    json={"title": f"Telegram User {user_id}"},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                topic_id = data.get("id", "")
                if topic_id:
                    self._sessions[uid] = topic_id
                    _save_sessions(self._sessions)
                    logger.info(f"Created topic {topic_id[:12]} for user {user_id}")
            except httpx.RequestError as e:
                logger.warning(f"创建话题失败 (连接错误): {e}")
            except Exception as e:
                logger.warning(f"创建话题失败: {e}")

        return topic_id

    def _call_tea_agent(self, user_id: int, message: str) -> str:
        """向 tea_agent API 发送消息并获取回复。"""
        topic_id = self._get_or_create_topic(user_id)

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
            if choices:
                reply = choices[0].get("message", {}).get("content", "")
            else:
                reply = data.get("text", "") or str(data)

            if not reply:
                reply = "（无回复）"

            self._last_active[user_id] = time.time()
            return reply

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            detail = e.response.text[:200]
            logger.error(f"API 请求失败 (HTTP {status}): {detail}")
            if status == 503:
                return (
                    "⚠️ *tea_agent 服务未就绪*\n\n"
                    "请确认 tea_agent server 正在运行且模型已配置。\n"
                    "> 启动方式: `tea_agent`"
                )
            return f"❌ 服务器错误 (HTTP {status})"
        except httpx.TimeoutException:
            logger.error("API 请求超时")
            return "⏳ *请求超时*\n\ntea_agent 处理时间过长，请稍后重试。"
        except httpx.RequestError as e:
            logger.error(f"无法连接到 tea_agent API: {e}")
            return (
                "🔌 *无法连接到 tea_agent*\n\n"
                f"请确认服务器已启动且 API 地址正确。\n"
                f"> 当前 API: `{self._api_base}`\n"
                f"> 启动方式: `tea_agent`"
            )
        except Exception as e:
            logger.exception(f"调用 API 异常: {e}")
            return f"❌ 内部错误: {type(e).__name__}"

    # ── API 辅助方法 ──

    def _api_get(self, path: str, timeout: int = 10) -> dict | None:
        """通用 GET 请求封装。"""
        try:
            resp = httpx.get(f"{self._api_base}{path}", timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"API GET {path} 失败: {e}")
            return None

    def _api_post(self, path: str, json_data: dict | None = None, timeout: int = 10) -> dict | None:
        """通用 POST 请求封装。"""
        try:
            resp = httpx.post(f"{self._api_base}{path}", json=json_data or {}, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"API POST {path} 失败: {e}")
            return None

    def _list_configs(self) -> list[dict]:
        """获取可用配置列表。"""
        data = self._api_get("/api/configs")
        if data:
            return data.get("configs", [])
        return []

    def _get_current_config_info(self) -> dict:
        """获取当前配置信息。"""
        data = self._api_get("/v1/config")
        return data or {}

    def _switch_config(self, config_path: str) -> dict:
        """切换配置。"""
        result = self._api_post("/v1/config/switch", {"config_path": config_path})
        return result or {"ok": False, "error": "API 无响应"}

    def _list_sessions(self, limit: int = 10) -> list[dict]:
        """获取会话列表。"""
        data = self._api_get(f"/v1/sessions?limit={limit}")
        if data:
            return data.get("data", [])
        return []

    def _get_session_info(self, topic_id: str) -> dict | None:
        """获取单个会话信息。"""
        return self._api_get(f"/v1/sessions/{topic_id}")

    def _format_configs(self, configs: list, active_filename: str = "") -> str:
        """格式化配置列表为可读文本。"""
        lines = ["📋 *可用配置：*"]
        for cfg in configs:
            name = cfg.get("filename", "?")
            valid = "✅" if cfg.get("is_valid") else "⚠️"
            model = cfg.get("main_model", {}).get("model_name", "?") or "?"
            active_flag = " ◀ 当前" if name == active_filename else ""
            lines.append(f"  {valid} `{name}`  →  {model}{active_flag}")
        lines.append("")
        lines.append("💡 使用 `/config <文件名>` 切换")
        return "\n".join(lines)

    # ── Telegram 消息处理 ──

    async def _handle_message(self, update, context):
        """处理用户消息。"""
        if not update.message or not update.message.text:
            return

        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "用户"
        text = update.message.text.strip()

        logger.info(f"📩 [{user_id}] {user_name}: {text[:80]}")

        # 显示"正在输入"状态
        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action="typing",
            )
        except Exception:
            pass

        # 调用 tea_agent
        reply = self._call_tea_agent(user_id, text)

        # 分段发送（Telegram 单条消息上限 ~4096 字符）
        max_len = 4000
        if len(reply) <= max_len:
            await update.message.reply_text(reply)
        else:
            for i in range(0, len(reply), max_len):
                chunk = reply[i : i + max_len]
                if i == 0:
                    await update.message.reply_text(chunk)
                else:
                    await update.message.reply_text(f"📎 (续 {i // max_len + 1})\n\n{chunk}")

    async def _handle_error(self, update, context):
        """处理 Bot 运行错误。"""
        logger.error(f"Telegram Bot 错误: {context.error}")

    async def _handle_start(self, update, context):
        """处理 /start 命令。"""
        help_text = (
            "🤖 *Tea Agent Telegram Bot*\n\n"
            "已连接到 tea_agent AI 助手，直接发送消息即可对话。\n\n"
            "📋 *命令*\n"
            "/start - 显示帮助\n"
            "/config - 查看/切换配置文件\n"
            "/topics - 列出最近会话\n"
            "/topic - 查看/切换当前话题\n"
            "/new - 开始新话题\n"
            "/about - 关于本 Bot\n\n"
            "💬 提示：发送任意消息开始对话。"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def _handle_new(self, update, context):
        """处理 /new 命令 - 创建新话题。"""
        user_id = update.effective_user.id
        uid = str(user_id)
        old_topic = self._sessions.get(uid, "")

        # 清除旧话题映射，下次消息自动创建新话题
        del self._sessions[uid]
        _save_sessions(self._sessions)
        if uid in self._last_active:
            del self._last_active[int(uid)]

        info = f"✅ 已创建新话题"
        if old_topic:
            info += f"（旧话题 {old_topic[:8]}... 已归档）"
        await update.message.reply_text(info)

    async def _handle_about(self, update, context):
        """处理 /about 命令。"""
        about_text = (
            "ℹ️ *关于 Tea Agent Telegram Bot*\n\n"
            "这是 tea_agent 的消息渠道适配器，通过 Telegram Bot API "
            "（Long Polling 模式）将 AI 助手带到你的手机。\n\n"
            "*技术特点*\n"
            "• 无需公网端口/域名\n"
            "• 所有请求走本地网络\n"
            "• 每个用户独立会话历史\n"
            "• 会话持久化到本地文件\n\n"
            "*架构*\n"
            "`手机 → Telegram → Bot(出站轮询) → tea_agent API`"
        )
        await update.message.reply_text(about_text, parse_mode="Markdown")

    # ── 新命令：/config ──

    async def _handle_config(self, update, context):
        """处理 /config 命令 - 显示/切换配置。"""
        parts = context.args
        configs = self._list_configs()
        # 获取当前配置文件名
        active_filename = ""
        config_info = self._get_current_config_info()
        if config_info:
            api_url = config_info.get("api_url", "")
            model = config_info.get("model", "")
        else:
            api_url = ""
            model = ""

        if parts:
            # 尝试切换配置
            filename = parts[0]
            target = None
            for cfg in configs:
                if cfg.get("filename") == filename or cfg.get("path") == filename:
                    target = cfg.get("path")
                    break
                if filename.casefold() in cfg.get("filename", "").casefold():
                    target = cfg.get("path")
                    break
            if not target:
                msg = f"❌ 未找到配置 `{filename}`\n\n"
                msg += self._format_configs(configs)
                await update.message.reply_text(msg, parse_mode="Markdown")
                return
            result = self._switch_config(target)
            if result.get("ok"):
                await update.message.reply_text(
                    f"✅ 已切换到配置 `{Path(target).name}`\n"
                    f"   🔄 新会话将使用新配置",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"❌ 切换失败: {result.get('error', '未知错误')}"
                )
        else:
            # 显示当前配置 + 可用配置列表
            msg = f"📌 *当前配置*\n"
            if model:
                msg += f"  模型: `{model}`\n"
            if api_url:
                msg += f"  API: `{api_url}`\n"
            msg += "\n"
            msg += self._format_configs(configs, active_filename=active_filename)
            await update.message.reply_text(msg, parse_mode="Markdown")

    # ── 新命令：/topics ──

    async def _handle_topics(self, update, context):
        """处理 /topics 命令 - 列出最近会话。"""
        sessions = self._list_sessions(limit=15)
        if not sessions:
            await update.message.reply_text("📭 暂无会话记录。")
            return

        lines = ["📋 *最近会话：*"]
        for s in sessions:
            tid = s.get("id", "")[:8]
            title = s.get("title", "?") or "?"
            updated = s.get("updated", "")[:10]
            tokens = s.get("total_tokens", 0)
            lines.append(f"  `{tid}`  {title}")
        lines.append("")
        lines.append(f"共 {len(sessions)} 个会话")
        lines.append("💡 使用 `/topic <id>` 切换到指定会话")
        lines.append("     使用 `/new` 创建新会话")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ── 新命令：/topic ──

    async def _handle_topic(self, update, context):
        """处理 /topic 命令 - 查看/切换当前话题。"""
        user_id = update.effective_user.id
        parts = context.args

        if parts:
            # 切换到指定话题
            topic_prefix = parts[0]
            sessions = self._list_sessions(limit=50)
            target = None
            for s in sessions:
                sid = s.get("id", "")
                if sid == topic_prefix or sid.startswith(topic_prefix):
                    target = sid
                    break

            if not target:
                await update.message.reply_text(
                    f"❌ 未找到话题 `{topic_prefix}`\n"
                    "使用 `/topics` 查看可用话题。"
                )
                return

            # 切换当前用户的话题映射
            uid = str(user_id)
            old_topic = self._sessions.get(uid, "")
            self._sessions[uid] = target
            _save_sessions(self._sessions)
            self._last_active[user_id] = time.time()

            info = f"✅ 已切换到话题 `{target[:12]}...`"
            if old_topic and old_topic != target:
                info += f"\n📦 旧话题 `{old_topic[:8]}...` 已归档"
            await update.message.reply_text(info)
        else:
            # 显示当前话题信息
            uid = str(user_id)
            current_id = self._sessions.get(uid, "")
            if current_id:
                info = self._get_session_info(current_id)
                if info:
                    title = info.get("title", "?") or "?"
                    created = info.get("created", "")[:10]
                    tokens = info.get("total_tokens", 0)
                    await update.message.reply_text(
                        f"📌 *当前话题*\n\n"
                        f"ID: `{current_id[:16]}...`\n"
                        f"标题: {title}\n"
                        f"创建时间: {created}\n"
                        f"Token 使用: {tokens:,}\n\n"
                        f"💡 `/topic <id>` 切换\n"
                        f"    `/topics` 查看列表",
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(f"📌 当前话题 ID: `{current_id[:16]}...`")
            else:
                await update.message.reply_text("📌 暂无活跃话题，发送消息将自动创建。")

    # ── 启动/停止 ──

    def start(self):
        """启动 Telegram Bot（同步阻塞，Long Polling 模式）。"""
        try:
            from telegram import Update
            from telegram.ext import Application, CommandHandler, MessageHandler, filters
        except ImportError:
            print("❌ 需要安装 python-telegram-bot 库")
            print("    pip install python-telegram-bot>=20.0")
            sys.exit(1)

        print("=" * 52)
        print(f"  🤖  Tea Agent Telegram Bot")
        print(f"  📡  模式: Long Polling (出站连接，无需公网)")
        print(f"  🔗  API: {self._api_base}")
        print(f"  ⏱   会话超时: {self._session_timeout // 60} 分钟")
        active = len([u for u, t in self._sessions.items() if t])
        print(f"  📋  活跃会话: {active}")
        print("=" * 52)

        self._application = Application.builder().token(self._bot_token).build()

        # 注册命令处理器
        self._application.add_handler(CommandHandler("start", self._handle_start))
        self._application.add_handler(CommandHandler("new", self._handle_new))
        self._application.add_handler(CommandHandler("help", self._handle_start))
        self._application.add_handler(CommandHandler("about", self._handle_about))
        self._application.add_handler(CommandHandler("config", self._handle_config))
        self._application.add_handler(CommandHandler("topics", self._handle_topics))
        self._application.add_handler(CommandHandler("topic", self._handle_topic))
        self._application.add_handler(CommandHandler("sessions", self._handle_topics))
        # 文本消息处理器（排除命令）
        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        self._application.add_error_handler(self._handle_error)

        print("  ✅ 已就绪，等待消息...")
        print("  ⏹️  Ctrl+C 停止")
        print("=" * 52)

        self._running = True
        try:
            self._application.run_polling(allowed_updates=Update.ALL_TYPES)
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            logger.exception(f"Bot 运行异常: {e}")
        finally:
            self._running = False

    def stop(self):
        """停止 Bot。"""
        self._running = False
        print("\n🛑 Bot 已停止。")


def run_telegram_bot():
    """CLI 入口：启动 Telegram Bot 适配器。"""
    parser = argparse.ArgumentParser(
        description="Tea Agent Telegram Bot — Long Polling 模式 (无需公网端口)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""使用示例：
  tea-agent-telegram
  tea-agent-telegram --token 123456:ABC-DEF...
  tea-agent-telegram --api http://127.0.0.1:8282
  tea-agent-telegram --token TOKEN --api http://192.168.1.100:8282
        """,
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        help="Telegram Bot Token（从 @BotFather 获取）",
    )
    parser.add_argument(
        "--api",
        default=os.environ.get("TEA_AGENT_API_URL", "http://127.0.0.1:8282"),
        help="tea_agent API 地址 (默认: http://127.0.0.1:8282)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("TELEGRAM_SESSION_TIMEOUT", "1800")),
        help="会话超时秒数 (默认: 1800 = 30 分钟)",
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
        for name in ["httpx", "httpcore", "telegram", "urllib3"]:
            logging.getLogger(name).setLevel(logging.WARNING)

    # ── Token 验证 ──
    if not args.token:
        print("❌ 错误：未指定 Telegram Bot Token")
        print()
        print("   请通过以下方式提供：")
        print("   1. 环境变量: export TELEGRAM_BOT_TOKEN='123456:ABC-DEF...'")
        print("   2. CLI 参数: --token '123456:ABC-DEF...'")
        print()
        print("   如何获取 Token：")
        print("   1. 在 Telegram 中搜索 @BotFather")
        print("   2. 发送 /newbot 并按照提示创建")
        print("   3. 复制获得的 HTTP API Token")
        sys.exit(1)

    if httpx is None:
        print("❌ 需要安装 httpx 库: pip install httpx")
        sys.exit(1)

    # ── 启动 ──
    adapter = TelegramAdapter(
        bot_token=args.token,
        api_base_url=args.api,
        session_timeout=args.timeout,
    )
    try:
        adapter.start()
    except KeyboardInterrupt:
        adapter.stop()


if __name__ == "__main__":
    run_telegram_bot()
