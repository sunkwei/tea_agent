# version: 1.3.0 — tolerant input contract (alias/wrapping coercion + self-correcting errors)

import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("toolkit")

# ── 进程自杀保护 ──
_process_tree_cache: set | None = None
_process_tree_cache_time: float = 0


def _get_process_tree() -> set:
    """获取当前进程及其所有祖先进程的 PID 集合（缓存 30 秒）。"""
    global _process_tree_cache, _process_tree_cache_time
    now = time.time()
    if _process_tree_cache is not None and (now - _process_tree_cache_time) < 30:
        return _process_tree_cache

    pids = {os.getpid()}
    if hasattr(os, "getppid"):
        pids.add(os.getppid())
    try:
        import psutil as _psutil
        current = _psutil.Process()
        parent = current.parent()
        while parent is not None and parent.pid > 1:
            pids.add(parent.pid)
            parent = parent.parent()
    except ImportError:
        pass
    except Exception:
        pass

    _process_tree_cache = pids
    _process_tree_cache_time = now
    return pids


# ── 提权拒绝（产品决策）──────────────────────────────────────
# Agent **不允许**获取管理员/root 权限执行任何命令：需要提权的操作必须由用户
# 自己手动执行。因此这里做硬拒绝，不再弹 GUI 密码框、不再调用 pkexec、
# 也不把 sudo 直接交给子进程（免密 NOPASSWD 环境下会真的提权成功）。
_ELEVATION_APPS = frozenset(
    {
        "sudo",
        "sudoedit",
        "sudo-rs",
        "su",
        "doas",
        "pkexec",
        "gksudo",
        "gksu",
        "beesu",
        "runas",
        "gsudo",
        "psexec",
        "psexec64",
    }
)

# shell 包装下的提权（powershell/cmd/bash -c "..."）：
# 只认 UAC 明确标记与"命令首 token 就是提权程序"，避免误伤普通文本参数
_ELEVATION_UAC_RE = re.compile(r"-verb\s+runas", re.IGNORECASE)

_SHELL_APPS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "cmd", "cmd.exe", "powershell", "pwsh"})

# 常见命令包装器：跳过它们才能看到真正的命令名（env sudo ... / timeout 5 sudo ...）
_CMD_WRAPPERS = frozenset({"env", "command", "nice", "nohup", "setsid", "time", "timeout", "xargs"})

# shell 命令分隔符（用于定位所有"命令位置"）
_SHELL_SEP_RE = re.compile(r"\|\||&&|[;|&\n]|\$\(|`")

# VAR=value 前缀
_ENV_ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\S*")


def _command_words(cmd: str) -> list[str]:
    """提取 shell 命令串中**每个命令位置**的可执行名（小写 basename）。

    按 ``;`` ``&&`` ``||`` ``|`` 换行等分隔符切段，跳过 ``VAR=value`` 前缀与
    ``env`` / ``timeout`` 之类的包装器，返回各段的命令名。
    这样 ``echo a; sudo rm`` 能识别出 ``sudo``，而 ``grep sudo /var/log`` 不会
    被误判（那里 sudo 只是参数）。
    """
    words: list[str] = []
    for segment in _SHELL_SEP_RE.split(cmd):
        tokens = segment.strip().split()
        for _ in range(4):  # 最多跳过 4 层前缀，避免病态输入
            if not tokens:
                break
            head = tokens[0]
            if _ENV_ASSIGN_RE.fullmatch(head):
                tokens = tokens[1:]
                continue
            if os.path.basename(head).lower() in _CMD_WRAPPERS:
                tokens = tokens[1:]
                # timeout 需要一个时长参数；nice 可能带 -n N
                if tokens and (tokens[0].startswith("-") or tokens[0].isdigit()):
                    tokens = tokens[1:]
                    if tokens and tokens[0].isdigit() and head.lower() == "nice":
                        tokens = tokens[1:]
                continue
            break
        if tokens:
            words.append(os.path.basename(tokens[0]).lower())
    return words


def _elevation_message(app: str = "", args: list | None = None, command_text: str = "") -> str:
    """生成拒绝提权的提示（含完整命令，便于用户手动复制执行）。"""
    cmd = command_text.strip() or " ".join([str(app)] + [str(a) for a in (args or [])]).strip()
    return (
        f"⛔ 已拒绝提权执行：Agent 不允许获取管理员/root 权限。\n"
        f"需要管理员权限的操作请由**用户手动执行**（复制以下命令到终端自行运行）：\n"
        f"    {cmd}"
    )


def elevation_refusal_for_command(command: str) -> dict | None:
    """对**命令字符串**做提权检测；供定时任务等非 argv 入口复用。

    Args:
        command: 完整命令行文本（如 ``sudo apt install nginx``）

    Returns:
        拒绝结果 dict 或 None（无需提权）
    """
    text = str(command or "").strip()
    if not text:
        return None
    if _ELEVATION_UAC_RE.search(text) or any(w in _ELEVATION_APPS for w in _command_words(text)):
        return {"ok": False, "error": _elevation_message(command_text=text), "returncode": 126}
    return None


def _elevation_refusal(app: str, args: list) -> dict | None:
    """检测提权请求；需要提权时返回拒绝结果，否则返回 None。

    识别范围：
    1. 可执行文件本身是提权工具（sudo / su / pkexec / doas / runas / gsudo ...），
       含 ``/usr/bin/sudo`` 这类绝对路径写法；
    2. PowerShell ``Start-Process ... -Verb RunAs``（Windows UAC 提权）；
    3. shell 包装（``bash -c "sudo ..."`` / ``cmd /c "runas ..."``）中，
       内层命令的**首个 token** 是提权工具。

    Args:
        app: 可执行程序
        args: 参数列表

    Returns:
        拒绝结果 dict（ok=False / error / returncode=126）或 None
    """
    name = os.path.basename(str(app or "").strip()).lower()
    arg_list = [str(a) for a in (args or [])]
    if name in _ELEVATION_APPS:
        return {"ok": False, "error": _elevation_message(app, arg_list), "returncode": 126}

    joined = " ".join(arg_list)
    if _ELEVATION_UAC_RE.search(joined):
        return {"ok": False, "error": _elevation_message(app, arg_list), "returncode": 126}

    # shell 包装：不只看首 token，而是检查**所有命令位置**，
    # 否则 `bash -c "echo x; sudo rm -rf /"` 这种拼接会被漏放。
    if name in _SHELL_APPS and arg_list:
        inner = ""
        for i, token in enumerate(arg_list):
            if token.lower() in ("-c", "/c", "-command", "-cmd", "/k"):
                inner = " ".join(arg_list[i + 1 :])
                break
        if inner and any(word in _ELEVATION_APPS for word in _command_words(inner)):
            return {"ok": False, "error": _elevation_message(app, arg_list), "returncode": 126}

    return None


