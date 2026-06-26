# llm generated tool func, created Wed Apr 15 13:13:26 2026
# version: 1.1.0

import logging
import threading
import time
import os
import signal
import subprocess
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("toolkit")


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
            import psutil
        except ImportError:
            logger.warning("psutil 不可用，回退到基础超时机制")
            return

        try:
            proc = psutil.Process(self.pid)
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
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                    # 内存检查（RSS 增长 > 1%）
                    try:
                        mem = proc.memory_info()
                        if self._last_rss > 0 and mem.rss > self._last_rss * 1.01:
                            is_active = True
                        self._last_rss = mem.rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                    # IO 检查（读写字节增长）
                    try:
                        io = proc.io_counters()
                        if (io.read_bytes > self._last_io_read or
                                io.write_bytes > self._last_io_write):
                            is_active = True
                        self._last_io_read = io.read_bytes
                        self._last_io_write = io.write_bytes
                    except (psutil.AccessDenied, AttributeError):
                        pass

                    # 子进程检查
                    if not is_active:
                        try:
                            for child in proc.children(recursive=True):
                                try:
                                    if child.cpu_percent(interval=0.1) > 0:
                                        is_active = True
                                        break
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    pass
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                    if is_active:
                        self.last_active_time = time.time()

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break
        except psutil.NoSuchProcess:
            pass

def _run_single_with_monitor(app: str, args: list, timeout: int) -> tuple:
    """使用 _ProcessMonitor 智能超时执行单条命令。

    流程：
    1. 启动子进程 + 监控线程
    2. 后台线程读取 stdout/stderr（避免管道阻塞）
    3. 主循环以 1s 间隔轮询：进程结束 → 返回；监控器 idle 超时 → 杀进程
    4. 硬保护：最多等待 timeout × 4 秒
    """
    process = subprocess.Popen(
        [app] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        start_new_session=True,
    )

    monitor = _ProcessMonitor(process.pid, base_timeout=timeout)
    monitor.start()

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _reader(stream, lines):
        try:
            for line in iter(stream.readline, ""):
                lines.append(line)
        except ValueError:
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    t_out = threading.Thread(target=_reader, args=(process.stdout, stdout_lines), daemon=True)
    t_err = threading.Thread(target=_reader, args=(process.stderr, stderr_lines), daemon=True)
    t_out.start()
    t_err.start()

    hard_deadline = time.time() + timeout * 4
    killed_by_monitor = False
    killed_by_hardlimit = False

    try:
        while time.time() < hard_deadline:
            retcode = process.poll()
            if retcode is not None:
                break
            if monitor.should_kill():
                killed_by_monitor = True
                break
            time.sleep(1)

        if process.poll() is None:
            killed_by_hardlimit = time.time() >= hard_deadline
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=5)
            except (ProcessLookupError, OSError):
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass
            except Exception:
                pass
    finally:
        monitor.stop()

    t_out.join(timeout=3)
    t_err.join(timeout=3)

    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)
    retcode = process.returncode if process.returncode is not None else -1

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

    return (retcode, stdout, stderr)


def _run_batch_with_monitor(idx, cmd, timeout):
    """Batch 子任务执行器，集成 _ProcessMonitor 智能超时。"""
    a = cmd.get("app", "")
    ar = cmd.get("args", [])
    result = {"index": idx, "returncode": -1, "stdout": "", "stderr": "", "error": True}
    if not a:
        result["stderr"] = "app为空"
        return result

    try:
        process = subprocess.Popen(
            [a] + list(ar),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            start_new_session=True,
        )
        monitor = _ProcessMonitor(process.pid, base_timeout=timeout)
        monitor.start()

        out_lines, err_lines = [], []

        def _reader(stream, lines):
            try:
                for line in iter(stream.readline, ""):
                    lines.append(line)
            except ValueError:
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        t_out = threading.Thread(target=_reader, args=(process.stdout, out_lines), daemon=True)
        t_err = threading.Thread(target=_reader, args=(process.stderr, err_lines), daemon=True)
        t_out.start()
        t_err.start()

        hard_deadline = time.time() + timeout * 4
        killed = False

        while time.time() < hard_deadline:
            retcode = process.poll()
            if retcode is not None:
                break
            if monitor.should_kill():
                killed = True
                break
            time.sleep(1)

        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=3)
                except Exception:
                    pass

        monitor.stop()
        t_out.join(timeout=2)
        t_err.join(timeout=2)

        stdout = "".join(out_lines)
        stderr = "".join(err_lines)
        retcode = process.returncode if process.returncode is not None else -1

        if killed:
            cmd_preview = f"{a} {' '.join(ar[:3])}"
            if len(ar) > 3:
                cmd_preview += f" ... (+{len(ar)-3} args)"
            stderr = (stderr + "\n" if stderr else "") + f"⏰ 空闲超时({timeout}s): {cmd_preview}"

        result.update({"returncode": retcode, "stdout": stdout, "stderr": stderr, "error": retcode != 0})
    except Exception as e:
        result["stderr"] = str(e)

    return result


