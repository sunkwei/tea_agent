"""
pytest 公共 fixtures。
提供可复用的测试资源：临时 Storage、临时配置文件、内存模型配置等。
"""

import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def tmp_db_path():
    """在临时目录创建数据库路径，测试结束后自动清理"""
    tmpdir = tempfile.mkdtemp(prefix="tea_test_")
    db_path = os.path.join(tmpdir, "test_chat_history.db")
    yield db_path
    # 清理
    with contextlib.suppress(Exception):
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def storage(tmp_db_path):
    """提供临时 Storage 实例，测试结束后安全关闭"""
    from tea_agent.store import Storage

    s = Storage(db_path=tmp_db_path)
    yield s
    with contextlib.suppress(Exception):
        s.close()


@pytest.fixture
def tmp_yaml_config(tmp_path, monkeypatch):
    """隔离的 provider.yaml 路径（唯一事实源），返回路径。

    文件名沿用历史 fixture 名，但语义已是 provider.yaml：路径一经设置即通过
    ``TEA_PROVIDER_FILE`` 生效，随后 ``write_provider_yaml(path)`` 写入内容。
    """
    path = tmp_path / "provider.yaml"
    monkeypatch.setenv("TEA_PROVIDER_FILE", str(path))
    return str(path)


@pytest.fixture(autouse=True)
def _isolate_provider_store(monkeypatch):
    """每个用例重置 provider_store / ProviderService / config 单例。

    这三个都是模块级单例，跨用例残留会让「读不到刚写的 provider.yaml」这类
    失败变成随机现象。
    """
    import tea_agent.provider_store as ps_mod

    monkeypatch.setattr(ps_mod, "_store", None, raising=False)
    try:
        import tea_agent.model_manager as mm_mod

        monkeypatch.setattr(mm_mod, "_service", None, raising=False)
    except Exception:
        pass
    import tea_agent.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_config_cache", None, raising=False)
    yield


@pytest.fixture
def default_agent_config():
    """返回默认的 AgentConfig 实例（不从文件加载）"""
    from tea_agent.config import AgentConfig

    return AgentConfig()
