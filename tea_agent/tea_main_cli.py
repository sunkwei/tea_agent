#!/usr/bin/env python3
"""
Tea Agent CLI — 无 GUI 的命令行交互入口，适用于自动化测试和终端使用。

用法:
    python -m tea_agent.tea_main_cli              # 交互模式
    python -m tea_agent.tea_main_cli --oneshot "你好"  # 单次对话
    python -m tea_agent.tea_main_cli --debug          # 调试模式
"""

# NOTE: 2026-05-04 08:36:14, self-evolved by tea_agent --- tea_main_cli.py 添加 logging 和 logger 定义，修复 NameError
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

# NOTE: 2026-05-02 18:31:59, self-evolved by tea_agent --- tea_main_cli.py 导入 chat_room_connector 并在初始化后启动
# NOTE: 2026-05-04 08:33:26, self-evolved by tea_agent --- tea_main_cli.py 导入并启动 mqtt_agent_connector
from tea_agent.onlinesession import OnlineToolSession
from tea_agent.store import Storage
from tea_agent import tlk
from tea_agent import chat_room_connector
from tea_agent import mqtt_agent_connector
from tea_agent.config import load_config, get_config

# ====================== 配置加载 ======================
_cfg = load_config()

if not _cfg.main_model.is_configured:
    print("错误: 请配置主模型 (main_model)")
    print("  编辑 $HOME/.tea_agent/config.yaml 或 tea_agent/config.yaml")
    sys.exit(1)

API_KEY = cast(str, _cfg.main_model.api_key)
API_URL = cast(str, _cfg.main_model.api_url)
MODEL = cast(str, _cfg.main_model.model_name)
CHEAP_MODEL = _cfg.cheap_model


class TeaCLI:
    """Tea Agent 命令行界面 — 与 GUI 共享相同的核心逻辑，无 GUI 依赖。"""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.generating = False

        # 初始化目录
        root_path = Path.home() / ".tea_agent"
        root_path.mkdir(parents=True, exist_ok=True)
        tool_dir = root_path / "toolkit"
        tool_dir.mkdir(parents=True, exist_ok=True)

        # 初始化 Storage 和 Toolkit
        db_path = root_path / "chat_history.db"
        self.db = Storage(db_path=str(db_path))
        self.toolkit = tlk.Toolkit(str(tool_dir))
        tlk._toolkit_ = self.toolkit
# NOTE: 2026-05-02 18:32:13, self-evolved by tea_agent --- TeaCLI.__init__ 中 toolkit reload 后启动 chat_room 连接器
        tlk.toolkit_reload()

# NOTE: 2026-05-04 08:33:36, self-evolved by tea_agent --- TeaCLI.__init__ 中启动 mqtt_agent_connector
        # 启动 chat_room 连接器（非阻塞守护线程）
        try:
            chat_room_connector.start(self.db)
        except Exception as e:
            logger.warning(f"chat_room 连接器启动失败: {e}")

# NOTE: 2026-05-04 09:24:00, self-evolved by tea_agent --- 添加 MQTT reply handler，将 mqtt_client 消息串入 chat_stream() 全流水线
        # 启动通用 MQTT 连接器（非阻塞守护线程，从 config.yaml 读取配置）
        try:
            mqtt_agent_connector.start(self.db)
        except Exception as e:
            logger.warning(f"MQTT 连接器启动失败: {e}")

        # 会话锁（CLI 主线程与 MQTT handler 互斥访问 session）
        self._sess_lock = threading.Lock()

        # 串接 MQTT reply handler：mqtt_client 消息 → chat_stream() 全流水线
        self._setup_mqtt_reply_handler()

        # 初始化会话
        self.current_topic_id: int = -1
        self._init_session()

        # 自动创建或加载主题
        self._auto_init_topic()

    # ------------------------------------------------------
    # 会话初始化
    # ------------------------------------------------------
    def _init_session(self):
        cfg = get_config()
        self.sess = OnlineToolSession(
            toolkit=self.toolkit,
            api_key=API_KEY,
            api_url=API_URL,
            model=MODEL,
            max_history=cfg.max_history,
            max_iterations=cfg.max_iterations,
            keep_turns=cfg.keep_turns,
            max_tool_output=cfg.max_tool_output,
            max_assistant_content=cfg.max_assistant_content,
            extra_iterations_on_continue=cfg.extra_iterations_on_continue,
            memory_extraction_threshold=cfg.memory_extraction_threshold,
            storage=self.db,
            cheap_api_key=cast(str, CHEAP_MODEL.api_key),
            cheap_api_url=cast(str, CHEAP_MODEL.api_url),
            cheap_model=cast(str, CHEAP_MODEL.model_name),
            enable_thinking=cfg.enable_thinking,
        )
        self.sess.tool_log = self._on_tool_log

        import tea_agent.session_ref as _sref
        _sref.set_session(self.sess)

        cheap_info = f" | 摘要: {CHEAP_MODEL.model_name}" if CHEAP_MODEL.model_name else ""
        print(f"📡 已连接 | 模型: {MODEL}{cheap_info}")
        print(f"🔧 工具: {len(self.toolkit.func_map)} 个已加载")
        print(f"💡 输入 /help 查看命令\n")

    def _auto_init_topic(self):
        topics = self.db.list_topics()
        if topics:
            self.current_topic_id = topics[0]["topic_id"]
            self._load_history()
            self._show_topic_info()
        else:
            self._new_topic()

    # ------------------------------------------------------
    # 主题管理
    # ------------------------------------------------------
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

        def status_cb(status_msg: str):
            if status_msg.startswith("!MAX_ITER:"):
                display = status_msg.replace("!MAX_ITER:", "")
                print(f"\n⚠️  {display}")
                ans = input("是否继续? (y/n): ").strip().lower()
                self.sess._continue_after_max = (ans == "y")
                self.sess._max_iter_wait.set()
                if ans == "y":
                    print("⏳ 续命5轮...")
                    self.sess._extra_iterations += self.sess.extra_iterations_on_continue
                else:
                    print("🛑 用户终止")

        def work():
            try:
                ai_msg, used_tools = self.sess.chat_stream(
                    msg,
                    callback=stream_cb,
                    topic_id=self.current_topic_id,
                    on_status=status_cb,
                )
                print()  # 换行