def _is_self_destructive(app: str, args: list) -> tuple:
    """检查命令是否可能终止当前进程或其祖先进程。

    Returns (is_dangerous, reason) or (False, "").
    """
    known_pids = _get_process_tree()
    app_lower = (app or "").lower()

    # ── 处理 cmd /c 包装（Windows shell 内置命令包装）──
    effective_app = app_lower
    effective_args = list(args) if args else []
    if app_lower == "cmd" and args and args[0].lower() in ("/c", "/k"):
        inner = args[1] if len(args) > 1 else ""
        parts = inner.split()
        if parts:
            effective_app = parts[0].lower()
            effective_args = parts[1:]

    # ── 模式1: PowerShell Stop-Process ──
    if effective_app in ("powershell", "pwsh"):
        cmd_text = " ".join(effective_args).lower()
        for m in re.finditer(r"stop-process\s.*?-id\s+(\d+)", cmd_text, re.I):
            try:
                target_pid = int(m.group(1))
                if target_pid in known_pids:
                    return (True, f"⛔ 阻止自杀：Stop-Process 目标 PID {target_pid} 是当前进程或其祖先进程")
            except ValueError:
                pass

    # ── 模式2: Windows taskkill ──
    if effective_app == "taskkill":
        for i, arg in enumerate(effective_args):
            if arg.lower() in ("/pid", "-pid") and i + 1 < len(effective_args):
                try:
                    target_pid = int(effective_args[i + 1])
                    if target_pid in known_pids:
                        return (True, f"⛔ 阻止自杀：taskkill 目标 PID {target_pid} 是当前进程或其祖先进程")
                except ValueError:
                    pass

    # ── 模式3: Windows tskill ──
    if effective_app == "tskill":
        for arg in effective_args:
            try:
                target_pid = int(arg)
                if target_pid in known_pids:
                    return (True, f"⛔ 阻止自杀：tskill 目标 PID {target_pid} 是当前进程或其祖先进程")
            except ValueError:
                pass

    # ── 模式4: Windows wmic process delete ──
    if effective_app == "wmic" and "delete" in " ".join(effective_args).lower():
        cmd_text = " ".join(effective_args).lower()
        m = re.search(r"processid[= ]+(\d+)", cmd_text)
        if m:
            try:
                target_pid = int(m.group(1))
                if target_pid in known_pids:
                    return (True, f"⛔ 阻止自杀：wmic delete 目标 PID {target_pid} 是当前进程或其祖先进程")
            except ValueError:
                pass

    # ── 模式5: Linux kill ──
    if effective_app == "kill" and effective_args:
        for arg in effective_args:
            stripped = arg.lstrip("-")
            if stripped.isdigit():
                try:
                    target_pid = int(stripped)
                    if target_pid in known_pids:
                        return (True, f"⛔ 阻止自杀：kill 目标 PID {target_pid} 是当前进程或其祖先进程")
                except ValueError:
                    pass

    # ── 模式6: 系统级危险命令（关机/重启）──
    _DANGEROUS_SYSTEM = {"shutdown", "reboot", "halt", "poweroff", "init"}  # noqa: N806
    if effective_app in _DANGEROUS_SYSTEM:
        return (True, f"⛔ 阻止危险系统命令：{effective_app} {' '.join(effective_args[:5])}")

    if effective_app == "systemctl":
        dangerous_actions = {"poweroff", "reboot", "halt", "suspend", "shutdown"}
        if any(a.lower() in dangerous_actions for a in effective_args):
            return (True, f"⛔ 阻止危险系统命令：systemctl {' '.join(effective_args[:3])}")

    return (False, "")


