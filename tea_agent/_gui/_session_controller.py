"""
@2026-07-05 gen by tea_agent, SessionController component
Handles session management, topic operations, history loading.
"""

import tkinter as tk
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class SessionController:
    """Session and topic management for TkGUI."""
    
    def __init__(self, gui):
        self.gui = gui

def _start_dream(self):
    """启动Dream潜意识引擎后台线程，每小时循环一次"""
    # 确保 cwd 为项目根目录，使 _is_tea_agent_cwd() 检查通过
    _proj_root = str(Path(__file__).resolve().parent.parent)
    try:
        os.chdir(_proj_root)
    except Exception:
        pass
    try:
        from tea_agent.toolkit.toolkit_subconscious import toolkit_subconscious
        result = toolkit_subconscious("start")
        status = result.get("status", "unknown")
        if status == "rejected":
            logger.warning(f"Dream 未自动启动: {result.get('reason')}, cwd={os.getcwd()}")
        elif status == "already_running":
            logger.info(f"Dream 已在运行中 (pid={result.get('pid')})")
        else:
            logger.info(f"Dream 自动启动成功: {status}")
    except Exception as e:
        logger.warning(f"Dream 自动启动失败: {e}")

# NOTE: 2026-05-16 gen by tea_agent, App启动自动启动定时任务调度器

def _start_scheduler(self):
    """启动定时任务调度器后台线程，每分钟检查一次"""
    try:
        from tea_agent.toolkit.toolkit_scheduler import toolkit_scheduler
        result = toolkit_scheduler("start")
        status = result.get("status", "unknown")
        if status == "already_running":
            logger.info(f"定时任务调度器已在运行中 (pid={result.get('pid')})")
        else:
            logger.info(f"定时任务调度器自动启动成功: {status}")
    except Exception as e:
        logger.warning(f"定时任务调度器自动启动失败: {e}")


def _history_prev_round(self, e=None):
    """Alt+Up: 切换到上一条历史轮次，若无则忽略"""
    if not HAS_TKINTERWEB or self._show_mode != "chat_view":
        return "break"
    rounds = self._chat_rounds
    if not rounds:
        return "break"
    curr = self._current_round_view
    if curr is None:
        # 当前在最新轮，跳到最后一轮
        self._current_round_view = len(rounds) - 1
    elif curr <= 0:
        # 已在第一轮，忽略
        return "break"
    else:
        self._current_round_view = curr - 1
    self._render_round_view(self._current_round_view)
    return "break"


def _history_next_round(self, e=None):
    """Alt+Down: 切换到下一条历史轮次，若无则忽略"""
    if not HAS_TKINTERWEB or self._show_mode != "chat_view":
        return "break"
    rounds = self._chat_rounds
    if not rounds:
        return "break"
    curr = self._current_round_view
    if curr is None:
        # 当前在最新轮，忽略（已是最新，无"下一条"）
        return "break"
    if curr >= len(rounds) - 1:
        # 已在最后一轮，回到最新轮
        self._current_round_view = None
        self._render_and_show_chat()
    else:
        self._current_round_view = curr + 1
        self._render_round_view(self._current_round_view)
    return "break"

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _switch_display(self, mode: str):

# NOTE: 2026-05-07 14:25:13, self-evolved by tea_agent --- _show_loading 支持动态进度文本 + switch_topic 中后台线程上报加载进度，GUI 不卡死
# NOTE: 2026-05-01, self-evolved by tea_agent --- _show_loading: HtmlFrame spinner动画，异步加载历史时不再长时间空白
# NOTE: 2026-05-07 gen by tea_agent, _show_loading 支持 progress 参数动态更新进度文本
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _show_loading(self, text: str = "正在加载历史记录", progress: str = None):
# NOTE: 2026-05-07 14:45:26, self-evolved by tea_agent --- 新增 _poll_loading_progress 方法：50ms 轮询共享变量，仅变化时 load_html
    # 不调用 root.update()：让 CSS animation 自己跑，GUI 主循环保持响应

# NOTE: 2026-05-07 14:48:15, self-evolved by tea_agent --- _poll_loading_progress 改为从队列逐条出队，确保每个进度都被渲染
# NOTE: 2026-05-07 14:49:37, self-evolved by tea_agent --- 轮询器：队列排空且 _loading_done 时触发 _render_loaded_topic 或 _render_topic_error
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _poll_loading_progress(self):

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def scroll_to_bottom(self):

# 2026-05-11 gen by tea_agent, 将 render 到 HtmlFrame 的 HTML 同时 print 到终端
# NOTE: 2026-05-14 16:00:34, self-evolved by tea_agent --- _html_render 增加渲染前校验：控制字符清洗 + 结构检查 + 自动修复缺失闭合标签
# NOTE: 2026-05-15 gen by tea_agent, 注释掉终端打印避免刷屏，调试时可取消注释
# NOTE: 2026-05-16 gen by tea_agent, 渲染前增加 HTML 校验与清洗：控制字符过滤 + 标签配对检查 + 自动修复
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _html_render(self, html: str):

# NOTE: 2026-05-07 17:33:05, self-evolved by tea_agent --- _render_chat 支持可选的流式缓冲区参数，_stream_render_tick 传递当前 think/stream 内容
# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _render_chat(self, streaming_think: str = "", streaming_text: str = ""):


def _init_session(self):
    """GUI 的会话初始化 — 继承 AgentCore 创建 sess。"""
    super()._init_session()


def toggle_reasoning(self, enable: Optional[bool] = None) -> dict:
    """切换或查询 reasoning/thinking 状态。供 toolkit 工具调用。"""
    if self.sess is None:
        return {"error": "无活跃会话"}
    if enable is None:
        return {"enable_thinking": self.sess.enable_thinking}
    self.sess.enable_thinking = bool(enable)
    state = "开启" if enable else "关闭"
    self._update_status(f"🧠 Reasoning 已{state}")
    return {"enable_thinking": self.sess.enable_thinking, "changed": True}


def clear_chat(self):
    self.console.config(state=tk.NORMAL)
    self.console.delete("1.0", tk.END)
    self.console.config(state=tk.DISABLED)
    self.chat_messages.clear()
    self._stream_buffer = ""
    self._think_buffer = ""
    self._pending_console_text.clear()
    self._pending_images.clear()  # NOTE: 2026-05-15 gen by tea_agent, 清理待发送图片
    self._img_label.config(text="")
    self._clear_img_btn.pack_forget()
    # NOTE: 2026-05-08 08:46:00, self-evolved by tea_agent --- 清理 _pending_console_text，移除废弃的 _stream_render_pending


def auto_new_topic(self):
    topics = self.db.list_topics()
    if topics:
        # Treeview: 选中第一项
        children = self.topic_list.get_children()
        if children:
            self.topic_list.selection_set(children[0])
        self.on_topic_select(None)
    else:
        self.new_topic()


def new_topic(self):
    title = f"主题 {datetime.now().strftime('%m-%d %H:%M:%S')}"
    tid = self.db.create_topic(title)
    self.current_topic_id = tid  # NOTE: 2026-06-18 gen by tea_agent, 先设置 current_topic_id 再 refresh_topics，确保新主题高亮
    self.refresh_topics()
    self.switch_topic(tid)

# NOTE: 2026-04-30 09:37:55, self-evolved by tea_agent --- 左侧主题列表移除token前缀，直接显示摘要标题（不超过20字）
# NOTE: 2026-05-08 gen by tea_agent, refresh_topics 刷新后自动高亮当前主题（第一条匹配）
    # NOTE: 2026-04-30 09:37:55, self-evolved by tea_agent --- 左侧主题列表移除token前缀，直接显示摘要标题（不超过20字）
# NOTE: 2026-05-08 gen by tea_agent, refresh_topics 刷新后自动高亮当前主题（第一条匹配）

