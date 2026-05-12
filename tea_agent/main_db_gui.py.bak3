import tkinter as tk
from tkinter import font as tkFont
from tkinter import ttk, scrolledtext, Listbox, Frame
import threading
import os
import os.path as osp
import sys
import re
import string
import html as html_mod
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, cast, Callable, Optional, List, Tuple
import logging

try:
    from tkinterweb import HtmlFrame
    import markdown
    HAS_TKINTERWEB = True
except ImportError:
    HAS_TKINTERWEB = False

logger = logging.getLogger("main_db_gui")

# ====================== 包导入兼容处理 ======================
# NOTE: 2026-05-02 18:31:44, self-evolved by tea_agent --- main_db_gui.py：导入 chat_room_connector 并在初始化后启动连接器
if __name__ == "__main__":
    parent_dir = str(Path(__file__).resolve().parent.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
# NOTE: 2026-05-04 08:34:18, self-evolved by tea_agent --- main_db_gui.py 导入 mqtt_agent_connector（两处分支）
# NOTE: 2026-05-04 18:47:48, self-evolved by tea_agent --- 添加 AgentCore 导入
    from tea_agent.onlinesession import OnlineToolSession
    from tea_agent.store import Storage
    from tea_agent import tlk
    from tea_agent import chat_room_connector
    from tea_agent import mqtt_agent_connector
    from tea_agent.agent_core import AgentCore
# NOTE: 2026-05-01 15:30:42, self-evolved by tea_agent --- 为 GUI 添加 ConfigDialog 配置编辑弹窗 + 左侧"⚙️ 配置"按钮
    from tea_agent.config import load_config, get_config, save_config, ModelConfig
else:
    from .onlinesession import OnlineToolSession
    from .store import Storage
    from . import tlk
    from . import chat_room_connector
    from . import mqtt_agent_connector
    from .agent_core import AgentCore
# NOTE: 2026-05-01 15:30:48, self-evolved by tea_agent --- 给 GUI 加 ConfigDialog 弹窗：import save_config（第二处）
    from .config import load_config, get_config, save_config, ModelConfig

# ====================== 配置加载 ======================
# 优先使用 $HOME/.tea_agent/config.yaml，不存在时使用 tea_agent/config.yaml
_cfg = load_config()

if not _cfg.main_model.is_configured:
    print("错误: 请配置主模型 (main_model)")
    print("  编辑 $HOME/.tea_agent/config.yaml 或 tea_agent/config.yaml")
    sys.exit(1)

API_KEY = _cfg.main_model.api_key
API_URL = _cfg.main_model.api_url
MODEL = _cfg.main_model.model_name
CHEAP_MODEL = _cfg.cheap_model

_storage_ = None
_toolkit_ = None


# ====================== 跨平台字体检测 ======================
# @2026-04-29 gen by deepseek-v4-pro, 跨平台字体自动检测(Windows/Linux)
import platform as _platform

_IS_WINDOWS = _platform.system() == "Windows"

SYSTEM_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"
# NOTE: 2026-04-30 20:02:57, self-evolved by tea_agent --- 添加 Wayland/X11 显示缩放检测：全局 _SCALE_FACTOR + _fs() 辅助函数，_init_fonts() 中自动检测 tk scaling 并更新 _DEFAULT_FONT_SIZE
_FONTS_DETECTED = False
_SCALE_FACTOR = 1.0


def _fs(size):
    """返回按显示缩放因子调整后的字体大小（适配 Wayland/X11 高分屏）。"""
    return max(1, int(size * _SCALE_FACTOR))


def _init_fonts():
    """延迟检测系统可用字体（需 Tk root 创建后调用）。"""
    global SYSTEM_FONT, MONO_FONT, _FONTS_DETECTED
    if _FONTS_DETECTED:
        return
    try:
        from tkinter import font as _tkfont
        available = set(_tkfont.families())

        def _detect(candidates):
            for f in candidates:
                if f in available:
                    return f
            return "TkDefaultFont"  # 最终回退：系统默认字体

        if _IS_WINDOWS:
            SYSTEM_FONT = _detect([
                "Microsoft YaHei", "Microsoft YaHei UI",
                "DengXian", "SimHei", "SimSun",
                "Noto Sans SC", "Microsoft JhengHei",
            ])
            MONO_FONT = _detect([
                "Cascadia Code", "Cascadia Mono",
                "Consolas", "Courier New", "Lucida Console",
            ])
        else:
            SYSTEM_FONT = _detect([
                "Noto Sans CJK SC", "Noto Sans SC",
                "WenQuanYi Micro Hei", "Source Han Sans SC",
                "DejaVu Sans",
            ])
            MONO_FONT = _detect([
                "Noto Sans Mono CJK SC", "DejaVu Sans Mono",
                "Source Han Mono SC", "Courier New",
            ])
        # DEBUG: 打印检测结果，方便排查字体问题
        import logging
        logging.getLogger("tea_agent").debug(
            f"字体检测: SYSTEM={SYSTEM_FONT}, MONO={MONO_FONT}"
        )
    except Exception as e:
        import logging
        logging.getLogger("tea_agent").warning(
            f"字体检测失败: {e}，使用默认字体"
        )

    global _SCALE_FACTOR, _DEFAULT_FONT_SIZE
    try:
        import tkinter as _tk2
        root = _tk2._default_root
        if root:
            sf = float(root.tk.call("tk", "scaling"))
            if 1.0 < sf <= 4.0:
                _SCALE_FACTOR = sf
    except Exception:
        pass
    _DEFAULT_FONT_SIZE = max(12, int(16 * _SCALE_FACTOR))

    _FONTS_DETECTED = True

_DEFAULT_FONT_SIZE = 16  # 模块级默认
# ====================== Markdown → HTML 渲染 ======================

_MD_CSS_TEMPLATE = string.Template("""
<style>
body { font-family: "Microsoft YaHei", "Microsoft YaHei UI", "DengXian", "SimHei", "SimSun", "Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "DejaVu Sans", sans-serif; font-size: ${font_size}px; line-height: 1.6; color: #333; padding: 8px; }
h1, h2, h3, h4, h5, h6 { margin: 0.8em 0 0.4em; color: #1a73e8; }
h1 { font-size: 1.5em; border-bottom: 2px solid #eee; padding-bottom: 0.3em; }
h2 { font-size: 1.3em; border-bottom: 1px solid #eee; padding-bottom: 0.3em; }
p { margin: 0.5em 0; }
code { background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-family: "Cascadia Code", "Consolas", "Courier New", "Noto Sans Mono CJK SC", "DejaVu Sans Mono", "Source Han Mono SC", monospace; font-size: 0.9em; }
pre { background: #f6f8fa; border: 1px solid #ddd; border-radius: 5px; padding: 12px; overflow-x: auto; }
pre code { background: none; padding: 0; }
ul, ol { padding-left: 1.5em; }
li { margin: 0.3em 0; }
blockquote { border-left: 4px solid #ddd; margin: 0.5em 0; padding: 0.5em 1em; color: #666; background: #f9f9f9; }
table { border-collapse: collapse; width: 100%; margin: 0.8em 0; }
th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
th { background: #f2f2f2; font-weight: bold; }
a { color: #1a73e8; text-decoration: none; }
a:hover { text-decoration: underline; }
hr { border: none; border-top: 1px solid #ddd; margin: 1em 0; }
strong { font-weight: bold; color: #222; }
/* NOTE: 2026-05-15 gen by tea_agent, 不同角色背景色区分 */
.msg-user { background: #dbeafe; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #3b82f6; }
.msg-user h3 { color: #1e40af; margin-top: 0; }
.msg-ai { background: #f3f4f6; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #6b7280; }
.msg-ai h3 { color: #374151; margin-top: 0; }
/* AI thinking blockquote */
.msg-ai blockquote { background: #fef3c7; border-left: 4px solid #f59e0b; padding: 6px 12px; border-radius: 4px; margin: 8px 0; color: #92400e; font-style: italic; }
/* code blocks = tool calls/results */
.msg-ai pre { background: #ecfdf5; border-left: 4px solid #10b981; padding: 8px 12px; border-radius: 4px; margin: 6px 0; font-size: 0.9em; }
.msg-ai code { background: #d1fae5; color: #065f46; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
/* notice / system */
.msg-notice { background: #fce7f3; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #ec4899; }
.msg-notice h3 { color: #9d174d; margin-top: 0; }
/* tool rounds */
.msg-tool { background: #ecfdf5; padding: 8px 14px; border-radius: 8px; margin: 6px 0; border-left: 4px solid #10b981; }
.msg-tool h5 { color: #065f46; margin-top: 0; font-size: 1em; }
em { font-style: italic; }
.msg-timestamp { font-size: 0.8em; color: #999; margin-bottom: 0.3em; }
.msg-divider { border: none; border-top: 2px solid #e8e8e8; margin: 1.2em 0; }
</style>
""")
def _render_markdown(text: str, font_size: int = _DEFAULT_FONT_SIZE) -> str:
    """将 markdown 文本转换为带样式的 HTML 片段"""
    if not HAS_TKINTERWEB:
        return text
    html_body = markdown.markdown(text, extensions=["fenced_code", "tables", "codehilite", "md_in_html"])
    css = _MD_CSS_TEMPLATE.safe_substitute(font_size=font_size)
    return f"<html><head>{css}</head><body>{html_body}</body></html>"


# NOTE: 2026-05-08 gen by tea_agent, 工具轮分组渲染：合并连续tool消息，生成带轮次编号的蓝色标题块

def _build_tool_blocks(messages):

    """扫描消息列表，将连续 tool 消息合并为分组 markdown 字符串。

    返回与原始消息列表等长的字符串列表，非 tool 位置为空字符串，tool 组只在组首输出。"""

    n = len(messages)

    result = [""] * n

    i = 0

    while i < n:

        if messages[i].get("role") != "tool":

            i += 1

            continue

        start = i

        while i < n and messages[i].get("role") == "tool":

            i += 1

        group = messages[start:i]

        ts = group[0].get("timestamp", "")

        ts_display = f'<span class="msg-timestamp">{ts}</span>' if ts else ""

        block = _render_tool_group(group, ts_display)

        result[start] = f'<div class="msg-tool" markdown="1">\n\n{block}\n</div>'

    return result





def _render_tool_group(group, ts_display):

    """将一组连续的 tool 消息渲染为 markdown，带轮次编号"""

    lines_out = [f"{ts_display}\n##### 🔧 工具"]

    round_num = 0

    for msg in group:

        text = msg.get("content", "").strip()

        m = re.match(r'🔧 调用工具：(\w+)\((.+)\)', text)

        if m:

            round_num += 1

            tool_name = m.group(1)

            args = m.group(2)

            if len(args) > 160:

                args = args[:160] + "..."

            lines_out.append(f"\n**第 {round_num} 轮**")

            lines_out.append(f"- **调用**: `{tool_name}`")

            lines_out.append(f"- **参数**: `{args}`")

            continue

        if text.startswith("📋 结果："):

            result = text[6:]

            if len(result) > 200:

                result = result[:200] + "..."

            lines_out.append(f"- **结果**: {result}")

            continue

        if text.startswith("ℹ️ "):

            info = text[3:]

            if len(info) > 200:

                info = info[:200] + "..."

            lines_out.append(f"\nℹ️ {info}")

            continue

        display = text

        if len(display) > 200:

            display = display[:200] + "..."

        lines_out.append(f"🔧 {display}")

    lines_out.append("")

    return "\n".join(lines_out)



def _chat_to_markdown(messages):
    """将聊天消息列表转换为 markdown 格式，包含时间戳和分割线"""
    # 预计算工具轮分组块
    tool_blocks = _build_tool_blocks(messages)
    parts = []
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")
        ts_display = f'<span class="msg-timestamp">{ts}</span>' if ts else ""
        if role == "user":
            parts.append(f'{ts_display}\n\n<div class="msg-user" markdown="1">\n\n### 👤 你\n\n{content.strip()}\n</div>\n')
        elif role == "ai":
            parts.append(f'{ts_display}\n\n<div class="msg-ai" markdown="1">\n\n### 🤖 AI\n\n{content.strip()}\n</div>\n\n---\n')
        elif role == "tool":
            if tool_blocks[i]:
                parts.append(tool_blocks[i])
        elif role == "notice":
            # NOTE: 2026-05-15 gen by tea_agent, 去掉 --- 包裹避免与 AI 末尾的 --- 连成三条水平线
            parts.append(f"\n{content.strip()}\n")
    return "\n".join(parts)

def _generate_topic_summary(client, model: str, conversations: List[Dict]) -> Optional[str]:
    """
    根据最近3轮对话通过 LLM 生成不超过20字的摘要。

    Args:
        client: OpenAI 客户端实例
        model: 模型名称
        conversations: 最近的对话列表（按时间正序），包含 user_msg 和 ai_msg

    Returns:
        不超过20字的摘要字符串；若生成失败则返回 None
    """
    if not conversations:
        return None
        
# NOTE: 2026-05-01 20:12:20, self-evolved by tea_agent --- _generate_topic_summary 只收集 user_msg，不混入 AI 回复
    user_msgs = []
    for conv in conversations:
        um = conv.get("user_msg", "").strip()
        if um:
            if len(um) > 200:
                um = um[:200] + "..."
            user_msgs.append(f"用户：{um}")

    if not user_msgs:
        return None

    user_content = _TOPIC_SUMMARY_USER_TEMPLATE.format(
        user_msgs="\n".join(user_msgs)
    )

# NOTE: 2026-05-07 11:27:55, self-evolved by tea_agent --- _generate_topic_summary 添加模型请求/响应的 DEBUG 日志
    try:
        logger.debug(f"generate_topic_summary request: model={model}, conversations={len(conversations)}, user_msgs={len(user_msgs)}")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _TOPIC_SUMMARY_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=50,
        )
        
        # 安全检查返回值
        if not response.choices or len(response.choices) == 0:
            return None
            
