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

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tea_agent.agent_core import AgentCore
from tea_agent.config import load_config

class TeaCLI(AgentCore):
    """Tea Agent 命令行客户端。"""

    def __init__(self, config_path: str = None, enable_think: bool = False,
                 verbose: bool = False, disable_summary: bool = False, debug: bool = False):
        """Initialize  .
        
        Args:
            config_path: Description.
            enable_think: Description.
            verbose: Description.
            disable_summary: Description.
            debug: Description.
        """
        self._cli_think = enable_think
        self._cli_verbose = verbose
        self._cli_debug = debug
        super().__init__(config_path=config_path, disable_summary=disable_summary, debug=debug)

        self._cfg.enable_thinking = self._cli_think
        self._init_session()

    def _on_post_reply(self, ai_msg, used_tools, topic_id):
        """Internal: handle post reply event.
        
        Args:
            ai_msg: Description.
            used_tools: Description.
            topic_id: Description.
        """
        pass

    def _on_init_done(self):
        """Internal: handle init done event"""
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

            if user_input.startswith("/"):
                if self._handle_command(user_input.strip()):
                    continue
                else:
                    break

            self._chat(user_input)

        print("\n👋 再见")

    def _read_multiline(self) -> str:
        """
        读取多行输入。Enter 发送，Shift+Enter 换行（输入末尾加「换行不分隔符」）。

        Returns:
            str: Description.
        """
        if sys.platform == "win32":
            return self._read_multiline_win32()
        else:
            return self._read_multiline_unix()

    def _read_multiline_unix(self) -> str:
        """
        Unix 终端：使用 termios 检测 Shift+Enter（ + 换行序列）。

        Returns:
            str: Description.
        """
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
                if ch == "\r":
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    lines.append("".join(current))
                    break
                elif ch == "\n":
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    lines.append("".join(current))
                    current = []
                elif ch == "\x1b":
                    seq = sys.stdin.read(2)
                    if seq == "[Z":
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        lines.append("".join(current))
                        current = []
                    else:
                        pass
                elif ch in ("\x03", "\x04"):
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    raise EOFError
                elif ch == "\x7f":
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
        """
        Windows：使用「\」续行符模拟多行输入。

        Returns:
            str: Description.
        """
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

    def _handle_command(self, cmd: str) -> bool:
        """
        返回 False 表示退出。

        Args:
            cmd (str): Description.

        Returns:
            bool: Description.
        """
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

        else:
            print(f"❓ 未知命令: {cmd_name}（输入 /help 查看帮助）")

        return True

    def _cmd_set(self, arg: str):
        """Internal: cmd set.
        
        Args:
            arg: Description.
        """
        if "=" not in arg:
            print("用法: /set think=on|off  或  /set verbose=on|off")
            return
        k, v = arg.split("=", 1)
        k, v = k.strip().lower(), v.strip().lower()
        if k == "think":
            val = v in ("on", "true", "1", "yes")
            self._cli_think = val
            self._cfg.enable_thinking = val
            self.sess.enable_thinking = val
            print(f"🧠 think = {'ON' if val else 'OFF'}")
        elif k == "verbose":
            val = v in ("on", "true", "1", "yes")
            self._cli_verbose = val
            print(f"📢 verbose = {'ON' if val else 'OFF'}")
        else:
            print(f"❓ 未知设置: {k}（支持: think, verbose）")

    def _toggle_think(self):
        """Internal: toggle think"""
        self._cli_think = not self._cli_think
        self._cfg.enable_thinking = self._cli_think
        self.sess.enable_thinking = self._cli_think
        print(f"🧠 think = {'ON' if self._cli_think else 'OFF'}")

    def _toggle_verbose(self):
        """Internal: toggle verbose"""
        self._cli_verbose = not self._cli_verbose
        print(f"📢 verbose = {'ON' if self._cli_verbose else 'OFF'}")

    def _new_topic(self):
        """Internal: new topic"""
        title = input("主题名称（留空自动生成）: ").strip()
        tid = self.db.create_topic(title or f"CLI 会话")
        self.current_topic_id = tid
        self.sess.messages = [{"role": "system", "content": self.sess.system_prompt}]
        self.sess._history_summary = ""
        print(f"📌 已切换到新主题: {title or tid[:8]}...")

    def _list_topics(self):
        """Internal: list topics"""
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

    def _chat(self, user_msg: str):
        """
        发送消息并流式输出回复。

        Args:
            user_msg (str): Description.
        """
        if not self.current_topic_id:
            self._auto_init_topic()

        print()

        final_reply = []
        tool_round_count = [0]

        def on_stream(chunk: str):
            """
            流式输出回调：处理 thinking/工具调用/最终回复。

            Args:
                chunk (str): Description.
            """
            if self._cli_verbose:
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
                if chunk.startswith("[REPLY]"):
                    text = chunk[7:]
                    final_reply.append(text)
                    print(text, end="", flush=True)
                elif not chunk.startswith("[") and not chunk.startswith("{"):
                    final_reply.append(chunk)
                    print(chunk, end="", flush=True)

        def on_status(status_msg: str):
            """
            状态回调（Max Iter 续命等）。

            Args:
                status_msg (str): Description.
            """
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

        print()

        if ai_msg:
            self._post_chat_pipeline(
                ai_msg=ai_msg,
                used_tools=used_tools,
                user_msg=user_msg,
                topic_id=self.current_topic_id,
            )

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
        """Internal: print welcome"""
        cfg = self._cfg
        print(f"🤖 Tea Agent CLI")
        print(f"   模型: {cfg.main_model.model_name}")
        print(f"   think: {'ON' if self._cli_think else 'OFF'}  "
              f"verbose: {'ON' if self._cli_verbose else 'OFF'}")
        print(f"   工具: {len(self.toolkit.func_map)} 个已加载")
        print(f"   输入 /help 查看命令，Shift+Enter 换行，Enter 发送")
        print()

    def _print_help(self):
        """Internal: print help"""
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
├─────────────────────────────────────────────┤
│  Enter       发送消息                        │
│  Shift+Enter 换行（Windows: 行末 \\\\ 续行）  │
└─────────────────────────────────────────────┘
""")

def main():
    """Main"""
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
    parser.add_argument("--disable_summary", action="store_true", default=False,
                        help="禁用历史压缩和摘要，超过30轮直接丢弃")
    parser.add_argument("--debug", action="store_true", default=False)

    args = parser.parse_args()

    cli = TeaCLI(
        config_path=args.config,
        enable_think=args.think,
        verbose=args.verbose,
        disable_summary=args.disable_summary,
        debug=args.debug,
    )
    cli.run()

if __name__ == "__main__":
    main()
