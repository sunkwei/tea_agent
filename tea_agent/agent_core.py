"""
AgentCore — Tea Agent 共享核心基类。

CLI (tea_main_cli.TeaCLI) 和 GUI (main_db_gui.TkGUI) 均继承此类，
消除重复代码。包含：
  - 配置加载、目录初始化、Storage/Toolkit 初始化
  - MQTT 连接器启动与消息处理
  - 对话后处理流水线（入库、MQTT 发布、Token 统计、摘要）
"""

import os
import sys
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, List, cast

logger = logging.getLogger("agent_core")

from tea_agent.onlinesession import OnlineToolSession
from tea_agent.store import Storage
from tea_agent import tlk
from tea_agent import chat_room_connector
from tea_agent import mqtt_agent_connector
from tea_agent.config import load_config, get_config


class AgentCore:
    """Tea Agent 共享核心 — CLI 和 GUI 的公共基类。

    子类需实现:
      - _on_post_reply(ai_msg, used_tools, topic_id): AI 回复后的 UI 回调
      - _on_init_done(): 初始化完成后的 UI 回调
    """

# NOTE: 2026-05-04 19:33:59, self-evolved by tea_agent --- AgentCore.__init__ 增加 _shutting_down 标志位，用于安全重启前阻止新操作
    def __init__(self, debug: bool = False, config_path: Optional[str] = None):
        self.debug = debug
        self.generating = False
        self._shutting_down = False  # 重启前安全闸门
        self._config_path = config_path

        # ── 1. 加载配置 ──
        self._cfg = load_config(config_path) if config_path else load_config()
        if not self._cfg.main_model.is_configured:
            print("错误: 请配置主模型 (main_model)")
            print(f"  编辑 {config_path or '$HOME/.tea_agent/config.yaml 或 tea_agent/config.yaml'}")
            sys.exit(1)

        # ── 2. 初始化目录 ──
        cfg = self._cfg
        root_path = Path(cfg.paths.data_dir_abs)
        root_path.mkdir(parents=True, exist_ok=True)
        tool_dir = Path(cfg.paths.toolkit_dir_abs)
        tool_dir.mkdir(parents=True, exist_ok=True)

        # ── 3. 初始化 Storage 和 Toolkit ──
        db_path = Path(cfg.paths.db_path_abs)
        self.db = Storage(db_path=str(db_path))
        self.toolkit = tlk.Toolkit(str(tool_dir))
        tlk._toolkit_ = self.toolkit
        tlk.toolkit_reload()

        # ── 4. 启动连接器 ──
        self._start_connectors()

        # ── 5. 会话锁 ──
        self._sess_lock = threading.Lock()

        # ── 6. 初始化会话 ──
        self.current_topic_id: int = -1
        self._init_session()

# NOTE: 2026-05-04 19:26:41, self-evolved by tea_agent --- AgentCore 添加 _start_file_watcher() — 监控非 toolkit 的 .py 变更并自动重启进程
        # ── 7. 串接 MQTT reply handler ──
        self._setup_mqtt_reply_handler()

        # ── 8. 启动文件监控（代码变更自动重启）──
        self._start_file_watcher()

# NOTE: 2026-05-04 19:27:06, self-evolved by tea_agent --- 添加 _start_file_watcher 方法实现 — watchdog 监控 + os.execv 重启
    # ═══════════════════════════════════════════════
    # 文件监控（非 toolkit .py 变更 → 自动重启）
    # ═══════════════════════════════════════════════
    def _start_file_watcher(self):
        """启动文件监控：非 toolkit/ 目录的 .py 文件变更时自动重启进程。

        使用 watchdog 库递归监控 tea_agent 包目录。
        排除 toolkit/ 子目录 — 工具文件用 toolkit_reload() 热加载即可。
        检测到变更后防抖 2 秒，然后 os.execv 原地替换进程。
        """
        try:
            import watchdog.events
            import watchdog.observers
        except ImportError:
            logger.debug("watchdog 未安装，跳过文件监控")
            return

        tea_agent_dir = Path(__file__).parent  # tea_agent/ 包目录

        class _RestartHandler(watchdog.events.FileSystemEventHandler):
            def __init__(self, agent):
                self._agent = agent
                self._timer: Optional[threading.Timer] = None
                self._lock = threading.Lock()

            def on_modified(self, event):
                if event.is_directory:
                    return
                src = event.src_path
                if not src.endswith('.py'):
                    return
                # 排除 toolkit/ 子目录 — 工具用 toolkit_reload() 热更
                if '/toolkit/' in src or '\\toolkit\\' in src:
                    return
                logger.info(f"🔄 检测到文件变更: {src}")
                self._schedule_restart()

            def _schedule_restart(self):
                with self._lock:
                    if self._timer:
                        self._timer.cancel()
                    self._timer = threading.Timer(2.0, self._do_restart)
                    self._timer.daemon = True
                    self._timer.start()

