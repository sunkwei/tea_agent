#!/usr/bin/env python3
"""
确保自进化进程启动的脚本。
每分钟检查一次，如果未启动则自动启动。
"""
import sys
import os
import json
from pathlib import Path
from datetime import datetime

# 状态文件路径
STATE_FILE = os.path.expanduser("~/.tea_agent/self_evolve_state.json")


def _read_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "running": False, "pid": os.getpid(), "started_at": None,
        "last_cycle_at": None, "cycles_completed": 0,
    }


def _write_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    state["_updated"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def ensure_running():
    """检查自进化进程状态，未启动则启动"""
    # 1. 检查状态
    state = _read_state()
    running = state.get("running", False)
    pid = state.get("pid")
    
    if running:
        print(f"[OK] 自进化进程已在运行 (PID: {pid}, 已完成 {state.get('cycles_completed', 0)} 轮)")
        return True
    
    # 2. 未启动，启动新线程
    print("[INFO] 自进化进程未启动，正在启动...")
    
    # 简化版：直接写入状态文件并启动线程
    # 实际应该调用完整的 toolkit_self_evolve_thread("start")
    try:
        # 使用子进程调用
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c", 
             "import sys; sys.path.insert(0, '.'); "
             "from tea_agent.toolkit.toolkit_self_evolve_thread import toolkit_self_evolve_thread; "
             "r = toolkit_self_evolve_thread('start'); "
             "import json; print(json.dumps(r))"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            try:
                r = json.loads(result.stdout)
                if r.get("status") in ("started", "already_running"):
                    print(f"[OK] 自进化进程已启动 (PID: {r.get('pid')})")
                    return True
                else:
                    print(f"[WARN] 启动返回: {r}")
                    return False
            except json.JSONDecodeError:
                print(f"[OK] 已调用启动命令")
                return True
        else:
            print(f"[ERROR] 启动失败: {result.stderr[:200]}")
            return False
    except Exception as e:
        print(f"[ERROR] 异常: {e}")
        return False


if __name__ == "__main__":
    success = ensure_running()
    sys.exit(0 if success else 1)