def refresh_topics(self):
    # Treeview: 先清空再填充
    for item in self.topic_list.get_children():
        self.topic_list.delete(item)
    topics = self.db.list_topics()
    self._topic_cache = topics       # 缓存供 tooltip 使用
    current_tid = getattr(self, 'current_topic_id', None)
    highlight_iid = ""
    for i, tp in enumerate(topics):
        title = tp.get("title", "")
        # 直接显示摘要标题，不超过20字
        display = title[:20] if len(title) > 20 else title
        iid = str(i)
        self.topic_list.insert("", tk.END, iid=iid, text=display, tags=("topic_item",))
        if tp.get("topic_id") == current_tid:
            highlight_iid = iid
    # 刷新后自动高亮当前主题
    if topics:
        self.topic_list.selection_set(highlight_iid)
        self.topic_list.see(highlight_iid)
# NOTE: 2026-05-15 gen by tea_agent, 统一标题栏更新，附加当前目录
# NOTE: 2026-05-16 gen by tea_agent, 格式改为 AI助手-{主题}-cwd{完整路径}, 启动时固化cwd不随后续chdir变化

def _update_title(self, topic_title=""):
    """设置窗口标题栏：AI助手 - {当前主题} - cwd {当前目录完整路径}"""
    cwd = getattr(self, "_initial_cwd", "")
    if topic_title:
        self.root.title(f"AI助手 - {topic_title} - cwd {cwd}")
    else:
        self.root.title(f"AI助手 - cwd {cwd}")


def switch_topic(self, topic_id):
# NOTE: 2026-05-09 18:59:41, self-evolved by tea_agent --- switch_topic 时更新窗口标题栏为 {topic_title} — AI 工具调用助手
    self.current_topic_id = topic_id
    # 更新窗口标题栏为当前主题标题
    try:
        tp = self.db.get_topic(topic_id)
        title = (tp or {}).get("title", "")
        self._update_title(title)
    except Exception:
        self._update_title()  # NOTE: 2026-05-15 gen by tea_agent, 标题含当前目录
    self.clear_chat()
# NOTE: 2026-05-07 14:45:13, self-evolved by tea_agent --- 启动进度轮询定时器，50ms 读共享变量更新 HtmlFrame
    # 加载期间阻塞输入（send() 检查 generating），但 GUI 主循环不受影响
    self.generating = True
# NOTE: 2026-05-07 14:48:24, self-evolved by tea_agent --- switch_topic 初始化 _progress_queue 替代 _last_progress_shown
    self._show_loading("正在加载历史记录")
    self._update_status("⏳ 加载中...")
    self._progress_queue = []  # 进度队列，后台线程入队，主线程定时器出队
    self._poll_loading_progress()  # 启动 50ms 轮询定时器，实时刷新 HtmlFrame 进度

    recent_turns = 10

    def load_worker():
        """后台线程：DB 查询 + JSON 解析 + 构建渲染列表（不阻塞 GUI）"""
        try:
            # === 第一阶段：DB 查询（后台线程） ===
            topic = cast(dict, self.db.get_topic(topic_id))
            ts = self.db.get_topic_tokens(topic_id)

