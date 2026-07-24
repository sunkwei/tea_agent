# 2026-05-06 gen by claude, 添加包版本号
# 2026-05-29 refactor: 统一 Agent 类

# 自动加载 .env 文件（项目根目录）
import os as _os

_env_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), '.env')
if _os.path.isfile(_env_path):
    with open(_env_path, encoding='utf-8') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                _os.environ.setdefault(_k.strip(), _v.strip())

__version__ = "0.13.0"

__all__ = [
    "Agent",
    "TeaAgent",      # 向后兼容别名
    "BaseChatSession",
    "OnlineToolSession",
    "Storage",
    "load_config",
    "get_config",
    "save_config",
]

from tea_agent.agent import Agent, TeaAgent
