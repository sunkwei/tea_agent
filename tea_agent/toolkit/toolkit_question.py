## llm generated tool func, created Mon Jun  1 09:28:09 2026
# version: 1.0.0

"""
问题工具 - 执行过程中向用户提问

支持 GUI 弹窗和 CLI 输入两种模式。
"""

import sys
import logging
import threading
from typing import List, Optional

logger = logging.getLogger("toolkit.question")

# 全局状态：存储用户回答
_answer_result = None
_answer_event = threading.Event()


def toolkit_question(
    title: str,
    question: str,
    options: List[str] = None,
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
    options: List[str] = None,
    default: str = "",
    timeout: int = 0
) -> str:
    """GUI 模式提问。"""
    global _answer_result, _answer_event
    
    import tkinter as tk
    from tkinter import ttk
    
    # 创建弹窗
    dialog = tk.Toplevel()
    dialog.title(f"❓ {title}")
    dialog.geometry("450x300")
    dialog.resizable(False, False)
    dialog.transient()
    dialog.grab_set()
    
    # 居中显示
    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() - 450) // 2
    y = (dialog.winfo_screenheight() - 300) // 2
    dialog.geometry(f"+{x}+{y}")
    
    # 标题
    title_label = ttk.Label(
        dialog,
        text=title,
        font=("", 14, "bold"),
        anchor="center"
    )
    title_label.pack(pady=(15, 5))
    
    # 问题描述
    question_label = ttk.Label(
        dialog,
        text=question,
        wraplength=400,
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
            rb = ttk.Radiobutton(
                options_frame,
                text=opt,
                variable=answer_var,
                value=opt
            )
            rb.pack(anchor="w", pady=3)
        
        # 自定义输入选项
        custom_frame = ttk.Frame(dialog)
        custom_frame.pack(fill=tk.X, padx=20, pady=(10, 0))
        
        ttk.Radiobutton(
            custom_frame,
            text="自定义:",
            variable=answer_var,
            value="__custom__"
        ).pack(side=tk.LEFT)
        
        custom_entry = ttk.Entry(custom_frame, width=30)
        custom_entry.pack(side=tk.LEFT, padx=(5, 0))
        
        def on_custom_focus(event):
            answer_var.set("__custom__")
        custom_entry.bind("<FocusIn>", on_custom_focus)
    else:
        # 自由输入模式
        input_frame = ttk.Frame(dialog)
        input_frame.pack(fill=tk.X, padx=20)
        
        entry = ttk.Entry(input_frame, width=50)
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
    
    submit_btn = ttk.Button(button_frame, text="确定", command=_submit)
    submit_btn.pack(side=tk.RIGHT, padx=5)
    
    cancel_btn = ttk.Button(button_frame, text="取消", command=_cancel)
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
                pass
        dialog.after(timeout * 1000, _timeout)
    
    # 等待用户回答
    dialog.wait_window()
    
    return _answer_result or default or ""


def _ask_cli(
    title: str,
    question: str,
    options: List[str] = None,
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
                    pass
                
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
