"""
tea_agent_mini — 启动 Web Server。

用法：
    python -m tea_agent_mini
    # 等价于 python -m tea_agent.server
"""

import sys
from tea_agent.server import main

if __name__ == "__main__":
    sys.exit(main())
