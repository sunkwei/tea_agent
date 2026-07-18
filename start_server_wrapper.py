#!/usr/bin/env python3
"""Server Wrapper - 确保在正确的虚拟环境中启动 server"""
import sys, os, subprocess, platform

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# 虚拟环境路径列表（按优先级排序）
VENV_PATHS = [
    # 项目本地虚拟环境
    os.path.join(PROJECT_ROOT, "venv"),
    os.path.join(PROJECT_ROOT, ".venv"),
    os.path.join(PROJECT_ROOT, "env"),
    os.path.join(PROJECT_ROOT, ".env"),
    # 全局虚拟环境
    os.path.expanduser("~/venv_work"),
]

def get_venv_python():
    for venv_path in VENV_PATHS:
        if not os.path.isdir(venv_path): continue
        exe = 'Scripts\python.exe' if platform.system()=='Windows' else 'bin/python'
        py = os.path.join(venv_path, exe)
        if os.path.isfile(py): return py, venv_path
    return None, None

def check_venv():
    in_v = hasattr(sys,'real_prefix') or (hasattr(sys,'base_prefix') and sys.base_prefix!=sys.prefix)
    return in_v, os.environ.get('VIRTUAL_ENV')

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Server Wrapper')
    parser.add_argument('--check', action='store_true', help='仅诊断，不启动')
    args = parser.parse_args()
    
    in_venv, venv_env = check_venv()
    venv_py, venv_path = get_venv_python()
    
    print(f"=== Server Wrapper 诊断 ===")
    print(f"当前 Python: {sys.executable}")
    print(f"sys.prefix: {sys.prefix}")
    print(f"在虚拟环境中: {in_venv}")
    print(f"VIRTUAL_ENV: {venv_env}")
    print(f"检测到 venv: {venv_path or '无'}")
    print(f"venv Python: {venv_py or '无'}")
    
    if args.check:
        print("\\n→ 使用 --check 模式，仅诊断不启动")
        return
    
    if os.environ.get('TEA_AGENT_WRAPPER_DONE')=='1':
        from tea_agent.server import run_server
        run_server(host="127.0.0.1", port=80)
        return
    
    if in_venv:
        from tea_agent.server import run_server
        run_server(host="127.0.0.1", port=80)
    elif venv_py:
        env = os.environ.copy(); env['TEA_AGENT_WRAPPER_DONE']='1'
        subprocess.run([venv_py, __file__], env=env, cwd=PROJECT_ROOT)
    else:
        print("未找到虚拟环境，请先创建: python -m venv venv")

if __name__=="__main__": main()