# NOTE: 2026-05-07 11:12:16, self-evolved by tea_agent --- 在 _generate_topic_summary 中添加原始返回调试日志，定位 LLM 返回被过滤的原因
# NOTE: 2026-05-07 11:14:38, self-evolved by tea_agent --- _generate_topic_summary 处理 reasoning_content：deepseek 推理模型的 content 可能为空，fallback 读 reasoning_content
        content = response.choices[0].message.content
        # DeepSeek 等推理模型可能把回复放到 reasoning_content 中，content 为空
        if not content:
            content = getattr(response.choices[0].message, 'reasoning_content', None)
        if not content or not isinstance(content, str):
            logger.warning(f"_generate_topic_summary: API 返回空 content, model={model}")
            return None
            
# NOTE: 2026-05-01 08:10:00, self-evolved by tea_agent --- _generate_topic_summary 增加最小长度≥2的校验，防止LLM返回如"为"的单字摘要
        raw = content.strip()
        # 调试日志：记录 LLM 原始返回，便于排查过滤原因
        logger.info(f"_generate_topic_summary 原始返回: model={model}, raw_len={len(raw)}, raw={repr(raw[:80])}")
        # 去掉各种引号包裹（中英文全角半角）
        raw = re.sub(r'^[\'"\u201c\u201d\u2018\u2019\u300c\u300d\uff02\uff07]+', '', raw)
        raw = re.sub(r'[\'"\u201c\u201d\u2018\u2019\u300c\u300d\uff02\uff07]+$', '', raw)
        raw = raw.strip()
        
# NOTE: 2026-05-07 11:12:33, self-evolved by tea_agent --- 在 _generate_topic_summary 过滤链各环节添加具体日志，区分"空 raw"和"过短被拒"
        if not raw:
            logger.warning(f"_generate_topic_summary: 清洗后 raw 为空, content={repr(content[:80])}")
            return None
        
