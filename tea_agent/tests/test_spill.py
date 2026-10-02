"""spill 大输出落盘引用化回归测试。

契约：大输出不得整体进上下文（落盘 + 头尾摘要），小输出原样透传；
落盘失败回退截断，绝不影响主调用。
"""

from __future__ import annotations

import os

from tea_agent import spill


def test_small_text_passes_through():
    r = spill.spill_text("hello", threshold=100)
    assert r == {"spilled": False, "truncated": False, "locator": "",
                 "chars": 5, "preview": "hello"}


def test_big_text_spills_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(spill, "_spill_dir", lambda: str(tmp_path))
    text = "A" * 5000 + "MID" + "B" * 5000
    r = spill.spill_text(text, source="test", threshold=1000)
    assert r["spilled"] is True
    assert os.path.isfile(r["locator"])
    with open(r["locator"], encoding="utf-8") as f:
        assert f.read() == text
    assert "已落盘" in r["preview"]
    assert len(r["preview"]) < len(text)


def test_fallback_truncates_without_dir(monkeypatch):
    monkeypatch.setattr(spill, "_spill_dir", lambda: None)
    text = "x" * 20000
    r = spill.spill_text(text, threshold=1000)
    assert r["spilled"] is False and r["truncated"] is True
    assert r["locator"] == ""
    assert "已截断" in r["preview"]


def test_write_failure_falls_back_to_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(spill, "_spill_dir", lambda: str(tmp_path))
    monkeypatch.setattr(spill, "open", None, raising=False)  # 写路径崩 → 回退
    r = spill.spill_text("y" * 5000, threshold=100)
    assert r["spilled"] is False and r["truncated"] is True


def test_maybe_spill_convenience():
    assert spill.maybe_spill("small", threshold=100) == "small"


def test_env_threshold(monkeypatch):
    monkeypatch.setenv("TEA_SPILL_THRESHOLD", "42")
    assert spill.spill_threshold() == 42
    monkeypatch.setenv("TEA_SPILL_THRESHOLD", "bad")
    assert spill.spill_threshold() == spill.DEFAULT_THRESHOLD


def test_toolkit_exec_wiring_big_output():
    """端到端：toolkit_exec 大输出被引用化（不整体进上下文）。"""
    from tea_agent.toolkit.toolkit_exec import toolkit_exec

    r = toolkit_exec(app="python", args=["-c", "print('Z'*200000)"])
    out = r["stdout"]
    assert len(out) < 10000, f"大输出未被引用化: {len(out)} 字符"
    assert "落盘" in out or "截断" in out
