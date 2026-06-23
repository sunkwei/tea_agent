#!/usr/bin/env python3
"""
Tea Agent 轻量 CLI — 单文件实现。

用法:
    python -m tea_agent.cli                          # 自动查找 config.yaml
    python -m tea_agent.cli --config my_agent.yaml   # 指定配置
    python -m tea_agent.cli --think --verbose        # 开启 think + verbose

交互:
    Enter       发送消息
    Shift+Enter 换行
    /bye        退出
    /help       帮助
    /set think=on|off    切换 think 模式
    /set verbose=on|off  切换 verbose 模式
"""

import argparse
import sys
import os
import threading
import atexit

# 将项目根目录加入 sys.path（支持 python -m tea_agent.cli）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tea_agent.agent import Agent
from tea_agent.config import load_config

class TeaCLI(Agent):
    """Tea Agent 命令行客户端。"""

    def __init__(self, config_path: str = None, enable_think: bool = False,
                 verbose: bool = False, debug: bool = False, disable_summary: bool = False,
                 no_stream_chunk: bool = False):
        self._cli_think = enable_think
        self._cli_verbose = verbose
        super().__init__(
            mode="full",
            config_path=config_path,
            enable_thinking=enable_think,
            debug=debug,
            disable_summary=disable_summary,
            no_stream_chunk=no_stream_chunk,
        )

    # ——— AgentCore 要求的回调 ———
    def _on_post_reply(self, ai_msg, used_tools, topic_id):
        """Internal: handle post reply event.
        
        Args:
            ai_msg: Description.
            used_tools: Description.
            topic_id: Description.
        """
        pass  # CLI 无需 UI 回调

    def _on_init_done(self):
        """Internal: handle init done event."""
        pass

    def run(self):
        """主循环：读用户输入 → 调用模型 → 输出回复。"""
        self._print_welcome()
        self._auto_init_topic()

        while True:
            try:
                user_input = self._read_multiline()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input.strip():
                continue

            # 处理斜杠命令
            if user_input.startswith("/"):
                if self._handle_command(user_input.strip()):
                    continue
                else:
                    break  # /bye

            # 发送到模型
            self._chat(user_input)

        print("\n👋 再见")

    def run_oneshot(self, msg: str):
        """单次对话模式（非交互）。"""
        self._auto_init_topic()
        self._chat(msg)

    # ——— 多行输入（Enter 发送，Shift+Enter 换行）———
    def _read_multiline(self) -> str:
        """读取多行输入。Enter 发送，Shift+Enter 换行（输入末尾加「换行不分隔符」）。

        实现策略：逐行读取，若行末以「换行符号」结尾则继续追加下一行。
        由于终端无法直接检测 Shift+Enter，改用「\」续行符：
        - 行末以「\」结尾 → 继续输入下一行
        - 否则 → 发送
        """
        if sys.platform == "win32":
            return self._read_multiline_win32()
        else:
            return self._read_multiline_unix()

    def _read_multiline_unix(self) -> str:
        """Unix 终端：使用 termios 检测 Shift+Enter（\x1b + 换行序列）。"""
        import tty
        import termios

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        lines = []
        current = []

        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch == "\r":  # Enter
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    lines.append("".join(current))
                    break
                elif ch == "\n":  # Shift+Enter 在某些终端产生 \n
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    lines.append("".join(current))
                    current = []
                elif ch == "\x1b":  # ESC 序列
                    seq = sys.stdin.read(2)
                    if seq == "[Z":  # Shift+Tab (部分终端 Shift+Enter)
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        lines.append("".join(current))
                        current = []
                    else:
                        # 忽略其他 ESC 序列
                        pass
                elif ch in ("\x03", "\x04"):  # Ctrl+C / Ctrl+D
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    raise EOFError
                elif ch == "\x7f":  # Backspace
                    if current:
                        current.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                elif ch.isprintable() or ch in ("\t",):
                    current.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

        return "\n".join(lines)

    def _read_multiline_win32(self) -> str:
        """Windows：使用「\\」续行符模拟多行输入。"""
        lines = []
        prompt = ">>> "
        while True:
            try:
                line = input(prompt)
            except (EOFError, KeyboardInterrupt):
                raise
            if line.rstrip().endswith("\\"):
                lines.append(line.rstrip()[:-1])
                prompt = "... "
            else:
                lines.append(line)
                break
        return "\n".join(lines)

    # ——— 斜杠命令 ———
    def _handle_command(self, cmd: str) -> bool:
        """返回 False 表示退出。"""
        parts = cmd.split(None, 1)
        cmd_name = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd_name == "/bye" or cmd_name == "/quit" or cmd_name == "/exit":
            return False

        elif cmd_name == "/help":
            self._print_help()

        elif cmd_name == "/set":
            self._cmd_set(arg)

        elif cmd_name == "/think":
            self._toggle_think()

        elif cmd_name == "/verbose":
            self._toggle_verbose()

        elif cmd_name == "/new":
            self._new_topic()

        elif cmd_name == "/list":
            self._list_topics()

        elif cmd_name == "/switch":
            self._switch_topic(arg)

        elif cmd_name == "/memories":
            self._show_memories()

        elif cmd_name == "/status":
            self._cmd_status()

        else:
            print(f"❓ 未知命令: {cmd_name}（输入 /help 查看帮助）")

        return True

    def _set_think(self, val: bool):
        """设置 think 模式并重建 session。"""
        self._cli_think = val
        self._cfg.enable_thinking = val
        self.sess.enable_thinking = val
        self._init_session()
        print(f"🧠 think = {'ON' if val else 'OFF'}")

    def _cmd_set(self, arg: str):
        if "=" not in arg:
            print("用法: /set think=on|off  或  /set verbose=on|off")
            return
        k, v = arg.split("=", 1)
        k, v = k.strip().lower(), v.strip().lower()
        if k == "think":
            self._set_think(v in ("on", "true", "1", "yes"))
        elif k == "verbose":
            self._cli_verbose = v in ("on", "true", "1", "yes")
            print(f"📢 verbose = {'ON' if self._cli_verbose else 'OFF'}")
        else:
            print(f"❓ 未知设置: {k}（支持: think, verbose）")

    def _toggle_think(self):
        self._set_think(not self._cli_think)

    def _toggle_verbose(self):
        self._cli_verbose = not self._cli_verbose
        print(f"📢 verbose = {'ON' if self._cli_verbose else 'OFF'}")

    def _new_topic(self):
        """Internal: new topic."""
        title = input("主题名称（留空自动生成）: ").strip()
        tid = self.db.create_topic(title or f"CLI 会话")
        self.current_topic_id = tid
        self.sess.messages = [{"role": "system", "content": self.sess.system_prompt}]
        self.sess._history_summary = ""
        print(f"📌 已切换到新主题: {title or tid[:8]}...")

    def _list_topics(self):
        """Internal: list topics."""
        topics = self.db.list_topics()
        print(f"\n{'ID':<10} {'标题':<30} {'更新时间'}")
        print("-" * 60)
        for t in topics[:20]:
            tid = t["topic_id"][:10]
            title = t.get("title", "")[:30]
            stamp = str(t.get("last_update_stamp", ""))[:19]
            mark = " ◀" if t["topic_id"] == self.current_topic_id else ""
            print(f"{tid:<10} {title:<30} {stamp}{mark}")

    def _switch_topic(self, arg: str):
        """Internal: switch topic.
        
        Args:
            arg: Description.
        """
        tid = arg.strip()
        tp = self.db.get_topic(tid)
        if not tp:
            # 尝试前缀匹配
            topics = self.db.list_topics()
            matched = [t for t in topics if t["topic_id"].startswith(tid)]
            if len(matched) == 1:
                tp = matched[0]
            elif len(matched) > 1:
                print("⚠️ 多个匹配，请提供更完整的 ID")
                return
            else:
                print(f"❓ 未找到主题: {tid}")
                return
        self.current_topic_id = tp["topic_id"]
        self._load_topic_history_into_session(tp["topic_id"])
        print(f"📌 已切换到: {tp.get('title', tp['topic_id'][:8])}")

    def _show_memories(self):
        """显示活跃的长期记忆。"""
        memories = self.db.get_active_memories(limit=20)
        if not memories:
            print("(无活跃记忆)")
            return
        labels = {0: "!!!", 1: "▲", 2: "●", 3: "○"}
        for m in memories:
            pri = labels.get(m.get("priority", 2), "?")
            cat = m.get("category", "general")
            content = m.get("content", "")[:80]
            print(f"  [{m['id']}] {pri} [{cat}] {content}")

    def _cmd_status(self):
        """显示当前会话状态。"""
        tp = self.db.get_topic(self.current_topic_id)
        ts = self.db.get_topic_tokens(self.current_topic_id)
        print(f"📌 当前主题: [{self.current_topic_id}] {tp.get('title', '') if tp else '?'}")
        if ts:
            t = ts.get("total_tokens", 0)
            print(f"📊 累计 Token: {t:,}")
        print(f"🔧 工具数量: {len(self.toolkit.func_map)}")
        print(f"🧠 活跃记忆: {len(self.db.get_active_memories(50))} 条")

    # ——— 对话 ———
    def _chat(self, user_msg: str):
        """发送消息并流式输出回复。"""
        # 确保 topic 存在
        if not self.current_topic_id:
            self._auto_init_topic()

        print()  # 空行分隔

        # 流式回调
        final_reply = []
        tool_round_count = [0]  # mutable counter

        def on_stream(chunk: str):
            """流式输出回调：处理 thinking/工具调用/最终回复。"""
            if self._cli_verbose:
                # verbose 模式：所有内容实时输出
                if chunk.startswith("[THINK_START]"):
                    print("\n💭 思考中...")
                elif chunk.startswith("[THINK_DONE]"):
                    print("✅ 思考完成")
                elif chunk.startswith("[TOOL_START:"):
                    tool_round_count[0] += 1
                    rn = tool_round_count[0]
                    tool_name = chunk.split(":", 1)[1].rstrip("]")
                    print(f"\n🔧 工具轮 {rn}: {tool_name}")
                elif chunk.startswith("[TOOL_DONE]"):
                    print("🔧 工具完成")
                elif chunk.startswith("[REPLY]"):
                    text = chunk[7:]
                    final_reply.append(text)
                    print(text, end="", flush=True)
                elif chunk.startswith("[STATUS:"):
                    print(f"\n📡 {chunk[8:].rstrip(']')}")
                else:
                    final_reply.append(chunk)
                    print(chunk, end="", flush=True)
            else:
                # 非 verbose：只收集最终回复，忽略中间过程
                if chunk.startswith("[REPLY]"):
                    text = chunk[7:]
                    final_reply.append(text)
                    print(text, end="", flush=True)
                elif not chunk.startswith("[") and not chunk.startswith("{"):
                    final_reply.append(chunk)
                    print(chunk, end="", flush=True)

        def on_status(status_msg: str):
            """状态回调（Max Iter 续命等）。"""
            if status_msg.startswith("!MAX_ITER:"):
                remaining = status_msg.split(":", 2)[1] if ":" in status_msg else "?"
                print(f"\n⏳ 达到最大轮次，自动续命...（剩余 {remaining} 轮）")

        try:
            with self._sess_lock:
                ai_msg, used_tools = self.sess.chat_stream(
                    user_msg,
                    callback=on_stream,
                    topic_id=self.current_topic_id,
                    on_status=on_status,
                )
        except Exception as e:
            print(f"\n❌ 错误: {e}")
            return

        print()  # 换行

        # Token 反馈
        usage = self.sess._last_usage
        if usage and usage.get("total_tokens", 0) > 0:
            ts = self.db.get_topic_tokens(self.current_topic_id)
            t_total = ts.get("total_tokens", 0) if ts else 0
            print(f"📊 本轮: {usage['total_tokens']:,} tokens | 主题累计: {t_total:,}", end="")
            hit = usage.get("prompt_cache_hit_tokens", 0)
            miss = usage.get("prompt_cache_miss_tokens", 0)
            if hit + miss > 0:
                rate = hit / (hit + miss) * 100
                print(f" | 缓存:{rate:.0f}%({hit:,}/{miss:,})")
            else:
                print()

        # 后处理
        if ai_msg:
            self._post_chat_pipeline(
                ai_msg=ai_msg,
                used_tools=used_tools,
                user_msg=user_msg,
                topic_id=self.current_topic_id,
            )

    # ——— 工具方法 ———
    def _auto_init_topic(self):
        """自动创建或加载主题。"""
        topics = self.db.list_topics()
        if topics:
            tp = topics[0]
            self.current_topic_id = tp["topic_id"]
            self._load_topic_history_into_session(tp["topic_id"])
        else:
            self.current_topic_id = self.db.create_topic("CLI 会话")
            self.sess.messages = [{"role": "system", "content": self.sess.system_prompt}]
            self.sess._history_summary = ""

    def _print_welcome(self):
        """Internal: print welcome."""
        cfg = self._cfg
        print(f"🤖 Tea Agent CLI")
        print(f"   模型: {cfg.main_model.model_name}")
        print(f"   think: {'ON' if self._cli_think else 'OFF'}  "
              f"verbose: {'ON' if self._cli_verbose else 'OFF'}")
        print(f"   工具: {len(self.toolkit.func_map)} 个已加载")
        print(f"   输入 /help 查看命令，Shift+Enter 换行，Enter 发送")
        print()

    def _print_help(self):
        """Internal: print help."""
        print("""
┌─────────────────────────────────────────────┐
│            Tea Agent CLI 帮助                │
├─────────────────────────────────────────────┤
│  /help                显示此帮助             │
│  /bye, /quit, /exit   退出                   │
│  /set think=on|off    开启/关闭 think 模式    │
│  /set verbose=on|off  开启/关闭 verbose 模式  │
│  /think               切换 think 模式         │
│  /verbose             切换 verbose 模式       │
│  /new                 创建新主题              │
│  /list                列出最近主题            │
│  /switch <id>         切换到指定主题          │
│  /memories            查看长期记忆             │
│  /status              查看当前状态             │
├─────────────────────────────────────────────┤
│  Enter       发送消息                        │
│  Shift+Enter 换行（Windows: 行末 \\\\ 续行）  │
└─────────────────────────────────────────────┘
""")

