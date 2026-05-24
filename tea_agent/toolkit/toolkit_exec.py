
import logging
import sys

# --- Windows 兼容层 ---
_IS_WINDOWS = sys.platform == "win32"

# Windows shell 内置命令，需要 cmd.exe /c 包装才能执行
_WIN_SHELL_BUILTINS = {
    "dir", "type", "find", "findstr", "copy", "del", "erase",
    "ren", "rename", "md", "mkdir", "rd", "rmdir", "move",
    "echo", "set", "cls", "date", "time", "ver", "vol",
    "cd", "chdir", "pushd", "popd", "more", "color", "mklink",
}

def _resolve_command(app, args):
    """跨平台命令解析：Windows 上对 shell 内置命令自动包装为 cmd.exe /c"""
    if _IS_WINDOWS and app.lower() in _WIN_SHELL_BUILTINS:
        cmd_line = app
        if args:
            cmd_line += " " + " ".join(args)
        return "cmd.exe", ["/c", cmd_line]
    return app, args

def _kill_process(process):
    """跨平台进程强制终止"""
    import signal as _sig
    if _IS_WINDOWS:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), _sig.SIGKILL)
            process.wait(timeout=5)
        except (ProcessLookupError, OSError):
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass

logger = logging.getLogger("toolkit")

def toolkit_exec(app: str = "", args: list = None, action: str = "single", commands: list = None, timeout: int = 30):
    """
    执行系统命令（单条或批量并行）。

    Args:
        app (str): Description.
        args (list): Description.
        action (str): Description.
        commands (list): Description.
        timeout (int): Description.
    """
    logger.info(f"toolkit_exec called: app={app!r}, args={repr(args)[:80]}, action={action!r}, commands={repr(commands)[:80]}, timeout={timeout!r}")

    import subprocess
    import json
    import os
    import signal
    import tempfile

    _PY_CMD_THRESHOLD = 500
    if action == "single" and app in ("python", "python3") and args:
        for i, arg in enumerate(args):
            if arg == "-c" and i + 1 < len(args):
                script = args[i + 1]
                if isinstance(script, str) and len(script) > _PY_CMD_THRESHOLD:
                    tmpfd, tmppath = tempfile.mkstemp(suffix=".py", prefix="tea_exec_")
                    try:
                        os.close(tmpfd)
                        with open(tmppath, "w", encoding="utf-8") as f:
                            f.write(script)
                        new_args = list(args[:i]) + [tmppath] + list(args[i+2:])
                        logger.info(f"toolkit_exec: -c脚本{len(script)}字符→临时文件 {tmppath}")
                        result = toolkit_exec(app=app, args=new_args, action="single",
                                             commands=None, timeout=timeout)
                    finally:
                        try:
                            os.unlink(tmppath)
                        except OSError:
                            pass
                    return result
                break

    if action == "batch":
        if not commands:
            return (0, "[]", "")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        results = [None] * len(commands)
        lock = threading.Lock()

        def _run(idx, cmd):
            """Internal: run.
            
            Args:
                idx: Description.
                cmd: Description.
            """
            import signal as _sig
            try:
                a = cmd.get("app", "")
                ar = cmd.get("args", [])
                if not a:
                    with lock:
                        results[idx] = {"index": idx, "returncode": -1, "stdout": "", "stderr": "app为空", "error": True}
                    return
                resolved_app, resolved_args = _resolve_command(a, ar)
                popen_kwargs = {
                    "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                    "text": True,
                }
                if not _IS_WINDOWS:
                    popen_kwargs["start_new_session"] = True
                try:
                    p = subprocess.Popen(
                        [resolved_app] + list(resolved_args),
                        **popen_kwargs,
                    )
                except FileNotFoundError:
                    with lock:
                        results[idx] = {"index": idx, "returncode": -1, "stdout": "", "stderr": f"❌ 命令未找到: {a}", "error": True}
                    return
                try:
                    stdout, stderr = p.communicate(timeout=timeout)
                    with lock:
                        results[idx] = {
                            "index": idx, "returncode": p.returncode,
                            "stdout": stdout, "stderr": stderr,
                            "error": p.returncode != 0,
                        }
                except subprocess.TimeoutExpired:
                    _kill_process(p)
                    cmd_preview = f"{a} {' '.join(ar[:3])}"
                    if len(ar) > 3:
                        cmd_preview += f" ... (+{len(ar)-3} args)"
                    with lock:
                        results[idx] = {"index": idx, "returncode": -1, "stdout": "", "stderr": f"⏰ 超时({timeout}s): {cmd_preview}", "error": True}
            except Exception as e:
                with lock:
                    results[idx] = {"index": idx, "returncode": -1, "stdout": "", "stderr": str(e), "error": True}

        workers = min(len(commands), 8)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run, i, cmd) for i, cmd in enumerate(commands)]
            for f in as_completed(futures):
                f.result()

        success = sum(1 for r in results if r and not r.get("error"))
        results.insert(0, {"summary": f"{success}/{len(commands)} 成功", "total": len(commands), "workers": workers})
        return (0, json.dumps(results, ensure_ascii=False, indent=2), "")

    else:
        if args is None:
            args = []

        if app == "sudo" or app.endswith("/sudo"):
            return _sudo_with_gui(app, args)

        effective_timeout = timeout if timeout else 120
        
        try:
            resolved_app, resolved_args = _resolve_command(app, args)
            popen_kwargs = {
                "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                "text": True,
            }
            if not _IS_WINDOWS:
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(
                [resolved_app] + list(resolved_args),
                **popen_kwargs,
            )
            stdout, stderr = process.communicate(timeout=effective_timeout)
            result = (process.returncode, stdout, stderr)
        except FileNotFoundError:
            result = (-1, "", f"❌ 命令未找到: {app}")
        except subprocess.TimeoutExpired:
            _kill_process(process)
            cmd_preview = f"{app} {' '.join(args[:5])}"
            if len(args) > 5:
                cmd_preview += f" ... (+{len(args)-5} args)"
            result = (-1, "", f"⏰ 命令超时被强制终止 (>{effective_timeout}s): {cmd_preview}")
        
        return result

