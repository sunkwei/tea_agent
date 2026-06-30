#!/usr/bin/env python3
"""启动Web服务器"""
import sys
import os
import time

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tea_agent.server import run_server

def main():
    print("启动 Tea Agent Web 服务器...")
    print("访问地址: http://127.0.0.1:8080")
    print("按 Ctrl+C 停止服务器")
    print("=" * 50)
    
    try:
        run_server(host="127.0.0.1", port=8080)
    except KeyboardInterrupt:
        print("\n服务器已停止")
    except Exception as e:
        print(f"服务器启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()