# NOTE: 2026-05-07 14:27:35, self-evolved by tea_agent --- 移除 load_worker 中多余的 _show_loading(progress) 调用，进度已改由状态栏展示
            # 轻量查询所有对话（不含 rounds_json）
            all_light = self.db.get_conversations(topic_id, limit=-1, include_rounds=False)
            total_convs = len(all_light)
            old_count = max(0, total_convs - recent_turns)

            # 最近 N 轮完整查询（含工具调用链）
            if total_convs > 0:
                recent_full = self.db.get_conversations(topic_id, limit=recent_turns, include_rounds=True)
                offset = total_convs - min(total_convs, recent_turns)
                for i in range(offset, total_convs):
                    j = i - offset
                    if j < len(recent_full):
                        all_light[i] = recent_full[j]

            summary = self.db.get_topic_summary(topic_id) or ""

            # 更新 session 消息列表
            self.sess.load_history(all_light, summary, recent_turns=recent_turns)

            # === 第二阶段：构建渲染列表（纯数据，无 GUI 操作） ===
            render_items = []  # list of (tag, text)

            render_items.append(("title", f"📌 当前主题：{topic['title']}"))
            render_items.append(("notice", "-" * 50))

            total_tokens = ts.get("total_tokens", 0)
            if total_tokens > 0:
                render_items.append(("notice",
                    f"📊 Token 消耗: {total_tokens:,} "
                    f"(prompt: {ts.get('total_prompt_tokens', 0):,}, "
                    f"completion: {ts.get('total_completion_tokens', 0):,})"))
                render_items.append(("notice", ""))

            if summary:
                render_items.append(("notice", f"📖 历史摘要：{summary}"))
                render_items.append(("notice", "-" * 50))

            if old_count > 0:
                render_items.append(("notice",
                    f"📖 最近 {recent_turns} 轮显示完整对话，更早的 {old_count} 轮仅显示问答"))
                render_items.append(("notice", ""))

# NOTE: 2026-05-07 14:27:20, self-evolved by tea_agent --- 进度文本改为更新状态栏（轻量），HtmlFrame 仅初始渲染一次 spinner
# NOTE: 2026-05-07 14:40:37, self-evolved by tea_agent --- 进度文本从状态栏改回 HtmlFrame 显示「正在加载 N 条记录中的第 n 条」
# NOTE: 2026-05-07 14:43:26, self-evolved by tea_agent --- 进度更新粒度从每20条改为每条，确保加载动画流畅
# NOTE: 2026-05-07 14:43:47, self-evolved by tea_agent --- 避免 root.after 堆积：后台线程写共享变量，主线程 50ms 定时器轮询更新 HtmlFrame
# NOTE: 2026-05-07 14:48:00, self-evolved by tea_agent --- 修复进度丢失：共享变量改为队列，后台线程入队，主线程逐条出队渲染，不丢任何进度
            # 遍历对话，构建渲染项 + 进度入队（后台线程入队，主线程定时器出队渲染）
            for i, c in enumerate(all_light):
                # 每条进度写入队列，主线程 _poll_loading_progress 逐条出队更新 HtmlFrame
                self._progress_queue.append((i + 1, total_convs))

                is_old = i < old_count
                # NOTE: 2026-05-15 gen by tea_agent, 支持 JSON 格式 user_msg（含图片）
                raw_user_msg = c['user_msg']
                user_images = []
                user_text = raw_user_msg
                if raw_user_msg and raw_user_msg.startswith('{'):
                    try:
                        import json as _json_um
                        parsed = _json_um.loads(raw_user_msg)
                        if isinstance(parsed, dict):
                            user_text = parsed.get("text", raw_user_msg)
                            user_images = parsed.get("images", [])
                    except Exception:
                        pass
                render_items.append(("user", f"你：{user_text}", user_images))

                if is_old:
                    render_items.append(("ai", f"AI：{c['ai_msg']}"))
                else:
                    rounds = c.get("rounds_json_parsed")
                    tool_names = []
                    if rounds and c.get("is_func_calling"):
                        for rd in rounds:
                            rd_role = rd.get("role", "")
                            if rd_role == "assistant" and rd.get("tool_calls"):
                                for tc in rd["tool_calls"]:
                                    fn_name = tc.get("function", {}).get("name", "unknown")
                                    fn_args = tc.get("function", {}).get("arguments", "")
                                    if fn_name not in tool_names:
                                        tool_names.append(fn_name)
