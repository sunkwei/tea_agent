"""Git commit — 固定 author: tea_agent <sunkwei@gmail.com>，不受全局 git 配置影响。"""
import logging
import os
import subprocess

logger = logging.getLogger("toolkit")

AUTHOR_NAME = "tea_agent"
AUTHOR_EMAIL = "sunkwei@gmail.com"


def _run_git(args, cwd=None):
    cmd = ["git"] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=60)
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, (r.stderr or r.stdout).strip()
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except FileNotFoundError:
        return False, "git not found"


def toolkit_git_commit(message, files=None, amend=False,
                       no_verify=False, allow_empty=False,
                       auto_add=False):
    """执行 git commit，固定使用 author: tea_agent <sunkwei@gmail.com>"""
    logger.info("toolkit_git_commit called: msg=%s files=%s", message, files)
    cwd = os.getcwd()
    result = {
        "success": False,
        "message": message,
        "author": "%s <%s>" % (AUTHOR_NAME, AUTHOR_EMAIL),
    }

    # 1. git add
    if files:
        ok, out = _run_git(["add"] + files, cwd)
        if not ok:
            result["step"] = "add"
            result["error"] = out
            return result
    elif auto_add:
        ok, out = _run_git(["add", "."], cwd)
        if not ok:
            result["step"] = "add"
            result["error"] = out
            return result

    # 2. 检查是否有变更待提交
    ok, status = _run_git(["status", "--porcelain"], cwd)
    has_changes = bool(status.strip()) if ok else True
    if not has_changes and not allow_empty:
        result["step"] = "check"
        result["error"] = "nothing to commit (use allow_empty=True to force)"
        result["status"] = "clean"
        return result

    # 3. commit（用 -c 注入 author，不影响全局/本地 git config）
    commit_args = [
        "-c", "user.name=" + AUTHOR_NAME,
        "-c", "user.email=" + AUTHOR_EMAIL,
        "commit",
        "-m", message,
    ]
    if amend:
        commit_args.append("--amend")
    if no_verify:
        commit_args.append("--no-verify")
    if allow_empty:
        commit_args.append("--allow-empty")

    ok, out = _run_git(commit_args, cwd)
    if ok:
        result["success"] = True
        result["output"] = out
        for line in out.split('\n'):
            if line.startswith('['):
                parts = line.split()
                if len(parts) >= 2:
                    result["branch"] = parts[0].lstrip('[')
                    result["hash"] = parts[1].rstrip(']')
        # 验证 author 是否确实生效
        if result.get("hash"):
            ok2, a_out = _run_git(["log", "--format=%an <%ae>", "-1"], cwd)
            if ok2:
                result["verified_author"] = a_out
    else:
        result["error"] = out

    return result


def meta_toolkit_git_commit():
    """Meta info for toolkit_git_commit."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_git_commit",
            "description": "Git commit — 固定 author: tea_agent <sunkwei@gmail.com>，不受全局 git 配置影响。支持 add/commit/amend。",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "commit 信息",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要 git add 的文件列表（相对于仓库根目录）",
                    },
                    "amend": {
                        "type": "boolean",
                        "description": "是否 --amend 修改上次 commit",
                    },
                    "no_verify": {
                        "type": "boolean",
                        "description": "是否 --no-verify 跳过 hooks",
                    },
                    "allow_empty": {
                        "type": "boolean",
                        "description": "是否 --allow-empty 允许空 commit",
                    },
                    "auto_add": {
                        "type": "boolean",
                        "description": "是否自动 git add .（未指定 files 时有效）",
                    },
                },
                "required": ["message"],
            },
        },
    }
