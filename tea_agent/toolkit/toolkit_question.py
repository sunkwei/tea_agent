## llm generated tool func, created Mon Jun  1 09:28:09 2026
# version: 1.0.0

"""
问题工具 - 执行过程中向用户提问

支持四种模式（按优先级）：
1. Web 模式：通过 tlk.toolkit._question_web_handler 回调（由 server.py 设置）
2. 静默模式（Server/Headless）：无交互时自动返回 default 值
3. GUI 模式：tkinter 弹窗
4. CLI 模式：终端输入

关键设计：通过 tlk.toolkit 共享单例传递 handler，规避 exec() 变量隔离问题。
"""

import logging
import threading
import os

logger = logging.getLogger("toolkit.question")

# 全局状态：存储用户回答
_answer_result = None
_answer_event = threading.Event()


def _get_web_handler():
    """从 tlk.toolkit 单例获取 Web handler（绕过 exec 隔离）。
    
    当 server.py 的 chat_stream_sse 设置 handler 后，
    exec 加载的函数也能通过 tlk.toolkit 访问到同一 handler。
    """
    try:
        from tea_agent import tlk
        if tlk.toolkit is not None:
            return getattr(tlk.toolkit, '_question_web_handler', None)
    except Exception:
        pass
    return None


def _is_headless_context() -> bool:
    """检测是否在无用户交互环境下运行（Server 后台 / TEA_HEADLESS）。
    
    此时不应弹出 GUI/CLI 提问，应直接返回 default。
    """
    # 显式环境变量
    if os.environ.get('TEA_HEADLESS', '').lower() in ('1', 'true', 'yes'):
        return True
    
    # Server 模式：tlk.toolkit 被标记为 server 实例
    try:
        from tea_agent import tlk
        if tlk.toolkit is not None and getattr(tlk.toolkit, '_is_server', False):
            return True
    except Exception:
        pass
    
    return False


def toolkit_question(
    title: str,
    question: str,
    options: list[str] = None,
    default: str = "",
    timeout: int = 0
) -> str:
    """
    执行过程中向用户提问。

    Args:
        title: 问题标题
        question: 问题描述
        options: 选项列表，为空时允许自由输入
        default: 默认选项或默认输入
        timeout: 超时秒数，0=不超时

    Returns:
        用户选择的答案字符串
    """
    # ── 优先级 1: Web 模式（通过 tlk.toolkit 共享单例） ──
    handler = _get_web_handler()
    if handler is not None:
        try:
            return handler(title, question, options, default, timeout)
        except Exception as e:
            logger.warning(f"Web question handler failed, fallback: {e}")

    # ── 优先级 2: 静默模式（Server 后台 / 无头环境） ──
    if _is_headless_context():
        logger.info(
            f"Headless/server mode: auto-return default={default!r} "
            f"for question: {title}"
        )
        return default or ""

    global _answer_result, _answer_event

    # 重置状态
    _answer_result = None
    _answer_event.clear()

    # 检测是否在 GUI 环境中
    try:
        import tkinter as tk
        # 尝试创建隐藏窗口测试 GUI 可用性
        test_root = tk.Tk()
        test_root.withdraw()
        test_root.destroy()
        gui_available = True
    except:
        gui_available = False

    # 根据环境选择模式
    if gui_available and _is_gui_running():
        return _ask_gui(title, question, options, default, timeout)
    else:
        return _ask_cli(title, question, options, default, timeout)


def _is_gui_running() -> bool:
    """检测是否有 GUI 主窗口正在运行。"""
    try:
        import tkinter as tk
        # 检查是否有 Tk 根窗口
        return len(tk._default_root.children) > 0 if tk._default_root else False
    except:
        return False