# NOTE: 2026-05-14 07:22:12, self-evolved by tea_agent --- 优化工具调用显示：参数多行展开（JSON解析），替换单行括号格式
                                    # @2026-05-16 gen by tea_agent, 工具调用参数多行展开显示
                                    import json as _json_tc2
                                    try:
                                        args_dict = _json_tc2.loads(fn_args) if fn_args else {}
                                        args_lines = []
                                        for k, v in args_dict.items():
                                            v_str = _json_tc2.dumps(v, ensure_ascii=False)
                                            if len(v_str) > 160:
                                                v_str = v_str[:160] + "..."
                                            args_lines.append(f"    {k}: {v_str}")
                                        args_block = "\n".join(args_lines)
                                        render_items.append(("tool", f"🔧 调用工具：{fn_name}\n参数：\n{args_block}"))
                                    except Exception:
                                        render_items.append(("tool", f"🔧 调用工具：{fn_name}\n参数：\n    {fn_args[:200]}"))
                                if rd.get("content"):
                                    render_items.append(("ai", f"AI：{rd['content']}"))
                            elif rd_role == "tool":
                                result_preview = rd.get("content", "")
                                if len(result_preview) > 200:
                                    result_preview = result_preview[:200] + "..."
                                render_items.append(("tool", f"📋 结果：{result_preview}"))
                            elif rd_role == "assistant" and rd.get("content"):
                                render_items.append(("ai", f"AI：{rd['content']}"))
                    else:
                        render_items.append(("ai", f"AI：{c['ai_msg']}"))

                    if c["is_func_calling"]:
                        if tool_names:
                            render_items.append(("tool", f"ℹ️ 工具：{', '.join(tool_names)}"))
                        else:
                            render_items.append(("tool", "ℹ️ 本条使用了工具调用"))
                render_items.append(("notice", ""))

# NOTE: 2026-05-07 14:49:21, self-evolved by tea_agent --- load_worker 不直接调度渲染，存 _pending_render/_pending_error，由轮询器触发
            # === 第三阶段：存入待渲染数据，由轮询器在进度队列排空后触发渲染 ===
            self._pending_render = render_items
            self._loading_done = True
        except Exception as e:
            self._pending_error = str(e)
            self._loading_done = True

    # 延迟 60ms 启动后台线程，让 spinner HTML 先渲染
    self.root.after(60, lambda: threading.Thread(target=load_worker, daemon=True).start())

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _render_loaded_topic(self, render_items):

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _render_topic_error(self, error_msg):


    def load_worker():
        """后台线程：DB 查询 + JSON 解析 + 构建渲染列表（不阻塞 GUI）"""
        try:
            # === 第一阶段：DB 查询（后台线程） ===
            topic = cast(dict, self.db.get_topic(topic_id))
            ts = self.db.get_topic_tokens(topic_id)

# NOTE: 2026-05-07 14:27:35, self-evolved by tea_agent --- 移除 load_worker 中多余的 _show_loading(progress) 调用，进度已改由状态栏展示
            # 轻量查询所有对话（不含 rounds_json）
            all_light = self.db.get_conversations(topic_id, limit=-1, include_rounds=False)
            total_convs = len(all_light)
            old_count = max(0, total_convs - recent_turns)

            # 最近 N 轮完整查询（含工具调用链）
            if total_convs > 0:
                recent_full = self.db.get_conversations(topic_id, limit=recent_turns, include_rounds=True)
                offset = total_convs - min(total_convs, recent_turns)
                for i in range(offset, total_convs):
                    j = i - offset
                    if j < len(recent_full):
                        all_light[i] = recent_full[j]

            summary = self.db.get_topic_summary(topic_id) or ""

            # 更新 session 消息列表
            self.sess.load_history(all_light, summary, recent_turns=recent_turns)

            # === 第二阶段：构建渲染列表（纯数据，无 GUI 操作） ===
            render_items = []  # list of (tag, text)

            render_items.append(("title", f"📌 当前主题：{topic['title']}"))
            render_items.append(("notice", "-" * 50))

            total_tokens = ts.get("total_tokens", 0)
            if total_tokens > 0:
                render_items.append(("notice",
                    f"📊 Token 消耗: {total_tokens:,} "
                    f"(prompt: {ts.get('total_prompt_tokens', 0):,}, "
                    f"completion: {ts.get('total_completion_tokens', 0):,})"))
                render_items.append(("notice", ""))

            if summary:
                render_items.append(("notice", f"📖 历史摘要：{summary}"))
                render_items.append(("notice", "-" * 50))

            if old_count > 0:
                render_items.append(("notice",
                    f"📖 最近 {recent_turns} 轮显示完整对话，更早的 {old_count} 轮仅显示问答"))
                render_items.append(("notice", ""))

