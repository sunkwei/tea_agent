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
import tempfile

logger = logging.getLogger("session.os_info_injector")

# ── OS 签名持久化文件 ─────────────────────────────────────────────────
# 这是一条纯旁路缓存：只用于「同一 topic 在同一主机上别重复注入环境信息」。
# 因此读写任何失败都必须静默降级（fail-open），绝不冒泡成 ERROR ——
# 见 AGENTS.md「辅助能力不绑架主流程」。
# 路径可用 TEA_OS_STATE_FILE 覆盖（测试 / 排障 / HOME 不可写的容器环境）。
_MAX_TRACKED_TOPICS = 500  # 防止用户级状态文件随 topic 数无界增长

# 同一进程内只对「文件已损坏」提示一次，避免每次会话都刷日志
_bad_state_warned = False


def _default_state_file() -> str:
    """默认状态文件路径；HOME 不可解析时退回临时目录（绝不抛异常）。"""
    try:
        home = os.path.expanduser("~")
        if not home or home == "~":
            raise RuntimeError(f"HOME 不可解析: {home!r}")
        return os.path.join(home, ".tea_agent", "os_state.json")
    except Exception as e:  # pragma: no cover - 仅在 HOME 异常的环境触发
        logger.debug("无法解析用户主目录，OS 签名改存临时目录: %s", e)
        return os.path.join(tempfile.gettempdir(), "tea_agent", "os_state.json")


_OS_STATE_FILE = _default_state_file()


def _state_file_path() -> str:
    """当前生效的状态文件路径（环境变量优先）。"""
    override = os.environ.get("TEA_OS_STATE_FILE", "").strip()
    return override or _OS_STATE_FILE


def _warn_bad_state(path: str, reason: str) -> None:
    """状态文件不可用时提示一次；warning 级别、无 traceback。"""
    global _bad_state_warned
    if _bad_state_warned:
        logger.debug("OS 签名文件仍不可用（%s）: %s", reason, path)
        return
    _bad_state_warned = True
    logger.warning(
        "OS 签名缓存文件不可用（%s），已忽略其内容，下次写入时自动重建: %s "
        "（该缓存只用于避免重复注入环境信息，不影响功能）",
        reason, path,
    )


def _read_state_file(path: str) -> dict:
    """健壮读取状态文件，任何异常都降级为 {}。

    覆盖现实中所有「坏文件」形态：
      - 0 字节（上次写入被中断 / 设备断电）
      - UTF-8 BOM（被其他工具或 Windows 编辑器改写过 → 用 utf-8-sig 吞掉）
      - 非 JSON 文本、JSON 顶层不是对象
      - 权限不足、路径被目录占据、非法字节
    """
    try:
        # utf-8-sig: 有 BOM 就读掉、无 BOM 也兼容；errors=replace 防坏字节抛错
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
    except FileNotFoundError:
        return {}
    except IsADirectoryError as e:
        _warn_bad_state(path, f"路径是目录: {e}")
        return {}
    except OSError as e:
        logger.debug("OS 签名文件不可读，已忽略: %s (%s)", path, e)
        return {}

    if not raw.strip():
        _warn_bad_state(path, "文件为空，疑似上次写入被中断")
        return {}

    try:
        data = json.loads(raw)
    except ValueError as e:  # JSONDecodeError 继承自 ValueError
        _warn_bad_state(path, f"JSON 解析失败(偏移 {getattr(e, 'pos', '?')}): {raw[:60]!r}")
        return {}

    if not isinstance(data, dict):
        _warn_bad_state(path, f"顶层应为对象，实为 {type(data).__name__}")
        return {}

    return data


def _write_state_file(data: dict, path: str) -> bool:
    """原子写入状态文件（临时文件 + os.replace）。

    旧实现直接 ``open(path, 'w')`` 截断再写：进程被 kill 或磁盘满时就会留下
    空文件/半截 JSON —— 正是本次线上报错的来源。改为先写同目录临时文件、
    fsync 后原子改名，读者永远只能看到完整文件；同时这次改名会直接覆盖掉
    已有的坏文件，实现自愈。
    """
    global _bad_state_warned

    directory = os.path.dirname(path) or "."
    tmp_path = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".os_state.", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)  # POSIX rename / Windows 覆盖改名，两者皆原子
        tmp_path = None
        _bad_state_warned = False  # 已成功重建，恢复提示配额
        return True
    except (OSError, TypeError, ValueError) as e:
        logger.debug("保存 OS 签名失败，已忽略: %s (%s)", path, e)
        return False
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _get_os_signature() -> str:
    """生成当前 OS 的简短签名，用于跨会话对比。

    格式: "system-release-machine"，如 "Windows-10-AMD64" / "Linux-6.8.0-x86_64"
    """
    try:
        return f"{platform.system()}-{platform.release()}-{platform.machine()}"
    except Exception:
        return "unknown"


def _load_persisted_os_sig(topic_id: str) -> str:
    """从持久化文件加载指定 topic 的上次 OS 签名。

    文件缺失/损坏一律返回 ""（视为「未注入过」）—— 调用方会重新生成文本并
    回写，回写采用原子改名，顺手把坏文件修好。此处绝不抛异常、不打 ERROR。
    """
    if not topic_id:
        return ""
    try:
        topics = _read_state_file(_state_file_path()).get("topics")
        if not isinstance(topics, dict):
            return ""
        value = topics.get(topic_id)
        return value if isinstance(value, str) else ""
    except Exception as e:  # pragma: no cover - 双保险，旁路不得影响主流程
        logger.debug("读取 OS 签名失败，按未注入处理: %s", e)
        return ""


