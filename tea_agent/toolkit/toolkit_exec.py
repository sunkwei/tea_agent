# NOTE: 2026-05-02 12:00:00, self-evolved by tea_agent --- 合并 toolkit_batch_exec 进入 toolkit_exec（action='batch'），消除命令执行工具重叠
# llm generated tool func, created Wed Apr 15 13:13:26 2026
# version: 1.1.0
# NOTE: 2026-05-02, self-evolved by tea_agent --- 合并 toolkit_batch_exec: 新增 action='batch'

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

    返回:
        single: (returncode, stdout, stderr)
        batch: (0, json结果数组, "")
    """
    import subprocess
    import json
    import os
    import signal

    if action == "batch":
        if not commands:
            return (0, "[]", "")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        results = [None] * len(commands)
        lock = threading.Lock()

        def _run(idx, cmd):
            try:
                a = cmd.get("app", "")
                ar = cmd.get("args", [])
                if not a:
                    with lock:
                        results[idx] = {"index": idx, "returncode": -1, "stdout": "", "stderr": "app为空", "error": True}
                    return
                p = subprocess.run([a] + list(ar), capture_output=True, text=True, timeout=timeout)
                with lock:
                    results[idx] = {
                        "index": idx, "returncode": p.returncode,
                        "stdout": p.stdout[:5000], "stderr": p.stderr[:1000],
                        "error": p.returncode != 0,
                    }
            except subprocess.TimeoutExpired:
                with lock:
                    results[idx] = {"index": idx, "returncode": -1, "stdout": "", "stderr": f"超时({timeout}s)", "error": True}
            except Exception as e:
                with lock:
                    results[idx] = {"index": idx, "returncode": -1, "stdout": "", "stderr": str(e)[:500], "error": True}

        workers = min(len(commands), 8)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run, i, cmd) for i, cmd in enumerate(commands)]
            for f in as_completed(futures):
                f.result()

        success = sum(1 for r in results if r and not r.get("error"))
        results.insert(0, {"summary": f"{success}/{len(commands)} 成功", "total": len(commands), "workers": workers})
        return (0, json.dumps(results, ensure_ascii=False, indent=2), "")

# NOTE: 2026-05-04 12:39:01, self-evolved by tea_agent --- toolkit_exec 检测 sudo 自动弹出 GUI 密码框，显示命令信息
    else:  # action == "single"
        if args is None:
            args = []

        # ── sudo 命令 → 弹出 GUI 密码框 ──
        if app == "sudo" or app.endswith("/sudo"):
            return _sudo_with_gui(app, args)

        # 单次命令超时默认 120s，可通过 timeout 参数覆盖
        effective_timeout = timeout if timeout else 120
        
        # Popen + communicate(timeout) + kill: 超时后强制终止进程
        try:
            process = subprocess.Popen(
                [app] + list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(timeout=effective_timeout)
            result = (process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            # 强制终止并收割
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
            cmd_preview = f"{app} {' '.join(args[:5])}"
            if len(args) > 5:
                cmd_preview += f" ... (+{len(args)-5} args)"
            result = (-1, "", f"⏰ 命令超时被强制终止 (>{effective_timeout}s): {cmd_preview}")
        
        return _truncate_result(result)



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
        pwd_result = subprocess.run(dialog_cmd, capture_output=True, text=True, timeout=30)
        if pwd_result.returncode != 0:
            return (126, "", "用户取消了密码输入")
        password = pwd_result.stdout.strip()
        if not password:
            return (1, "", "密码不能为空")

# NOTE: 2026-05-04 12:45:05, self-evolved by tea_agent --- sudo 路径也使用 _truncate_result 截断输出
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
            result = (-1, "", f"⏰ sudo 命令超时被强制终止 (>180s)")
        # 清除密码
        password = "\x00" * len(password)
        del password
        return _truncate_result(result)

    # 无 GUI 工具 → 回退到 pkexec（自带弹框）或直接 sudo
    if shutil.which("pkexec"):
# NOTE: 2026-05-04 12:45:12, self-evolved by tea_agent --- pkexec 和回退路径也使用 _truncate_result
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
        return _truncate_result(result)

# NOTE: 2026-05-04 12:44:57, self-evolved by tea_agent --- 添加 _truncate_result 函数，智能截断 stdout/stderr
    # 最后回退 — 可能失败（需要 tty）
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
    return _truncate_result(result)


def _truncate_result(result, max_lines: int = 80, max_chars: int = 4000):
    """截断过大的输出。支持 subprocess.CompletedProcess 或 (rc, stdout, stderr) tuple"""
    if isinstance(result, tuple):
        rc, stdout, stderr = result
        stdout = stdout or ""
        stderr = stderr or ""
    else:
        rc = result.returncode
        stdout = result.stdout or ""
        stderr = result.stderr or ""

    # 截断 stdout
    if len(stdout) > max_chars:
        lines = stdout.split("\n")
        if len(lines) > max_lines:
            head = "\n".join(lines[:max_lines//2])
            tail = "\n".join(lines[-max_lines//2:])
            skipped = len(lines) - max_lines
            stdout = f"{head}\n... [跳过 {skipped} 行] ...\n{tail}"
        if len(stdout) > max_chars:
            original_len = len(result.stdout) if not isinstance(result, tuple) else len(result[1] or '')
            stdout = stdout[:max_chars] + f"\n... [截断，原长度 {original_len} 字符]"

    # stderr 只保留前 500 字符
    if len(stderr) > 500:
        original_len = len(result.stderr) if not isinstance(result, tuple) else len(result[2] or '')
        stderr = stderr[:500] + f"\n... [截断，原长度 {original_len} 字符]"

    return (rc, stdout, stderr)


def meta_toolkit_exec() -> dict:
    return {
        "type": "function",
        "function": {
# NOTE: 2026-05-04 12:39:08, self-evolved by tea_agent --- 更新 toolkit_exec meta 描述：注明 sudo 自动弹框
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
                "type": "object",
            },
        },
    }
