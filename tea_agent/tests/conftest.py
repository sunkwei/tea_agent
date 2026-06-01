"""
pytest 公共 fixtures。
提供可复用的测试资源：临时 Storage、临时配置文件、内存模型配置等。
"""

import os
import sys
import tempfile
import shutil
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
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def storage(tmp_db_path):
    """提供临时 Storage 实例，测试结束后安全关闭"""
    from tea_agent.store import Storage

    s = Storage(db_path=tmp_db_path)
    yield s
    try:
        s.close()
    except Exception:
        pass


@pytest.fixture
def tmp_yaml_config():
    """临时 YAML 配置文件，返回路径"""
    tmpdir = tempfile.mkdtemp(prefix="tea_config_")
    yaml_path = os.path.join(tmpdir, "config.yaml")
    yield yaml_path
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def default_agent_config():
    """返回默认的 AgentConfig 实例（不从文件加载）"""
    from tea_agent.config import AgentConfig
    return AgentConfig()