class _ProcessMonitor:
    """进程资源监控器 — 后台线程周期检查进程 CPU/MEM/IO 使用情况。

    核心逻辑：
    - 若进程正在消耗资源（CPU > 0 / 内存增长 / IO 活跃），更新 last_active_time
    - should_kill() 返回 True 当进程已空闲超过 base_timeout 秒
    - 硬上限 base_timeout × 4，超过后强制终止
    """

    def __init__(self, pid: int, base_timeout: int, check_interval: float = 3.0):
        self.pid = pid
        self.base_timeout = base_timeout
        self.max_idle = base_timeout
        self.check_interval = check_interval
        self.last_active_time = time.time()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_rss = 0
        self._last_io_read = 0
        self._last_io_write = 0

    def start(self):
        """启动监控后台线程（daemon，随主线程退出自动结束）"""
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"Mon-{self.pid}")
        self._thread.start()

    def stop(self):
        """通知监控线程停止"""
        self._stop.set()

    def should_kill(self) -> bool:
        """是否该杀掉进程：空闲时间超过 base_timeout -> True"""
        elapsed = time.time() - self.last_active_time
        return elapsed > self.max_idle

    def _run(self):
        try:
            import psutil as _psutil
        except ImportError:
            logger.warning("psutil 不可用，回退到基础超时机制")
            return

        try:
            proc = _psutil.Process(self.pid)
            while not self._stop.is_set():
                if self._stop.wait(self.check_interval):
                    break
                try:
                    if not proc.is_running():
                        break

                    is_active = False

                    # CPU 检查
                    try:
                        cpu_pct = proc.cpu_percent(interval=0.2)
                        if cpu_pct > 0:
                            is_active = True
                    except (OSError, _psutil.NoSuchProcess, _psutil.AccessDenied):
                        # 进程已退出（WSL2 下 psutil 可能抛原始 FileNotFoundError），监控结束
                        break

                    # 内存检查（RSS 增长 > 1%）
                    try:
                        mem = proc.memory_info()
                        if self._last_rss > 0 and mem.rss > self._last_rss * 1.01:
                            is_active = True
                        self._last_rss = mem.rss
                    except (OSError, _psutil.NoSuchProcess, _psutil.AccessDenied):
                        break

                    # IO 检查（读写字节增长）
                    try:
                        io = proc.io_counters()
                        if io.read_bytes > self._last_io_read or io.write_bytes > self._last_io_write:
                            is_active = True
                        self._last_io_read = io.read_bytes
                        self._last_io_write = io.write_bytes
                    except (OSError, _psutil.AccessDenied, AttributeError):
                        break

                    # 子进程检查
                    if not is_active:
                        try:
                            for child in proc.children(recursive=True):
                                try:
                                    if child.cpu_percent(interval=0.1) > 0:
                                        is_active = True
                                        break
                                except (OSError, _psutil.NoSuchProcess, _psutil.AccessDenied):
                                    break

                        except (OSError, _psutil.NoSuchProcess, _psutil.AccessDenied):
                            break

                    if is_active:
                        self.last_active_time = time.time()

                except (OSError, _psutil.NoSuchProcess, _psutil.AccessDenied):
                    break
        except (OSError, _psutil.NoSuchProcess):
            logger.debug("monitor: 进程 %s 已退出，监控线程结束", self.pid)


# ── 环境变量清洗（DeepSeek Harness 防御模式） ──
_ENV_SECRET_PATTERNS = re.compile(
    r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.IGNORECASE
)


def _build_scrubbed_env() -> dict:
    """构建清洗后的子进程环境：丢弃含敏感关键词的变量，防止 harness 凭据泄入命令输出/日志。

    参考 DeepSeek Harness 防御模式：
    "Spawned commands get a scrubbed env (drop *KEY*/*SECRET*/*TOKEN*/*PASSWORD*) so
    harness credentials cannot leak into output, env, or spill files."

    若不清洗，模型执行 `echo $DEEPSEEK_API_KEY` 之类的命令时，
    harness 凭据会直接泄进对话历史/日志。只删除敏感变量，其余（PATH/HOME 等）保留。
    """
    scrubbed = {}
    for key, value in os.environ.items():
        if _ENV_SECRET_PATTERNS.search(key):
            continue
        scrubbed[key] = value
    return scrubbed


def _wait_with_monitor(process, monitor, timeout: int, kill_wait: float = 5.0) -> str:
    """轮询等待子进程结束，处理空闲/硬上限超时，必要时强制终止（single/batch 共用）。

    返回终止原因字符串：
        ""          — 进程正常结束
        "monitor"   — 空闲超时（超过 timeout 秒无资源消耗）被监控器终止
        "hardlimit" — 超过硬上限（timeout × 4 秒）被强制终止

    该函数统一了 _run_single_with_monitor 与 _run_batch_with_monitor 中重复的
    hard_deadline 等待/终止逻辑，避免两处行为漂移。始终在 finally 中停止监控器。
    """
    hard_deadline = time.time() + timeout * 4
    kill_reason = ""
    try:
        while time.time() < hard_deadline:
            if process.poll() is not None:
                return ""  # 进程正常结束
            if monitor.should_kill():
                kill_reason = "monitor"
                break
            time.sleep(1)

        if process.poll() is None:  # 仍在运行 → 需要强制终止
            if not kill_reason:
                kill_reason = "hardlimit"
            try:
                if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()  # Windows: 无 killpg，直接 kill 子进程
                process.wait(timeout=kill_wait)
            except (ProcessLookupError, OSError):
                try:
                    process.kill()
                    process.wait(timeout=kill_wait)
                except Exception:
                    logger.exception('op_failed')
            except Exception:
                logger.exception('op_failed')
    finally:
        monitor.stop()
    return kill_reason