# NOTE: 2026-05-07 14:27:20, self-evolved by tea_agent --- 进度文本改为更新状态栏（轻量），HtmlFrame 仅初始渲染一次 spinner
# NOTE: 2026-05-07 14:40:37, self-evolved by tea_agent --- 进度文本从状态栏改回 HtmlFrame 显示「正在加载 N 条记录中的第 n 条」
# NOTE: 2026-05-07 14:43:26, self-evolved by tea_agent --- 进度更新粒度从每20条改为每条，确保加载动画流畅
# NOTE: 2026-05-07 14:43:47, self-evolved by tea_agent --- 避免 root.after 堆积：后台线程写共享变量，主线程 50ms 定时器轮询更新 HtmlFrame
# NOTE: 2026-05-07 14:48:00, self-evolved by tea_agent --- 修复进度丢失：共享变量改为队列，后台线程入队，主线程逐条出队渲染，不丢任何进度
            # 遍历对话，构建渲染项 + 进度入队（后台线程入队，主线程定时器出队渲染）
            for i, c in enumerate(all_light):
                # 每条进度写入队列，主线程 _poll_loading_progress 逐条出队更新 HtmlFrame
                self._progress_queue.append((i + 1, total_convs))

                is_old = i < old_count
                # NOTE: 2026-05-15 gen by tea_agent, 支持 JSON 格式 user_msg（含图片）
                raw_user_msg = c['user_msg']
                user_images = []
                user_text = raw_user_msg
                if raw_user_msg and raw_user_msg.startswith('{'):
                    try:
                        import json as _json_um
                        parsed = _json_um.loads(raw_user_msg)
                        if isinstance(parsed, dict):
                            user_text = parsed.get("text", raw_user_msg)
                            user_images = parsed.get("images", [])
                    except Exception:
                        pass
                render_items.append(("user", f"你：{user_text}", user_images))

                if is_old:
                    render_items.append(("ai", f"AI：{c['ai_msg']}"))
                else:
                    rounds = c.get("rounds_json_parsed")
                    tool_names = []
                    if rounds and c.get("is_func_calling"):
                        for rd in rounds:
                            rd_role = rd.get("role", "")
                            if rd_role == "assistant" and rd.get("tool_calls"):
                                for tc in rd["tool_calls"]:
                                    fn_name = tc.get("function", {}).get("name", "unknown")
                                    fn_args = tc.get("function", {}).get("arguments", "")
                                    if fn_name not in tool_names:
                                        tool_names.append(fn_name)
# NOTE: 2026-05-14 07:22:12, self-evolved by tea_agent --- 优化工具调用显示：参数多行展开（JSON解析），替换单行括号格式
                                    # @2026-05-16 gen by tea_agent, 工具调用参数多行展开显示
                                    import json as _json_tc2
                                    try:
                                        args_dict = _json_tc2.loads(fn_args) if fn_args else {}
                                        args_lines = []
                                        for k, v in args_dict.items():
                                            v_str = _json_tc2.dumps(v, ensure_ascii=False)
                                            if len(v_str) > 160:
                                                v_str = v_str[:160] + "..."
                                            args_lines.append(f"    {k}: {v_str}")
                                        args_block = "\n".join(args_lines)
                                        render_items.append(("tool", f"🔧 调用工具：{fn_name}\n参数：\n{args_block}"))
                                    except Exception:
                                        render_items.append(("tool", f"🔧 调用工具：{fn_name}\n参数：\n    {fn_args[:200]}"))
                                if rd.get("content"):
                                    render_items.append(("ai", f"AI：{rd['content']}"))
                            elif rd_role == "tool":
                                result_preview = rd.get("content", "")
                                if len(result_preview) > 200:
                                    result_preview = result_preview[:200] + "..."
                                render_items.append(("tool", f"📋 结果：{result_preview}"))
                            elif rd_role == "assistant" and rd.get("content"):
                                render_items.append(("ai", f"AI：{rd['content']}"))
                    else:
                        render_items.append(("ai", f"AI：{c['ai_msg']}"))

                    if c["is_func_calling"]:
                        if tool_names:
                            render_items.append(("tool", f"ℹ️ 工具：{', '.join(tool_names)}"))
                        else:
                            render_items.append(("tool", "ℹ️ 本条使用了工具调用"))
                render_items.append(("notice", ""))