def _sudo_with_gui(app: str, args: list):
    """
    sudo 命令通过 GUI 对话框获取密码 — 显示完整命令信息

    Args:
        app (str): Description.
        args (list): Description.
    """
    import shutil
    import subprocess

    cmd_text = " ".join(args) if args else "(无参数)"
    title = "🔐 管理员权限请求"
    prompt = f"Tea Agent 需要执行一条管理员命令：\n\n{cmd_text}\n\n请输入管理员密码："

    dialog_cmd = None

    if shutil.which("kdialog"):
        dialog_cmd = ["kdialog", "--title", title, "--password", prompt]
    elif shutil.which("zenity"):
        dialog_cmd = [
            "zenity", "--password", "--title", title,
            "--text", prompt,
        ]

    if dialog_cmd:
        pwd_result = subprocess.run(dialog_cmd, capture_output=True, text=True, timeout=30)
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
                text=True,
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
            result = (-1, "", "⏰ sudo 命令超时被强制终止 (>180s)")
        password = "\x00" * len(password)
        del password
        return result

    if shutil.which("pkexec"):
        try:
            process = subprocess.Popen(
                ["pkexec"] + list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
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

    try:
        process = subprocess.Popen(
            [app] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
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
    """
    Meta toolkit exec

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "description": "执行系统命令。action='single' 执行单条；action='batch' 并行批量执行多条。执行 sudo 命令时自动弹出 GUI 密码框并显示完整命令信息。",
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
                        "description": "[single] 超时秒数(默认120), [batch] 每个命令超时秒数(默认30)。超时后进程强制终止",
                    },
                },
                "required": [],
            },        },
    }
