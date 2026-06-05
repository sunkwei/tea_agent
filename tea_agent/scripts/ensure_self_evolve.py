#!/usr/bin/env python3
"""
确保自进化进程启动的脚本。
每分钟检查一次，如果未启动则自动启动。
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tea_agent.toolkit.toolkit_self_evolve_thread import toolkit_self_evolve_thread


def ensure_running():
    """检查自进化进程状态，未启动则启动"""
    # 1. 检查状态
    status = toolkit_self_evolve_thread("status")
    running = status.get("running", False)
    
    if running:
        print(f"[OK] 自进化进程已在运行 (PID: {status.get('pid')}, 已完成 {status.get('cycles_completed', 0)} 轮)")
        return True
    
    # 2. 未启动，执行启动
    print("[INFO] 自进化进程未启动，正在启动...")
    result = toolkit_self_evolve_thread("start")
    
    if result.get("status") == "started":
        print(f"[OK] 自进化进程已启动 (PID: {result.get('pid')})")
        return True
    elif result.get("status") == "already_running":
        print(f"[OK] 自进化进程已在运行 (PID: {result.get('pid')})")
        return True
    else:
        print(f"[ERROR] 启动失败: {result}")
        return False


if __name__ == "__main__":
    success = ensure_running()
    sys.exit(0 if success else 1)
