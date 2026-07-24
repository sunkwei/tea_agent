"""
toolkit_dynamic_skill 测试 — 技能记录与推荐
"""



def test_meta_exists():
    from tea_agent.tlk import Toolkit
    tk = Toolkit()
    assert "toolkit_dynamic_skill" in tk.meta_map


def test_list_empty():
    """首次 list 应返回空列表（无技能记录）"""
    from tea_agent.toolkit.toolkit_dynamic_skill import toolkit_dynamic_skill
    result = toolkit_dynamic_skill(action="list")
    assert result.get("ok") is True
    assert result.get("total", 0) >= 0


def test_recommend_no_task_error():
    """空 task 应返回错误"""
    from tea_agent.toolkit.toolkit_dynamic_skill import toolkit_dynamic_skill
    result = toolkit_dynamic_skill(action="recommend", task="")
    assert result.get("ok") is False
    assert "error" in result
