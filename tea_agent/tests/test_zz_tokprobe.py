"""临时探针：tokens 用量准确性 + 上溢防护 的运行时实证（用后删除）。

用户要求「准确判断 tokens 用量，防止上溢，不浪费 tokens」。既有测试
（test_overflow_guard 24/24、test_context_fill_rules 22/22）覆盖了**裁剪逻辑**，
但未验证**计数本身是否准确**——而计数错了裁剪就会错（这正是本会话反复出现的
「静默失真」形态）。本探针只测两件事：

A. 用量记账往返：add/get 各字段、累加语义、pending 清零
B. 估算器形式合理性：单调、边界（空/超长/多模态/emoji）不崩且量级可信
"""

import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_token_accounting_and_estimator():
    from tea_agent.session.history_builder import estimate_messages_tokens, estimate_tokens
    from tea_agent.store import Storage

    out: dict = {}

    # ── B. 估算器 ──
    empty = estimate_tokens("")
    ascii_t = estimate_tokens("hello world " * 100)          # 1200 chars
    cjk_t = estimate_tokens("你好世界" * 100)                 # 400 chars
    out["estimator"] = {
        "empty": empty,
        "ascii_1200ch": ascii_t,
        "cjk_400ch": cjk_t,
        # 中文每字符信息量高 → 同等字符数下不应低于 ASCII
        "cjk_per_char_gte_ascii": (cjk_t / 400) >= (ascii_t / 1200) * 0.9,
        "monotonic": estimate_tokens("abc" * 500) > estimate_tokens("abc" * 100),
    }
    out["multimodal_msg"] = estimate_messages_tokens([
        {"role": "user", "content": [{"type": "text", "text": "看图"},
                                     {"type": "image_url", "image_url": {"url": "x"}}]},
    ])
    out["tool_calls_msg"] = estimate_messages_tokens([
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "f", "arguments": "{}"}}]},
    ])
    out["reasoning_msg"] = estimate_messages_tokens([
        {"role": "assistant", "content": "a", "reasoning_content": "想" * 300},
    ])

    # ── A. 记账往返 ──
    db = Storage(str(Path(tempfile.mkdtemp()) / "probe.db"))
    tid = db.create_topic("probe")
    db.add_topic_tokens(tid, total_tokens=100, prompt_tokens=60, completion_tokens=40,
                        cheap_tokens=10, cheap_prompt_tokens=5, cheap_completion_tokens=5,
                        embedding_tokens=3)
    g1 = db.get_topic_tokens(tid)
    db.add_topic_tokens(tid, total_tokens=50, prompt_tokens=30, completion_tokens=20)
    g2 = db.get_topic_tokens(tid)
    out["accounting"] = {
        "after_first": {k: g1.get(k) for k in
                        ("total_tokens", "prompt_tokens", "completion_tokens",
                         "cheap_tokens", "embedding_tokens") if k in g1},
        "after_second": {k: g2.get(k) for k in
                         ("total_tokens", "prompt_tokens", "completion_tokens") if k in g2},
        "accumulates": (g2.get("total_tokens") == 150 and g2.get("prompt_tokens") == 90),
        "all_fields_keys": sorted(g1.keys()),
    }

    db.accumulate_pending_cheap_tokens(tid, {"total_tokens": 7})
    db.accumulate_pending_cheap_tokens(tid, {"total_tokens": 5})
    p1 = db.get_and_clear_pending_cheap_tokens(tid)
    p2 = db.get_and_clear_pending_cheap_tokens(tid)
    out["pending_cheap"] = {"accumulated": p1, "cleared_second": p2}

    (ROOT / "_tokens_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    raise AssertionError(json.dumps(out, ensure_ascii=False, default=str)[:1500])