# NOTE: 2026-05-01 08:17:32, self-evolved by tea_agent --- _generate_topic_summary min_length从2提高到5，拒绝"KB与"这种3字残句
# NOTE: 2026-05-01 08:18:13, self-evolved by tea_agent --- min_length调整为4：拒绝"为"(1)、"KB与"(3)，放行"你好世界"(4)
        # 拒绝过短的摘要（<4个字符，如"为"(1)、"KB与"(3)等LLM残句）
        if len(raw) < 4:
            logger.warning(f"_generate_topic_summary: 摘要过短被拒, len={len(raw)}, raw={repr(raw)}")
            return None
            
        if len(raw) > 20:
            raw = raw[:20]
            
        return raw if raw else None
    except Exception as e:
        # 2026-05-06 gen by tea_agent, log summary failure reason for debugging
        logger.warning(f"_generate_topic_summary 失败: {type(e).__name__}: {e}, model={model}")
        return None


# ====================== GUI 主界面 ======================

# 2026-05-09 gen by tea_agent, Dialog 类拆分至 gui_dialogs.py
from tea_agent.gui_dialogs import MemoryDialog, TopicDialog, ConfigDialog

# NOTE: 2026-05-04 18:47:26, self-evolved by tea_agent --- TkGUI 继承 AgentCore，消除重复代码
class TkGUI(AgentCore):
    def __init__(self, root, debug:bool=False):
        self.root = root
        self._update_title()  # NOTE: 2026-05-15 gen by tea_agent, 标题含当前目录
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)

        self.sess = None  # 预设，AgentCore._init_session 会创建它

        # ── AgentCore 初始化：配置、目录、Storage/Toolkit、连接器、会话、MQTT ──
        super().__init__(debug=debug)

        # 暴露给 toolkit 工具函数
        globals()["_storage_"] = self.db
        globals()["tlk"]._toolkit_ = self.toolkit

        # HtmlFrame 缩放级别
        self._zoom_level = 100

        # 聊天消息列表
        self.chat_messages: List[Dict] = []
        # NOTE: 2026-05-15 gen by tea_agent, 当前查看的历史轮次索引，None=最新轮
        self._current_round_view: Optional[int] = None
        self._chat_rounds: List[List[Dict]] = []

        # 当前 stream 累积 buffer
        self._stream_buffer = ""
        self._think_buffer = ""  # think/reasoning 内容缓冲区
        # NOTE: 2026-05-08 08:50:00, self-evolved by tea_agent --- 初始化 _pending_console_text 缓冲队列，供 500ms 定时器批量刷新
        self._pending_console_text = []  # (text, tag) 列表

        # 当前对话 ID
        self._current_conversation_id: Optional[int] = None

# NOTE: 2026-05-04 18:59:23, self-evolved by tea_agent --- 移除冗余 _init_session 调用，在 UI 创建后加 status 显示
        # 创建界面
        self._create_ui()
        if hasattr(self,"sess") and self.sess is not None:
            self.sess.tool_log = self.safe_log_tool

        # 会话已由 AgentCore.__init__ 初始化，这里补状态显示
        cheap_m = self._cfg.cheap_model
        cheap_info = f" | 摘要模型: {cheap_m.model_name}" if cheap_m.model_name else ""
        self._update_status(f"📡 已连接 | 模型: {self._cfg.main_model.model_name}{cheap_info}")

# NOTE: 2026-05-04 17:16:04, self-evolved by tea_agent --- GUI on_closing: 退出时调用 storage.close() 完成 WAL checkpoint + 关闭连接
        # 加载主题
        self.refresh_topics()
        self.auto_new_topic()

        # 注册窗口关闭回调：退出时正常关闭数据库（WAL checkpoint + close）
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    # NOTE: 2026-05-05, self-evolved by tea_agent --- 退出时正常关闭数据库：WAL checkpoint + MQTT 断开
    def _on_closing(self):
        """窗口关闭时的清理流程"""
        self._update_status("⏳ 正在清理资源...")
        try:
            self.db.close()
            self._update_status("✅ 数据库已正常关闭")
        except Exception as e:
            logger.warning(f"关闭数据库失败: {e}")
        try:
            mqtt_agent_connector.stop()
        except Exception:
            pass
        try:
            chat_room_connector.stop()
        except Exception:
            pass
        self.root.destroy()

    def _create_ui(self):
        """创建界面"""
        main_split = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_split.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # ===== 左侧面板 =====
        left = Frame(main_split, width=220)
        main_split.add(left, weight=1)

# NOTE: 2026-04-30 20:03:32, self-evolved by tea_agent --- 主题标签(12→_fs(12))和主题列表(10→_fs(10))字体适配缩放
        ttk.Label(left, text="聊天主题", font=(SYSTEM_FONT, _fs(14), "bold")).pack(pady=5)
        # NOTE: 2026-05-08 gen by tea_agent, 主题列表字体从 _fs(10) 调大到 _fs(15)，减少密集感
        # NOTE: 2026-05-08 gen by tea_agent, 显式构造字体对象确保正确渲染
        _topic_font = tkFont.Font(family=SYSTEM_FONT, size=_fs(12))
        # NOTE: 2026-06-18 gen by tea_agent, Listbox→Treeview：字体渲染更好
        _topic_style = ttk.Style()
        _topic_style.configure("Topic.Treeview", rowheight=_fs(30))
        self.topic_list = ttk.Treeview(left, show="tree", style="Topic.Treeview",
                                       selectmode="browse", height=12)
        self.topic_list.tag_configure("topic_item", font=_topic_font)
        self.topic_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.topic_list.bind("<<TreeviewSelect>>", self.on_topic_select)
        # NOTE: 2026-05-08 gen by tea_agent, 鼠标悬停显示主题日期tooltip
        self.topic_list.bind("<Motion>", self._on_topic_hover, add="+")
        self.topic_list.bind("<Leave>", self._on_topic_leave, add="+")
        self._topic_cache = []           # 缓存 list_topics 原始数据
        self._topic_tooltip = None       # tooltip Toplevel
        self._topic_hover_after = None   # debounce after_id
        ttk.Button(left, text="➕ 新建主题", command=self.new_topic).pack(
            fill=tk.X, padx=4, pady=2)
        ttk.Separator(left, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=4, pady=6)
        ttk.Button(left, text="📁 主题管理", command=self.open_topic_dialog).pack(
            fill=tk.X, padx=4, pady=2)
# NOTE: 2026-05-01 15:33:14, self-evolved by tea_agent --- 左侧面板加"⚙️ 配置"按钮 + TkGUI.open_config_dialog 方法
        ttk.Button(left, text="🧠 记忆管理", command=self.open_memory_dialog).pack(
            fill=tk.X, padx=4, pady=2)
        ttk.Button(left, text="⚙️ 配置", command=self.open_config_dialog).pack(
            fill=tk.X, padx=4, pady=2)

        # ===== 右侧面板 =====
        right = Frame(main_split)
        main_split.add(right, weight=5)

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        status_frame = ttk.Frame(right)
        status_frame.pack(anchor=tk.E, padx=6, fill=tk.X)
        ttk.Label(status_frame, textvariable=self.status_var,
                  foreground="#666").pack(side=tk.LEFT, padx=(0, 20))

        # 聊天区域
        chat_split = ttk.PanedWindow(right, orient=tk.VERTICAL)
        chat_split.pack(fill=tk.BOTH, expand=True)

        chat_frame = Frame(chat_split)
        chat_split.add(chat_frame, weight=4)