# NOTE: 2026-05-07 14:49:21, self-evolved by tea_agent --- load_worker 不直接调度渲染，存 _pending_render/_pending_error，由轮询器触发
            # === 第三阶段：存入待渲染数据，由轮询器在进度队列排空后触发渲染 ===
            self._pending_render = render_items
            self._loading_done = True
        except Exception as e:
            self._pending_error = str(e)
            self._loading_done = True

    # 延迟 60ms 启动后台线程，让 spinner HTML 先渲染
    self.root.after(60, lambda: threading.Thread(target=load_worker, daemon=True).start())

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _render_loaded_topic(self, render_items):

# @2026-05-15 gen by tea_agent, Composition: moved to ChatRenderer → def _render_topic_error(self, error_msg):


def on_topic_select(self, e):
    # Treeview: 获取选中项的索引
    sel = self.topic_list.selection()
    if not sel:
        return
    idx = self.topic_list.index(sel[0])
    tp = self.db.list_topics()[idx]
    # NOTE: 2026-05-15 gen by tea_agent, 同主题跳过，避免 refresh_topics 触发全量覆盖
    if tp["topic_id"] == self.current_topic_id:
        return
    self.switch_topic(tp["topic_id"])


def _suggest_new_topic_if_needed(self, topic_id: str):
    """2026-05-17 gen by tea_agent, GUI 覆盖：状态栏提示新主题建议"""
    count = getattr(self, '_pending_topic_suggestion', 0)
    if count > 0:
        self.root.after(100, lambda c=count: self._update_status(
            f"💡 已切换 {c} 次方向，建议「➕ 新建主题」保持聚焦"
        ))
        self._pending_topic_suggestion = 0


def _on_summary_updated(self, topic_id: str, summary: str):
    """摘要更新后刷新 GUI 主题列表和状态栏。"""
    self.root.after(200, self._refresh_topics_preserve_selection)
    self.root.after(100, lambda s=summary: self._update_status(f"📝 摘要: {s}"))

# NOTE: 2026-05-02 09:06:48, self-evolved by tea_agent --- 添加 _notify_completion 方法：LLM完成后发送系统桌面通知

def _refresh_topics_preserve_selection(self):
    """刷新主题列表，refresh_topics() 已按 current_topic_id 自动高亮。"""
    self.refresh_topics()

# ── 主题列表 Tooltip ──
# NOTE: 2026-05-08 gen by tea_agent, 鼠标悬停显示创建日期和最后使用日期

def _on_topic_hover(self, event):
    """鼠标在主题列表上移动时，延迟显示 tooltip"""
    # Treeview: identify_row → find index
    item_id = self.topic_list.identify_row(event.y)
    idx = self.topic_list.index(item_id) if item_id else -1
    if idx < 0 or idx >= len(self._topic_cache):
        self._hide_tooltip()
        return

    # 取消之前的延迟任务
    if self._topic_hover_after:
        self.root.after_cancel(self._topic_hover_after)
        self._topic_hover_after = None

    # 300ms 后显示
    self._topic_hover_after = self.root.after(
        300, lambda: self._show_tooltip(event, idx)
    )