def toolkit_exec(app: str = "", args: list = None, action: str = "single", commands: list = None, timeout: int = 30):
    """
    执行系统命令（单条或批量并行）。

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
        single: (returncode, stdout, stderr)
        batch: (0, json结果数组, "")
    """
    logger.info(f"toolkit_exec called: app={app!r}, args={repr(args)[:80]}, action={action!r}, commands={repr(commands)[:80]}, timeout={timeout!r}")

    _PY_CMD_THRESHOLD = 500  # -c 脚本超过此字符数则写入临时文件
    if action == "single" and app in ("python", "python3") and args:
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
                            pass
                    return result
                break  # 只处理第一个 -c

    if action == "batch":
        if not commands:
            return (0, "[]", "")

        results = [None] * len(commands)
        lock = threading.Lock()

        def _run_wrapper(idx, cmd):
            """Batch 子任务包装器，集成 _ProcessMonitor 智能超时。"""
            result = _run_batch_with_monitor(idx, cmd, timeout)
            with lock:
                results[idx] = result

        workers = min(len(commands), 8)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_wrapper, i, cmd) for i, cmd in enumerate(commands)]
            for f in as_completed(futures):
                f.result()

        success = sum(1 for r in results if r and not r.get("error"))
        results.insert(0, {"summary": f"{success}/{len(commands)} 成功", "total": len(commands), "workers": workers})
        return (0, json.dumps(results, ensure_ascii=False, indent=2), "")

    else:  # action == "single"
        if args is None:
            args = []

        # ── sudo 命令 → 弹出 GUI 密码框（保持原有逻辑） ──
        if app == "sudo" or app.endswith("/sudo"):
            return _sudo_with_gui(app, args)

        # 使用智能超时：监控进程资源使用，动态延长超时
        effective_timeout = timeout if timeout else 120
        result = _run_single_with_monitor(app, args, effective_timeout)
        return result

def _sudo_with_gui(app: str, args: list):
    """sudo 命令通过 GUI 对话框获取密码 — 显示完整命令信息"""
    import shutil
    import subprocess

    cmd_text = " ".join(args) if args else "(无参数)"
    title = "🔐 管理员权限请求"
    prompt = f"Tea Agent 需要执行一条管理员命令：\n\n{cmd_text}\n\n请输入管理员密码："

    # 尝试顺序: kdialog → zenity → pkexec → 回退到普通执行
    dialog_cmd = None

    if shutil.which("kdialog"):
        dialog_cmd = ["kdialog", "--title", title, "--password", prompt]
    elif shutil.which("zenity"):
        dialog_cmd = [
            "zenity", "--password", "--title", title,
            "--text", prompt,
        ]

    if dialog_cmd:
        pwd_result = subprocess.run(dialog_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if pwd_result.returncode != 0:
            return (126, "", "用户取消了密码输入")
        password = pwd_result.stdout.strip()
        if not password:
            return (1, "", "密码不能为空")

        try:
            process = subprocess.Popen(
                ["sudo", "-S"] + list(args),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
            stdout, stderr = process.communicate(
                input=password + "\n",
                timeout=180,
            )
            result = (process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
            result = (-1, "", "⏰ sudo 命令超时被强制终止 (>180s)")        # 清除密码
        password = "\x00" * len(password)
        del password
        return result

    # 无 GUI 工具 → 回退到 pkexec（自带弹框）或直接 sudo
    if shutil.which("pkexec"):
        try:
            process = subprocess.Popen(
                ["pkexec"] + list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
            stdout, stderr = process.communicate(timeout=120)
            result = (process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
            result = (-1, "", "⏰ pkexec 命令超时被强制终止 (>120s)")
        return result

    # 最后回退 — 可能失败（需要 tty）
    try:
        process = subprocess.Popen(
            [app] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        stdout, stderr = process.communicate(timeout=120)
        result = (process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            pass
        result = (-1, "", f"⏰ 命令超时被强制终止 (>120s): {app}")
    return result

def meta_toolkit_exec() -> dict:
    """Meta toolkit exec."""
    return {
        "type": "function",
        "function": {
            "description": "执行系统命令。action='single' 执行单条；action='batch' 并行批量执行多条。执行 sudo 命令时自动弹出 GUI 密码框。智能超时(v2.0)：后台 _ProcessMonitor 监控 CPU/MEM/IO，进程活跃时最多延长 4x 超时，空闲时按时终止。",
            "name": "toolkit_exec",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["single", "batch"],
                        "description": "single=单条命令, batch=批量并行。默认 single",
                    },
                    "app": {
                        "type": "string",
                        "description": "[single] 可执行程序路径",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "[single] 命令行参数列表",
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
                        "description": "[batch] 命令列表",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "[single] 基础超时秒数(默认120), [batch] 每个命令基础超时秒数(默认30)。进程活跃消耗资源时，最多延长 4x 时间；空闲超过 base_timeout 则终止。",
                    },
                },
                "required": [],
            },        },
    }
