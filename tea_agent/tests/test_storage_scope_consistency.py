"""会话与工具必须共用同一个数据库（记忆可靠性的前提）。

背景（真实缺陷，由「删除记忆后仍被持续注入」暴露）：
`Agent._init_storage` 用 `cfg.paths.db_path_abs`（用户级回退层），而
`store.get_storage()`（toolkit_memory 等工具走它）用 `cfg.paths.active_db_path_abs`
（项目级）。在默认配置 + 项目目录下二者**路径不同** → 会话与工具打开两个数据库：
工具删除记忆「报告成功」，会话侧却仍从自己的库读到该记忆并每轮注入 —— 记忆不可靠，
且每轮白烧 token（实测删除后注入持续 6+ 轮不停）。

`active_db_path_abs` 的 docstring 已声明「Agent._init_storage / store.get_storage
使用此属性」，故本测试同时锁定该契约。
"""

from __future__ import annotations

import os
from pathlib import Path

from tea_agent.storage_scope import PROJECT_RUN_DIR, resolve_db_path

_ROOT = Path(__file__).resolve().parents[2]


def test_init_storage_uses_active_db_path_contract():
    """契约：Agent._init_storage 必须取 active_db_path_abs（而非 db_path_abs）。

    二者在默认配置 + 项目目录下不同；用错就会与 get_storage() 分叉成两个库。
    """
    seg = (_ROOT / "tea_agent" / "agent.py").read_text(encoding="utf-8").split(
        "def _init_storage", 1)[1].split("\n    def ", 1)[0]
    assert "active_db_path_abs" in seg, (
        "Agent._init_storage 必须使用 active_db_path_abs —— 否则会话与 "
        "store.get_storage()（记忆工具）会打开两个数据库，删除记忆看似成功实则无效"
    )


def test_default_scope_resolves_to_project_run_dir(tmp_path):
    """默认配置 + 普通项目目录 → active 落到 <cwd>/.tea_agent_run/（与用户级不同）。

    这正是分叉发生的条件：若无此差异，会话与工具本不会错开。
    """
    user_db = str(tmp_path / "home" / ".tea_agent" / "chat_history.db")
    active = resolve_db_path(
        user_db_abs=user_db, db_path_cfg="", cwd=str(tmp_path),
        storage_scope_cfg="auto",
    )
    assert os.path.dirname(active).endswith(PROJECT_RUN_DIR), active
    assert os.path.basename(active) == "chat_history.db"
    assert os.path.abspath(active) != os.path.abspath(user_db)


def test_user_scope_keeps_single_db(tmp_path):
    """storage_scope=user → active == 用户级（旧行为），此配置下本无分叉。"""
    user_db = str(tmp_path / "home" / ".tea_agent" / "chat_history.db")
    active = resolve_db_path(
        user_db_abs=user_db, db_path_cfg="", cwd=str(tmp_path),
        storage_scope_cfg="user",
    )
    assert os.path.abspath(active) == os.path.abspath(user_db)


def test_explicit_absolute_db_path_is_respected(tmp_path):
    """显式绝对 db_path → 尊重用户指定位置（不自动项目化）。"""
    user_db = str(tmp_path / "home" / ".tea_agent" / "chat_history.db")
    abs_cfg = str(tmp_path / "custom" / "my.db")
    active = resolve_db_path(
        user_db_abs=abs_cfg, db_path_cfg=abs_cfg, cwd=str(tmp_path),
        storage_scope_cfg="auto",
    )
    assert os.path.abspath(active) == os.path.abspath(abs_cfg)
