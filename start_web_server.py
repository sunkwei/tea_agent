#!/usr/bin/env python3
"""启动Web服务器"""
import sys
import os
import time

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tea_agent.server import run_server

def main():
    try:
        run_server(host="127.0.0.1", port=8080)
    except KeyboardInterrupt:
        print("\nServer stopped")
    except Exception as e:
        print(f"Server start failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()