# NOTE: 2026-05-04 09:07:11, self-evolved by tea_agent --- CLI chat() 中 AI 回复生成后发布到 MQTT
                # 保存到数据库
                conv_id = self.db.save_msg(self.current_topic_id, msg, "", False)
                rounds = self.sess._rounds_collector
                self.db.update_msg_rounds(
                    conversation_id=conv_id,
                    ai_msg=ai_msg,
                    is_func_calling=used_tools,
                    rounds=rounds if rounds else None,
                )

                # 发布 AI 回复到 MQTT（其他客户端可实时收到）
                self._publish_to_mqtt(ai_msg)

                # Token 统计
                usage = self.sess._last_usage
                cheap_usage = self.sess._last_cheap_usage
                if usage and usage.get("total_tokens", 0) > 0:
                    self.db.add_topic_tokens(
                        self.current_topic_id,
                        total_tokens=usage["total_tokens"],
                        prompt_tokens=usage["prompt_tokens"],
                        completion_tokens=usage["completion_tokens"],
                        cheap_tokens=cheap_usage.get("total_tokens", 0),
                        cheap_prompt_tokens=cheap_usage.get("prompt_tokens", 0),
                        cheap_completion_tokens=cheap_usage.get("completion_tokens", 0),
                    )
                    ts = self.db.get_topic_tokens(self.current_topic_id)
                    t_total = ts.get("total_tokens", 0) if ts else 0
                    print(f"📊 本轮: {usage['total_tokens']:,} tokens | 主题累计: {t_total:,}")

                # 摘要
                self._auto_summary()
            except Exception as ex:
                print(f"\n❌ 错误: {ex}")
            finally:
                self.generating = False

        self._work_thread = threading.Thread(target=work, daemon=True)
        self._work_thread.start()
        self._work_thread.join()  # CLI 模式下阻塞等待，便于测试

# NOTE: 2026-05-04 09:07:24, self-evolved by tea_agent --- TeaCLI 添加 _publish_to_mqtt 方法，将 AI 回复发布到 MQTT
# NOTE: 2026-05-04 09:24:45, self-evolved by tea_agent --- 添加 _setup_mqtt_reply_handler 和 _process_mqtt_message 方法
    def _publish_to_mqtt(self, ai_msg: str):
        """将 AI 回复发布到 MQTT，让所有订阅客户端实时收到"""
        try:
            conn = mqtt_agent_connector.get_connector()
            if conn and conn.is_ready and ai_msg:
                # 判断是否回复 MQTT 客户端
                tp = self.db.get_topic(self.current_topic_id)
                title = tp.get("title", "") if tp else ""
                if title.startswith("mqtt_"):
                    # 定向回复给发送者
                    sender = title[5:]  # 去掉 "mqtt_" 前缀
                    conn.publish_reply(ai_msg, reply_to=sender)
                else:
                    # 广播到 agent 自己的 channel
                    conn.publish_reply(ai_msg)
        except Exception:
            pass  # MQTT 发布失败不影响主流程

    # ── MQTT 远程输入处理 ──────────────────────────

    def _setup_mqtt_reply_handler(self):
        """将 MQTT 消息串入 chat_stream() 全流水线。mqtt_client 即远程输入。"""
        conn = mqtt_agent_connector.get_connector()
        if not conn:
            return

        def handle_mqtt(sender: str, content: str, msg_id: str):
            """MQTT 消息 → AI 处理（独立线程，不阻塞 MQTT 事件循环）"""
            threading.Thread(
                target=self._process_mqtt_message,
                args=(sender, content),
                daemon=True,
                name=f"mqtt-reply-{sender}",
            ).start()
            return None  # 非阻塞

        conn.set_reply_handler(handle_mqtt)
        logger.info("MQTT reply handler 已注册 — mqtt_client 消息将触发 chat_stream() 全流水线")