def _save_os_sig(topic_id: str, sig: str) -> None:
    """持久化指定 topic 的当前 OS 签名（坏文件自动重建）。

    旧实现先 ``json.load`` 再写：一旦文件损坏，load 抛错被外层吞掉，整个保存
    被跳过 → 坏文件永不自愈，每次启动重复报错。现在读取端已降级为 {}，
    这里必定能把干净的 JSON 原子写回去。
    """
    if not topic_id:
        return
    path = _state_file_path()
    data = _read_state_file(path)

    topics = data.get("topics")
    if not isinstance(topics, dict):
        topics = {}
    topics.pop(topic_id, None)      # 重插到末尾 → dict 顺序即最近使用时间
    topics[topic_id] = sig
    while len(topics) > _MAX_TRACKED_TOPICS:  # 裁剪最久未更新的 topic
        topics.pop(next(iter(topics)))
    data["topics"] = topics

    _write_state_file(data, path)


def _detect_interface_type() -> str:
    """检测当前接口类型。

    交互面已收敛为 Web（GUI / CLI / TUI 入口废弃），故检测不到特征时回退
    ``'web'`` 而非旧的 ``'cli'`` —— 回退 cli 会让提示词按「纯文本、无 HTML
    渲染」组装，与实际 Web 渲染能力相反。

    Returns:
        'web' | 'mcp' — 当前服务接口类型
    """
    # 环境变量覆盖（各入口点预置）
    env_type = os.environ.get('TEA_AGENT_INTERFACE', '') or ''
    if env_type.lower() in ('web', 'mcp'):
        return env_type.lower()

    # 从已加载模块检测
    if 'starlette' in sys.modules or 'uvicorn' in sys.modules:
        return 'web'

    # 从 argv 推断
    script = os.path.basename(sys.argv[0]) if sys.argv else ''
    if any(x in script.lower() for x in ('server', 'web')):
        return 'web'

    return 'web'


def _get_interface_hints(interface_type: str) -> str:
    """根据接口类型返回交互格式提示。

    未知值（含已废弃的 ``gui`` / ``cli`` / ``tui`` 与任意拼写错误）一律回退
    **web** 提示：旧实现 ``hints.get(interface_type, "")`` 返回空串，会让模型
    失去全部格式约定；而 Web 是当前唯一的内置交互面。
    """
    hints = {
        "web": (
            "【交互格式】响应中可用 Markdown + HTML 链接。\n"
            "【话题链接】使用 #topic:UUID 格式引用其他会话（自动转为可点击链接）。\n"
            "【下载链接】生成的 .zip/.exe/.pdf 等文件链接会自动添加下载图标。\n"
            "【URL链接】裸 URL 自动转为可点击的超链接。"
        ),
        "mcp": (
            "【交互格式】纯文本/JSON 格式。\n"
            "【链接】使用裸 URL 文本。"
        ),
    }
    return hints.get(interface_type) or hints["web"]


def generate_os_info_text(toolkit_root_dir: str = "",
                         interface_type: str | None = None) -> str:
    """生成操作系统环境信息文本（纯文本，不修改消息列表）。

    为属性注入模式设计，返回 OS 信息文本，
    由 _build_l0_enriched_system() 合并到 system prompt 尾部。

    Args:
        toolkit_root_dir: toolkit 目录路径
        interface_type: 接口类型，None 则自动检测

    Returns:
        OS 环境信息文本字符串
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

    # 已废弃的 gui / cli / tui 与任意未知值一律按 web 呈现
    # （与 _get_interface_hints 同一口径，避免「标签说 CLI、提示却是 Web」的自相矛盾）
    iface_labels = {"web": "Web 浏览器", "mcp": "MCP 协议"}
    iface_label = iface_labels.get(interface_type) or iface_labels["web"]

    # ── OS 概要 ──
    lines = [
        f"操作系统: {os_name} {os_release} ({os_version})",
        f"架构: {os_machine}",
        f"主机名: {hostname}",
        f"Python: {py_ver}",
    ]

    # ── 接口类型 ──
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
            "【权限】需要 sudo 的操作不会自动执行：请提示用户手动运行（Agent 无提权能力）",
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
    lines.append("• 如需获取更详细的 OS 信息，可用 toolkit_exec 执行 python platform 查询")

    info_text = "[系统环境信息]\n" + "\n".join(lines)

    # ── 接口类型说明（追加到 info_text 中） ──
    if iface_label:
        info_text += f"\n当前服务接口为「{iface_label}」。\n"
        info_text += _get_interface_hints(interface_type)

    return info_text


def inject_os_info(messages: list[dict], toolkit_root_dir: str = "",
                   supports_reasoning: bool = True,
                   interface_type: str | None = None) -> list[dict]:
    """注入操作系统环境信息轮次（放在用户消息之前）。

    ⚠️ 已弃用：请使用 generate_os_info_text() 纯函数 + 属性注入方式。
    保留此函数仅为向后兼容。

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
    os_machine = platform.machine()

    if interface_type is None:
        interface_type = _detect_interface_type()

    # 已废弃的 gui / cli / tui 与任意未知值一律按 web 呈现
    # （与 _get_interface_hints 同一口径，避免「标签说 CLI、提示却是 Web」的自相矛盾）
    iface_labels = {"web": "Web 浏览器", "mcp": "MCP 协议"}
    iface_label = iface_labels.get(interface_type) or iface_labels["web"]

    # 使用纯函数生成文本（避免重复）
    info_text = generate_os_info_text(
        toolkit_root_dir=toolkit_root_dir,
        interface_type=interface_type,
    )

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
