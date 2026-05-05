#!/usr/bin/env python3
"""
Tea Agent CLI — 无 GUI 的命令行交互入口，适用于自动化测试和终端使用。

用法:
    python -m tea_agent.tea_main_cli              # 交互模式
    python -m tea_agent.tea_main_cli --oneshot "你好"  # 单次对话
    python -m tea_agent.tea_main_cli --debug          # 调试模式
    python -m tea_agent.tea_main_cli --config /path/to/config.yaml  # 多 agent
"""

import os
import sys
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, cast

logger = logging.getLogger("tea_cli")

# ====================== 包导入 ======================
_parent_dir = str(Path(__file__).resolve().parent.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from tea_agent.agent_core import AgentCore
from tea_agent.config import load_config


class TeaCLI(AgentCore):
    """Tea Agent 命令行界面 — 继承 AgentCore 共享核心逻辑。

    支持 --config 参数指定配置文件，实现多 agent 隔离。
    """

    def __init__(self, debug: bool = False, config_path: Optional[str] = None):
        # ── AgentCore 初始化：配置、目录、Storage/Toolkit、连接器、会话、MQTT ──
        super().__init__(debug=debug, config_path=config_path)

        # ── CLI 特定：显示状态信息 ──
        print(self._init_session_info_str())
        print("💡 输入 /help 查看命令\n")

        # ── 自动创建或加载主题 ──
        self._auto_init_topic()

    # ------------------------------------------------------
    # 主题管理
    # ------------------------------------------------------
    def _auto_init_topic(self):
        topics = self.db.list_topics()
        if topics:
            self.current_topic_id = topics[0]["topic_id"]
            self._load_history()
            self._show_topic_info()
        else:
            self._new_topic()

    def _new_topic(self) -> int:
        title = f"CLI {datetime.now().strftime('%m-%d %H:%M')}"
        tid = self.db.create_topic(title)
        self.current_topic_id = tid
        print(f"📌 新主题 [{tid}]: {title}")
        return tid

    def _list_topics(self):
        topics = self.db.list_topics()
        if not topics:
            print("(无主题)")
            return
        for tp in topics:
            tid = tp["topic_id"]
            title = tp.get("title", "")[:30]
            active = "🟢" if tp.get("is_active", 1) else "⚫"
            mark = " ← 当前" if tid == self.current_topic_id else ""
            print(f"  {active} [{tid}] {title}{mark}")

    def _switch_topic(self, tid: int):
        tp = self.db.get_topic(tid)
        if not tp:
            print(f"❌ 主题 [{tid}] 不存在")
            return
        self.current_topic_id = tid
        self.sess.clear_history()
        self._load_history()
        self._show_topic_info()

    def _load_history(self):
        """加载当前主题的历史到会话。"""
        if self.current_topic_id <= 0:
            return
        all_light = self.db.get_conversations(self.current_topic_id, limit=-1, include_rounds=False)
        if not all_light:
            return
        total = len(all_light)
        recent = self.db.get_conversations(self.current_topic_id, limit=10, include_rounds=True)
        offset = max(0, total - min(total, 10))
        for i in range(offset, total):
            j = i - offset
            if j < len(recent):
                all_light[i] = recent[j]
        summary = self.db.get_topic_summary(self.current_topic_id) or ""
        self.sess.load_history(all_light, summary, recent_turns=10)

    def _show_topic_info(self):
        tp = self.db.get_topic(self.current_topic_id)
        ts = self.db.get_topic_tokens(self.current_topic_id)
        if tp:
            print(f"📌 [{self.current_topic_id}] {tp.get('title', '')}")
        if ts:
            t = ts.get("total_tokens", 0)
            if t > 0:
                print(f"📊 Token: {t:,} (P:{ts.get('total_prompt_tokens', 0):,} "
                      f"C:{ts.get('total_completion_tokens', 0):,})")

    # ------------------------------------------------------
    # 记忆管理
    # ------------------------------------------------------
    def _show_memories(self):
        memories = self.db.get_active_memories(limit=20)
        if not memories:
            print("(无活跃记忆)")
            return
        stats = self.db.get_memory_stats()
        print(f"🧠 {stats.get('total', 0)} 条活跃记忆")
        labels = {0: "!!!", 1: "▲", 2: "●", 3: "○"}
        for m in memories:
            pri = labels.get(m.get("priority", 2), "?")
            cat = m.get("category", "general")
            content = m.get("content", "")[:80]
            print(f"  [{m['id']}] {pri} [{cat}] {content}")

    # ------------------------------------------------------
    # 对话
    # ------------------------------------------------------
    def chat(self, msg: str):
        """发送消息并流式输出回复。"""
        if self.generating:
            print("⏳ 正在生成中，请等待或按 Ctrl+C 打断...")
            return

        self.generating = True
        print(f"\n👤 {msg}")
        print("🤖 ", end="", flush=True)

        def stream_cb(text: str):
            print(text, end="", flush=True)

# NOTE: 2026-05-04 19:37:48, self-evolved by tea_agent --- CLI 续命模式：去除用户确认，自动续命 10 轮并打印提示
        def status_cb(status_msg: str):
            if status_msg.startswith("!MAX_ITER:"):
                display = status_msg.replace("!MAX_ITER:", "")
                print(f"\n⚠️  {display}")
                print("⏳ 自动续命 10 轮...")
                self.sess._continue_after_max = True
                self.sess._extra_iterations += 10  # 追加 10 轮
                self.sess._max_iter_wait.set()

        def work():
            try:
                ai_msg, used_tools = self.sess.chat_stream(
                    msg,
                    callback=stream_cb,
                    topic_id=self.current_topic_id,
                    on_status=status_cb,
                )
                print()  # 换行

                # 标准后处理流水线（入库 → MQTT → Token → 摘要）
                self._post_chat_pipeline(ai_msg, used_tools, msg, self.current_topic_id)

                # Token 终端反馈
                usage = self.sess._last_usage
                if usage and usage.get("total_tokens", 0) > 0:
                    ts = self.db.get_topic_tokens(self.current_topic_id)
                    t_total = ts.get("total_tokens", 0) if ts else 0
                    print(f"📊 本轮: {usage['total_tokens']:,} tokens | 主题累计: {t_total:,}")
            except Exception as ex:
                print(f"\n❌ 错误: {ex}")
            finally:
                self.generating = False

        self._work_thread = threading.Thread(target=work, daemon=True)
        self._work_thread.start()
        self._work_thread.join()  # CLI 模式下阻塞等待

    # ------------------------------------------------------
    # 回调
    # ------------------------------------------------------
    def _on_tool_log(self, msg: str):
        print(f"\n🔧 {msg}")

    def _on_summary_updated(self, topic_id: int, summary: str):
        """摘要更新后终端无额外动作（已在 _post_chat_pipeline 中处理）。"""
        pass

    # ------------------------------------------------------
    # REPL
    # ------------------------------------------------------
    def run(self):
        """运行交互式 REPL。"""
        print("输入消息开始对话，或输入命令（/help 查看帮助）\n")
        while True:
            try:
                raw = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n👋 再见")
                break

            if not raw:
                continue

            if raw.startswith("/"):
                self._handle_command(raw)
            else:
                self.chat(raw)

    def run_oneshot(self, msg: str):
        """单次对话（非交互模式）。"""
        self.chat(msg)

    # ------------------------------------------------------
    # 命令处理
    # ------------------------------------------------------
    def _handle_command(self, raw: str):
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/help":
            self._cmd_help()
        elif cmd == "/new":
            self._new_topic()
        elif cmd == "/topics":
            self._list_topics()
        elif cmd == "/switch":
            try:
                self._switch_topic(int(arg))
            except ValueError:
                print("用法: /switch <topic_id>")
        elif cmd == "/memories":
            self._show_memories()
        elif cmd == "/status":
            self._cmd_status()
        elif cmd in ("/exit", "/quit", "/q"):
            print("👋 再见")
            sys.exit(0)
        else:
            print(f"未知命令: {cmd}，输入 /help 查看帮助")

    def _cmd_help(self):
        print("""
命令列表:
  /new          新建主题
  /topics       列出所有主题
  /switch <id>  切换到指定主题
  /memories     查看长期记忆
  /status       查看当前状态
  /help         显示此帮助
  /exit, /quit  退出

直接输入文本即发送消息。
Ctrl+C 可打断当前生成。
""")

    def _cmd_status(self):
        tp = self.db.get_topic(self.current_topic_id)
        ts = self.db.get_topic_tokens(self.current_topic_id)
        print(f"📌 当前主题: [{self.current_topic_id}] {tp.get('title', '') if tp else '?'}")
        if ts:
            t = ts.get("total_tokens", 0)
            print(f"📊 累计 Token: {t:,}")
        print(f"🔧 工具数量: {len(self.toolkit.func_map)}")
        mem_count = len(self.db.get_active_memories(50))
        print(f"🧠 活跃记忆: {mem_count} 条")


# ====================== 入口 ======================
def main():
    import argparse

    ap = argparse.ArgumentParser(description="Tea Agent CLI")
    ap.add_argument("--debug", action="store_true", help="调试模式")
    ap.add_argument("--oneshot", type=str, default=None, help="单次对话（非交互）")
    ap.add_argument("--config", type=str, default=None,
                    help="配置文件路径（支持多 agent 隔离）")
    args = ap.parse_args()

    cli = TeaCLI(debug=args.debug, config_path=args.config)

    if args.oneshot:
        cli.run_oneshot(args.oneshot)
    else:
        cli.run()


if __name__ == "__main__":
    main()
