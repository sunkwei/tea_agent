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

# ── 惰性导出（PEP 562）──────────────────────────────────────────────
# `__all__` 声明的其余公开名都定义在较重的子模块中。若在此处急切导入，会把
# `import tea_agent` 与这些子模块的导入顺序绑死、并增加包导入开销；而完全不
# 导入则会让 `from tea_agent import Storage` 抛 ImportError —— 即 `__all__`
# 承诺了却拿不到（运行时实证曾确认 8 个公开名仅 2 个可用）。
# 模块级 __getattr__ 兼顾两者：首次访问时导入并缓存进 globals()。
_LAZY_EXPORTS = {
    "BaseChatSession": ".basesession",
    "OnlineToolSession": ".onlinesession",
    "Storage": ".store",
    "load_config": ".config",
    "get_config": ".config",
    "save_config": ".config",
}


def __getattr__(name: str):
    """PEP 562：按 _LAZY_EXPORTS 惰性解析 __all__ 中的公开名。"""
    mod_name = _LAZY_EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(mod_name, __package__), name)
    globals()[name] = value  # 缓存：后续访问不再经过 __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
