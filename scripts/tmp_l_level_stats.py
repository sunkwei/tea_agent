"""临时诊断脚本：L0/L1/L2/L3 上下文占用统计（只读，不修改任何数据）。

用法：
    python scripts/tmp_l_level_stats.py [db_path]

默认按 config.paths.db_path 解析，回退 ~/.tea_agent/ds_flash.db → chat_history.db。
本脚本**只读**打开数据库（mode=ro&immutable=1，不建表、不迁移），输出用与
build_api_messages 相同的启发式估算器，便于把"窗口被谁打满"定位到具体层。
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tea_agent.session.history_builder import (  # noqa: E402
    estimate_messages_tokens,
    estimate_tokens,
)


def _resolve_db_path() -> str:
    """解析要诊断的数据库路径（命令行参数 > config.paths.db_path > 常见默认）。"""
    if len(sys.argv) > 1:
        return sys.argv[1]
    candidates: list[str] = []
    try:
        from tea_agent.config import get_config

        cfg = get_config()
        name = getattr(getattr(cfg, "paths", None), "db_path", "") or ""
        if name:
            candidates.append(os.path.join(os.path.expanduser("~"), ".tea_agent", name))
            candidates.append(name)
    except Exception:
        pass
    home = os.path.expanduser("~")
    candidates += [
        os.path.join(home, ".tea_agent", "ds_flash.db"),
        os.path.join(home, ".tea_agent", "chat_history.db"),
        "chat_history.db",
    ]
    for cand in candidates:
        if cand and os.path.isfile(cand):
            return cand
    return candidates[-1]


def _connect_ro(db_path: str) -> sqlite3.Connection:
    """只读打开数据库（优先 immutable，避免触发 WAL/建表写入）。"""
    uri_path = db_path.replace("\\", "/")
    for uri in (f"file:{uri_path}?mode=ro&immutable=1", f"file:{uri_path}?mode=ro"):
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            conn.execute("select count(*) from sqlite_master")
            return conn
        except sqlite3.Error:
            continue
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_live_context():
    """尽力取当前活跃 context（Web 场景可能取不到，返回 None）。"""
    try:
        from tea_agent.server.modules.agent_module import current_session_ctx

        return current_session_ctx()
    except Exception:
        return None


def main() -> None:
    db_path = _resolve_db_path()
    print("=" * 70)
    print(f"[0] 诊断目标: {db_path}")
    print("=" * 70)

    print()
    print("=" * 70)
    print("[1] 当前会话 context 聚合视图（取不到时跳过）")
    print("=" * 70)
    ctx = get_live_context()
    if ctx is None:
        print("  (未找到活跃 context，仅做离线统计)")
    else:
        for label, attr in (
            ("model", "model"),
            ("max_context_tokens", "max_context_tokens"),
            ("_last_request_prompt_tokens", "_last_request_prompt_tokens"),
            ("_last_estimate_tokens", "_last_estimate_tokens"),
            ("_output_cap", "_output_cap"),
            ("keep_turns", "keep_turns"),
            ("rc_keep_steps", "rc_keep_steps"),
        ):
            print(f"  {label:<28}: {getattr(ctx, attr, '?')}")
        for label, attr in (
            ("_injected_os_info", "_injected_os_info_text"),
            ("_injected_memories", "_injected_memories_text"),
            ("_semantic_summary", "_semantic_summary"),
            ("_tool_chain_summary", "_tool_chain_summary"),
        ):
            value = getattr(ctx, attr, "") or ""
            print(f"  {label:<28}: {len(value)} 字符")
        print(f"  {'_level2 条数':<28}: {len(getattr(ctx, '_level2', []) or [])}")
        print(f"  {'messages 条数':<28}: {len(getattr(ctx, 'messages', []) or [])}")

    print()
    print("=" * 70)
    print("[2] DB 读取：最近 topic 的 L1/L2/L3")
    print("=" * 70)
    conn = _connect_ro(db_path)
    cur = conn.cursor()
    cur.execute(
        "select topic_id, title, last_update_stamp, semantic_summary, "
        "tool_chain_summary, level2_json from topics "
        "order by last_update_stamp desc limit 1"
    )
    row = cur.fetchone()
    if row is None:
        print("  (db 无 topic)")
        return
    topic_id = row["topic_id"]
    keep_turns = int(getattr(ctx, "keep_turns", 0) or 5)
    max_ctx = int(getattr(ctx, "max_context_tokens", 0) or 0)
    print(f"  最近 topic: {topic_id} | {(row['title'] or '')[:40]}")
    print(f"  最后更新  : {row['last_update_stamp']}")

    sem = row["semantic_summary"] or ""
    tool_chain = row["tool_chain_summary"] or ""
    try:
        level2 = json.loads(row["level2_json"] or "[]")
    except Exception:
        level2 = []

    cur.execute(
        "select id, stamp, user_msg, ai_msg, rounds_json from conversations "
        "where topic_id = ? order by stamp desc limit ?",
        (topic_id, keep_turns),
    )
    recent = [dict(r) for r in cur.fetchall()]
    recent.reverse()
    conn.close()
    print(f"  L1 载入轮数(keep_turns={keep_turns}): {len(recent)}")

    print()
    print("=" * 70)
    print("[3] 分层会计（与 build_api_messages 相同的估算器）")
    print("=" * 70)
    print("  说明：L0（system prompt）无法离线获取，运行时见 _last_estimate_tokens；")
    print("        L2 的 thinking 只入库不注入，单列以供判断存储膨胀。")

    from tea_agent.basesession import BaseChatSession  # noqa: E402

    l1_tokens = 0
    l1_rc_tokens = 0
    l1_tool_tokens = 0
    for conv in recent:
        try:
            conv["rounds_json_parsed"] = json.loads(conv.get("rounds_json") or "[]")
        except Exception:
            conv["rounds_json_parsed"] = []
        conv_msgs = BaseChatSession._load_single_conversation(conv)
        l1_tokens += estimate_messages_tokens(conv_msgs)
        for msg in conv_msgs:
            if msg.get("role") == "assistant":
                l1_rc_tokens += estimate_tokens(msg.get("reasoning_content") or "")
            elif msg.get("role") == "tool":
                content = msg.get("content")
                l1_tool_tokens += estimate_tokens(content if isinstance(content, str) else "")

    l2_inject = 0
    l2_thinking = 0
    for item in level2:
        l2_inject += estimate_tokens(str(item.get("user", "") or ""))
        l2_inject += estimate_tokens(str(item.get("assistant", "") or ""))
        l2_thinking += estimate_tokens(str(item.get("thinking", "") or ""))
    l3_tokens = estimate_tokens(sem) + estimate_tokens(tool_chain)

    total = l1_tokens + l2_inject + l3_tokens
    print(f"  L1 合计（{len(recent)} 轮，含工具链）    : {l1_tokens:>10,} tok")
    print(f"    ├─ 其中 reasoning_content        : {l1_rc_tokens:>10,} tok")
    print(f"    └─ 其中 tool 消息                : {l1_tool_tokens:>10,} tok")
    print(f"  L2 注入部分（user+assistant）       : {l2_inject:>10,} tok  ({len(level2)} 条)")
    print(f"  L2 仅入库 thinking（不回传请求）    : {l2_thinking:>10,} tok")
    print(f"  L3 摘要（semantic+tool_chain）      : {l3_tokens:>10,} tok")
    print(f"  ── 合计（不含 L0）                  : {total:>10,} tok")
    if max_ctx > 0:
        print(f"  ── 占窗口 {max_ctx:,} 的 {total / max_ctx * 100:.1f}%")
    print()
    print("  判读：L1 里 reasoning_content 占比高 → 思考链是主因（rc_keep_steps 限步）；")
    print("        tool 消息占比高 → 工具输出/源码回放是主因（回放阈值/工具输出上限）；")
    print("        L2 入库 thinking 远大于注入部分 → L2 存储膨胀（l2_thinking_max_chars）。")


if __name__ == "__main__":
    main()