def _run_single_with_monitor(app: str, args: list, timeout: int) -> dict:
    """使用 _ProcessMonitor 智能超时执行单条命令。

    流程：
    1. 启动子进程 + 监控线程
    2. 后台线程读取 stdout/stderr（避免管道阻塞）
    3. 主循环以 1s 间隔轮询：进程结束 → 返回；监控器 idle 超时 → 杀进程
    4. 硬保护：最多等待 timeout × 4 秒
    """
    try:
        process = subprocess.Popen(
            [app] + list(args),
            # stdin=DEVNULL：子进程不得继承父进程 stdin。否则交互式提示
            # （ssh/git/sudo 的密码对话）会阻塞至超时（硬上限 timeout×4）
            # 才被监控器视为「空闲」杀掉，表现为长时间无输出假死。
            # 工具本无 stdin 入参，故 DEVNULL 使这类命令立即 EOF 快速失败。
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            start_new_session=True,
            env=_build_scrubbed_env(),
        )
    except (FileNotFoundError, PermissionError, OSError) as e:
        # 命令不存在/无权限等启动失败：返回结构化 dict，与正常路径及 tool 契约一致
        return {
            "ok": False,
            "returncode": 127,
            "timed_out": False,
            "timeout_kind": "",
            "signal": None,
            "stdout": "",
            "stderr": f"命令启动失败: {app}\n{str(e)}",
        }

    monitor = _ProcessMonitor(process.pid, base_timeout=timeout)
    monitor.start()

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _reader(stream, lines):
        try:
            for line in iter(stream.readline, ""):
                lines.append(line)
        except ValueError:
            logger.exception('op_failed')

        finally:
            try:
                stream.close()
            except OSError:
                logger.exception('op_failed')


    t_out = threading.Thread(target=_reader, args=(process.stdout, stdout_lines), daemon=True)
    t_err = threading.Thread(target=_reader, args=(process.stderr, stderr_lines), daemon=True)
    t_out.start()
    t_err.start()

    kill_reason = _wait_with_monitor(process, monitor, timeout, kill_wait=5)
    killed_by_monitor = kill_reason == "monitor"
    killed_by_hardlimit = kill_reason == "hardlimit"

    t_out.join(timeout=3)
    t_err.join(timeout=3)

    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)
    retcode = process.returncode if process.returncode is not None else -1

    # ── 正交结果独立报告（DeepSeek Harness 防御模式） ──
    # 一个进程可能同时"超时"且"exit 0"（捕获了信号）。每个独立事实单独字段，
    # 绝不嵌套报告，避免调用方把被截断的运行误读为干净成功。
    timed_out = killed_by_monitor or killed_by_hardlimit
    timeout_kind = "monitor" if killed_by_monitor else ("hardlimit" if killed_by_hardlimit else "")
    exit_signal = None
    if retcode < 0:
        exit_signal = -retcode  # 被信号终止时 retcode 为负数

    if killed_by_monitor:
        cmd_preview = f"{app} {' '.join(args[:5])}"
        if len(args) > 5:
            cmd_preview += f" ... (+{len(args)-5} args)"
        hint = (f"⏰ 进程空闲超时被终止 (>{timeout}s 无资源消耗): {cmd_preview}")
        stderr = (stderr + "\n" + hint) if stderr else hint
    elif killed_by_hardlimit:
        cmd_preview = f"{app} {' '.join(args[:5])}"
        if len(args) > 5:
            cmd_preview += f" ... (+{len(args)-5} args)"
        hint = f"⏰ 命令超过硬上限被强制终止 (>{timeout*4}s): {cmd_preview}"
        stderr = (stderr + "\n" + hint) if stderr else hint

    # ok 语义：超时被终止 = 失败（即使进程自身 exit 0）
    return {
        "ok": (retcode == 0) and not timed_out,
        "returncode": retcode,
        "timed_out": timed_out,
        "timeout_kind": timeout_kind,
        "signal": exit_signal,
        "stdout": stdout,
        "stderr": stderr,
    }


def _run_batch_with_monitor(idx, cmd, timeout):
    """Batch 子任务执行器，集成 _ProcessMonitor 智能超时。"""
    # 与 toolkit_exec 入口共用同一套归一化：主入口已归一化，这里兜底
    # （_run_batch_with_monitor 也可能被内部其它路径直接调用）。
    _norm = _normalize_commands([cmd])
    cmd = _norm[0] if _norm else {"app": "", "args": []}
    a = cmd.get("app", "")
    ar = cmd.get("args", [])
    result = {"index": idx, "returncode": -1, "stdout": "", "stderr": "", "error": True}
    if not a:
        # 逐项失败隔离；错误信息带正确用法，便于模型下轮自纠
        result["stderr"] = (
            "app 为空或类型不可用（需要可执行程序路径字符串）。"
            f"正确用法：commands=[{{'app': 'ls', 'args': ['-la']}}]。收到：{_describe(cmd)}"
        )
        return result

    try:
        process = subprocess.Popen(
            [a] + list(ar),
            # 同 _run_single_with_monitor：禁止继承 stdin，避免交互提示假死
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            start_new_session=True,
            env=_build_scrubbed_env(),
        )
        monitor = _ProcessMonitor(process.pid, base_timeout=timeout)
        monitor.start()

        out_lines, err_lines = [], []

        def _reader(stream, lines):
            try:
                for line in iter(stream.readline, ""):
                    lines.append(line)
            except ValueError:
                logger.exception('op_failed')

            finally:
                try:
                    stream.close()
                except OSError:
                    logger.exception('op_failed')


        t_out = threading.Thread(target=_reader, args=(process.stdout, out_lines), daemon=True)
        t_err = threading.Thread(target=_reader, args=(process.stderr, err_lines), daemon=True)
        t_out.start()
        t_err.start()

        kill_reason = _wait_with_monitor(process, monitor, timeout, kill_wait=3)
        # 注意：_wait_with_monitor 内部 finally 已调用 monitor.stop()
        t_out.join(timeout=2)
        t_err.join(timeout=2)

        stdout = "".join(out_lines)
        stderr = "".join(err_lines)
        retcode = process.returncode if process.returncode is not None else -1

        # 正交结果独立报告：超时与 exit code 分开字段
        timed_out = kill_reason != ""
        timeout_kind = kill_reason  # "monitor"/"hardlimit"/""（正常）
        exit_signal = -retcode if retcode < 0 else None

        if kill_reason:
            cmd_preview = f"{a} {' '.join(ar[:3])}"
            if len(ar) > 3:
                cmd_preview += f" ... (+{len(ar)-3} args)"
            if kill_reason == "monitor":
                hint = f"⏰ 空闲超时({timeout}s): {cmd_preview}"
            else:
                hint = f"⏰ 硬上限超时(>{timeout*4}s): {cmd_preview}"
            stderr = (stderr + "\n" if stderr else "") + hint

        result.update({
            "returncode": retcode,
            "timed_out": timed_out,
            "timeout_kind": timeout_kind,
            "signal": exit_signal,
            "stdout": stdout,
            "stderr": stderr,
            "error": (retcode != 0) or timed_out,
        })
    except Exception as e:
        result["stderr"] = str(e)

    return result