# NOTE: 2026-04-30 20:03:16, self-evolved by tea_agent --- 控制台字体使用 _fs(11) 适配缩放
        self.console = scrolledtext.ScrolledText(
            chat_frame, font=(SYSTEM_FONT, _fs(15)), bg="white", fg="black", wrap=tk.WORD
        )
        self.console.config(state=tk.DISABLED)

        if HAS_TKINTERWEB:
            # NOTE: 2026-05-15 gen by tea_agent, 添加 on_link_click 回调支持历史轮次链接
            self.chat_view = HtmlFrame(chat_frame, messages_enabled=False, on_link_click=self._on_history_link_click)
        else:
            self.chat_view = scrolledtext.ScrolledText(
                chat_frame, font=(SYSTEM_FONT, _fs(15)), bg="#fafafa", fg="black", wrap=tk.WORD
            )
            self.chat_view.config(state=tk.DISABLED)

        self._show_mode = "console"
        self._switch_display("console")

        # 输入区域
        input_frame = Frame(chat_split)
        chat_split.add(input_frame, weight=1)
# NOTE: 2026-04-30 20:03:24, self-evolved by tea_agent --- 输入框字体使用 _fs(14)、输入提示使用 _fs(9) 适配缩放
        self.input_box = scrolledtext.ScrolledText(
            input_frame, font=(SYSTEM_FONT, _fs(16)), height=4, bg="#f8f8f8"
        )
        self.input_box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)


        ttk.Label(input_frame, text="Enter 发送 | Shift+Enter 换行 | ESC 打断",
                  foreground="#666").pack(anchor=tk.E, padx=6)

        # 样式配置
        self.console.tag_configure("user", foreground="#0055cc")
        self.console.tag_configure("ai", foreground="black")
        self.console.tag_configure("tool", foreground="#d68000")
# NOTE: 2026-04-30 20:03:47, self-evolved by tea_agent --- title 标签字体使用 _fs(12) 适配缩放
        self.console.tag_configure(
            "title", foreground="#0066cc", font=(SYSTEM_FONT, _fs(14), "bold"))
        self.console.tag_configure("notice", foreground="#008800")
# NOTE: 2026-05-07 17:33:59, self-evolved by tea_agent --- 添加 think 标签（灰色斜体）用于控制台思考过程显示
        self.console.tag_configure("error", foreground="#cc0000")
        self.console.tag_configure("think", foreground="#888888", font=(SYSTEM_FONT, _fs(13), "italic"))

        # 快捷键绑定
        self.input_box.bind("<Return>", self.send)
        self.input_box.bind("<Shift-Return>", self.newline)
        self.root.bind("<Escape>", self.interrupt)

        # HtmlFrame 缩放快捷键
        if HAS_TKINTERWEB:
            self.root.bind("<Control-equal>", self.zoom_in)
            self.root.bind("<Control-plus>", self.zoom_in)
            self.root.bind("<Control-minus>", self.zoom_out)
            self.root.bind("<Control-underscore>", self.zoom_out)

    def zoom_in(self, e=None):
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = min(self._zoom_level + 10, 200)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"

    def zoom_out(self, e=None):
        if not HAS_TKINTERWEB or self._show_mode != "chat_view":
            return "break"
        self._zoom_level = max(self._zoom_level - 10, 50)
        self._apply_zoom()
        self._update_status(f"🔍 缩放: {self._zoom_level}%")
        return "break"

    def _apply_zoom(self):
        if not HAS_TKINTERWEB or not self._filtered_messages():
            return
        md = _chat_to_markdown(self._filtered_messages())
        font_size = int(_DEFAULT_FONT_SIZE * self._zoom_level / 100)
        html = _render_markdown(md, font_size=font_size)
        self._html_render(html)
        self.root.after(200, self.scroll_to_bottom)

# NOTE: 2026-05-01 10:38:17, self-evolved by tea_agent --- 在 _switch_display 之后添加 _show_loading 方法（简单 spinner + 三点动画）
    def _switch_display(self, mode: str):
        if mode == self._show_mode:
            return
        self._show_mode = mode
        if mode == "console":
            self.chat_view.pack_forget()
            self.console.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        else:
            self.console.pack_forget()
            self.chat_view.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            self.root.after(400, self.scroll_to_bottom)

# NOTE: 2026-05-07 14:25:13, self-evolved by tea_agent --- _show_loading 支持动态进度文本 + switch_topic 中后台线程上报加载进度，GUI 不卡死
    # NOTE: 2026-05-01, self-evolved by tea_agent --- _show_loading: HtmlFrame spinner动画，异步加载历史时不再长时间空白
    # NOTE: 2026-05-07 gen by tea_agent, _show_loading 支持 progress 参数动态更新进度文本
    def _show_loading(self, text: str = "正在加载历史记录", progress: str = None):
        """在 HtmlFrame 中显示加载动画（spinner + 文字），用于异步加载期间的过渡。
        progress 非空时显示为进度文本（如 '第 5 / 20 条'），常用于后台线程实时更新。"""
        if not HAS_TKINTERWEB:
            self._switch_display("console")
            msg = f"⏳ {text}..."
            if progress:
                msg = f"⏳ {text}: {progress}"
            self.log(msg, "notice")
            return

        display_text = text
        if progress:
            display_text = f"{text}（{progress}）"

        loading_html = f'''<html><head>
<style>
body {{ display:flex; align-items:center; justify-content:center; height:100vh;
       margin:0; background:#fafafa; font-family:"Noto Sans CJK SC","Microsoft YaHei",sans-serif; }}
.loader {{ text-align:center; }}
.spinner {{ width:48px; height:48px; border:4px solid #e0e0e0; border-top-color:#1a73e8;
           border-radius:50%; animation:spin 0.8s linear infinite; margin:0 auto 20px; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
.text {{ color:#888; font-size:{_DEFAULT_FONT_SIZE}px; }}
.dots::after {{ content:''; animation:d 1.5s steps(4,end) infinite; }}
@keyframes d {{ 0% {{ content:'' }} 25% {{ content:'.' }} 50% {{ content:'..' }} 75% {{ content:'...' }} 100% {{ content:'' }} }}
</style></head>
<body><div class="loader">
<div class="spinner"></div>
<div class="text">{html_mod.escape(display_text)}<span class="dots"></span></div>
</div></body></html>'''

        # 切换到 chat_view 但不修改 chat_messages
        if self._show_mode != "chat_view":
            self.console.pack_forget()
            self.chat_view.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            self._show_mode = "chat_view"
        self._html_render(loading_html)
# NOTE: 2026-05-07 14:45:26, self-evolved by tea_agent --- 新增 _poll_loading_progress 方法：50ms 轮询共享变量，仅变化时 load_html
        # 不调用 root.update()：让 CSS animation 自己跑，GUI 主循环保持响应

# NOTE: 2026-05-07 14:48:15, self-evolved by tea_agent --- _poll_loading_progress 改为从队列逐条出队，确保每个进度都被渲染
# NOTE: 2026-05-07 14:49:37, self-evolved by tea_agent --- 轮询器：队列排空且 _loading_done 时触发 _render_loaded_topic 或 _render_topic_error
    def _poll_loading_progress(self):
        """定时器（50ms）：从 _progress_queue 逐条出队更新 HtmlFrame 进度；
        队列排空后若后台线程已完成，触发最终渲染。"""
        if not HAS_TKINTERWEB:
            return
        if self._progress_queue:
            progress = self._progress_queue.pop(0)  # FIFO
            self._show_loading("正在加载历史记录", f"{progress[0]}/{progress[1]}")
            self.root.after(50, self._poll_loading_progress)
            return
        # 队列已空，检查后台线程是否完成
        if getattr(self, '_loading_done', False):
            # 最终渲染
            if hasattr(self, '_pending_error'):
                self._render_topic_error(self._pending_error)
                delattr(self, '_pending_error')
            elif hasattr(self, '_pending_render'):
                self._render_loaded_topic(self._pending_render)
                delattr(self, '_pending_render')
            self._loading_done = False
            return
        # 线程还在跑，继续等待
        self.root.after(50, self._poll_loading_progress)

    def scroll_to_bottom(self):
        self.chat_view.yview_moveto(1.0)

    # 2026-05-11 gen by tea_agent, 将 render 到 HtmlFrame 的 HTML 同时 print 到终端
    def _html_render(self, html: str):
        # NOTE: 2026-05-15 gen by tea_agent, 注释掉终端打印避免刷屏，调试时可取消注释
        # print(f"\n{'='*60}")
        # print(f"[HtmlFrame render] {len(html)} chars")
        # print(f"{'='*60}")
        # print(html)
        # print(f"{'='*60}\n")
        try:
            self.chat_view.load_html(html)
        except Exception as e:
            print(f"[_html_render ERROR] {e}")
            import traceback
            traceback.print_exc()

