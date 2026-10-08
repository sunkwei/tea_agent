"""回归测试：代码类工具回放不受 2K 截断 + 截断修复标记送达。

对应两处缺陷修复：
1. `_compress_tool_rounds` 此前对所有工具参数按 2048B/1024B 截断，
   代码类工具（toolkit_file/edit/...）的历史参数被砍成首尾残片。
2. `try_fix_truncated_json` 修复截断 JSON 后静默执行，尾部缺失的
   文件内容被不完整地写入，只能靠读回才发现。
"""

import json

from tea_agent.basesession import (
    BaseChatSession,
    _args_compress_threshold,
    _args_keep_bytes,
    relaxed_json_loads,
)
from tea_agent.session.json_sanitizer import (
    TRUNCATION_FIX_KEY,
    normalize_tool_args,
    pop_truncation_fix,
)

# ── 1. 代码类工具阈值 ──────────────────────────────────────────

def test_code_tool_thresholds_higher_than_default():
    """代码类工具用 64KB 阈值，非代码工具维持 2048/1024。"""
    assert _args_compress_threshold() == 2048
    assert _args_compress_threshold("toolkit_file") == 65536
    assert _args_compress_threshold("toolkit_edit") == 65536
    assert _args_compress_threshold("toolkit_exec") == 65536
    assert _args_compress_threshold("toolkit_search") == 2048  # 非代码工具不受影响

    assert _args_keep_bytes() == 1024
    assert _args_keep_bytes("toolkit_edit") == 65536


def _big_code(n_funcs: int = 120) -> str:
    """生成 >2048B 但 <64KB 的代码串。"""
    return "\n".join(f"def func_{i}(x):\n    return x + {i}" for i in range(n_funcs))


def test_compress_json_args_keeps_code_for_code_tools():
    """代码类工具的参数字符串不被截断；非代码工具仍按 1024B 截首尾。"""
    code = _big_code()
    args_str = json.dumps({"action": "write", "filename": "a.py", "content": code})
    n = len(args_str.encode("utf-8"))
    assert n > 2048

    kept = BaseChatSession._compress_json_args(args_str, n, tool_name="toolkit_file")
    assert json.loads(kept)["content"] == code  # 完整保留

    cut = BaseChatSession._compress_json_args(args_str, n)  # 默认阈值
    cut_content = json.loads(cut)["content"]
    assert "[截断" in cut_content and cut_content != code


def test_compress_tool_rounds_keeps_code_args():
    """_compress_tool_rounds 端到端：代码类工具参数完整，非代码工具截断。"""
    code = _big_code()
    rounds = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "1", "function": {"name": "toolkit_file", "arguments": json.dumps({"action": "write", "content": code})}},
                {"id": "2", "function": {"name": "toolkit_kb", "arguments": json.dumps({"action": "read", "content": code})}},
            ],
        },
        {"role": "tool", "tool_call_id": "1", "content": "0"},
        {"role": "tool", "tool_call_id": "2", "content": "0"},
        {"role": "assistant", "content": "done"},
    ]
    out = BaseChatSession._compress_tool_rounds(rounds)
    tcs = out[1]["tool_calls"]
    assert json.loads(tcs[0]["function"]["arguments"])["content"] == code  # 代码工具：完整
    assert "[截断" in json.loads(tcs[1]["function"]["arguments"])["content"]  # 非代码：仍截断


# ── 2. 截断修复标记送达 ────────────────────────────────────────

def test_relaxed_json_loads_marks_truncated_repair():
    """Step 9 截断修复后必须携带 _truncated_fix 标记（不再静默）。"""
    obj = relaxed_json_loads('{"content": "hello world')
    assert obj[TRUNCATION_FIX_KEY] is True
    assert obj["content"] == "hello world"


def test_normalize_tool_args_injects_marker():
    """源头规范化修复截断参数时注入标记。"""
    fixed = normalize_tool_args("toolkit_file", '{"action": "write", "content": "abc')
    assert fixed is not None
    obj = json.loads(fixed)
    assert obj[TRUNCATION_FIX_KEY] is True
    assert obj["action"] == "write"

    # 合法 JSON 不注入标记（逐字节保留，前缀缓存友好）
    ok = '{"a": 1}'
    assert normalize_tool_args("toolkit_file", ok) == ok


def test_pop_truncation_fix_warns_and_strips():
    """执行点：弹出标记 → 返回警告且不残留（防入参绑定拒绝）。"""
    args = {"action": "write", TRUNCATION_FIX_KEY: True}
    warn = pop_truncation_fix(args)
    assert warn  # 有警告文案
    assert TRUNCATION_FIX_KEY not in args  # 已弹出，不会污染工具入参
    assert pop_truncation_fix({"a": 1}) == ""  # 无标记 → 空串
    assert pop_truncation_fix("not a dict") == ""  # 非 dict 容错