# ── 入参归一化：等价形态收敛 + 可自纠错误 ──────────────────────────────
# 背景（设备端 tea_agent_api 日志高频出现）：
#   "toolkit_exec 参数错误：app 需要可执行程序路径字符串，收到 bool"
#   "toolkit_exec() got an unexpected keyword argument 'command'/'arguments'"
# 两者都是**参数形态**问题（模型/客户端换了个等价写法），而原实现要么直接失败，
# 要么报错信息对模型毫无指导性（"收到 bool"不知道该改成什么）。这里统一收敛：
#   - 等价参数名：command / cmd / executable / program … → app；argv / options → args
#   - 整行命令：app='ls -la'、commands=['ls -la'] 自动拆分
#   - 包装层：{'arguments': {'app': ..., 'args': [...]}} 展开
#   - 形态：["bash"] → "bash"；args="x" → ["x"]；数字/布尔元素转 str
# 不能安全解释的一律返回「原因 + 正确用法 + 实际收到的参数形态」，绝不在退化参数上
# 继续执行（宁可报错，不可执行错命令）。
_APP_ALIASES = (
    "command", "cmd", "executable", "program", "program_path", "binary",
    "exe", "process", "script", "shell_command", "shell", "run",
)
_ARGS_ALIASES = ("argv", "arguments_list", "options", "flags", "params_list")
_COMMANDS_ALIASES = ("cmds", "command_list", "cmd_list", "batch", "tasks", "jobs")
_BLOB_KEYS = ("arguments", "params", "parameters", "kwargs", "input", "payload", "body")
_ACTION_ALIASES = ("mode", "kind", "type")
_TIMEOUT_ALIASES = ("timeout_seconds", "time_limit", "deadline")
_ACTIONS = ("single", "batch")

# 这些字符串不是可执行程序名（模型把布尔/空值写成了字符串）
_FAKE_APP_TOKENS = frozenset(
    {"true", "false", "null", "none", "nil", "undefined", "nan", "bool", "string"}
)

_EXEC_USAGE = (
    "toolkit_exec(app='ls', args=['-la']) 或 "
    "toolkit_exec(action='batch', commands=[{'app': 'ls', 'args': ['-la']}])"
)


def _describe(value, limit: int = 160) -> str:
    """把任意值渲染成简短的「类型 + 值」描述，用于参数错误消息。"""
    if isinstance(value, str):
        shown = value if len(value) <= limit else value[:limit] + "…"
        return f"str={shown!r}"
    if value is None or isinstance(value, (bool, int, float)):
        return f"{type(value).__name__}={value!r}"
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}[{len(value)}]={repr(value)[:limit]}"
    if isinstance(value, dict):
        return f"dict(keys={sorted(map(str, value))[:8]})"
    return type(value).__name__


def _exec_arg_error(reason: str, received: dict | None = None, example: str = "") -> dict:
    """构造 toolkit_exec 参数错误结果：原因 + 正确用法 + 实际收到的参数形态。

    「收到 bool」这类信息不足以让模型自纠，必须同时给出正确用法与收到的原始形态。
    """
    parts = [f"toolkit_exec 参数错误：{reason}"]
    if example:
        parts.append(f"正确用法：{example}")
    shown = ", ".join(f"{k}={_describe(v)}" for k, v in (received or {}).items())
    if shown:
        parts.append(f"实际收到：{shown}")
    logger.warning("toolkit_exec 参数错误：%s | 收到: %s", reason, shown)
    return {"ok": False, "error": "\n".join(parts), "returncode": -1}


def _strip_wrapping_quotes(text: str) -> str:
    """去掉整体包裹的引号（内部含同类引号时不动）。"""
    s = text.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0] and s[0] not in s[1:-1]:
        return s[1:-1]
    return s


def _split_command_line(text: str) -> tuple[str, list[str]]:
    """把一整行命令文本拆成 (可执行程序, 参数列表)。"""
    line = (text or "").strip()
    if not line:
        return "", []
    try:
        # Windows 下不做 POSIX 反转义，否则 C:\Program Files\x.exe 这类路径的
        # 反斜杠会被吃掉；非 Windows 保持 POSIX 语义以正确处理引号。
        parts = shlex.split(line, posix=(os.name != "nt"))
    except ValueError:
        parts = line.split()
    if not parts:
        return "", []
    return _strip_wrapping_quotes(parts[0]), [_strip_wrapping_quotes(p) for p in parts[1:]]


def _coerce_app(value) -> tuple[str, list[str]]:
    """把 app 收敛为 (可执行程序, 从 app 里拆出的额外参数)；无法收敛返回 ("", [])。

    覆盖形态：字符串、整行命令 bash -c "ls"、["bash"]、["ls", "-la"]、带包裹引号的值，
    以及 true/false/null 这类「伪程序名」字符串（直接判为不可用）。
    """
    if isinstance(value, str):
        text = _strip_wrapping_quotes(value)
        if not text or text.lower() in _FAKE_APP_TOKENS:
            return "", []
        if re.search(r"\s", text):
            return _split_command_line(text)
        return text, []
    if isinstance(value, (list, tuple)):
        items = [x for x in value if isinstance(x, str) and x.strip()]
        if not items:
            return "", []
        prog, extra = _coerce_app(items[0])
        if not prog:
            return "", []
        return prog, extra + [_strip_wrapping_quotes(x) for x in items[1:]]
    return "", []


def _coerce_args(value) -> list | None:
    """把 args 收敛为字符串列表；无法安全解释时返回 None（由调用方报错）。"""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text[0] in "[{":
            parsed = _parse_json_blob(text)
            if parsed is not None:
                return _coerce_args(parsed)
        return [value]
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if item is None:
                out.append("")
            elif isinstance(item, str):
                out.append(item)
            elif isinstance(item, bool):
                out.append(str(item).lower())
            elif isinstance(item, (int, float)):
                out.append(str(item))
            else:
                out.append(json.dumps(item, ensure_ascii=False, default=str))
        return out
    return None


def _parse_json_blob(text: str):
    """尽力把字符串解析成 JSON 对象/数组（arguments/params 包装字符串）。"""
    s = (text or "").strip()
    if len(s) < 2 or s[0] not in "[{":
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        logger.debug("toolkit_exec: 参数字符串非严格 JSON（%s），尝试容错修复", e)
    try:
        from tea_agent.session.json_sanitizer import normalize_tool_args

        fixed = normalize_tool_args("toolkit_exec", s)
        return json.loads(fixed) if fixed else None
    except Exception as e:  # noqa: BLE001 — 容错解析失败不阻断主流程
        logger.debug("toolkit_exec: 参数字符串容错解析失败: %s", e)
        return None


def _equivalent(a, b) -> bool:
    """判断两个候选参数值是否等价（用于识别同一参数的重复/冲突写法）。"""
    if a is None or b is None:
        return False
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return list(a) == list(b)
    return a == b


