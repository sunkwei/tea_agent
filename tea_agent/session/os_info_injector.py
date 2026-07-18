"""
操作系统信息注入模块

从 onlinesession.py 提取的独立功能：
- inject_os_info: 根据当前 OS 注入差异化的工具使用提示
"""

import json
import logging
import os
import platform
import socket
import sys

logger = logging.getLogger("session.os_info_injector")

# 持久化 OS 签名文件，跨会话跟踪执行环境变化
_OS_STATE_FILE = os.path.join(os.path.expanduser("~"), ".tea_agent", "os_state.json")


def _get_os_signature() -> str:
    """生成当前 OS 的简短签名，用于跨会话对比。

    格式: "system-release-machine"，如 "Windows-10-AMD64" / "Linux-6.8.0-x86_64"
    """
    try:
        import platform as _plat
        return f"{_plat.system()}-{_plat.release()}-{_plat.machine()}"
    except Exception:
        return "unknown"


def _load_persisted_os_sig(topic_id: str) -> str:
    """从持久化文件加载指定 topic 的上次 OS 签名。"""
    if not topic_id:
        return ""
    try:
        if os.path.exists(_OS_STATE_FILE):
            with open(_OS_STATE_FILE, encoding='utf-8') as f:
                data = json.load(f)
            return data.get("topics", {}).get(topic_id, "")
    except Exception:
        logger.exception('op_failed')

    return ""


def _save_os_sig(topic_id: str, sig: str) -> None:
    """持久化指定 topic 的当前 OS 签名。"""
    if not topic_id:
        return
    try:
        os.makedirs(os.path.dirname(_OS_STATE_FILE), exist_ok=True)
        data = {}
        if os.path.exists(_OS_STATE_FILE):
            with open(_OS_STATE_FILE, encoding='utf-8') as f:
                data = json.load(f)
        data.setdefault("topics", {})[topic_id] = sig
        with open(_OS_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"保存 OS 签名失败: {e}")


def _detect_interface_type() -> str:
    """检测当前接口类型。

    Returns:
        'web' | 'gui' | 'cli' — 当前服务接口类型
    """
    # 环境变量覆盖（各入口点预置）
    env_type = os.environ.get('TEA_AGENT_INTERFACE', '') or ''
    if env_type.lower() in ('web', 'gui', 'cli', 'tui', 'mcp'):
        return env_type.lower()

    # 从已加载模块检测
    if 'starlette' in sys.modules or 'uvicorn' in sys.modules:
        return 'web'
    if 'tkinter' in sys.modules:
        return 'gui'

    # 从 argv 推断
    script = os.path.basename(sys.argv[0]) if sys.argv else ''
    if any(x in script.lower() for x in ('server', 'web')):
        return 'web'
    if any(x in script.lower() for x in ('gui', 'tk')):
        return 'gui'

    return 'cli'


def _get_interface_hints(interface_type: str) -> str:
    """根据接口类型返回交互格式提示。"""
    hints = {
        "web": (
            "【交互格式】响应中可用 Markdown + HTML 链接。\n"
            "【话题链接】使用 #topic:UUID 格式引用其他会话（自动转为可点击链接）。\n"
            "【下载链接】生成的 .zip/.exe/.pdf 等文件链接会自动添加下载图标。\n"
            "【URL链接】裸 URL 自动转为可点击的超链接。"
        ),
        "gui": (
            "【交互格式】响应中支持 Markdown 渲染。\n"
            "【文件操作】桌面 GUI 支持文件拖拽和剪贴板图片粘贴。\n"
            "【通知】长时间任务完成后可通过 toolkit_notify 发送桌面通知。"
        ),
        "cli": (
            "【交互格式】纯文本响应，无 HTML 渲染。\n"
            "【链接】使用裸 URL 文本，用户可手动复制。\n"
            "【输出】避免依赖 HTML/富文本渲染。"
        ),
        "tui": (
            "【交互格式】终端富文本，支持基本 Markdown。\n"
            "【链接】使用裸 URL 文本。"
        ),
        "mcp": (
            "【交互格式】纯文本/JSON 格式。\n"
            "【链接】使用裸 URL 文本。"
        ),
    }
    return hints.get(interface_type, "")