# NOTE: 2026-05-07 17:33:05, self-evolved by tea_agent --- _render_chat 支持可选的流式缓冲区参数，_stream_render_tick 传递当前 think/stream 内容
    def _render_chat(self, streaming_think: str = "", streaming_text: str = ""):
        """渲染 HtmlFrame。可选 streaming_think/streaming_text 用于流式输出期间实时显示。"""
        msgs = self._filtered_messages()
        # 流式内容临时追加到最后一条 AI 消息
        streaming = streaming_think + streaming_text
        if streaming:
            if msgs and msgs[-1]["role"] == "ai":
                msgs[-1] = dict(msgs[-1])
                msgs[-1]["content"] = msgs[-1]["content"] + streaming
            else:
                msgs.append({"role": "ai", "content": streaming, "timestamp": self._now_ts()})
        md = _chat_to_markdown(msgs)
        if HAS_TKINTERWEB:
            font_size = int(_DEFAULT_FONT_SIZE * self._zoom_level / 100)
            html = _render_markdown(md, font_size=font_size)
            self._html_render(html)
        else:
            self.chat_view.config(state=tk.NORMAL)
            self.chat_view.delete("1.0", tk.END)
            self.chat_view.insert("1.0", md)
            self.chat_view.config(state=tk.DISABLED)
            self.chat_view.see(tk.END)

    def _now_ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

# NOTE: 2026-05-04 09:27:57, self-evolved by tea_agent --- GUI 添加 _sess_lock 和 _setup_mqtt_reply_handler 调用
# NOTE: 2026-05-04 18:48:10, self-evolved by tea_agent --- _init_session 继承 AgentCore，仅补 UI 回调
# NOTE: 2026-05-04 18:58:17, self-evolved by tea_agent --- GUI _init_session 调用 super() 确保 sess 被创建
# NOTE: 2026-05-04 18:58:47, self-evolved by tea_agent --- _init_session 只设 tool_log，status 移到 UI 创建后
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

    def _update_status(self, msg: str):
        self.status_var.set(msg)

    def safe_stream(self, text):
        self.root.after(0, self.stream, text)

    def safe_log(self, msg, tag="ai"):
        self.root.after(0, self.log, msg, tag)

    def safe_log_tool(self, msg: str):
        self.root.after(0, self.log_tool, msg)

    def safe_update_status(self, msg: str):
        if msg.startswith("!MAX_ITER:"):
            self.root.after(0, self._handle_max_iter, msg)
        else:
            self.root.after(0, self._update_status, msg)

    # @2026-04-29 gen by deepseek-v4-pro, 工具调用达上限时弹框询问继续/终止
    def _handle_max_iter(self, msg: str):
        """弹出对话框询问用户是否继续工具调用。"""
# NOTE: 2026-05-04 19:39:42, self-evolved by tea_agent --- GUI 续命弹窗：文案从 5 轮改为 10 轮，确认后追加 10 轮
        from tkinter import messagebox
        display = msg.replace("!MAX_ITER:", "")
        result = messagebox.askyesno(
            "达到工具调用上限",
            f"{display}\n\n选择「是」再执行 10 轮\n选择「否」终止当前回答",
            parent=self.root,
        )
        if hasattr(self, 'sess') and self.sess:
            self.sess._continue_after_max = result
            self.sess._max_iter_wait.set()
            if result:
                self.sess._extra_iterations += 10
                self._update_status("⏳ 已续命 10 轮，继续生成... (ESC 打断)")
            else:
                self._update_status("🛑 用户终止工具调用")

        self.log("=" * 50, "title")
        self.log(f"📦 已加载工具函数（共 {len(self.toolkit.func_map)} 个）", "title")
        for name in self.toolkit.func_map.keys():
            self.log(f"✅ {name}", "notice")
        self.log("=" * 50, "title")
        self.log("")

    def log(self, msg, tag="ai"):
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, msg + "\n", tag)
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

        if tag in ("user", "ai", "tool", "notice"):
            self.chat_messages.append({"role": tag, "content": msg, "timestamp": self._now_ts()})

# NOTE: 2026-05-07 17:32:01, self-evolved by tea_agent --- stream() 识别 [THINK] 前缀分别缓冲，控制台灰色显示，触发 HtmlFrame 定期渲染
# NOTE: 2026-05-08 08:26:53, self-evolved by tea_agent --- 流式输出期间仅更新ScrolledText控制台，移除HtmlFrame的150ms定时渲染，会话完成后统一渲染HtmlFrame，降低GUI阻塞感
    def stream(self, text):
        # 检测 [THINK_DONE] 信号：本轮思考结束，刷新思考缓冲为独立消息
        if text == "[THINK_DONE]":
            self._flush_think_buffer_to_messages()
            return

        # 检测 thinking/reasoning 内容（[THINK] 前缀标记）
        is_think = text.startswith("[THINK]")
        display_text = text[7:] if is_think else text  # 去掉 7 字符标记

        # 分别缓冲：think + content 都入队，由 500ms 定时器批量刷新
        # # NOTE: 2026-05-08 09:04:24, self-evolved by tea_agent --- think 也入 pending 队列，500ms 批量刷新，既实时又不碎片化
        if is_think:
            self._think_buffer += display_text
            self._pending_console_text.append((display_text, "think"))
        else:
            self._stream_buffer += display_text
            self._pending_console_text.append((display_text, None))

        # 流式过程中不渲染 HtmlFrame（load_html 是重型操作），会话完成后 _render_and_show_chat 统一渲染

    def log_tool(self, msg: str):
        self.log(msg, "tool")
    def _stream_flush_tick(self):
        """500ms 定时器：批量将累积文本刷新到 ScrolledText 控制台。
        # NOTE: 2026-05-08 08:46:00, self-evolved by tea_agent --- 用 500ms 定时器替代每 token 的 GUI 操作，降低高速输出时的阻塞感
        相比每个 token 都 config(ENABLE/DISABLE) + insert + see(END)，
        合并为 500ms 批量操作可大幅降低 GUI 阻塞感。"""
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
        if self.generating:
            self.root.after(500, self._stream_flush_tick)


    def _flush_stream_to_messages(self):
        # 先刷新控制台剩余内容（确保最后一批 pending 文本显示完毕）
        # NOTE: 2026-05-08 08:46:00, self-evolved by tea_agent --- flush 前先清空 _pending_console_text 到 ScrolledText
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


        if self._think_buffer or self._stream_buffer:
            # @2026-05-16 gen by tea_agent, 最终 flush：先存思考消息，再存文本
            self._flush_think_buffer_to_messages()
            if self._stream_buffer:
                self.chat_messages.append({"role": "ai", "content": self._stream_buffer, "timestamp": self._now_ts()})
            self._stream_buffer = ""
    # @2026-05-16 gen by tea_agent, 工具轮思考过程独立存储
    def _flush_think_buffer_to_messages(self):
        """将当前 think 缓冲刷新为独立的 AI 思考消息。
        工具调用每轮结束后调用，确保思考过程与工具轮对应。"""
        if self._think_buffer:
            think_text = self._think_buffer.strip()
            self.chat_messages.append({
                "role": "ai",
                "content": f"> 💭 **思考过程**: {think_text}",
                "timestamp": self._now_ts()
            })
            self._think_buffer = ""

