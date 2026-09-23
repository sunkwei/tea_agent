"""storage_scope 项目级 db 与临时目录回退的回归测试。

## 需求（本次变更）

1. 默认用**启动目录** ``.tea_agent_run/chat_history.db``（随项目隔离）
2. 启动目录不可写（无权限 / 无磁盘空间 / 只读）→ 回退**系统临时目录**
3. 使用临时目录时，每轮会话结束**明确提示** db 路径并要求手动复制

## 为什么提示必须走 callback 而不并入 full_reply

``server/modules/agent_module._save_chat_result`` 用 ``ai_msg``（= chat_stream
的**返回值**）写库：

    ai_msg, used_tools = session.chat_stream(...)
    cls._save_chat_result(storage, session, topic_id, msg, _effective_ai_msg, ...)

若把提示拼进 ``full_reply``，它会**被持久化进对话历史**，每轮追加 → 污染
上下文、挤占 token，且下次读历史时模型会看到自己"说过"这段运维提示。
故提示经 ``callback`` 发出（只到 UI），并用 ``test_notice_not_concatenated_into_reply``
钉住该契约。
"""

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, ".")
from tea_agent import storage_scope as ss  # noqa: E402


@pytest.fixture()
def proj(tmp_path):
    d = tmp_path / "myproj"
    d.mkdir()
    return d


@pytest.fixture()
def user_db(tmp_path):
    return str(tmp_path / "home" / ".tea_agent" / ss.DEFAULT_DB_NAME)


# ─────────────────────── 命名 ───────────────────────

def test_default_db_name_is_chat_history_db():
    """默认 db 名固定 chat_history.db（沿用历史名，不做改名迁移）。"""
    assert ss.DEFAULT_DB_NAME == "chat_history.db"
    # 迁移代码已删除：不应再有 LEGACY_DB_NAME / _migrate_legacy_db
    assert not hasattr(ss, "LEGACY_DB_NAME"), "迁移代码应已移除"
    assert not hasattr(ss, "_migrate_legacy_db"), "迁移代码应已移除"


# ─────────────────────── 项目级（默认） ───────────────────────

def test_project_writable_uses_tea_agent_run(proj, user_db, monkeypatch):
    """启动目录可写 → <项目>/.tea_agent_run/chat_history.db。"""
    run = proj / ss.PROJECT_RUN_DIR
    run.mkdir()
    monkeypatch.setattr(ss, "project_run_dir", lambda cwd=None: str(run))

    got = ss.resolve_db_path(user_db_abs=user_db, cwd=str(proj))

    assert got == str(run / ss.DEFAULT_DB_NAME)
    assert os.path.basename(got) == ss.DEFAULT_DB_NAME
    assert not ss.is_temp_fallback(got)
    assert ss.storage_notice(got) is None, "项目级不应提示"


def test_custom_relative_db_name_respected(proj, monkeypatch):
    """用户配了相对 db_path → 沿用其自定义名（仅换目录）。"""
    run = proj / ss.PROJECT_RUN_DIR
    run.mkdir()
    monkeypatch.setattr(ss, "project_run_dir", lambda cwd=None: str(run))

    got = ss.resolve_db_path(
        user_db_abs=str(proj / "custom.db"), cwd=str(proj)
    )
    assert os.path.basename(got) == "custom.db"


def test_explicit_absolute_db_path_respected(proj, tmp_path, monkeypatch):
    """显式绝对 db_path → 尊重用户位置，不项目化。"""
    abs_db = str(tmp_path / "elsewhere" / "mine.db")
    monkeypatch.setattr(ss, "project_run_dir", lambda cwd=None: str(proj / "run"))

    got = ss.resolve_db_path(
        user_db_abs=abs_db, db_path_cfg=abs_db, cwd=str(proj)
    )
    assert got == abs_db


def test_scope_user_forces_user_level(proj, user_db, monkeypatch):
    """显式 scope=user → 用户级（durable，不提示）。"""
    monkeypatch.setattr(ss, "project_run_dir", lambda cwd=None: str(proj / "run"))

    got = ss.resolve_db_path(
        user_db_abs=user_db, cwd=str(proj), storage_scope_cfg="user"
    )
    assert got == user_db
    assert ss.storage_notice(got) is None


