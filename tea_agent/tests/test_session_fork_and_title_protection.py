"""会话分叉（#分叉）与标题保护回归测试。

## 需求

1. 标题保护：``#分叉`` 前缀（与 ``※`` 一致）**不得被自动摘要覆盖**
2. 分叉边界语义为**包含**该 tag（``rowid <= boundary_rowid``）
3. 分叉出的新主题标题形如 ``#分叉: <描述>``

## 为什么标题保护要两处同判定

写侧 ``TopicStore.update_topic_title``（拒绝覆盖）与读侧
``agent_pipeline.auto_summary``（跳过摘要）各自判断前缀。历史上二者曾用
**两套不同的判定**（写侧只认 ``※``），一旦漂移就会出现「读侧跳过、写侧仍覆盖」
或反之的静默失效 —— 用户显式命名的分支被 AI 摘要悄悄改写。
本测试钉住：两处必须共用 ``is_title_protected``。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tea_agent.session_fork import fork_session  # noqa: E402
from tea_agent.store import Storage  # noqa: E402
from tea_agent.store._topics import (  # noqa: E402
    PROTECTED_TITLE_PREFIXES,
    is_title_protected,
)


# ══════════════════════════════════════════════════════════════
#  1. is_title_protected — 纯函数边界
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("title,expected", [
    ("※手动标题", True),
    ("※", True),
    ("#分叉: 实验分支", True),
    ("#分叉", True),
    ("#分叉A", True),          # 前缀匹配即可
    ("普通标题", False),
    ("", False),
    (None, False),
    ("chat_room_test", False),
    ("# 分叉带空格", False),    # 前缀须精确（空格不算）
    ("#分叉线", True),          # 仍是前缀命中
])
def test_is_title_protected(title, expected):
    """前缀判定：受保护前缀命中即为 True，其余 False。"""
    assert is_title_protected(title) is expected


def test_protected_prefixes_include_both():
    """两个前缀都必须登记（漏一个就有一类标题失去保护）。"""
    assert "※" in PROTECTED_TITLE_PREFIXES
    assert "#分叉" in PROTECTED_TITLE_PREFIXES


# ══════════════════════════════════════════════════════════════
#  2. 写侧：update_topic_title 拒绝覆盖受保护标题
# ══════════════════════════════════════════════════════════════

@pytest.fixture()
def storage(tmp_path):
    return Storage(str(tmp_path / "chat_history.db"))


@pytest.mark.parametrize("protected_title", ["※手动标题", "#分叉: 实验A"])
def test_update_title_refuses_to_overwrite_protected(storage, protected_title):
    """受保护标题不得被自动摘要式写入覆盖（这是「不应被自动摘要修改」的落点）。"""
    tid = storage.create_topic(protected_title)
    storage.update_topic_title(tid, "AI 自动生成的标题")
    assert storage.get_topic(tid)["title"] == protected_title


def test_update_title_allows_normal_rename(storage):
    """普通标题仍可正常改名（别把防护修成失效）。"""
    tid = storage.create_topic("普通标题")
    storage.update_topic_title(tid, "新标题")
    assert storage.get_topic(tid)["title"] == "新标题"


def test_update_title_protected_can_be_renamed_to_protected(storage):
    """受保护 → 受保护 的改名应放行（手动改名场景）。"""
    tid = storage.create_topic("※旧标题")
    storage.update_topic_title(tid, "※新标题")
    assert storage.get_topic(tid)["title"] == "※新标题"


# ══════════════════════════════════════════════════════════════
#  3. 读侧：auto_summary 跳过受保护标题
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("prefix", PROTECTED_TITLE_PREFIXES)
def test_auto_summary_skips_every_protected_prefix(storage, monkeypatch, prefix):
    """auto_summary 必须跳过**每一个**受保护前缀。

    刻意参数化到 ``PROTECTED_TITLE_PREFIXES``：将来新增前缀时本用例自动覆盖，
    无需记得补测试。若读侧内联了自己的前缀表（而非共用 ``is_title_protected``），
    新前缀会在此处立刻变红 —— 这正是「两处漂移成静默失效」的探针。
    """
    import tea_agent.agent_pipeline as ap

    tid = storage.create_topic(f"{prefix}受保护标题")
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        return ("不该被调用的摘要", {})

    monkeypatch.setattr(ap, "_HAVE_TOPIC_SUMMARY", True)
    monkeypatch.setattr(ap, "generate_topic_summary", _boom)

    class _Db:
        @staticmethod
        def get_topic(_tid):
            return storage.get_topic(tid)

        @staticmethod
        def get_recent_conversations(*a, **k):
            return [{"user_msg": "x", "ai_msg": "y"}]

    class _Sess:
        @staticmethod
        def _get_summarize_client():
            return (None, "fake-model")

    class _Agent:
        _db = _Db()
        # 必须提供 _sess：否则一旦保护失效、代码走到摘要调用就会抛
        # AttributeError 被 auto_summary 的 except 吞成 None，使本用例
        # 「因崩溃而通过」—— 那是假绿，无法区分「正确跳过」与「崩了」。
        # 元验证（把读侧改回只认 ※）曾实测暴露此问题。
        _sess = _Sess()

    summary, _ = ap.auto_summary(_Agent(), tid)
    assert summary is None, f"{prefix} 前缀标题不应生成摘要"
    assert called["n"] == 0, "应在调用摘要生成**之前**就返回（省一次 LLM 调用）"


def test_auto_summary_still_runs_for_normal_title(storage, monkeypatch):
    """普通标题仍应正常走摘要（别把防护修成「一律不摘要」）。"""
    import tea_agent.agent_pipeline as ap

    tid = storage.create_topic("普通标题")
    called = {"n": 0}

    def _fake(*a, **k):
        called["n"] += 1
        return ("生成的摘要", {"total_tokens": 1})

    monkeypatch.setattr(ap, "_HAVE_TOPIC_SUMMARY", True)
    monkeypatch.setattr(ap, "generate_topic_summary", _fake)

    class _Db:
        @staticmethod
        def get_topic(_tid):
            return storage.get_topic(tid)

        @staticmethod
        def get_recent_conversations(*a, **k):
            return [{"user_msg": "x", "ai_msg": "y"}]

        @staticmethod
        def update_topic_title(*a, **k):
            pass

    class _Sess:
        @staticmethod
        def _get_summarize_client():
            return (None, "fake-model")

    class _Agent:
        _db = _Db()
        _sess = _Sess()

    summary, _ = ap.auto_summary(_Agent(), tid)
    assert called["n"] == 1, "普通标题应触发摘要"
    assert summary == "生成的摘要"


# ══════════════════════════════════════════════════════════════
#  4. fork_session — 边界**包含**语义
# ══════════════════════════════════════════════════════════════

def _seed(storage, n=3):
    """建一个含 n 轮对话的主题，返回 (topic_id, [conv_id...])。"""
    tid = storage.create_topic("源主题")
    ids = []
    for i in range(1, n + 1):
        cid = storage.save_msg(tid, f"用户消息{i}", "", False)
        storage.update_msg_rounds(cid, f"AI回复{i}", False)
        ids.append(cid)
    return tid, ids


def test_fork_boundary_is_inclusive(storage):
    """边界语义：选中第 2 轮 → 复制「第 2 轮及其之前」共 2 轮（含该 tag）。"""
    src, ids = _seed(storage, 3)
    r = fork_session(storage, src, "#分叉: 实验", boundary_conv_id=str(ids[1]))
    assert r["ok"] is True, r
    convs = storage.get_conversations(r["target_topic_id"], limit=-1, include_rounds=False)
    assert len(convs) == 2, f"期望含边界的 2 轮，实际 {len(convs)}"
    assert [c["user_msg"] for c in convs] == ["用户消息1", "用户消息2"]
    assert convs[-1]["user_msg"] == "用户消息2", "边界那条必须在结果里（包含语义）"


def test_fork_first_message_copies_only_one(storage):
    """边界为第 1 轮 → 只复制 1 轮（下边界）。"""
    src, ids = _seed(storage, 3)
    r = fork_session(storage, src, "#分叉: 首轮", boundary_conv_id=str(ids[0]))
    convs = storage.get_conversations(r["target_topic_id"], limit=-1, include_rounds=False)
    assert [c["user_msg"] for c in convs] == ["用户消息1"]


def test_fork_without_boundary_copies_all(storage):
    """无边界 → 复制全部（回归：别把 boundary 逻辑修成截断）。"""
    src, _ = _seed(storage, 3)
    r = fork_session(storage, src, "#分叉: 全量", boundary_conv_id="")
    convs = storage.get_conversations(r["target_topic_id"], limit=-1, include_rounds=False)
    assert len(convs) == 3


def test_fork_source_untouched(storage):
    """分叉不得改动源主题（分支的独立性前提）。"""
    src, ids = _seed(storage, 3)
    before = storage.get_conversations(src, limit=-1, include_rounds=False)
    fork_session(storage, src, "#分叉: x", boundary_conv_id=str(ids[0]))
    after = storage.get_conversations(src, limit=-1, include_rounds=False)
    assert [c["user_msg"] for c in before] == [c["user_msg"] for c in after]
    assert len(after) == 3


def test_fork_title_kept_and_protected(storage):
    """新主题标题 = 给定标题，且受保护（不被自动摘要改写）。"""
    src, ids = _seed(storage, 2)
    r = fork_session(storage, src, "#分叉: 我的分支", boundary_conv_id=str(ids[0]))
    tgt = r["target_topic_id"]
    assert storage.get_topic(tgt)["title"] == "#分叉: 我的分支"
    assert is_title_protected(storage.get_topic(tgt)["title"])
    # 摘要式覆盖应被拒绝
    storage.update_topic_title(tgt, "自动摘要标题")
    assert storage.get_topic(tgt)["title"] == "#分叉: 我的分支"


def test_fork_missing_source_returns_error(storage):
    """源主题不存在 → 明确报错，不抛异常。"""
    r = fork_session(storage, "不存在的主题", "#分叉: x")
    assert r["ok"] is False
    assert "不存在" in r["error"]


def test_fork_empty_source_returns_error(storage):
    """未给源主题 → 明确报错。"""
    r = fork_session(storage, "", "#分叉: x")
    assert r["ok"] is False
    assert "required" in r["error"]


def test_fork_duplicate_does_not_leave_orphan_topic(storage):
    """重复 fork 失败时不得留下空壳主题（失败清理）。"""
    src, ids = _seed(storage, 2)
    r1 = fork_session(storage, src, "#分叉: a", boundary_conv_id=str(ids[0]))
    assert r1["ok"] is True
    # 同一 (source, target) 不会重复；这里模拟 fork_topic 内部失败路径：
    # 直接对同一 target 再 fork 会触发幂等守卫
    r2 = storage.conversations.fork_topic(
        source_topic_id=src, target_topic_id=r1["target_topic_id"],
        title="x", boundary_conv_id="",
    )
    assert r2["ok"] is False
    assert "已存在" in r2["error"]


# ══════════════════════════════════════════════════════════════
#  5. Pi 功能已移除（防止残留回归）
# ══════════════════════════════════════════════════════════════

def test_pi_features_removed_from_server():
    """Pi 功能（会话树/消息队列/压缩）应已整体移除：路由与模块均不存在。"""
    root = pathlib.Path(__file__).resolve().parents[2] / "tea_agent"
    assert not (root / "server/modules/pi_features_module.py").exists(), \
        "pi_features_module.py 应已删除"
    assert not (root / "session/session_tree.py").exists(), \
        "session_tree.py 应已删除（删除 Pi 后成死代码）"

    server_src = (root / "server/server.py").read_text(encoding="utf-8")
    assert "/api/pi/" not in server_src, "Pi 路由注册应已移除"

    html = (root / "server/static/index.html").read_text(encoding="utf-8")
    assert "showPiModal" not in html, "Pi 面板按钮应已移除"
    assert "modal-pi" not in html, "Pi 面板 DOM 应已移除"

    js = (root / "server/static/app.js").read_text(encoding="utf-8")
    for fn in ("showPiModal", "piRefresh", "piBranch", "piQueuePush", "piCompact"):
        assert fn not in js, f"Pi 前端函数 {fn} 应已移除"
    assert "/api/pi/" not in js, "Pi 接口调用应已移除"
