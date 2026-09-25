"""导出轮次取数的回归测试。

缺陷背景（2026-09-25 实测）：导出（md/pdf）在 ``filter=full`` 下从
``conversations.rounds_json`` 直读轮次，但该列**已废弃**（与 agent_rounds
重复存储，新会话只写 agent_rounds）→ 该列停写之后的对话导出时
**静默丢失全部工具调用与思考链**。

实测影响面：126 个对话中 22 个（分界 2026-09-23 21:01），单个最多 369 轮。

修复：``_load_rounds_map`` —— legacy rounds_json 优先（向后兼容），缺失则从
``agent_rounds``（唯一事实源）派生。
"""

import json
import sqlite3

from tea_agent.toolkit.toolkit_export_last_pdf import _load_rounds_map


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE conversations (id TEXT, rounds_json TEXT)")
    c.execute(
        "CREATE TABLE agent_rounds (id INTEGER PRIMARY KEY, conversation_id TEXT, "
        "round_num INTEGER, role TEXT, content TEXT, tool_calls TEXT, "
        "tool_call_id TEXT, reasoning_content TEXT, deleted_at TEXT)"
    )
    return c


def _add_conversation(c, cid, rounds_json=None):
    c.execute("INSERT INTO conversations VALUES (?, ?)", (cid, rounds_json))


def _add_round(c, cid, n, role, content="", tool_calls=None, rc=None, deleted=False):
    c.execute(
        "INSERT INTO agent_rounds (conversation_id, round_num, role, content, "
        "tool_calls, tool_call_id, reasoning_content, deleted_at) VALUES (?,?,?,?,?,?,?,?)",
        (cid, n, role, content, tool_calls, None, rc, "2026-01-01" if deleted else None),
    )


def test_prefers_legacy_rounds_json():
    """legacy rounds_json 有值 → 用它（向后兼容，行为不变）。"""
    c = _conn()
    legacy = [{"role": "assistant", "content": "legacy"}]
    _add_conversation(c, "c1", json.dumps(legacy))
    _add_round(c, "c1", 0, "assistant", content="from_agent_rounds")

    got = _load_rounds_map(c, c.execute("SELECT * FROM conversations").fetchall())
    assert got["c1"] == legacy, "legacy rounds_json 应优先"


def test_falls_back_to_agent_rounds():
    """rounds_json 为空（废弃列停写）→ 从 agent_rounds 派生。

    这条是缺陷本体：修复前返回 [] → 导出丢光工具轮。
    """
    c = _conn()
    _add_conversation(c, "c2", None)  # 新会话：该列为空
    _add_round(c, "c2", 0, "assistant", content="thinking out loud",
               tool_calls=json.dumps([{"id": "t1", "type": "function",
                                       "function": {"name": "toolkit_exec"}}]),
               rc="推理内容")
    _add_round(c, "c2", 1, "tool", content="tool output")

    got = _load_rounds_map(c, c.execute("SELECT * FROM conversations").fetchall())
    rounds = got["c2"]
    assert len(rounds) == 2, f"应从 agent_rounds 取到 2 轮，实际 {len(rounds)}"
    assert rounds[0]["tool_calls"][0]["function"]["name"] == "toolkit_exec", "工具调用必须保留"
    assert rounds[0]["reasoning_content"] == "推理内容", "思考链必须保留"
    assert rounds[1]["role"] == "tool"


def test_deleted_rounds_excluded():
    """已标记删除的轮次不导出（append-only：行在库中但带 deleted_at）。"""
    c = _conn()
    _add_conversation(c, "c3", None)
    _add_round(c, "c3", 0, "assistant", content="keep")
    _add_round(c, "c3", 1, "assistant", content="gone", deleted=True)

    rounds = _load_rounds_map(c, c.execute("SELECT * FROM conversations").fetchall())["c3"]
    assert [r["content"] for r in rounds] == ["keep"]


def test_rounds_ordered_by_round_num():
    """轮次顺序按 round_num（乱序插入也要还原顺序）。"""
    c = _conn()
    _add_conversation(c, "c4", None)
    for n in (2, 0, 1):
        _add_round(c, "c4", n, "assistant", content=f"r{n}")

    rounds = _load_rounds_map(c, c.execute("SELECT * FROM conversations").fetchall())["c4"]
    assert [r["content"] for r in rounds] == ["r0", "r1", "r2"]


def test_broken_json_does_not_raise():
    """损坏的 rounds_json → 降级走 agent_rounds，不抛异常。"""
    c = _conn()
    _add_conversation(c, "c5", "{not valid json")
    _add_round(c, "c5", 0, "assistant", content="fallback")

    rounds = _load_rounds_map(c, c.execute("SELECT * FROM conversations").fetchall())["c5"]
    assert [r["content"] for r in rounds] == ["fallback"]


def test_empty_input():
    """空输入不抛异常。"""
    c = _conn()
    assert _load_rounds_map(c, []) == {}


def test_export_source_reads_agent_rounds_not_rounds_json():
    """导出实现不得再直读 conversations.rounds_json（防回归）。"""
    import ast
    import pathlib

    p = pathlib.Path("tea_agent/toolkit/toolkit_export_last_pdf.py")
    src = p.read_text(encoding="utf-8")
    hits = [
        (n.lineno, ast.unparse(n))
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Subscript) and "rounds_json" in ast.unparse(n)
    ]
    # 只允许出现在 _load_rounds_map 内部（helper 自身负责兼容 legacy）
    tree = ast.parse(src)
    helper = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_load_rounds_map")
    lo, hi = helper.lineno, (helper.end_lineno or helper.lineno)
    outside = [(ln, s) for ln, s in hits if not (lo <= ln <= hi)]
    assert not outside, f"导出实现仍在直读 rounds_json: {outside}"