# NOTE: 2026-05-07 17:33:40, self-evolved by tea_agent --- clear_chat 初始化 _think_buffer 和 _stream_render_pending
    def clear_chat(self):
        self.console.config(state=tk.NORMAL)
        self.console.delete("1.0", tk.END)
        self.console.config(state=tk.DISABLED)
        self.chat_messages.clear()
        self._stream_buffer = ""
        self._think_buffer = ""
        self._pending_console_text.clear()
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
    def _update_title(self, topic_title=""):
        """设置窗口标题栏：{主题} - AI 工具调用助手 - {当前目录}"""
        import os
        cwd = os.path.basename(os.getcwd()) or os.getcwd()
        if topic_title:
            self.root.title(f"{topic_title} - AI 工具调用助手 - {cwd}")
        else:
            self.root.title(f"AI 工具调用助手 - {cwd}")

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
                    render_items.append(("user", f"你：{c['user_msg']}"))

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
                                        render_items.append(("tool", f"🔧 调用工具：{fn_name}({fn_args})"))
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

    def _render_loaded_topic(self, render_items):
        """主线程：清屏 + 逐条渲染准备好的数据"""
        self.clear_chat()
        for tag, text in render_items:
            self.log(text, tag)

        if HAS_TKINTERWEB and self.chat_messages:
            # NOTE: 2026-05-15 gen by tea_agent, 主题加载后也使用轮次视图
            self._render_and_show_chat()
        else:
            self._switch_display("chat_view")

        self.generating = False
        self._update_status("✅ 就绪")

    def _render_topic_error(self, error_msg):
        """主线程：加载失败回调"""
        self.clear_chat()
        self.log(f"❌ 加载历史失败: {error_msg}", "error")
        self.generating = False
        self._update_status("❌ 加载失败")

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

    def newline(self, e=None):
        self.input_box.insert(tk.INSERT, "\n")
        return "break"

# NOTE: 2026-05-01 11:43:46, self-evolved by tea_agent --- _update_topic_summary: 状态栏可见反馈 + LLM失败时用首条用户消息兜底 + 主线程刷新
# NOTE: 2026-05-01 11:49:01, self-evolved by tea_agent --- _update_topic_summary 加控台可见调试日志，追踪每一步执行
# NOTE: 2026-05-01 11:49:45, self-evolved by tea_agent --- _update_topic_summary 日志调用改用 root.after 调度到主线程，避免 tk 线程安全问题
# NOTE: 2026-05-01 11:57:59, self-evolved by tea_agent --- 移除 _update_topic_summary 调试日志，保留 WAL + 兜底 + 状态栏反馈等核心修复
# NOTE: 2026-05-04 09:08:01, self-evolved by tea_agent --- GUI TeaApp 添加 _publish_to_mqtt 方法
# NOTE: 2026-05-04 09:28:50, self-evolved by tea_agent --- GUI 添加 MQTT reply handler 三个方法
    # ── AgentCore 回调覆盖 ──────────────────────────

    def _on_mqtt_session_restored(self):
        """MQTT 消息处理后恢复 GUI 界面。"""
        self.root.after(0, self.refresh_topics)

    def _on_summary_updated(self, topic_id: str, summary: str):
        """摘要更新后刷新 GUI 主题列表和状态栏。"""
        self.root.after(200, self._refresh_topics_preserve_selection)
        self.root.after(100, lambda s=summary: self._update_status(f"📝 摘要: {s}"))

# NOTE: 2026-05-02 09:06:48, self-evolved by tea_agent --- 添加 _notify_completion 方法：LLM完成后发送系统桌面通知
    def _refresh_topics_preserve_selection(self):
        # Treeview: 用 selection() + index() 获取当前项
        sel = self.topic_list.selection()
        current_idx_val = self.topic_list.index(sel[0]) if sel else None
        self.refresh_topics()
        if current_idx_val is not None:
            try:
                children = self.topic_list.get_children()
                if 0 <= current_idx_val < len(children):
                    self.topic_list.selection_set(children[current_idx_val])
            except Exception:
                pass

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

    def _show_tooltip(self, event, idx):
        """在鼠标位置显示主题日期 tooltip"""
        if idx < 0 or idx >= len(self._topic_cache):
            return
        tp = self._topic_cache[idx]
        create_ts = tp.get("create_stamp", "")
        update_ts = tp.get("last_update_stamp", "")

        # 格式化时间戳（截断秒）
        def fmt(ts):
            if not ts:
                return "未知"
            s = str(ts)
            return s[:16] if len(s) >= 16 else s

        self._hide_tooltip()

        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg="#ffffcc")

        lines = [f"📅 创建: {fmt(create_ts)}", f"🕐 最后使用: {fmt(update_ts)}"]
        tip_text = "\n".join(lines)
        label = tk.Label(
            tip, text=tip_text,
            bg="#ffffcc", fg="#333333",
            font=(SYSTEM_FONT, _fs(10)),
            padx=8, pady=4,
            relief=tk.SOLID, borderwidth=1,
        )
        label.pack()

        # 定位：鼠标右下偏移
        x = self.root.winfo_pointerx() + 12
        y = self.root.winfo_pointery() + 8
        tip.geometry(f"+{x}+{y}")

        self._topic_tooltip = tip

    def _hide_tooltip(self):
        """隐藏 tooltip"""
        if self._topic_tooltip:
            try:
                self._topic_tooltip.destroy()
            except Exception:
                pass
            self._topic_tooltip = None

# NOTE: 2026-05-06 09:50:18, self-evolved by tea_agent --- 修正 _notify_completion 通知格式：标题 TeaAgent，内容 TeaAgent: {user} + {ai_msg}
# NOTE: 2026-05-06 09:49, self-evolved by tea_agent --- _notify_completion 通知格式修正：TeaAgent: {user} + {ai_msg}
    def _notify_completion(self, ai_msg: Optional[str] = None, user_msg: Optional[str] = None):
        """LLM 任务完成后发送桌面通知。通知内容: TeaAgent: {user_msg} + {ai_msg}。
        委托给 toolkit_notify（跨平台兼容：Windows/macOS/Linux）。"""
        # 构建通知消息：TeaAgent: {user_msg} + {ai_msg}
        if user_msg and ai_msg:
            u = user_msg.strip()
            a = ai_msg.strip()
            if len(u) > 20:
                u = u[:20] + "..."
            if len(a) > 40:
                a = a[:40] + "..."
            notification_msg = f"TeaAgent: {u} + {a}"
        elif ai_msg:
            notification_msg = ai_msg.strip()
            if len(notification_msg) > 60:
                notification_msg = notification_msg[:60] + "..."
            notification_msg = f"TeaAgent: {notification_msg}"
        else:
            notification_msg = "TeaAgent: AI 任务已完成"

        try:
            # 直接导入 toolkit_notify 以复用其跨平台实现
            from tea_agent.toolkit.toolkit_notify import toolkit_notify
            toolkit_notify("TeaAgent", notification_msg, urgency="normal", duration=5000)
        except Exception:
            pass  # 通知失败不影响主流程

# NOTE: 2026-05-04 19:35:31, self-evolved by tea_agent --- GUI send() 入口加 _shutting_down 闸门 — 重启中拒绝新消息
    def send(self, e=None):
        if self._shutting_down:
            self._update_status("🔄 代码已变更，等待重启...")
            return "break"
        if self.generating or not self.current_topic_id:
            return "break"
        msg = self.input_box.get("1.0", tk.END).strip()
        if not msg:
            return "break"
        self.input_box.delete("1.0", tk.END)

        self._switch_display("console")

        self.log(f"你：{msg}", "user")
        self.generating = True
        # 启动 500ms 定时器，批量刷新流式内容到 ScrolledText（不渲染 HtmlFrame）
        # NOTE: 2026-05-08 08:46:00, self-evolved by tea_agent --- 流式输出启动 _stream_flush_tick 500ms 定时器
        self.root.after(500, self._stream_flush_tick)
        self.log("AI：", "ai")

        mem_count = len(self.db.get_active_memories(50))
        self._update_status(f"⏳ 生成中... (ESC 打断) | 🧠 {mem_count}")

        def work():
            try:
                ai_msg, is_func = self.sess.chat_stream(
                    msg, 
                    callback=self.safe_stream,
                    topic_id=self.current_topic_id,
                    on_status=self.safe_update_status,
                )
                self.root.after(0, self._flush_stream_to_messages)

                # ── 标准后处理流水线（入库 → MQTT → Token → 摘要）──
                self._post_chat_pipeline(ai_msg, is_func, msg, self.current_topic_id)

                # GUI 特定：token 渲染 + 通知
                usage = self.sess._last_usage
                cheap_usage = self.sess._last_cheap_usage
