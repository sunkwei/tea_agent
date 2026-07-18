"""
toolkit_evolution_exp 测试 — 经验库管理
"""


def test_meta_exists():
    from tea_agent.tlk import Toolkit
    tk = Toolkit()
    assert "toolkit_evolution_exp" in tk.meta_map


def test_list_empty():
    """首次 list 应返回空"""
    from tea_agent.toolkit.toolkit_evolution_exp import toolkit_evolution_exp
    result = toolkit_evolution_exp(action="list")
    assert result.get("ok") is True


def test_record_and_search():
    """记录一条经验后应能搜到"""
    from tea_agent.toolkit.toolkit_evolution_exp import toolkit_evolution_exp, _get_exp_path, _save_exp_db
    # 清空测试数据
    _save_exp_db([])
    result = toolkit_evolution_exp(action="record", description="test_exp", category="test")
    assert result.get("ok") is True
    search = toolkit_evolution_exp(action="search", query="test_exp")
    assert search.get("ok") is True
    assert len(search.get("results", [])) >= 1
