"""
AgentCore — Tea Agent 共享核心基类。

CLI (tea_main_cli.TeaCLI) 和 GUI (gui.TkGUI) 均继承此类，
消除重复代码。包含：
  - 配置加载、目录初始化、Storage/Toolkit 初始化
  - 对话后处理流水线（入库、Token 统计、摘要）
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
from tea_agent.config import load_config, get_config

class AgentCore:
    """AgentCore class."""
    DRIFT_SUGGEST_THRESHOLD = 3
    """Tea Agent 共享核心 — CLI 和 GUI 的公共基类。

    子类需实现:
      - _on_post_reply(ai_msg, used_tools, topic_id): AI 回复后的 UI 回调
      - _on_init_done(): 初始化完成后的 UI 回调
    """

    def __init__(self, debug: bool = False, config_path: Optional[str] = None,
                 disable_summary: bool = False, disable_background_tasks: bool = False):
        """Initialize  .
        
        Args:
            debug: Description.
            config_path: Description.
            disable_summary: Description.
        """
        from tea_agent.logging_setup import setup_logging
        self.debug = debug
        self.disable_summary = disable_summary
        self.disable_background_tasks = disable_background_tasks
        setup_logging(debug=self.debug)
        self.generating = False
        self._config_path = config_path

        self._cfg = load_config(config_path) if config_path else load_config()
        if not self._cfg.main_model.is_configured:
            print("错误: 请配置主模型 (main_model)")
            print(f"  编辑 {config_path or '$HOME/.tea_agent/config.yaml 或 tea_agent/config.yaml'}")
            sys.exit(1)

        cfg = self._cfg
        root_path = Path(cfg.paths.data_dir_abs)
        root_path.mkdir(parents=True, exist_ok=True)
        tool_dir = Path(cfg.paths.toolkit_dir_abs)
        tool_dir.mkdir(parents=True, exist_ok=True)

        db_path = Path(cfg.paths.db_path_abs)
        self.db = Storage(db_path=str(db_path))
        self.toolkit = tlk.Toolkit(str(tool_dir))
        tlk._toolkit_ = self.toolkit
        tlk.toolkit_reload()

        self._sess_lock = threading.Lock()

        self.current_topic_id: int = 0
        self._init_session()

        if not self.disable_background_tasks:
            self._start_subconscious()
            self._start_scheduler()
        else:
            logger.info("BG tasks disabled (subconscious/scheduler)")

    def _start_subconscious(self):
        """自动启动潜意识引擎 daemon 线程。"""
        try:
            import importlib.util
            fpath = os.path.join(self.toolkit.root_dir, "toolkit_subconscious.py")
            if not os.path.exists(fpath):
                logger.debug(f"潜意识引擎文件不存在: {fpath}")
                return
            spec = importlib.util.spec_from_file_location("_subconscious_startup", fpath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.toolkit_subconscious("start")
            if result.get("status") == "started":
                logger.info("🧠 潜意识引擎已自动启动 | 间隔1小时 | 场景自适应")
            elif result.get("status") == "already_running":
                logger.info(
                    f"🧠 潜意识引擎已在运行中 "
                    f"| 周期: {result.get('cycles_completed', 0)}"
                )
            else:
                logger.debug(f"潜意识引擎状态: {result.get('status')}")
        except Exception as e:
            logger.debug(f"潜意识引擎自动启动跳过: {e}")

    def _start_scheduler(self):
        """启动定时任务调度器 daemon 线程，每分钟检查一次。"""
        try:
            from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
            result = toolkit_scheduler("start")
            status = result.get("status", "unknown")
            if status == "already_running":
                logger.info(f"⏰ 定时任务调度器已在运行中 (pid={result.get('pid')})")
            else:
                logger.info(f"⏰ 定时任务调度器已自动启动")
        except Exception as e:
            logger.debug(f"定时任务调度器自动启动跳过: {e}")

    def _init_session(self):
        """初始化 OnlineToolSession。子类可覆盖以添加 UI 回调。"""
        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model
        supports_vision = main_m.options.get("supports_vision", False) if main_m.options else False
        supports_reasoning = main_m.options.get("supports_reasoning", True) if main_m.options else True
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
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            disable_summary=self.disable_summary,
            disable_background_tasks=self.disable_background_tasks,
            debug=self.debug,
        )

        import tea_agent.session_ref as _sref
        _sref.set_session(self.sess)
        _sref.set_agent(self)

    def _init_session_info_str(self) -> str:
        """
        返回会话初始化信息字符串（子类用于显示）。

        Returns:
            str: Description.
        """
        cfg = self._cfg
        main_m = cfg.main_model
        cheap_m = cfg.cheap_model
        cheap_info = f" | 摘要: {cheap_m.model_name}" if cheap_m.model_name else ""
        return f"📡 已连接 | 模型: {main_m.model_name}{cheap_info}\n🔧 工具: {len(self.toolkit.func_map)} 个已加载"

    @staticmethod
    def _extract_reasoning_from_rounds(rounds: list) -> str:
        """
        从工具调用轮次中提取 assistant 的 reasoning_content。

        Args:
            rounds (list): Description.

        Returns:
            str: 合并后的 reasoning_content，多条用换行分隔。
        """
        reasoning_parts = []
        if not rounds:
            return ""
        for rd in rounds:
            if rd.get("role") == "assistant" and rd.get("reasoning_content"):
                reasoning_parts.append(rd["reasoning_content"])
        return "\n".join(reasoning_parts)

    @staticmethod
    def _extract_files_from_rounds(rounds: list) -> list:
        """
        从工具调用轮次中提取触碰的文件路径列表。

        Args:
            rounds (list): Description.

        Returns:
            list: Description.
        """
        import re, json as _json
        files = []
        seen = set()
        FILE_ARG_NAMES = {'filename', 'file_path', 'path', 'file', 'directory'}
        SKIP_VALUES = {'.', '..', '/', 'true', 'false'}

        if not rounds:
            return files

        for rd in rounds:
            tool_calls = rd.get('tool_calls', [])
            if not tool_calls:
                continue
            for tc in tool_calls:
                fn = tc.get('function', {})
                fn_name = fn.get('name', '')
                args_str = fn.get('arguments', '{}')
                try:
                    args = _json.loads(args_str) if isinstance(args_str, str) else args_str
                except _json.JSONDecodeError:
                    continue
                if not isinstance(args, dict):
                    continue

                for key in FILE_ARG_NAMES:
                    val = args.get(key)
                    if isinstance(val, str) and val not in SKIP_VALUES and len(val) > 1:
                        if '.' in val or '/' in val or '\\' in val:
                            if val not in seen:
                                files.append(val)
                                seen.add(val)

                cmd = args.get('cmd', '') or args.get('command', '')
                if cmd and isinstance(cmd, str):
                    for m in re.finditer(r'[a-zA-Z0-9_./\\-]+\.py\b', cmd):
                        fp = m.group()
                        if fp not in seen:
                            files.append(fp)
                            seen.add(fp)

        return files

    def _post_chat_pipeline(self, ai_msg: str, used_tools: bool,
                            user_msg, topic_id: str) -> None:
        """
        AI 回复后流水线。1.入库 2.三级推送 3.Token 4.摘要

        Args:
            ai_msg (str): Description.
            used_tools (bool): Description.
            user_msg: Description.
            topic_id (str): Description.

        Returns:
            None: Description.
        """
        conv_id = self.db.save_msg(topic_id, user_msg, "", False)
        rounds = self.sess._rounds_collector
        self.db.update_msg_rounds(
            conversation_id=conv_id, ai_msg=ai_msg,
            is_func_calling=used_tools, rounds=rounds if rounds else None,
        )
        overflow = None
        need_l3_summary = False
        l2_max = getattr(self._cfg, 'history_l2_max', 30)
        l3_batch = getattr(self._cfg, 'history_l3_batch', 10)
        prev_convs = self.db.get_conversations(topic_id, limit=2, include_rounds=True)
        if len(prev_convs) >= 2:
            old_l1 = prev_convs[-2]
            old_rounds = old_l1.get('rounds_json_parsed') or []
            old_files = self._extract_files_from_rounds(old_rounds)
            old_reasoning = self._extract_reasoning_from_rounds(old_rounds)
            overflow = self.db.push_to_level2(
                topic_id, old_l1["user_msg"], old_l1["ai_msg"], files=old_files,
                max_level2=l2_max, reasoning_content=old_reasoning,
            )
            if overflow:
                self.db.push_l3_pending(topic_id, overflow)
                pending_count = len(self.db.get_l3_pending(topic_id))
                need_l3_summary = pending_count >= l3_batch
                logger.info(
                    f"Level 2 overflow {len(overflow)} -> L3 pending "
                    f"(total pending={pending_count}, batch={l3_batch}, trigger={need_l3_summary})"
                )
        usage = self.sess._last_usage
        cheap_usage = self.sess._last_cheap_usage
        if usage and usage.get("total_tokens", 0) > 0:
            try:
                from tea_agent.embedding_util import get_embedding_engine
                emb_engine = get_embedding_engine()
                emb_usage = emb_engine.get_embedding_usage(reset=True)
                emb_tokens = emb_usage.get("total_tokens", 0)
                emb_prompt = emb_usage.get("prompt_tokens", 0)
            except Exception:
                emb_tokens = 0; emb_prompt = 0
            self.db.add_topic_tokens(
                topic_id, total_tokens=usage["total_tokens"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                cheap_tokens=cheap_usage.get("total_tokens", 0),
                cheap_prompt_tokens=cheap_usage.get("prompt_tokens", 0),
                cheap_completion_tokens=cheap_usage.get("completion_tokens", 0),
                embedding_tokens=emb_tokens, embedding_prompt_tokens=emb_prompt,
            )
        if not self.disable_background_tasks:
            threading.Thread(
                target=self._do_async_summaries,
                args=(topic_id, need_l3_summary),
                daemon=True
            ).start()
        self._suggest_new_topic_if_needed(topic_id)
    def _update_level3_summary(self, topic_id: str):
        """
        L3 批处理摘要：取 L3 pending 缓冲，用便宜模型生成摘要，合并到 semantic_summary。

        Args:
            topic_id (str): Description.
        """
        pending = self.db.get_l3_pending(topic_id)
        if not pending:
            return

        l3_batch = getattr(self._cfg, 'history_l3_batch', 10)
        logger.info(f"L3 summary triggered: {len(pending)} pending items (batch={l3_batch})")

        try:
            cli, mdl = self.sess._get_summarize_client()

            new_text = ""
            for pair in pending:
                u = (pair.get('user', '') or '')[:500]
                a = (pair.get('assistant', '') or '')[:500]
                new_text += f"User: {u}\nAssistant: {a}\n\n"

            old_sem = self.db.get_semantic_summary(topic_id) or ""

            sem_prompt = (
                "你是对话摘要器。将以下新对话片段合并到已有摘要中。\n"
                "规则：\n"
                "1. 保留已有摘要的全部内容不变\n"
                "2. 追加新段落的摘要（格式：'## 阶段N'），包含：核心主题、关键操作/决定、用户偏好\n"
                "3. 语言简洁，每阶段不超过5句话\n"
                "4. 如新对话无实质内容，仅输出已有摘要\n\n"
                f"[已有摘要]\n{old_sem if old_sem else '(无)'}\n\n"
                f"[新对话片段（{len(pending)}轮）]\n{new_text[:8000]}\n\n"
                "请输出更新后的完整摘要："
            )

            r = cli.chat.completions.create(
                model=mdl, messages=[{"role": "user", "content": sem_prompt}],
                temperature=0.3, max_tokens=2048,
            )
            new_sem = r.choices[0].message.content.strip() if r.choices else old_sem or ""

            if new_sem:
                self.db.set_semantic_summary(topic_id, new_sem)
                self.sess._semantic_summary = new_sem
                logger.info(f"L3 summary: {len(old_sem)}->{len(new_sem)} chars")

            self.db.clear_l3_pending(topic_id)

        except Exception as e:
            logger.warning(f"L3 summary fail: {type(e).__name__}: {e}")

    def _load_topic_history_into_session(self, tid: str):
        """
        将指定 topic 的对话历史加载到 session。

        Args:
            tid (str): Description.
        """
        all_full = self.db.get_conversations(tid, limit=-1, include_rounds=True)
        if all_full:
            old_summary = self.db.get_topic_summary(tid) or ""
            self.sess.load_history(all_full, summary=old_summary)
            self.sess._level2 = self.db.get_level2(tid) or []
            self.sess._semantic_summary = self.db.get_semantic_summary(tid) or ""
            self.sess._tool_chain_summary = self.db.get_tool_chain_summary(tid) or ""
        else:
            self.sess.messages = [{"role": "system", "content": self.sess.system_prompt}]
            self.sess._history_summary = ""
            self.sess._semantic_summary = ""
            self.sess._tool_chain_summary = ""
            self.sess._level2 = []
        self.current_topic_id = tid

    def _do_async_summaries(self, topic_id: str, need_l3: bool):
        """
        后台线程：执行 L3 批处理摘要 + auto_summary，完成后触发 UI 回调。

        Args:
            topic_id (str): Description.
            need_l3 (bool): Description.
        """
        try:
            if need_l3:
                self._update_level3_summary(topic_id)
            self._auto_summary(topic_id)
        except Exception as e:
            logger.warning(f"异步摘要失败 (topic={topic_id}): {type(e).__name__}: {e}")

    def _auto_summary(self, topic_id: str = None):
        """
        自动生成主题摘要。CLI/GUI 共用核心逻辑，子类加 UI 回调。

        Args:
            topic_id (str): Description.
        """
        if topic_id is None:
            topic_id = self.current_topic_id
        if not topic_id:
            return
        tp = self.db.get_topic(topic_id)
        if tp and (tp.get("title") or "").startswith("※"):
            logger.debug(f"跳过自动摘要: topic={topic_id} 标题为手动设置 (※前缀)")
            return
        recent = self.db.get_recent_conversations(topic_id, limit=10)
        if not recent:
            return
        try:
            cli, mdl = self.sess._get_summarize_client()
            logger.debug(f"call summarize model: {mdl}, topic={topic_id}, msgs={len(recent)}")
            from tea_agent._gui._topic_summary import _generate_topic_summary
            summary = _generate_topic_summary(client=cli, model=mdl, conversations=recent)
            if summary:
                self.db.update_topic_title(topic_id, summary)
                logger.info(f"📝 主题摘要更新: topic={topic_id} → {summary}")
                self._on_summary_updated(topic_id, summary)
            else:
                logger.warning(f"摘要生成返回空: topic={topic_id}, model={mdl}, msgs={len(recent)}")
        except Exception as e:
            logger.warning(f"自动摘要失败 (topic={topic_id}): {type(e).__name__}: {e}")

    def _suggest_new_topic_if_needed(self, topic_id: str):
        """
        检查主题漂移计数，达阈值时建议用户开新主题。

        Args:
            topic_id (str): Description.
        """
        count = getattr(self, '_pending_topic_suggestion', 0)
        if count > 0:
            logger.info(
                f"\n💡 本主题已切换 {count} 次讨论方向 (阈值={self.DRIFT_SUGGEST_THRESHOLD})，"
                f"建议 /new 开新主题以保持上下文聚焦。"
            )
            self._pending_topic_suggestion = 0

    def _on_summary_updated(self, topic_id: str, summary: str):
        """
        摘要更新后的 UI 回调（子类覆盖）。

        Args:
            topic_id (str): Description.
            summary (str): Description.
        """
        pass