def _take_alias(extra: dict, names: tuple, current, label: str) -> tuple:
    """从 extra 中取出第一个命中的等价参数；返回 (value, conflict_reason)。

    命中即移除该键（避免误报「未知参数」）；当前值已绑定且新值不等价时返回冲突原因，
    由调用方报错 —— 同一参数给出两个不同值属语义歧义，猜错就会执行错命令。
    """
    for key in names:
        if key not in extra:
            continue
        value = extra.pop(key)
        if current is None or current == "" or current == []:
            return value, ""
        if value not in (None, "", []) and not _equivalent(current, value):
            return current, f"{label} 同时给出 {_describe(current)} 与 {_describe(value)}（键 {key}），语义冲突"
        return current, ""
    return current, ""


def _coerce_timeout(value) -> int:
    """收敛 timeout：布尔/不可解析一律回落默认 30；<=0 视作未指定；上限一天。"""
    default = 30
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, str):
        try:
            value = int(float(value.strip()))
        except ValueError:
            return default
    elif isinstance(value, float):
        value = int(value)
    elif not isinstance(value, int):
        return default
    if value <= 0:
        return default
    return min(value, 86400)


def _normalize_commands(commands):
    """把命令清单收敛为 [{'app': str, 'args': [str]}…]（逐项失败隔离，空 app 留给执行层报错）。"""
    if commands is None:
        return None
    if isinstance(commands, (dict, str)):
        commands = [commands]
    if not isinstance(commands, (list, tuple)):
        return None
    out = []
    for item in commands:
        if isinstance(item, str):
            prog, rest = _split_command_line(item)
            out.append({"app": prog, "args": rest})
            continue
        if not isinstance(item, dict):
            out.append({"app": "", "args": []})
            continue
        e_app = item.get("app")
        if not e_app:
            for key in _APP_ALIASES:
                if item.get(key):
                    e_app = item[key]
                    break
        e_args = item.get("args")
        if e_args is None:
            for key in ("arguments",) + _ARGS_ALIASES:
                if item.get(key) is not None:
                    e_args = item[key]
                    break
        prog, extra = _coerce_app(e_app)
        coerced = _coerce_args(e_args)
        if coerced is None:
            coerced = (
                [json.dumps(e_args, ensure_ascii=False, default=str)]
                if isinstance(e_args, dict) else [str(e_args)]
            )
        out.append({"app": prog, "args": extra + coerced})
    return out


def _infer_app_from_args(args: list) -> tuple[str, list[str]]:
    """app 缺失/不可用时，从 args 首项推断可执行程序（仅接受「明显像程序」的首项）。

    只认可：存在的文件路径，或 PATH 中能解析到的命令名。像 /c、-la 这类选项一律
    不推断 —— 宁可报错，也不执行一条错误的命令。
    """
    if not isinstance(args, list) or not args or not isinstance(args[0], str):
        return "", []
    cand = _strip_wrapping_quotes(args[0])
    if not cand or re.search(r"\s", cand) or cand.startswith("-"):
        return "", []
    if cand.startswith("/") and not os.path.exists(cand):
        return "", []
    if "/" in cand or "\\" in cand:
        return (cand, args[1:]) if os.path.isfile(cand) else ("", [])
    if shutil.which(cand):
        return cand, args[1:]
    return "", []


