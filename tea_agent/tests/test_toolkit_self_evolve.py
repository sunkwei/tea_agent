"""
toolkit_self_evolve 测试 — 自进化核心链路
"""



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


def test_cleanup_removes_old_timestamped_backups(tmp_path):
    """_cleanup_old_backups 保留最近 keep 份，删除更早的时间戳备份。"""
    from tea_agent.toolkit.toolkit_self_evolve import _cleanup_old_backups

    target = tmp_path / "foo.py"
    target.write_text("x = 1\n", encoding="utf-8")
    # 创建 5 个时间戳备份 foo.py.bak.<ts>，时间戳字典序=新序
    for ts in ("20260801_000001", "20260802_000002", "20260803_000003",
               "20260804_000004", "20260805_000005"):
        (tmp_path / f"foo.py.bak.{ts}").write_text("backup\n", encoding="utf-8")
    # 一个不匹配的无关备份应当保留（不误删手工命名）
    unrelated = tmp_path / "foo.py.manual_bak"
    unrelated.write_text("keep\n", encoding="utf-8")

    _cleanup_old_backups(str(target), keep=3)

    remaining = sorted(p.name for p in tmp_path.iterdir() if "foo.py.bak." in p.name)
    assert remaining == [
        "foo.py.bak.20260803_000003",
        "foo.py.bak.20260804_000004",
        "foo.py.bak.20260805_000005",
    ]
    assert unrelated.exists()  # 无关备份不受影响


def test_cleanup_noop_below_threshold(tmp_path):
    """备份数不超过 keep 时不删除任何文件。"""
    from tea_agent.toolkit.toolkit_self_evolve import _cleanup_old_backups

    target = tmp_path / "bar.py"
    target.write_text("x = 1\n", encoding="utf-8")
    for ts in ("20260801_000001", "20260802_000002"):
        (tmp_path / f"bar.py.bak.{ts}").write_text("b\n", encoding="utf-8")

    _cleanup_old_backups(str(target), keep=3)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "bar.py", "bar.py.bak.20260801_000001", "bar.py.bak.20260802_000002",
    ]