# NOTE: 2026-05-07 13:14:48, self-evolved by tea_agent --- 完成状态栏消息增加嵌入模型 token (Emb:xxx)
                if usage and usage.get("total_tokens", 0) > 0:
                    self.root.after(0, lambda u=usage, cu=cheap_usage: self._add_token_notice_and_render(u, cu))
                    # 读取嵌入模型用量
                    emb_str = ""
                    try:
                        from tea_agent.embedding_util import get_embedding_engine
                        euse = get_embedding_engine().get_embedding_usage(reset=False)
                        if euse.get("total_tokens", 0) > 0:
                            emb_str = f" | Emb:{euse['total_tokens']:,}"
                    except Exception:
                        pass
                    status_msg = (f"✅ 完成 | Tokens: {usage['total_tokens']:,} "
                                  f"(P:{usage['prompt_tokens']:,} C:{usage['completion_tokens']:,}){emb_str}")
                    self.root.after(0, lambda m=status_msg: self._update_status(m))
                    self.root.after(0, self._refresh_topics_preserve_selection)
# NOTE: 2026-05-06 09:31, self-evolved by tea_agent --- 通知传入 user_msg，显示用户消息+AI回复
                    self.root.after(600, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
                else:
                    self.root.after(0, self._render_and_show_chat)
                    self.root.after(0, lambda: self._update_status("✅ 完成"))
# NOTE: 2026-05-06 09:31, self-evolved by tea_agent --- 通知传入 user_msg，显示用户消息+AI回复
                    self.root.after(600, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
            except Exception as ex:
                ai_msg = f"异常：{ex}"
                self.safe_stream(ai_msg)
                self.root.after(0, self._flush_stream_to_messages)
                if self._current_conversation_id is not None:
                    rounds = self.sess._rounds_collector
                    try:
                        self.db.update_msg_rounds(
                            conversation_id=self._current_conversation_id,
                            ai_msg=ai_msg,
                            is_func_calling=False,
                            rounds=rounds if rounds else None,
                        )
                    except Exception:
                        pass
                self.root.after(0, self._render_and_show_chat)
                self.root.after(0, lambda: self._update_status(f"❌ 错误: {ai_msg}"))
# NOTE: 2026-05-06 09:31, self-evolved by tea_agent --- 异常时通知也传入 user_msg
                self.root.after(600, lambda am=ai_msg, um=msg: self._notify_completion(am, um))
            finally:
                self.generating = False
                self.safe_log("")

        threading.Thread(target=work, daemon=True).start()
        return "break"

# NOTE: 2026-04-30 09:12:24, self-evolved by tea_agent --- 新增 _add_token_notice_and_render 方法，在聊天区域显示本轮token消耗
# NOTE: 2026-04-30 09:13:24, self-evolved by tea_agent --- 简化token显示格式，修复括号配对问题
# NOTE: 2026-04-30 09:15:53, self-evolved by tea_agent --- token通知增加当前主题累积消耗显示
# NOTE: 2026-04-30 09:26:32, self-evolved by tea_agent --- _add_token_notice_and_render改为Markdown表格(主模型+便宜模型，本轮+主题累积)
# NOTE: 2026-05-07 13:14:07, self-evolved by tea_agent --- _add_token_notice_and_render 表格新增嵌入模型列：本轮 reading + 主题累积 te_total/te_p
    def _add_token_notice_and_render(self, usage: dict, cheap_usage: dict = None):
        """在聊天消息中追加 Markdown 表格：本轮/主题累积 × 主模型/便宜模型/嵌入模型 token 消耗"""
        if cheap_usage is None:
            cheap_usage = {}
        # 本轮：主模型
        m_total = usage.get("total_tokens", 0)
        m_p = usage.get("prompt_tokens", 0)
        m_c = usage.get("completion_tokens", 0)
        # 本轮：便宜模型
        c_total = cheap_usage.get("total_tokens", 0)
        c_p = cheap_usage.get("prompt_tokens", 0)
        c_c = cheap_usage.get("completion_tokens", 0)
        # 嵌入模型 token 用量（从 EmbeddingEngine 读取本轮）
        e_total = 0
        e_p = 0
        try:
            from tea_agent.embedding_util import get_embedding_engine
            emb_engine = get_embedding_engine()
            emb_usage = emb_engine.get_embedding_usage(reset=False)  # 已在 _post_chat_pipeline reset
            e_total = emb_usage.get("total_tokens", 0)
            e_p = emb_usage.get("prompt_tokens", 0)
        except Exception:
            pass
        # 主题累积
        try:
            ts = self.db.get_topic_tokens(self.current_topic_id)
            tm_total = ts.get("total_tokens", 0)
            tm_p = ts.get("total_prompt_tokens", 0)
            tm_c = ts.get("total_completion_tokens", 0)
            tc_total = ts.get("total_cheap_tokens", 0)
            tc_p = ts.get("total_cheap_prompt_tokens", 0)
            tc_c = ts.get("total_cheap_completion_tokens", 0)
            te_total = ts.get("total_embedding_tokens", 0)
            te_p = ts.get("total_embedding_prompt_tokens", 0)
        except Exception:
            tm_total = tm_p = tm_c = tc_total = tc_p = tc_c = te_total = te_p = 0

# NOTE: 2026-04-30 09:27:37, self-evolved by tea_agent --- _cell()中去掉<br>改用空格，保证Markdown表格兼容性
# NOTE: 2026-05-07 13:18:26, self-evolved by tea_agent --- _cell 支持只有 P 无 C 的场景（嵌入模型），显示 total (P:xxx)
        def _cell(val, detail_p=None, detail_c=None):
            """格式化为 'total (P:x C:y)' 或 'total (P:x)' 或 '—'"""
            if val <= 0:
                return "—"
            if detail_p is not None and detail_c is not None:
                return f"{val:,} (P:{detail_p:,} C:{detail_c:,})"
            if detail_p is not None:
                return f"{val:,} (P:{detail_p:,})"
            return f"{val:,}"

# NOTE: 2026-05-07 13:14:18, self-evolved by tea_agent --- Token 表格新增嵌入模型列
        lines = [
            "| | 主模型 | 便宜模型 | 嵌入模型 |",
            "|-------|--------|----------|----------|",
            f"| 本轮 | {_cell(m_total, m_p, m_c)} | {_cell(c_total, c_p, c_c)} | {_cell(e_total, e_p)} |",
            f"| 主题 | {_cell(tm_total, tm_p, tm_c)} | {_cell(tc_total, tc_p, tc_c)} | {_cell(te_total, te_p)} |",
        ]
        token_msg = "\n".join(lines)
        self.chat_messages.append({"role": "notice", "content": token_msg, "timestamp": self._now_ts()})
        self._render_and_show_chat()

    # NOTE: 2026-05-16 gen by tea_agent, 工具轮始终显示：移除过滤逻辑，每次render显示全部消息
    def _filtered_messages(self):
        """返回用于 HtmlFrame 渲染的消息列表（始终包含工具轮）。"""
        return list(self.chat_messages)


    # NOTE: 2026-05-15 gen by tea_agent, 历史轮次分组：按 user 消息切分轮次
    def _group_into_rounds(self, msgs):
        """将消息列表按 user 角色切分为轮次列表。每轮从 user 开始。"""
        rounds = []
        current = []
        for msg in msgs:
            if msg["role"] == "user":
                if current:
                    rounds.append(current)
                current = [msg]
            else:
                current.append(msg)
        if current:
            rounds.append(current)
        return rounds

    # NOTE: 2026-05-15 gen by tea_agent, HtmlFrame 历史链接点击回调
    def _on_history_link_click(self, url):
        """处理 tea://round/N 或 tea://latest 链接点击"""
        try:
            if url.startswith("tea://round/"):
                idx = int(url.rsplit("/", 1)[-1])
                self._current_round_view = idx
                self._render_round_view(idx)
            elif url == "tea://latest":
                self._current_round_view = None
                self._render_and_show_chat()
        except Exception:
            pass

    # NOTE: 2026-05-15 gen by tea_agent, 构建轮次视图完整 HTML
    def _build_round_view_html(self, rounds, active_idx, font_size):
        """构建包含历史轮次链接表 + 当前轮内容的完整 HTML。"""
        import markdown as _md_lib
        total = len(rounds)
        is_latest = (self._current_round_view is None)
        
        # -- 状态指示行 --
        if is_latest:
            status_line = '<p style="margin:0 0 6px; color:#1a73e8; font-weight:bold;">\U0001f4cc 当前：最新轮（第' + str(total) + '轮 / 共' + str(total) + '轮）</p>'
        else:
            status_line = '<p style="margin:0 0 6px; color:#e67e22; font-weight:bold;">\U0001f4cc 当前查看：第' + str(active_idx + 1) + '轮 / 共' + str(total) + '轮 | <a href="tea://latest">\u2190 返回最新轮</a></p>'
        
        # -- 历史轮次表格 --
        max_rows = 12
        shown = []
        if total <= max_rows:
            shown = list(range(total))
        else:
            shown = list(range(3))
            if active_idx > 3:
                shown.append(-1)
            start = max(3, active_idx - 1)
            end = min(total - 3, active_idx + 2)
            for i in range(start, end):
                if i not in shown:
                    shown.append(i)
            if active_idx < total - 4:
                shown.append(-2)
            for i in range(total - 3, total):
                if i not in shown:
                    shown.append(i)
        
        rows_html = []
        for i in shown:
            if i < 0:
                rows_html.append('<tr><td colspan="2" style="text-align:center;color:#999;padding:4px;">\u00b7\u00b7\u00b7</td></tr>')
            elif i == active_idx:
                rows_html.append('<tr style="background:#e8f0fe;"><td style="padding:4px 10px;">第' + str(i+1) + '轮</td><td style="padding:4px 10px;"><strong>\u2190 当前</strong></td></tr>')
            else:
                rows_html.append('<tr><td style="padding:4px 10px;">第' + str(i+1) + '轮</td><td style="padding:4px 10px;"><a href="tea://round/' + str(i) + '">查看</a></td></tr>')
        
        table_html = '<div style="background:#eff6ff; border:2px solid #93c5fd; border-radius:6px; padding:8px 12px; margin-bottom:14px;">\n' + status_line + '\n<p style="margin:4px 0 8px; color:#666; font-size:0.9em;">\U0001f4cb 历史轮次（共' + str(total) + '轮）</p>\n<table style="margin:0; font-size:0.9em;">\n<thead><tr><th style="width:70px;">轮次</th><th>操作</th></tr></thead>\n<tbody>\n' + '\n'.join(rows_html) + '\n</tbody>\n</table></div>'
        
        # -- 当前轮内容 --
        round_msgs = rounds[active_idx]
        round_md = _chat_to_markdown(round_msgs)
        if HAS_TKINTERWEB:
            round_body = _md_lib.markdown(round_md, extensions=["fenced_code", "tables", "codehilite", "md_in_html"])
            css = _MD_CSS_TEMPLATE.safe_substitute(font_size=font_size)
            full_html = "<html><head>" + css + "</head><body>" + table_html + round_body + "</body></html>"
        else:
            full_html = round_md
        return full_html

    # NOTE: 2026-05-15 gen by tea_agent, 渲染指定历史轮次（用户点击链接时调用）
    def _render_round_view(self, round_idx):
        """渲染指定轮次：后台线程生成 HTML，主线程加载"""
        rounds = self._chat_rounds
        if not rounds or round_idx < 0 or round_idx >= len(rounds):
            return
        font_size = int(_DEFAULT_FONT_SIZE * self._zoom_level / 100)
        
        def _prepare():
            return self._build_round_view_html(rounds, round_idx, font_size)
        
        def _on_done(html):
            if HAS_TKINTERWEB:
                print("[RENDER ROUND " + str(round_idx) + "] " + str(len(html)) + " chars")
                self._html_render(html)
                self._switch_display("chat_view")
                self.root.after(200, self.scroll_to_bottom)
            else:
                self.chat_view.config(state=tk.NORMAL)
                self.chat_view.delete("1.0", tk.END)
                self.chat_view.insert("1.0", html)
                self.chat_view.config(state=tk.DISABLED)
                self.chat_view.see(tk.END)
                self._switch_display("chat_view")
        
        import threading
        def _worker():
            try:
                result = _prepare()
                self.root.after(0, lambda r=result: _on_done(r))
            except Exception:
                self.root.after(0, lambda: _on_done("<p>渲染错误</p>"))
        threading.Thread(target=_worker, daemon=True).start()

    # NOTE: 2026-05-15 gen by tea_agent, 重构：渲染最新轮 + 历史轮次链接表
    def _render_and_show_chat(self):
        """会话完成后渲染：历史轮次链接表 + 最新轮内容"""
        msgs = self._filtered_messages()
        print("[DIAG] _render_and_show_chat: total filtered msgs=" + str(len(msgs)))
        
        # 分组为轮次
        rounds = self._group_into_rounds(msgs)
        self._chat_rounds = rounds
        self._current_round_view = None
        
        if not rounds:
            return
        
        active_idx = len(rounds) - 1  # 最新轮
        font_size = int(_DEFAULT_FONT_SIZE * self._zoom_level / 100)
        
        def _prepare():
            return self._build_round_view_html(rounds, active_idx, font_size)
        
        def _on_done(html):
            if HAS_TKINTERWEB:
                print("[RENDER] " + str(len(html)) + " chars")
                self._html_render(html)
                self._switch_display("chat_view")
                self.root.after(300, self.scroll_to_bottom)
            else:
                self.chat_view.config(state=tk.NORMAL)
                self.chat_view.delete("1.0", tk.END)
                self.chat_view.insert("1.0", html)
                self.chat_view.config(state=tk.DISABLED)
                self.chat_view.see(tk.END)
                self._switch_display("chat_view")
        
        import threading
        def _worker():
            try:
                result = _prepare()
                self.root.after(0, lambda r=result: _on_done(r))
            except Exception:
                self.root.after(0, lambda: _on_done("<p>渲染错误</p>"))
        threading.Thread(target=_worker, daemon=True).start()


    # @2026-04-29 gen by deepseek-v4-pro, 打开主题管理弹窗
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
            self._update_status("🛑 已打断")


# NOTE: 2026-04-30 19:36:28, self-evolved by tea_agent --- 补回缺失的 __main__ 入口，使 python -m tea_agent.main_db_gui 可正常启动 GUI
# NOTE: 2026-05-09 19:26:36, self-evolved by tea_agent --- 修复 main() no_gui 模式：用 CLI 回退替代 NotImplementedError 崩溃
def main(debug:bool=False, no_gui:bool=False):
    if no_gui:
        # 回退到 CLI 模式
        from tea_agent.tea_main_cli import main as cli_main
        cli_main()
        return
    
    root = tk.Tk()
    app = TkGUI(root, debug=debug)
    root.mainloop()


if __name__ == "__main__":
    main()