def _normalize_exec_inputs(app, args, action, commands, timeout, extra):
    """把 toolkit_exec 的等价入参形态收敛为内部形态。

    Returns:
        (app, args, action, commands, timeout, error)：error 非 None 时调用方必须
        直接返回，不得继续执行（避免在退化参数上跑出错误命令）。
    """
    extra = dict(extra or {})
    app_received, args_received = app, args

    # ── 0. 参数包装层：arguments/params 里塞着真实参数（客户端多包了一层）──
    for key in list(extra.keys()):
        if key not in _BLOB_KEYS:
            continue
        blob = extra.pop(key)
        if isinstance(blob, str):
            blob = _parse_json_blob(blob)
        if isinstance(blob, dict):
            for k, v in blob.items():
                extra.setdefault(k, v)
        elif isinstance(blob, (list, tuple)) and not args and not commands:
            args = list(blob)
        else:
            # 无法解释的包装层不得静默丢弃（静默丢弃会让模型以为参数已生效）
            return "", [], action, None, timeout, _exec_arg_error(
                f"{key} 无法解析为参数对象（需要 dict 或 JSON 对象字符串）",
                received={key: blob}, example=_EXEC_USAGE)

    # ── 1. 等价参数名收敛（规范名优先；同义名重复且不等价 → 报冲突）──
    app, conflict = _take_alias(extra, ("app",) + _APP_ALIASES, app, "app")
    if conflict:
        return "", [], action, None, timeout, _exec_arg_error(
            conflict, received={"app": app_received, "args": args_received}, example=_EXEC_USAGE)
    args, conflict = _take_alias(extra, ("args",) + _ARGS_ALIASES, args, "args")
    if conflict:
        return "", [], action, None, timeout, _exec_arg_error(
            conflict, received={"args": args_received, "app": app_received}, example=_EXEC_USAGE)
    commands, conflict = _take_alias(extra, ("commands",) + _COMMANDS_ALIASES, commands, "commands")
    if conflict:
        return "", [], action, None, timeout, _exec_arg_error(
            conflict, received={"commands": commands, "app": app_received}, example=_EXEC_USAGE)
    for key in ("action",) + _ACTION_ALIASES:
        if key in extra:
            _v = extra.pop(key)
            _v_low = _v.strip().lower() if isinstance(_v, str) else ""
            # 显式 batch 不被别名改回；别名只负责把默认 single 纠正为 batch
            if _v_low in _ACTIONS and (action != "batch" or _v_low == "batch"):
                action = _v_low
            break
    for key in ("timeout",) + _TIMEOUT_ALIASES:
        if key in extra:
            _v = extra.pop(key)
            if not timeout:
                timeout = _v
            break

    # 剩余未知键：明确指出（静默忽略会让模型误以为参数已生效）
    if extra:
        return "", [], action, None, timeout, _exec_arg_error(
            f"不支持参数 {sorted(map(str, extra))}；该工具只接受 app / args / action / commands / timeout",
            received=dict(extra), example=_EXEC_USAGE)

    # ── 2. args 里塞着完整参数对象 → 展开为真实参数后重新收敛 ──
    if isinstance(args, dict):
        if any(k in args for k in ("app", "action", "commands", "args", "command")):
            for k, v in args.items():
                extra.setdefault(k, v)
            return _normalize_exec_inputs(app, None, action, commands, timeout, extra)
        return "", [], action, None, timeout, _exec_arg_error(
            f"args 需要字符串数组，收到 dict(keys={sorted(map(str, args))[:8]})",
            received={"args": args, "app": app_received}, example=_EXEC_USAGE)

    # ── 3. app / args 形态归一 ──
    app, app_inline_args = _coerce_app(app)
    coerced_args = _coerce_args(args)
    if coerced_args is None:
        return "", [], action, None, timeout, _exec_arg_error(
            f"args 需要字符串数组，收到 {type(args).__name__}",
            received={"args": args, "app": app_received}, example=_EXEC_USAGE)
    args = app_inline_args + coerced_args if app_inline_args else coerced_args

    # ── 4. action / timeout / commands 归一 ──
    action = action if action in _ACTIONS else "single"
    timeout = _coerce_timeout(timeout)
    commands = _normalize_commands(commands)

    # ── 5. 出口校验：绝不带着不可用的 app 继续执行 ──
    if not commands and not app:
        inferred, inferred_args = _infer_app_from_args(args)
        if inferred:
            logger.info("toolkit_exec: app 缺失/不可用，从 args 推断可执行程序 %r", inferred)
            app, args = inferred, inferred_args
    if action == "batch" and not commands:
        if app:
            # 声明了 batch 却只给了单条 app：按 single 执行（原先静默返回 results=[]）
            logger.info("toolkit_exec: action=batch 但无 commands 清单 → 按 single 执行")
            action = "single"
        else:
            return "", [], action, None, timeout, _exec_arg_error(
                "action=batch 需要 commands 清单（形如 [{'app': 'ls', 'args': ['-la']}]）",
                received={"action": action, "app": app_received, "commands": commands},
                example=_EXEC_USAGE)
    if action == "single" and not app:
        return "", [], action, commands, timeout, _exec_arg_error(
            "app 缺失或类型不可用（需要可执行程序路径字符串；布尔值/空值均不可用）",
            received={"app": app_received, "args": args_received}, example=_EXEC_USAGE)
    return app, args, action, commands, timeout, None