def _ask_gui(
    title: str,
    question: str,
    options: list[str] = None,
    default: str = "",
    timeout: int = 0
) -> str:
    """GUI 模式提问。"""
    global _answer_result, _answer_event

    import tkinter as tk
    from tkinter import ttk

    # 创建弹窗 - 根据选项数量动态调整窗口高度
    base_height = 300
    option_height = 32 if options else 0
    window_height = base_height + (len(options) * option_height if options else 60)
    window_height = min(window_height, 600)  # 限制最大高度
    window_width = 500

    dialog = tk.Toplevel()
    dialog.title(f"❓ {title}")
    dialog.minsize(400, 280)  # 保证按钮可见的最小尺寸
    dialog.geometry(f"{window_width}x{window_height}")
    dialog.resizable(True, True)  # 允许调整大小
    dialog.transient()
    dialog.grab_set()

    # 居中显示
    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() - window_width) // 2
    y = (dialog.winfo_screenheight() - window_height) // 2
    dialog.geometry(f"+{x}+{y}")

    # 字体配置 - Windows 使用微软雅黑，其他平台使用系统默认
    import platform
    if platform.system() == "Windows":
        font_family = "Microsoft YaHei UI"  # 微软雅黑 UI 版，更清晰
    else:
        font_family = "System"  # Linux/macOS 使用系统字体

    # 标题
    title_label = ttk.Label(
        dialog,
        text=title,
        font=(font_family, 16, "bold"),
        anchor="center"
    )
    title_label.pack(pady=(15, 5))

    # 问题描述
    question_label = ttk.Label(
        dialog,
        text=question,
        font=(font_family, 12),
        wraplength=450,
        anchor="center",
        justify="center"
    )
    question_label.pack(pady=(0, 15))

    # 答案变量
    answer_var = tk.StringVar(value=default)

    if options and len(options) > 0:
        # 选项模式
        options_frame = ttk.Frame(dialog)
        options_frame.pack(fill=tk.BOTH, expand=True, padx=20)

        for opt in options:
            rb = tk.Radiobutton(
                options_frame,
                text=opt,
                variable=answer_var,
                value=opt,
                font=(font_family, 12)
            )
            rb.pack(anchor="w", pady=4)

        # 自定义输入选项
        custom_frame = tk.Frame(dialog)
        custom_frame.pack(fill=tk.X, padx=20, pady=(10, 0))

        tk.Radiobutton(
            custom_frame,
            text="自定义:",
            variable=answer_var,
            value="__custom__",
            font=(font_family, 12)
        ).pack(side=tk.LEFT)

        custom_entry = tk.Entry(custom_frame, width=30, font=(font_family, 12))
        custom_entry.pack(side=tk.LEFT, padx=(5, 0))

        def on_custom_focus(event):
            answer_var.set("__custom__")
        custom_entry.bind("<FocusIn>", on_custom_focus)
    else:
        # 自由输入模式
        input_frame = tk.Frame(dialog)
        input_frame.pack(fill=tk.X, padx=20)

        entry = tk.Entry(input_frame, width=50, font=(font_family, 12))
        entry.pack(fill=tk.X)
        entry.insert(0, default)
        entry.select_range(0, tk.END)
        entry.focus_set()

        # 回车提交
        def on_enter(event):
            answer_var.set(entry.get())
            _submit()
        entry.bind("<Return>", on_enter)

    # 按钮区域
    button_frame = ttk.Frame(dialog)
    button_frame.pack(fill=tk.X, padx=20, pady=15)

    def _submit():
        global _answer_result
        answer = answer_var.get()

        # 处理自定义输入
        if answer == "__custom__":
            try:
                answer = custom_entry.get()
            except:
                answer = ""

        if not answer:
            answer = default

        _answer_result = answer
        _answer_event.set()
        dialog.destroy()

    def _cancel():
        global _answer_result
        _answer_result = default or ""
        _answer_event.set()
        dialog.destroy()

    # 使用 tk.Button 以支持 font 参数
    submit_btn = tk.Button(button_frame, text="确定", command=_submit, font=(font_family, 12))
    submit_btn.pack(side=tk.RIGHT, padx=5)

    cancel_btn = tk.Button(button_frame, text="取消", command=_cancel, font=(font_family, 12))
    cancel_btn.pack(side=tk.RIGHT, padx=5)

    # 超时处理
    if timeout > 0:
        def _timeout():
            global _answer_result
            _answer_result = default or ""
            _answer_event.set()
            try:
                dialog.destroy()
            except:
                logger.exception("operation failed")

        dialog.after(timeout * 1000, _timeout)

    # 等待用户回答
    dialog.wait_window()

    return _answer_result or default or ""


def _ask_cli(
    title: str,
    question: str,
    options: list[str] = None,
    default: str = "",
    timeout: int = 0
) -> str:
    """CLI 模式提问。"""
    print(f"\n{'='*50}")
    print(f"❓ {title}")
    print(f"{'='*50}")
    print(f"\n{question}\n")

    if options and len(options) > 0:
        # 选项模式
        for i, opt in enumerate(options, 1):
            marker = "→" if opt == default else " "
            print(f"  {marker} {i}. {opt}")

        if default:
            print(f"\n  默认: {default}")

        print()

        while True:
            try:
                user_input = input("请选择 (输入序号或选项名称): ").strip()

                if not user_input and default:
                    return default

                # 尝试解析为序号
                try:
                    idx = int(user_input) - 1
                    if 0 <= idx < len(options):
                        return options[idx]
                except ValueError:
                    logger.exception("operation failed")


                # 尝试匹配选项名称
                for opt in options:
                    if user_input.lower() == opt.lower():
                        return opt

                # 模糊匹配
                matches = [opt for opt in options if user_input.lower() in opt.lower()]
                if len(matches) == 1:
                    return matches[0]

                print("❌ 无效选择，请重试")

            except (EOFError, KeyboardInterrupt):
                return default or ""
    else:
        # 自由输入模式
        if default:
            print(f"  默认: {default}")

        print()

        try:
            user_input = input("请输入: ").strip()
            return user_input if user_input else default
        except (EOFError, KeyboardInterrupt):
            return default or ""


# 工具元信息
TOOL_META = {
    "type": "function",
    "function": {
        "name": "toolkit_question",
        "description": "执行过程中向用户提问。支持选项列表和自定义输入。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "问题标题"},
                "question": {"type": "string", "description": "问题描述"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "选项列表"},
                "default": {"type": "string", "description": "默认选项"},
                "timeout": {"type": "integer", "description": "超时秒数"}
            },
            "required": ["title", "question"]
        }
    }
}


def meta_toolkit_question() -> dict:
    return {"type": "function", "function": {"name": "toolkit_question", "description": "执行过程中向用户提问。支持选项列表和自定义输入。\n\n使用场景：\n- 收集用户偏好或需求\n- 澄清模糊的指令\n- 获取实现方案的决策\n- 提供方向选择的选项\n\n返回：用户选择的答案字符串", "parameters": {"type": "object", "properties": {"title": {"type": "string", "description": "问题标题，如 '选择编程语言'"}, "question": {"type": "string", "description": "问题描述，如 '您希望使用哪种编程语言？'"}, "options": {"type": "array", "items": {"type": "string"}, "description": "选项列表，如 ['Python', 'JavaScript', 'Go']。为空时允许自由输入"}, "default": {"type": "string", "description": "默认选项或默认输入"}, "timeout": {"type": "integer", "description": "超时秒数，0=不超时，默认 0"}}, "required": ["title", "question"]}}}
