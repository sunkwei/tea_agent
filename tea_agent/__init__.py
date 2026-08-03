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

def _get_version() -> str:
    """获取项目版本（单一来源）：优先 pyproject.toml，回退已安装包元数据。"""
    _pp = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), 'pyproject.toml')
    try:
        if _os.path.isfile(_pp):
            with open(_pp, encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line.startswith('version'):
                        _v = _line.split('=', 1)[-1].strip().strip('"').strip("'")
                        if _v:
                            return _v
    except Exception:
        pass
    try:
        from importlib.metadata import version as _md_version
        return _md_version("tea_agent")
    except Exception:
        return "0.0.0"


__version__ = _get_version()

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