# NOTE: 2026-05-04 19:28:47, self-evolved by tea_agent --- _do_restart 添加 Windows 支持 — subprocess.Popen + os._exit 替代 os.execv
# NOTE: 2026-05-04 19:34:24, self-evolved by tea_agent --- _do_restart 数据安全加固：设闸门 → 等会话锁 → WAL checkpoint → 关DB → 重启
            def _do_restart(self):
                """数据安全重启：
                1. 设 _shutting_down 闸门，阻止新操作
                2. 等待 _sess_lock（最长 10s），确保当前 chat_stream 完成
                3. WAL checkpoint(TRUNCATE) 刷盘 → close DB
                4. 跨平台重启进程
                """
                import subprocess
                import time as _time
                agent = self._agent

                # ── 1. 设闸门 ──
                agent._shutting_down = True
                logger.info("🔁 收到重启信号，等待活跃操作完成...")

                # ── 2. 等待 _sess_lock（chat_stream 释放锁后 DB 写入已完成）──
                if hasattr(agent, '_sess_lock'):
                    deadline = _time.monotonic() + 10.0  # 最多等10秒
                    acquired = False
                    while _time.monotonic() < deadline:
                        if agent._sess_lock.acquire(blocking=False):
                            acquired = True
                            agent._sess_lock.release()
                            break
                        _time.sleep(0.1)
                    if not acquired:
                        logger.warning("等待会话锁超时（10s），强制关闭")

                # ── 3. 安全关闭数据库 ──
                try:
                    if hasattr(agent, 'db') and agent.db:
                        agent.db.close()  # 内含 WAL checkpoint(TRUNCATE)
                        logger.info("数据库已安全关闭")
                except Exception as e:
                    logger.warning(f"关闭数据库异常 (非致命): {e}")

                # ── 4. 跨平台重启 ──
                print("\n🔁 代码已变更，正在重启...\n", flush=True)
                args = [sys.executable] + sys.argv
                if sys.platform == 'win32':
                    subprocess.Popen(args, close_fds=True)
                    os._exit(0)
                else:
                    os.execv(sys.executable, args)

        handler = _RestartHandler(self)
        observer = watchdog.observers.Observer()
        observer.schedule(handler, str(tea_agent_dir), recursive=True)
        observer.daemon = True
        observer.start()
        logger.info("📁 文件监控已启动（非 toolkit .py 变更时自动重启）")
    def _start_connectors(self):
        """启动 chat_room 和 MQTT 连接器（非阻塞守护线程）。"""
        try:
            chat_room_connector.start(self.db)
        except Exception as e:
            logger.warning(f"chat_room 连接器启动失败: {e}")

        try:
            mqtt_agent_connector.start(self.db)
        except Exception as e:
            logger.warning(f"MQTT 连接器启动失败: {e}")

    # ═══════════════════════════════════════════════
    # 会话初始化
    # ═══════════════════════════════════════════════
    def _init_session(self):
        """初始化 OnlineToolSession。子类可覆盖以添加 UI 回调。"""
        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model
        self.sess = OnlineToolSession(
            toolkit=self.toolkit,
            api_key=cast(str, main_m.api_key),
            api_url=cast(str, main_m.api_url),
            model=cast(str, main_m.model_name),
            max_history=cfg.max_history,
            max_iterations=cfg.max_iterations,
            keep_turns=cfg.keep_turns,
            max_tool_output=cfg.max_tool_output,
            max_assistant_content=cfg.max_assistant_content,
            extra_iterations_on_continue=cfg.extra_iterations_on_continue,
            memory_extraction_threshold=cfg.memory_extraction_threshold,
            storage=self.db,
            cheap_api_key=cast(str, cheap_m.api_key),
            cheap_api_url=cast(str, cheap_m.api_url),
            cheap_model=cast(str, cheap_m.model_name),
            enable_thinking=cfg.enable_thinking,
        )

        import tea_agent.session_ref as _sref
        _sref.set_session(self.sess)

    def _init_session_info_str(self) -> str:
        """返回会话初始化信息字符串（子类用于显示）。"""
        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model
        cheap_info = f" | 摘要: {cheap_m.model_name}" if cheap_m.model_name else ""
        return f"📡 已连接 | 模型: {main_m.model_name}{cheap_info}\n🔧 工具: {len(self.toolkit.func_map)} 个已加载"

    # ═══════════════════════════════════════════════
    # 对话后处理流水线（入库 → MQTT → Token → 摘要）
    # ═══════════════════════════════════════════════
    def _post_chat_pipeline(self, ai_msg: str, used_tools: bool,
                            user_msg: str, topic_id: int) -> None:
        """AI 回复后的标准处理流水线。CLI 和 GUI 共用。

        1. 保存到数据库
        2. 发布到 MQTT
        3. Token 统计
        4. 自动摘要
        """
        # ── 1. 保存到数据库 ──
        conv_id = self.db.save_msg(topic_id, user_msg, "", False)
        rounds = self.sess._rounds_collector
        self.db.update_msg_rounds(
            conversation_id=conv_id,
            ai_msg=ai_msg,
            is_func_calling=used_tools,
            rounds=rounds if rounds else None,
        )

        # ── 2. 发布到 MQTT ──
        self._publish_to_mqtt(ai_msg)

        # ── 3. Token 统计 ──
        usage = self.sess._last_usage
        cheap_usage = self.sess._last_cheap_usage
        if usage and usage.get("total_tokens", 0) > 0:
            self.db.add_topic_tokens(
                topic_id,
                total_tokens=usage["total_tokens"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                cheap_tokens=cheap_usage.get("total_tokens", 0),
                cheap_prompt_tokens=cheap_usage.get("prompt_tokens", 0),
                cheap_completion_tokens=cheap_usage.get("completion_tokens", 0),
            )

        # ── 4. 自动摘要 ──
        self._auto_summary(topic_id)

    # ═══════════════════════════════════════════════
    # MQTT 方法（CLI 和 GUI 100% 共享）
    # ═══════════════════════════════════════════════
    def _publish_to_mqtt(self, ai_msg: str):
        """将 AI 回复发布到 MQTT，让所有订阅客户端实时收到"""
        try:
            conn = mqtt_agent_connector.get_connector()
            if conn and conn.is_ready and ai_msg:
                tp = self.db.get_topic(self.current_topic_id)
                title = tp.get("title", "") if tp else ""
                if title.startswith("mqtt_"):
                    sender = title[5:]  # 去掉 "mqtt_" 前缀
                    conn.publish_reply(ai_msg, reply_to=sender)
                else:
                    conn.publish_reply(ai_msg)
        except Exception:
            pass  # MQTT 发布失败不影响主流程

    def _setup_mqtt_reply_handler(self):
        """将 MQTT 消息串入 chat_stream() 全流水线。"""
        conn = mqtt_agent_connector.get_connector()
        if not conn:
            return

        def handle_mqtt(sender: str, content: str, msg_id: str):
            threading.Thread(
                target=self._process_mqtt_message,
                args=(sender, content),
                daemon=True,
                name=f"mqtt-reply-{sender}",
            ).start()
            return None

        conn.set_reply_handler(handle_mqtt)
        logger.info("MQTT reply handler 已注册")

# NOTE: 2026-05-04 19:35:00, self-evolved by tea_agent --- _process_mqtt_message 入口加 _shutting_down 闸门检查
    def _process_mqtt_message(self, sender: str, content: str):
        """处理单条 MQTT 消息：切换上下文 → chat_stream → 入库 → MQTT 回复。

        用户消息已由 connector._route_message() 存入 DB。
        这里取最后一条 conv_id，用 AI 回复更新之。
        """
        if self._shutting_down:
            logger.info(f"正在关闭中，拒绝处理 MQTT 消息 (sender={sender})")
            return
        with self._sess_lock:
            # 1. 获取/创建 mqtt_{sender} topic
            tid = self._get_or_create_mqtt_topic(sender)

            # 2. 取 _route_message 刚保存的用户消息 conv_id
            recent = self.db.get_recent_conversations(tid, limit=1)
            conv_id = recent[0]["id"] if recent else -1

            # 3. 保存当前 session 状态
            saved_topic_id = self.current_topic_id
            saved_messages = list(self.sess.messages) if hasattr(self.sess, 'messages') else []
            saved_summary = getattr(self.sess, '_history_summary', '')

            # 4. 加载 MQTT topic 的对话历史
            self._load_topic_history_into_session(tid)

            try:
                # 5. 调用 AI（静默，max_iter 时自动续命）
                self.sess._continue_after_max = True
# NOTE: 2026-05-04 19:38:19, self-evolved by tea_agent --- MQTT 续命也追加 10 轮，与 CLI 保持一致
                def _on_status_mqtt(status_msg: str):
                    if status_msg.startswith("!MAX_ITER:"):
                        self.sess._continue_after_max = True
                        self.sess._extra_iterations += 10
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
                    self._on_mqtt_session_restored()

    def _on_mqtt_session_restored(self):
        """MQTT 消息处理后恢复 session 的 UI 回调（GUI 覆盖来刷新界面）。"""
        pass

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

    # ═══════════════════════════════════════════════
    # 摘要
    # ═══════════════════════════════════════════════
    def _auto_summary(self, topic_id: int = None):
        """自动生成主题摘要。CLI/GUI 共用核心逻辑，子类加 UI 回调。"""
        if topic_id is None:
            topic_id = self.current_topic_id
        if topic_id <= 0:
            return
        recent = self.db.get_recent_conversations(topic_id, limit=3)
        if not recent:
            return
        try:
            cli, mdl = self.sess._get_summarize_client()
            from tea_agent.main_db_gui import _generate_topic_summary
            summary = _generate_topic_summary(client=cli, model=mdl, conversations=recent)
            if summary:
                self.db.update_topic_title(topic_id, summary)
                self._on_summary_updated(topic_id, summary)
        except Exception:
            pass

    def _on_summary_updated(self, topic_id: int, summary: str):
        """摘要更新后的 UI 回调（子类覆盖）。"""
        pass