def inject_os_info(messages: list[dict], toolkit_root_dir: str = "",
                   supports_reasoning: bool = True,
                   interface_type: str | None = None) -> list[dict]:
    """注入操作系统环境信息轮次（放在用户消息之前）。

    根据实际运行的 OS 注入差异化的工具使用提示，
    指导 LLM 使用正确的命令、路径分隔符和工具策略。

    Args:
        messages: 当前消息列表（会被原地修改）
        toolkit_root_dir: toolkit 目录路径
        supports_reasoning: 模型是否支持 reasoning

    Returns:
        修改后的消息列表
    """
    os_name = platform.system()
    os_release = platform.release()
    os_version = platform.version()
    os_machine = platform.machine()
    py_ver = platform.python_version()
    hostname = socket.gethostname()
    path_sep = os.sep
    env_sep = os.pathsep

    is_windows = os_name == "Windows"
    is_linux = os_name == "Linux"
    is_macos = os_name == "Darwin"

    if interface_type is None:
        interface_type = _detect_interface_type()

    # ── OS 概要 ──
    lines = [
        f"操作系统: {os_name} {os_release} ({os_version})",
        f"架构: {os_machine}",
        f"主机名: {hostname}",
        f"Python: {py_ver}",
    ]

    # ── 接口类型 ──
    iface_labels = {"web": "Web 浏览器", "gui": "桌面 GUI (Tkinter)", "cli": "命令行终端",
                    "tui": "终端 TUI", "mcp": "MCP 协议"}
    iface_label = iface_labels.get(interface_type, interface_type)
    lines.append(f"服务接口: {iface_label}" if iface_label else "")

    # ── 路径约定 ──
    lines.append("")
    lines.append("═══ 路径与分隔符 ═══")
    lines.append(f"路径分隔符: '{path_sep}'（Windows 使用 \\\\，Linux/macOS 使用 /）")
    lines.append(f"环境变量分隔符: '{env_sep}'（Windows 使用 ;，Linux/macOS 使用 :）")
    lines.append(f"当前工作目录: {os.getcwd()}")

    # ── OS 特有工具提示 ──
    lines.append("")
    lines.append("═══ 操作提示（请严格遵循当前 OS 的指令语法）═══")

    if is_windows:
        lines.extend([
            "🪟 Windows 环境 — 请特别注意：",
            "",
            "【路径】使用反斜杠 \\（如 C:\\Users\\...），但在 Python 字符串中请用正斜杠 / 或双反斜杠 \\\\",
            "【环境变量】用 %VAR% 引用（如 %USERPROFILE%），PowerShell 用 $env:VAR",
            "",
            "【文件搜索】使用 findstr（代替 grep）：",
            "  toolkit_exec(app='findstr', args=['/i', '关键词', 'C:\\path\\file.txt'])",
            "  或 dir /s /b | findstr /i 关键词",
            "",
            "【目录列表】使用 dir（代替 ls）：",
            "  toolkit_exec(app='cmd', args=['/c', 'dir /b /s C:\\path'])",
            "",
            "【文件读取】使用 type（代替 cat）：",
            "  toolkit_exec(app='cmd', args=['/c', 'type', 'C:\\path\\file.txt'])",
            "  或在 Python 中直接用 open() 读取（推荐）",
            "",
            "【路径环境】可用环境变量：%USERPROFILE%, %APPDATA%, %LOCALAPPDATA%, %TEMP%, %PATH%",
            "【Shell】默认 cmd.exe；如需 PowerShell 需显式指定 app='powershell'",
        ])
    elif is_linux:
        lines.extend([
            "🐧 Linux 环境 — 请特别注意：",
            "",
            "【路径】使用正斜杠 /（如 /home/user/...）",
            "【环境变量】用 $VAR 引用（如 $HOME, $PATH）",
            "",
            "【文件搜索】使用 grep：",
            "  toolkit_exec(app='grep', args=['-rn', '关键词', '/path'])",
            "",
            "【目录列表】使用 ls：",
            "  toolkit_exec(app='ls', args=['-la', '/path'])",
            "",
            "【文件读取】使用 cat：",
            "  toolkit_exec(app='cat', args=['/path/file.txt'])",
            "  或在 Python 中直接用 open() 读取（推荐）",
            "",
            "【路径环境】可用环境变量：$HOME, $PWD, $SHELL, $PATH",
            "【权限】部分操作需 sudo，将自动弹出 GUI 密码框",
        ])
    elif is_macos:
        lines.extend([
            "🍎 macOS 环境 — 请特别注意：",
            "",
            "【路径】使用正斜杠 /（如 /Users/username/...）",
            "【环境变量】用 $VAR 引用（如 $HOME, $PATH）",
            "",
            "【文件搜索】使用 grep：",
            "  toolkit_exec(app='grep', args=['-rn', '关键词', '/path'])",
            "",
            "【目录列表】使用 ls：",
            "  toolkit_exec(app='ls', args=['-la', '/path'])",
            "",
            "【文件读取】使用 cat：",
            "  toolkit_exec(app='cat', args=['/path/file.txt'])",
            "",
            "【路径环境】可用环境变量：$HOME, $PWD, $SHELL, $PATH",
        ])

    # ── 通用工具提示 ──
    lines.append("")
    lines.append("═══ 通用规则 ═══")
    lines.append("• 文件读写优先使用 toolkit_file（跨平台兼容），避免执行 shell 命令")
    lines.append("• 执行 shell 命令使用 toolkit_exec，注意不同 OS 下命令名和参数不同")
    lines.append("• 路径字符串在 Python 中统一用正斜杠 /，Python 会自动适配底层 OS")
    if toolkit_root_dir:
        lines.append(f"• 当前 tool 目录: {toolkit_root_dir}")
    lines.append("• 如需获取更详细的 OS 信息，可调用 toolkit_os_info() 工具")

    info_text = "[系统环境信息]\n" + "\n".join(lines)

    # ── 接口类型说明（追加到 info_text 中） ──
    if iface_label:
        info_text += f"\n当前服务接口为「{iface_label}」。\n"
        info_text += _get_interface_hints(interface_type)

    # 注入为用户轮次 + 助手确认
    messages.append({"role": "user", "content": info_text})
    ack = {
        "role": "assistant",
        "content": f"✅ 已识别当前环境为 {os_name} {os_machine}，"
                    f"接口类型: {iface_label}。将遵循对应的路径约定、命令语法和交互格式。"
    }
    if supports_reasoning:
        ack["reasoning_content"] = ""
    messages.append(ack)

    return messages