def test_home_dir_uses_user_level(user_db, monkeypatch):
    """启动目录 == 主目录 → 用户级（主目录即项目，不另建 .tea_agent_run）。"""
    home = os.path.expanduser("~")
    monkeypatch.setattr(ss, "project_run_dir", lambda cwd=None: None)

    got = ss.resolve_db_path(user_db_abs=user_db, cwd=home)
    assert got == user_db
    assert ss.storage_notice(got) is None, "主目录不算临时回退"


# ─────────────────────── 临时目录回退 ───────────────────────

def test_temp_fallback_when_project_unwritable(proj, user_db, tmp_path, monkeypatch):
    """项目目录不可用 → 回退系统临时目录（确定性注入，不依赖 chmod）。"""
    monkeypatch.setattr(ss, "project_run_dir", lambda cwd=None: None)
    monkeypatch.setattr(ss.tempfile, "gettempdir", lambda: str(tmp_path))

    got = ss.resolve_db_path(user_db_abs=user_db, cwd=str(proj))

    assert ss.is_temp_fallback(got), f"应回退临时目录，实际 {got}"
    assert got.startswith(str(tmp_path))
    assert os.path.basename(got).startswith("tea_agent_")
    assert os.path.basename(got).endswith(".db")


def test_temp_db_path_stable_per_project(proj, tmp_path, monkeypatch):
    """同一项目多次解析应得到同一临时库（保证会话连续性）。"""
    monkeypatch.setattr(ss.tempfile, "gettempdir", lambda: str(tmp_path))
    assert ss.temp_db_path(str(proj)) == ss.temp_db_path(str(proj))


def test_temp_db_path_differs_across_projects(tmp_path, monkeypatch):
    """不同项目应得到不同临时库（避免互相串数据）。"""
    monkeypatch.setattr(ss.tempfile, "gettempdir", lambda: str(tmp_path))
    a = tmp_path / "projA"
    b = tmp_path / "projB"
    a.mkdir()
    b.mkdir()
    assert ss.temp_db_path(str(a)) != ss.temp_db_path(str(b))


def test_is_temp_fallback_rejects_non_temp(tmp_path, proj):
    """项目内路径、用户级路径都不得被误判为临时回退。"""
    assert not ss.is_temp_fallback(str(proj / ss.PROJECT_RUN_DIR / ss.DEFAULT_DB_NAME))
    assert not ss.is_temp_fallback("")
    assert not ss.is_temp_fallback(str(tmp_path / "chat_history.db"))


# ─────────────────────── 提示内容 ───────────────────────

def test_storage_notice_contains_path_and_copy_instruction(tmp_path, monkeypatch):
    """提示必须含**具体路径**与「手动复制」要求 —— 这是需求原文。"""
    monkeypatch.setattr(ss.tempfile, "gettempdir", lambda: str(tmp_path))
    db = ss.temp_db_path(str(tmp_path / "p"))

    notice = ss.storage_notice(db)

    assert notice, "临时回退必须提示"
    assert db in notice, "必须给出具体 db 路径"
    assert "复制" in notice, "必须要求手动复制"
    assert "临时" in notice


def test_storage_notice_none_for_project_db(proj, user_db, monkeypatch):
    """非临时回退一律不提示（避免噪音）。"""
    run = proj / ss.PROJECT_RUN_DIR
    monkeypatch.setattr(ss, "project_run_dir", lambda cwd=None: str(run))
    got = ss.resolve_db_path(user_db_abs=user_db, cwd=str(proj))
    assert ss.storage_notice(got) is None


# ─────────────────────── 提示接线（关键契约） ───────────────────────

class _FakeStorage:
    def __init__(self, db_path):
        self.db_path = db_path


def _make_session(db_path):
    """构造**真实** OnlineToolSession 实例（绕过重量级 __init__）。

    为什么不用替身类：``_emit_storage_notice`` / ``_finalize_turn_reply`` 会调用
    ``self._emit_storage_notice``，替身若没实现该方法会直接 AttributeError ——
    那样测到的是替身缺陷而非真实逻辑。用 ``__new__`` 拿到真实例、只注入
    ``storage``，保证被测的是产品代码本身。
    """
    from tea_agent.onlinesession import OnlineToolSession

    sess = OnlineToolSession.__new__(OnlineToolSession)
    sess.storage = _FakeStorage(db_path)
    return sess


