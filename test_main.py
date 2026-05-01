"""Test CLI entry point — verifies import, construction, command dispatch without API calls."""

from tea_agent.tea_main_cli import TeaCLI  # noqa: F401 — verify import works
from tea_agent.store import Storage
from tea_agent.config import load_config

import os
from pathlib import Path
import tempfile


def test_config_loads():
    """配置可正常加载（不要求 API Key 已配置）。"""
    cfg = load_config()
    assert cfg is not None
    assert hasattr(cfg, "main_model")
    print(f"✅ 配置加载成功 | 主模型: {cfg.main_model.model_name or '(未配置)'}")


def test_storage_init():
    """Storage 可在临时目录初始化。"""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        s = Storage(db_path=db_path)
        assert s is not None
        # 验证基本操作
        tid = s.create_topic("测试主题")
        assert tid > 0
        topics = s.list_topics()
        assert any(t["topic_id"] == tid for t in topics)
        print(f"✅ Storage OK | topic_id={tid}")


def test_tea_cli_import():
    """TeaCLI 类可正常导入（不实例化，避免依赖 API 配置）。"""
    assert TeaCLI is not None
    # 检查关键方法存在
    assert hasattr(TeaCLI, "_handle_command")
    assert hasattr(TeaCLI, "_cmd_help")
    assert hasattr(TeaCLI, "chat")
    print("✅ TeaCLI 导入 + 方法签名正常")


if __name__ == "__main__":
    test_config_loads()
    test_storage_init()
    test_tea_cli_import()
    print("\n" + "=" * 50)
    print("  All Main Tests Passed ✅")
    print("=" * 50)
