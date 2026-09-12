"""会话与工具必须共用同一个数据库（记忆可靠性的前提）。

背景（真实缺陷，由「删除记忆后仍被持续注入」暴露）：
`Agent._init_storage` 用 `cfg.paths.db_path_abs`（用户级回退层），而
`store.get_storage()`（toolkit_memory 等工具走它）用 `cfg.paths.active_db_path_abs`
（项目级）。在默认配置 + 项目目录下二者**路径不同** → 会话与工具打开两个数据库：
工具删除记忆「报告成功」，会话侧却仍从自己的库读到该记忆并每轮注入 —— 记忆不可靠，
且每轮白烧 token（实测删除后注入持续 5+ 轮）。

`active_db_path_abs` 的 docstring 已声明「Agent._init_storage / store.get_storage
使用此属性」，故本测试同时锁定该契约。
"""

from __future__ import annotations

import os
from pathlib import Path

from tea_agent.config import get_config
from tea_agent.store import get_storage


def test_agent_storage_uses_active_db_path(tmp_path, monkeypatch):
    """Agent._init_storage 必须与 store.get_storage() 指向同一 db。

    显式 data_dir（隔离，不碰用户真实数据）时 active == user，二者本应一致；
    关键是要断言「Agent 取的是 active 语义」，而非各自解析出不同路径。
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    cfg = get_config()
    active = getattr(cfg.paths, "active_db_path_abs", "")
    user = cfg.paths.db_path_abs
    assert active, "active_db_path_abs 不应为空"

    # 显式 data_dir 下 active 应回落到 user 层（尊重用户配置，不自动项目化）
    src = Path("tea_agent/agent.py").read_text(encoding="utf-8")
    seg = src.split("def _init_storage", 1)[1].split("def ", 1)[0]
    assert "active_db_path_abs" in seg, (
        "Agent._init_storage 必须使用 active_db_path_abs（否则与 get_storage 分叉）"
    )


def test_get_storage_matches_active_db_path():
    """get_storage() 打开的就是 active_db_path_abs（工具与配置一致）。"""
    cfg = get_config()
    st = get_storage()
    opened = os.path.abspath(str(getattr(st, "db_path", "")))
    active = os.path.abspath(str(cfg.paths.active_db_path_abs))
    assert opened == active, f"get_storage 打开 {opened!r}，配置 active={active!r}"