def toolkit_exec(app: str = "", args: list = None, action: str = "single",
                 commands: list = None, timeout: int = 30, **extra):
    """
    执行系统命令（单条或批量并行）。

    入参容错（宽松入口，严格出口）:
        - 等价参数名: command / cmd / executable / program → app；argv / options → args
        - 整行命令: app='ls -la' 或 commands=['ls -la'] 会被自动拆分
        - 包装层: 形如 arguments={'app': ..., 'args': [...]} 会被展开
        - app/args 形态: ["bash"] → "bash"；args='x' → ['x']；数字/布尔元素转字符串
        - 无法安全收敛时返回「原因 + 正确用法 + 实际收到」，并拒绝执行（不猜）

    action='single' (默认): 执行单条命令
        toolkit_exec(action='single', app='python', args=['--version'])
        或简写: toolkit_exec(app='python', args=['--version'])

    action='batch': 并行批量执行多条命令 (线程池)
        toolkit_exec(action='batch', commands=[
            {"app": "echo", "args": ["hello"]},
            {"app": "ls", "args": ["-la"]},
        ], timeout=30)

    智能超时（v2.0）:
        - 启动后台 _ProcessMonitor 线程，周期检查进程 CPU/MEM/IO
        - 若进程持续消耗资源（CPU>0/内存增长/IO活跃），最多延长至 timeout×4 秒
        - 若进程空闲超过 timeout 秒，立即终止，避免资源耗尽
        - 有效解决长时间编译、下载等正常操作被误杀的问题

    返回:
        single: {"ok": bool, "returncode": int, "stdout": str, "stderr": str}
        batch: {"ok": bool, "results": list, "success_rate": str, "total": int}
    """
    logger.info(f"toolkit_exec called: app={app!r}, args={repr(args)[:80]}, action={action!r}, commands={repr(commands)[:80]}, timeout={timeout!r}, extra={sorted(map(str, extra))}")

    # ── 入参归一化（等价参数名/整行命令/包装层/形态收敛，详见 _normalize_exec_inputs）──
    # 归一化失败必须直接返回：绝不带着退化的 app/args 继续执行，否则会跑出错误命令。
    app, args, action, commands, timeout, _norm_err = _normalize_exec_inputs(
        app, args, action, commands, timeout, extra)
    if _norm_err is not None:
        return _norm_err
    if args is None:
        args = []

    # ── 提权拒绝：Agent 不得获取管理员/root 权限 ──
    # 需要管理员权限的操作必须由**用户自己手动执行**；这里硬拒绝，
    # 不再尝试弹密码框 / 调 pkexec / 直接跑 sudo（NOPASSWD 下会真的提权成功）。
    if action == "single" and app:
        refusal = _elevation_refusal(app, args or [])
        if refusal:
            logger.warning(f"toolkit_exec refused elevation: {app} {' '.join(map(str, args or []))[:120]}")
            return refusal
    elif action == "batch" and commands:
        for cmd in commands:
            a = cmd.get("app", "")
            ar = cmd.get("args", [])
            if a:
                refusal = _elevation_refusal(a, ar or [])
                if refusal:
                    logger.warning(f"toolkit_exec batch refused elevation: {a}")
                    return {
                        "ok": False,
                        "error": refusal["error"],
                        "results": [{"error": True, "stderr": refusal["error"]}],
                    }

    # ── 自杀检测：阻止可能终止自身进程的危险命令 ──
    if action == "single" and app:
        dangerous, reason = _is_self_destructive(app, args or [])
        if dangerous:
            logger.warning(f"toolkit_exec blocked: {reason}")
            return {"ok": False, "error": reason, "returncode": -1}
    elif action == "batch" and commands:
        for cmd in commands:
            a = cmd.get("app", "")
            ar = cmd.get("args", [])
            if a:
                dangerous, reason = _is_self_destructive(a, ar)
                if dangerous:
                    logger.warning(f"toolkit_exec batch blocked: {reason}")
                    return {"ok": False, "error": reason, "results": [{"error": True, "stderr": reason}]}

    _PY_CMD_THRESHOLD = 500  # -c 脚本超过此字符数则写入临时文件  # noqa: N806
    _PY_APP_RE = re.compile(r"^python(3(\.\d+)?)?(\.exe)?$", re.IGNORECASE)  # noqa: N806
    _py_app = bool(app) and bool(_PY_APP_RE.match(os.path.basename(str(app))))
    if action == "single" and _py_app and args:
        # 检测 python -c "很长的代码" 模式
        for i, arg in enumerate(args):
            if arg == "-c" and i + 1 < len(args):
                script = args[i + 1]
                if isinstance(script, str) and len(script) > _PY_CMD_THRESHOLD:
                    # 写入临时 .py 文件
                    tmpfd, tmppath = tempfile.mkstemp(suffix=".py", prefix="tea_exec_")
                    try:
                        with os.fdopen(tmpfd, "w", encoding="utf-8") as f:
                            f.write(script)
                        # 重建 args：用临时文件路径替换 -c + script
                        new_args = list(args[:i]) + [tmppath] + list(args[i+2:])
                        logger.info(f"toolkit_exec: -c脚本{len(script)}字符→临时文件 {tmppath}")
                        # 递归调用但跳过重检测（临时文件路径不含-c，不会再触发）
                        result = toolkit_exec(app=app, args=new_args, action="single",
                                             commands=None, timeout=timeout)
                    finally:
                        # 清理临时文件
                        try:
                            os.unlink(tmppath)
                        except OSError:
                            logger.exception('op_failed')

                    return result
                break  # 只处理第一个 -c

    if action == "batch":
        if not commands:
            return {"ok": True, "results": [], "total": 0}
        # 检测 python -c "很长的代码" 模式
        for i, arg in enumerate(args):
            if arg == "-c" and i + 1 < len(args):
                script = args[i + 1]
                if isinstance(script, str) and len(script) > _PY_CMD_THRESHOLD:
                    # 写入临时 .py 文件
                    tmpfd, tmppath = tempfile.mkstemp(suffix=".py", prefix="tea_exec_")
                    try:
                        with os.fdopen(tmpfd, "w", encoding="utf-8") as f:
                            f.write(script)
                        # 重建 args：用临时文件路径替换 -c + script
                        new_args = list(args[:i]) + [tmppath] + list(args[i+2:])
                        logger.info(f"toolkit_exec: -c脚本{len(script)}字符→临时文件 {tmppath}")
                        # 递归调用但跳过重检测（临时文件路径不含-c，不会再触发）
                        result = toolkit_exec(app=app, args=new_args, action="single",
                                             commands=None, timeout=timeout)
                    finally:
                        # 清理临时文件
                        try:
                            os.unlink(tmppath)
                        except OSError:
                            logger.exception('op_failed')

                    return result
                break  # 只处理第一个 -c

    if action == "batch":
        if not commands:
            return {"ok": True, "results": [], "total": 0}

        results = [None] * len(commands)
        lock = threading.Lock()

        def _run_wrapper(idx, cmd):
            result = _run_batch_with_monitor(idx, cmd, timeout)
            with lock:
                results[idx] = result

        workers = min(len(commands), 8)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_wrapper, i, cmd) for i, cmd in enumerate(commands)]
            for f in as_completed(futures):
                f.result()

        success = sum(1 for r in results if r and not r.get("error"))
        # ok 反映是否有任一命令成功（避免全失败仍报 ok:True 误导 LLM）；成功比例见 success_rate
        return {
            "ok": success > 0,
            "results": results,
            "success_rate": f"{success}/{len(commands)}",
            "total": len(commands),
        }

    else:  # action == "single"
        if args is None:
            args = []

        # 使用智能超时：监控进程资源使用，动态延长超时
        effective_timeout = timeout if timeout else 120
        result = _run_single_with_monitor(app, args, effective_timeout)
        return result

def meta_toolkit_exec() -> dict:
    """Meta toolkit exec."""
    return {
        "type": "function",
        "function": {
            "description": "执行系统命令。action='single' 执行单条（app + args）；action='batch' 并行批量执行多条（commands）。等价写法（command/cmd/executable、整行命令 app='ls -la'、arguments 包装）会被自动归一化。注意：不接受提权命令（sudo/su/pkexec/runas 等一律拒绝）——需要管理员权限的操作必须提示用户手动执行。智能超时(v2.0)：后台 _ProcessMonitor 监控 CPU/MEM/IO，进程活跃时最多延长 4x 超时，空闲时按时终止。",
            "name": "toolkit_exec",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["single", "batch"],
                        "description": "single/batch。默认 single",
                    },
                    "app": {
                        "type": "string",
                        "description": "可执行程序名或路径（不含参数）。整行命令请写进 args，例如 app='ls', args=['-la']",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "命令行参数列表，每个参数一项（如 ['-la', '/tmp']）",
                    },
                    "commands": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "app": {"type": "string", "description": "程序路径"},
                                "args": {"type": "array", "items": {"type": "string"}, "description": "参数"},
                            },
                            "required": ["app", "args"],
                        },
                        "description": "命令列表",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "基础超时秒数, 默认 30。单条命令有效超时 = timeout 或 120(未指定时); 进程活跃消耗资源时最多延长 4x，空闲超过 base_timeout 则终止。",
                    },
                },
                "required": [],
            },        },
    }
