"""
消息渠道框架 - 将 tea_agent 接入多种即时通讯平台。

支持的渠道：
  - Telegram (Long Polling) ← 当前实现
  - 未来可扩展: Discord / Slack / WhatsApp / 短信

每个渠道适配器需实现：
  - start(): 启动监听
  - stop(): 优雅关闭
  - 将用户消息转发给 tea_agent HTTP API，返回回复
"""

from .telegram_adapter import TelegramAdapter, run_telegram_bot

__all__ = ["TelegramAdapter", "run_telegram_bot"]