def _on_topic_leave(self, event):
    """鼠标离开列表时隐藏 tooltip"""
    if self._topic_hover_after:
        self.root.after_cancel(self._topic_hover_after)
        self._topic_hover_after = None
    self._hide_tooltip()


def _on_history_link_click(self, url):
    """处理 tea://round/N 或 tea://latest 或 tea://image/N 链接点击，外部链接用系统浏览器打开"""
    try:
        # NOTE: 2026-05-18 gen by tea_agent, 外部链接用系统默认浏览器打开
        if url.startswith("http://") or url.startswith("https://"):
            webbrowser.open(url)
            return
        if url.startswith("tea://image/"):
            idx = int(url.rsplit("/", 1)[-1])
            self.images.show_popup(idx)
            return
        if url.startswith("tea://round/"):
            idx = int(url.rsplit("/", 1)[-1])
            self._current_round_view = idx
            self._render_round_view(idx)
        elif url == "tea://latest":
            self._current_round_view = None
            self._render_and_show_chat()
    except Exception:
        pass

# @2026-05-15 gen by tea_agent, 图片点击放大弹窗

def open_topic_dialog(self):
    """打开主题管理弹窗"""
    TopicDialog(self.root, self.db,
                on_switch=lambda tid: self.root.after(0, self.switch_topic, tid))

# NOTE: 2026-05-01 15:33:25, self-evolved by tea_agent --- 添加 TkGUI.open_config_dialog 方法（紧挨 open_memory_dialog）

def open_memory_dialog(self):
    """打开记忆管理对话框"""
    MemoryDialog(self.root, self.db)


def open_config_dialog(self):
    """打开配置编辑对话框"""

    def on_save(cfg):
        # 同步到当前 session
        if hasattr(self, 'sess') and self.sess:
            for key in cfg._RUNTIME_CONFIG_KEYS:
                val = getattr(cfg, key, None)
                if val is not None and hasattr(self.sess, key):
                    try:
                        setattr(self.sess, key, val)
                    except Exception:
                        pass
        self._update_status("⚙️ 配置已更新")

    ConfigDialog(self.root, on_save=on_save)


    def on_save(cfg):
        # 同步到当前 session
        if hasattr(self, 'sess') and self.sess:
            for key in cfg._RUNTIME_CONFIG_KEYS:
                val = getattr(cfg, key, None)
                if val is not None and hasattr(self.sess, key):
                    try:
                        setattr(self.sess, key, val)
                    except Exception:
                        pass
        self._update_status("⚙️ 配置已更新")

    ConfigDialog(self.root, on_save=on_save)


def interrupt(self, e=None):
    if self.generating:
        self.sess.interrupt()
        self.safe_log("\n🛑 已打断", "tool")
        self.generating = False
        # 先刷新控制台剩余内容，再 flush 到 messages
        # NOTE: 2026-05-08 08:46:00, self-evolved by tea_agent --- interrupt 时也刷新 pending 控制台内容
        if self._pending_console_text:
            self.console.config(state=tk.NORMAL)
            for text, tag in self._pending_console_text:
                if tag == "think":
                    self.console.insert(tk.END, text, "think")
                else:
                    self.console.insert(tk.END, text)
            self.console.see(tk.END)
            self.console.config(state=tk.DISABLED)
            self._pending_console_text.clear()
        self.root.after(0, self._flush_stream_to_messages)
        self.root.after(0, self._render_and_show_chat)
        self.root.after(0, self._show_raw_check_btn)
        self._update_status("🛑 已打断")

# NOTE: 2026-04-30 19:36:28, self-evolved by tea_agent --- 补回缺失的 __main__ 入口，使 python -m tea_agent.main_db_gui 可正常启动 GUI
# NOTE: 2026-05-09 19:26:36, self-evolved by tea_agent --- 修复 main() no_gui 模式：用 CLI 回退替代 NotImplementedError 崩溃
# ═══ @2026-05-15 gen by tea_agent, Composition 委派包装器 ═══