def _emit(db_path, monkeypatch=None):
    """调用 _emit_storage_notice，返回其收到的 callback 内容。"""
    got = []
    _make_session(db_path)._emit_storage_notice(got.append)
    return got


def test_emit_notice_sent_for_temp_db(tmp_path, monkeypatch):
    """临时回退 → 提示经 callback 送达用户。"""
    monkeypatch.setattr(ss.tempfile, "gettempdir", lambda: str(tmp_path))
    db = ss.temp_db_path(str(tmp_path / "p"))

    got = _emit(db, monkeypatch)

    assert len(got) == 1, "临时回退应恰好提示一次"
    assert db in got[0]
    assert "复制" in got[0]


def test_emit_notice_silent_for_project_db(proj):
    """项目级 db → 不打扰用户。"""
    assert _emit(str(proj / ss.PROJECT_RUN_DIR / ss.DEFAULT_DB_NAME), None) == []


def test_emit_notice_never_raises(monkeypatch):
    """旁路不得把主流程带崩：storage 异常也要静默。"""

    class _Boom:
        @property
        def db_path(self):
            raise RuntimeError("boom")

    from tea_agent.onlinesession import OnlineToolSession

    OnlineToolSession._emit_storage_notice(
        type("S", (), {"storage": _Boom()})(), lambda t: None
    )  # 不抛异常即通过


def test_finalize_turn_reply_does_not_append_notice(tmp_path, monkeypatch):
    """**关键契约（动态）**：收尾方法对 full_reply 只读不写。

    提示必须经 callback 直达 UI；一旦拼进返回值，就会被 server 持久化进
    对话历史（``agent_module._save_chat_result`` 的 ``ai_msg``），每轮往历史
    写一段运维提示 → 污染上下文、挤占 token。

    为什么用**动态**断言而非静态 AST 检查：早前版本只扫描
    ``_emit_storage_notice`` 的函数体，而真实错误写法是在**调用点**拼接
    （``full_reply += "".join(notices)``），静态检查完全抓不住 —— 元验证
    已证实那是假绿守卫。动态断言「返回值 == 入参」无法被绕过。
    """
    monkeypatch.setattr(ss.tempfile, "gettempdir", lambda: str(tmp_path))
    db = ss.temp_db_path(str(tmp_path / "p"))
    from tea_agent.onlinesession import OnlineToolSession

    got = []
    reply, tools = OnlineToolSession._finalize_turn_reply(
        _make_session(db), "原始回复正文", True, got.append
    )

    assert reply == "原始回复正文", "提示不得混入回复（会入库污染历史）"
    assert tools is True, "返回值不得改变 used_tools"
    assert got, "临时回退应经 callback 提示用户"
    assert db in got[0] and "复制" in got[0], "提示须含路径与复制要求"


def test_finalize_turn_reply_silent_for_project_db(proj):
    """项目级 db → 收尾不打扰用户，且回复原样返回。"""
    from tea_agent.onlinesession import OnlineToolSession

    got = []
    reply, _ = OnlineToolSession._finalize_turn_reply(
        _make_session(str(proj / ss.PROJECT_RUN_DIR / ss.DEFAULT_DB_NAME)),
        "正文", False, got.append,
    )
    assert reply == "正文"
    assert got == []


def test_finalize_turn_reply_never_raises():
    """旁路不得把主流程带崩：storage 异常也要静默且照常返回回复。"""

    class _Boom:
        @property
        def db_path(self):
            raise RuntimeError("boom")

    from tea_agent.onlinesession import OnlineToolSession

    reply, tools = OnlineToolSession._finalize_turn_reply(
        _make_session(""), "正文", True, lambda t: None
    )
    assert reply == "正文" and tools is True


def test_chat_stream_delegates_to_finalize():
    """chat_stream 必须经 _finalize_turn_reply 收尾（否则提示永远不会发出）。"""
    tree = ast.parse(pathlib.Path("tea_agent/onlinesession.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "chat_stream"
    )
    calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_finalize_turn_reply"
    ]
    assert calls, "chat_stream 未委派 _finalize_turn_reply → 用户看不到存储提示"
    # 必须在最后一个 return 处返回其结果（而非自行拼接）
    rets = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    assert any(
        isinstance(r.value, ast.Call)
        and getattr(r.value.func, "attr", "") == "_finalize_turn_reply"
        for r in rets
    ), "chat_stream 应直接 return _finalize_turn_reply(...)"