def main():
    """Main."""
    parser = argparse.ArgumentParser(
        description="Tea Agent CLI — 命令行 AI 助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m tea_agent.cli
  python -m tea_agent.cli --config my_agent.yaml --think
  python -m tea_agent.cli --verbose --think
        """,
    )
    parser.add_argument("--config", type=str, default=None,
                        help="配置文件路径（默认自动查找）")
    parser.add_argument("--think", action="store_true", default=False,
                        help="启用 thinking 模式")
    parser.add_argument("--verbose", action="store_true", default=False,
                        help="显示工具调用中间轮次")
    parser.add_argument("--debug", action="store_true", default=False,
                        help="调试模式")
    parser.add_argument("--oneshot", type=str, default=None,
                        help="单次对话（非交互模式）")
    parser.add_argument("--disable_summary", action="store_true", default=False,
                        help="禁用历史压缩和摘要")
    parser.add_argument("--no_stream_chunk", action="store_true", default=False,
                        help="非流式模式，方便单步调试")

    # ── Web 服务器参数 ──
    parser.add_argument("--web", action="store_true", default=False,
                        help="启动 Web 服务器模式")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="Web 服务器监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8080,
                        help="Web 服务器监听端口（默认 8080）")

    args = parser.parse_args()

    # ── Web 模式 ──
    if args.web:
        try:
            from tea_agent.web import run_server
        except ImportError as e:
            print(f"❌ {e}")
            print("请安装 web 依赖: pip install starlette uvicorn")
            sys.exit(1)
        run_server(
            config_path=args.config,
            host=args.host,
            port=args.port,
        )
        return

    # ── CLI 模式 ──
    cli = TeaCLI(
        config_path=args.config,
        enable_think=args.think,
        verbose=args.verbose,
        debug=args.debug,
        disable_summary=args.disable_summary,
        no_stream_chunk=args.no_stream_chunk,
    )

    if args.oneshot:
        cli.run_oneshot(args.oneshot)
    else:
        cli.run()

if __name__ == "__main__":
    main()
