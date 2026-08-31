"""量化 tea_agent 前缀缓存命中率：动态上下文插入位置的影响（诊断脚本）。

对比同一会话连续两个用户回合的请求，用真实 build_api_messages 构建，
计算第二个回合请求的"字节相同前缀"占比（近似 DeepSeek 前缀缓存命中率）：

- 修复后（当前代码）：动态上下文**追加到消息末尾** → L1 历史跨回合逐字节稳定
- 修复前（模拟）：动态上下文**插入 L1 起点之前** → 内容变化时 L1 历史整体失效

实测结论（本脚本）：同一会话动态内容变化时，
  修复前 ≈ 62%，修复后 ≈ 99%（剩余 ~1% 为动态消息本身的新内容）。
背景：DSH（DeepSeek Harness）的 dsh-time-context 同样把时间上下文追加到
消息列表末尾（append-only），历史前缀永不改写，因此可达 ~99% 命中。
"""
import json
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from tea_agent.session.history_builder import build_api_messages  # noqa: E402


def _tokens(text: str) -> int:
    cn = len(re.findall(r"[\u4e00-\u9fff]", text))
    return int(cn / 1.5 + (len(text) - cn) / 4.0) + 4


def _serialize(msg: dict) -> str:
    return json.dumps(msg, ensure_ascii=False)


def common_prefix_ratio(req_a: list[dict], req_b: list[dict]) -> float:
    """req_b 相对 req_a 的字节相同前缀占比（消息粒度）。"""
    total = sum(_tokens(_serialize(m)) for m in req_a)
    common = 0
    for m_a, m_b in zip(req_a, req_b, strict=False):
        if _serialize(m_a) != _serialize(m_b):
            break
        common += _tokens(_serialize(m_a))
    return common / max(total, 1)


def make_context(dynamic_text: str, user_msg: str) -> SimpleNamespace:
    ctx = SimpleNamespace(
        supports_reasoning=True, supports_vision=False,
        disable_summary=False, disable_l3=False, disable_l2=False,
        model="deepseek-v4-flash", max_context_tokens=1048576,
        _injected_os_info_text="",
        _semantic_summary="用户正在开发一个 AI Agent 框架。",
        _tool_chain_summary="历史工具链：toolkit_exec → toolkit_file → toolkit_edit。",
        _history_summary="", _skill_rules_set=True,
        _level2_dirty=True, _level2_selected=None,
        _loop_max_ratio=0.0, _loop_trim_done=False, _token_exhausted=False,
        _last_estimate_tokens=0, _last_request_prompt_tokens=0,
        _dynamic_ctx_cache=dynamic_text,  # 模拟 add_user_message 后重算的结果
        _injected_memories_text="", _level2=[],
    )
    messages = [{"role": "system", "content": "system prompt"}]
    for i in range(3):
        messages.append({"role": "user", "content": f"第 {i + 1} 轮用户问题：请分析项目结构。"})
        messages.append({
            "role": "assistant", "content": "",
            "reasoning_content": f"第 {i + 1} 轮思考。",
            "tool_calls": [{
                "id": f"c{i}1", "type": "function",
                "function": {"name": "toolkit_exec", "arguments": '{"command": "dir"}'},
            }],
        })
        messages.append({"role": "tool", "tool_call_id": f"c{i}1", "content": "README.md\ntea_agent/\n" * 20})
        messages.append({
            "role": "assistant",
            "content": f"第 {i + 1} 轮回答。\n" + "详细结论…" * 50,
            "reasoning_content": f"第 {i + 1} 轮总结。",
        })
    messages.append({"role": "user", "content": user_msg})
    ctx.messages = messages
    return ctx


def build_fixed(dynamic_text: str, user_msg: str) -> list[dict]:
    """修复后（当前代码）：动态上下文追加到消息末尾。"""
    return build_api_messages(make_context(dynamic_text, user_msg), "system prompt")


def build_old_style(dynamic_text: str, user_msg: str) -> list[dict]:
    """修复前模拟：把末尾的动态消息改插到 L1 起点（L2 之后、L1 历史之前）。"""
    base = build_fixed(dynamic_text, user_msg)
    dyn = base.pop()  # 末尾的动态消息
    insert_at = 1
    for i, m in enumerate(base[1:], start=1):
        if m.get("role") == "user" and str(m.get("content", "")).startswith("第 1 轮"):
            insert_at = i
            break
    base.insert(insert_at, dyn)
    return base


def main():
    dyn_n = "[动态上下文 — 由 tea_agent 自动注入，供参考]\n\n当前无待完成任务。"
    dyn_n1 = (
        "[动态上下文 — 由 tea_agent 自动注入，供参考]\n\n"
        "[未完成任务提醒]\n有 3 个未完成的 TODO 项:\n"
        "  - [1] 修复 reasoning_content 400\n  - [2] 优化前缀缓存\n  - [3] 补充测试\n\n"
        "## 长期记忆\n用户偏好：使用中文回复，重视缓存命中率。"
    )
    user_msg = "继续优化缓存命中率"

    req_n = build_fixed(dyn_n, user_msg)
    req_n1 = build_fixed(dyn_n1, user_msg)
    fixed = common_prefix_ratio(req_n, req_n1)

    old_n = build_old_style(dyn_n, user_msg)
    old_n1 = build_old_style(dyn_n1, user_msg)
    old = common_prefix_ratio(old_n, old_n1)

    total = sum(_tokens(_serialize(m)) for m in req_n)
    print(f"请求规模: {len(req_n)} 条消息, ~{total} tokens")
    print("动态上下文跨回合变化时前缀命中率：")
    print(f"  修复前（插 L1 起点前）: {old:.1%}")
    print(f"  修复后（追加消息末尾）: {fixed:.1%}")
    print(f"  差值: {(fixed - old) * 100:+.1f} 个百分点")
    return {"fixed": fixed, "old": old}


if __name__ == "__main__":
    main()
