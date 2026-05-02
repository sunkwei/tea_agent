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

    else:  # action == "single"
        if args is None:
            args = []
        result = subprocess.run([app] + args, capture_output=True, text=True)
        return (result.returncode, result.stdout, result.stderr)


def meta_toolkit_exec() -> dict:
    return {
        "type": "function",
        "function": {
            "description": "执行系统命令。action='single' 执行单条；action='batch' 并行批量执行多条。",
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
                        "description": "[batch] 每个命令超时秒数，默认30",
                    },
                },
                "required": [],
                "type": "object",
            },
        },
    }
