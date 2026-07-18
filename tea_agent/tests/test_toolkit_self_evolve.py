"""
toolkit_self_evolve 测试 — 自进化核心链路
"""

import pytest


def test_meta_exists():
    """self_evolve 应有 meta 注册"""
    from tea_agent.tlk import Toolkit
    tk = Toolkit()
    assert "toolkit_self_evolve" in tk.meta_map


def test_meta_has_file_path():
    """meta 应包含 file_path 参数"""
    from tea_agent.tlk import Toolkit
    meta = Toolkit().meta_map["toolkit_self_evolve"]
    params = meta["function"]["parameters"]["properties"]
    assert "file_path" in params


def test_meta_has_required_params():
    """meta 应声明 file_path/description/old_code/new_code"""
    from tea_agent.tlk import Toolkit
    meta = Toolkit().meta_map["toolkit_self_evolve"]
    props = meta["function"]["parameters"]["properties"]
    for key in ("file_path", "description", "old_code", "new_code"):
        assert key in props, f"缺少参数: {key}"
