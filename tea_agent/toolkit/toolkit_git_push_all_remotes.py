"""git 全远程推送工具 — 向所有配置的远程仓库推送当前分支"""
import logging
import subprocess

logger = logging.getLogger("toolkit")

def toolkit_git_push_all_remotes() -> dict:
    """向当前 git repo 配置的所有远程仓库推送当前分支。返回每个 remote 的推送结果。"""
    logger.info("toolkit_git_push_all_remotes called")
    try:
        res = subprocess.run(['git', 'remote'], capture_output=True, text=True, timeout=10)
        remotes = [r for r in res.stdout.strip().split('\n') if r]
        if not remotes:
            return {"ok": False, "error": "未配置任何远程仓库", "results": []}
        
        results = []
        all_ok = True
        for name in remotes:
            r = subprocess.run(['git', 'push', name], capture_output=True, text=True, timeout=60)
            ok = r.returncode == 0
            if not ok:
                all_ok = False
            msg = r.stdout.strip().split('\n')[-1] if r.stdout else (r.stderr.strip()[:200] if r.stderr else "未知错误")
            results.append({"remote": name, "ok": ok, "message": msg})
        
        return {"ok": all_ok, "results": results, "count": len(results)}
    except Exception as e:
        logger.warning(f"toolkit_git_push_all_remotes error: {e}")
        return {"ok": False, "error": str(e), "results": []}

def meta_toolkit_git_push_all_remotes() -> dict:
    """Meta toolkit git push all remotes."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_git_push_all_remotes",
            "description": "向当前 git repo 配置的所有远程仓库推送当前分支。",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }
