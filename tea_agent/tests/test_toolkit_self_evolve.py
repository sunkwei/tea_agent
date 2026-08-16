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


def test_cleanup_removes_old_timestamped_backups():
    """_cleanup_old_backups 保留最近 keep 份，删除更早的时间戳备份。"""
    import os
    import shutil
    from tea_agent.toolkit.toolkit_self_evolve import _cleanup_old_backups

    d = "cleabt_test"
    os.makedirs(d, exist_ok=True)
    try:
        target = os.path.join(d, "foo.py")
        open(target, "w", encoding="utf-8").write("x = 1\n")
        # 创建 5 个时间戳备份，时间戳字典序=新序
        for ts in ("20260801_000001", "20260802_000002", "20260803_000003",
                   "20260804_000004", "20260805_000005"):
            open(os.path.join(d, f"foo.py.bak.{ts}"), "w", encoding="utf-8").write("backup\n")
        # 无关备份必须保留（不误删手工命名）
        unrelated = os.path.join(d, "foo.py.manual_bak")
        open(unrelated, "w", encoding="utf-8").write("keep\n")

        _cleanup_old_backups(target, keep=3)

        remaining = sorted(n for n in os.listdir(d) if "foo.py.bak." in n)
        assert remaining == [
            "foo.py.bak.20260803_000003",
            "foo.py.bak.20260804_000004",
            "foo.py.bak.20260805_000005",
        ]
        assert os.path.exists(unrelated)  # 无关备份不受影响
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_cleanup_noop_below_threshold():
    """备份数不超过 keep 时不删除任何文件。"""
    import os
    import shutil
    from tea_agent.toolkit.toolkit_self_evolve import _cleanup_old_backups

    d = "cleabt2_test"
    os.makedirs(d, exist_ok=True)
    try:
        target = os.path.join(d, "bar.py")
        open(target, "w", encoding="utf-8").write("x = 1\n")
        for ts in ("20260801_000001", "20260802_000002"):
            open(os.path.join(d, f"bar.py.bak.{ts}"), "w", encoding="utf-8").write("b\n")

        _cleanup_old_backups(target, keep=3)
        assert sorted(n for n in os.listdir(d) if n.startswith("bar.py")) == [
            "bar.py", "bar.py.bak.20260801_000001", "bar.py.bak.20260802_000002",
        ]
    finally:
        shutil.rmtree(d, ignore_errors=True)