# NOTE: 2026-05-04 09:26:47, self-evolved by tea_agent --- 修正 _process_mqtt_message：复用 _route_message 已保存的 conv_id，避免重复保存用户消息
    def _process_mqtt_message(self, sender: str, content: str):
        """处理单条 MQTT 消息：切换上下文 → chat_stream → 入库 → MQTT 回复。
        
        注意：用户消息已由 connector._route_message() 存入了 DB。
        这里取最后一条 conv_id，用 AI 回复更新之。
        """
        with self._sess_lock:
            # 1. 获取/创建 mqtt_{sender} topic
            tid = self._get_or_create_mqtt_topic(sender)

            # 2. 取 _route_message 刚保存的用户消息 conv_id（最后一条）
            recent = self.db.get_recent_conversations(tid, limit=1)
            conv_id = recent[0]["id"] if recent else -1

            # 3. 保存当前 session 状态
            saved_topic_id = self.current_topic_id
            saved_messages = list(self.sess.messages) if hasattr(self.sess, 'messages') else []
            saved_summary = getattr(self.sess, '_history_summary', '')

            # 4. 加载 MQTT topic 的对话历史到 session
            self._load_topic_history_into_session(tid)

            try:
# NOTE: 2026-05-04 09:30:19, self-evolved by tea_agent --- MQTT handler 添加 on_status 回调自动续命，避免多次 max_iter 卡死
                # 5. 调用 AI（静默，不输出到终端；max_iterations 超限时自动续命）
                self.sess._continue_after_max = True
                def _on_status_mqtt(status_msg: str):
                    if status_msg.startswith("!MAX_ITER:"):
                        self.sess._continue_after_max = True
                        self.sess._max_iter_wait.set()
                ai_msg, used_tools = self.sess.chat_stream(
                    content,
                    callback=lambda _: None,
                    topic_id=tid,
                    on_status=_on_status_mqtt,
                )

                # 6. AI 回复入库 + MQTT 推送
                if ai_msg:
                    try:
                        if conv_id > 0:
                            rounds = self.sess._rounds_collector
                            self.db.update_msg_rounds(
                                conversation_id=conv_id,
                                ai_msg=ai_msg,
                                is_func_calling=used_tools,
                                rounds=rounds if rounds else None,
                            )
                        else:
                            self.db.save_msg(tid, content, ai_msg, used_tools)
                    except Exception as e:
                        logger.error(f"MQTT 保存 AI 回复失败: {e}")

                    # 推送 assistant 最后回复给 MQTT 发送者
                    conn = mqtt_agent_connector.get_connector()
                    if conn and conn.is_ready:
                        conn.publish_reply(ai_msg, reply_to=sender)

                    logger.info(
                        f"MQTT → AI → MQTT 完成: sender={sender}, "
                        f"topic=mqtt_{sender}, reply_len={len(ai_msg)}"
                    )
            except Exception as e:
                logger.error(f"MQTT AI 处理失败 (sender={sender}): {e}")
            finally:
                # 7. 恢复 session 状态
                if saved_topic_id > 0 and saved_topic_id != tid:
                    self.sess.messages = saved_messages
                    self.sess._history_summary = saved_summary
                    self.current_topic_id = saved_topic_id

    def _get_or_create_mqtt_topic(self, sender: str) -> int:
        """获取或创建 mqtt_{sender} 主题"""
        title = f"mqtt_{sender}"
        try:
            topics = self.db.list_topics()
            for t in topics:
                if t.get("title") == title:
                    return t["topic_id"]
        except Exception:
            pass
        return self.db.create_topic(title)

    def _load_topic_history_into_session(self, tid: int):
        """将指定 topic 的对话历史加载到 session"""
        all_light = self.db.get_conversations(tid, limit=-1, include_rounds=False)
        if all_light:
            total = len(all_light)
            recent = self.db.get_conversations(tid, limit=10, include_rounds=True)
            offset = max(0, total - min(total, 10))
            for i in range(offset, total):
                j = i - offset
                if j < len(recent):
                    all_light[i] = recent[j]
            summary = self.db.get_topic_summary(tid) or ""
            self.sess.load_history(all_light, summary, recent_turns=10)
        else:
            self.sess.messages = [{"role": "system", "content": self.sess.system_prompt}]
            self.sess._history_summary = ""
        self.current_topic_id = tid

    def _auto_summary(self):
        if self.current_topic_id <= 0:
            return
        recent = self.db.get_recent_conversations(self.current_topic_id, limit=3)
        if not recent:
            return
        try:
            cli, mdl = self.sess._get_summarize_client()
            from tea_agent.main_db_gui import _generate_topic_summary
            summary = _generate_topic_summary(client=cli, model=mdl, conversations=recent)
            if summary:
                self.db.update_topic_title(self.current_topic_id, summary)
        except Exception:
            pass

    # ------------------------------------------------------
    # 回调
    # ------------------------------------------------------
    def _on_tool_log(self, msg: str):
        """工具日志回调。"""
        print(f"\n🔧 {msg}")

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
    args = ap.parse_args()

    cli = TeaCLI(debug=args.debug)

    if args.oneshot:
        cli.run_oneshot(args.oneshot)
    else:
        cli.run()


if __name__ == "__main__":
    main()
