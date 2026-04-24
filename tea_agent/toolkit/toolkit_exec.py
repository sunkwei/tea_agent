# llm generated tool func, created Wed Apr 15 13:13:26 2026

def toolkit_exec(app: str, args: list) -> tuple:
    import subprocess
    result = subprocess.run([app] + args, capture_output=True, text=True)
    return (result.returncode, result.stdout, result.stderr)


def meta_toolkit_exec() -> dict:
    return {"type": "function", "function": {"description": "执行系统命令，返回 (返回值, stdout, stderr)", "name": "toolkit_exec", "parameters": {"properties": {"app": {"description": "可执行程序路径", "type": "string"}, "args": {"description": "命令行参数列表", "items": {"type": "string"}, "type": "array"}}, "required": ["app", "args"], "type": "object"}}}
