# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 构建Python包(处理build目录冲突)
def toolkit_build_package() -> dict:
    """
    在当前目录构建 Python 包（调用 python -m build）。
    自动处理本地 build/ 目录遮蔽 build 包的常见问题：
    临时重命名 build/ → build.bak/，构建完成后恢复。
    """
    import os
    import subprocess
    import shutil

    cwd = os.getcwd()
    build_dir = os.path.join(cwd, "build")
    bak_dir = os.path.join(cwd, "build.bak")
    had_conflict = os.path.isdir(build_dir)

    if had_conflict:
        # 移除旧的 bak（如果存在）
        if os.path.exists(bak_dir):
            shutil.rmtree(bak_dir)
        os.rename(build_dir, bak_dir)

    try:
        result = subprocess.run(
            ["python", "-m", "build"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout,
            "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
            "had_build_conflict": had_conflict,
            "ok": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stderr": "构建超时 (>120s)", "ok": False}
    except Exception as e:
        return {"exit_code": -1, "stderr": str(e), "ok": False}
    finally:
        if had_conflict and os.path.exists(bak_dir):
            # 恢复原 build 目录
            if os.path.exists(build_dir):
                shutil.rmtree(build_dir)
            os.rename(bak_dir, build_dir)


def meta_toolkit_build_package():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_build_package",
            "description": "在当前目录构建 Python 包（python -m build），自动处理本地 build/ 目录遮蔽 build 包的冲突。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
