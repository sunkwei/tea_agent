"""按会话提取 L0 / L1 / L2 / L3 四级历史（严格审计读取侧）。

为什么需要这个工具：
    四级历史此前**只有写入侧，没有读取出口**。get_level2 / get_semantic_summary /
    get_tool_chain_summary 仅被 _load_topic_history 内部消费；L0 富化系统提示词
    更是从不落盘。于是「提取某次会话的 L0-L3」在审计/复盘时根本无从下手。

⚠️ 四级历史的**作用域不同**，这是本工具最容易误用的地方，故在输出里显式标注：
    - L0 / L1 是**回合级**（per conversation_id）
    - L2 / L3 是**主题级**（per topic_id），且是**滚动覆盖值、非历史版本**
      → 拿它们「复原某一回合当时看到的 L2/L3」是**做不到**的，只能得到
        「该主题当前最新的 L2/L3」。本工具如实标注 historical=false。
"""

import json
import logging

logger = logging.getLogger("toolkit")

_ALL_LEVELS = ("L0", "L1", "L2", "L3")


def _safe_call(fn, default=None):
    """执行 ``fn()``，任何异常降级为 ``default`` 并留痕（fail-open 单点）。

    本模块所有「旁路读取不得带崩主流程」的兜底都集中在此：既避免在每个调用点
    重复 try/except（也让「静默吞异常」这类度量集中在一处、便于审计），
    又保证**调用点之间仍然互相隔离** —— 某层读取失败不影响其余层。

    刻意捕获宽泛的 ``Exception`` 而非具体类型：本模块服务的是**审计读取**，
    调用对象可能是鸭子类型替身、旧库、或跨版本 Storage。窄化异常会让
    ``AttributeError`` / ``TypeError`` 这类「实现漂移」逃逸，从而击穿
    「单层失败隔离」的契约（该契约有回归测试钉住）。

    Args:
        fn: 无参可调用对象（用 lambda 绑定参数）。
        default: 失败时的返回值。

    Returns:
        ``(value, error_str)``。``error_str`` 为空表示成功；否则为
        ``"异常类型: 消息"``，供调用方写入审计报告的 reason 字段。
    """
    try:
        return fn(), ""
    except Exception as e:
        logger.debug("history_extract: 调用失败，已降级", exc_info=True)
        return default, f"{type(e).__name__}: {e}"


def _probe_agent_db():
    """优先取当前活动 Agent 的 db（正跑着的会话库/项目库）。"""
    from tea_agent.session_ref import get_agent

    agent = get_agent()
    return getattr(agent, "db", None) if agent is not None else None


def _probe_peek():
    """其次取**已存在**的单例（peek_storage 绝不触发建库）。"""
    from tea_agent.store import peek_storage

    return peek_storage()


def _probe_new():
    """兜底新建。"""
    from tea_agent.store import get_storage

    return get_storage()


def _resolve_storage():
    """定位可用的 Storage 实例。

    优先级：活动 Agent 的 db → 已存在的单例（peek_storage，绝不触发建库）
    → 兜底新建。

    刻意不硬编码 ``~/.tea_agent/chat_history.db``：存储作用域可能是项目级
    ``$pwd/.tea_agent_run/``，写死路径会读错库（得到「空结果」而非报错，
    属静默失效）。

    Returns:
        (storage, source) ；都不行时返回 (None, "")。
    """
    for probe, source in ((_probe_agent_db, "agent"),
                          (_probe_peek, "singleton"),
                          (_probe_new, "new")):
        val, _err = _safe_call(probe, None)
        if val is not None:
            return val, source
    return None, ""


def _resolve_topic_id(storage, topic_id: str) -> str:
    """topic_id 未显式给出时，回落到当前活动主题。"""
    if topic_id:
        return str(topic_id)

    def _current() -> str:
        from tea_agent.session_ref import get_agent

        agent = get_agent()
        cur = getattr(agent, "current_topic_id", None) if agent is not None else None
        return str(cur) if cur else ""

    cur, _err = _safe_call(_current, "")
    return cur or ""


def _clip(text: str, max_chars: int) -> tuple:
    """截断并**留痕**（静默截断会让审计误以为原文就这么短）。

    Returns:
        (截断后文本, 是否被截断)
    """
    if not isinstance(text, str):
        text = str(text or "")
    if max_chars and max_chars > 0 and len(text) > max_chars:
        return (
            text[:max_chars] + f"\n...[已截断: 原长 {len(text)} 字符, 上限 {max_chars}]",
            True,
        )
    return text, False


def _parse_levels(levels) -> list:
    """把 levels 归一化为大写字符串列表；None/空 → 全部四级。"""
    if levels is None or levels == "" or levels == []:
        return list(_ALL_LEVELS)
    if isinstance(levels, str):
        parts = [p.strip().upper() for p in levels.replace(";", ",").split(",")]
    elif isinstance(levels, (list, tuple, set)):
        parts = []
        for p in levels:
            if isinstance(p, str):
                parts.extend(x.strip().upper() for x in p.replace(";", ",").split(","))
            else:
                parts.append(str(p).strip().upper())
    else:
        parts = [str(levels).strip().upper()]
    out = []
    for p in parts:
        if not p:
            continue
        if p in ("L0", "L1", "L2", "L3"):
            if p not in out:
                out.append(p)
        elif p.isdigit() and 0 <= int(p) <= 3:
            name = f"L{p}"
            if name not in out:
                out.append(name)
    return out or list(_ALL_LEVELS)


# ── 各层提取 ────────────────────────────────────────────────

def _extract_l0(storage, conversation_id: str, max_chars: int) -> dict:
    """L0：本回合实际发给模型的富化 system 消息（回合级）。"""
    out = {
        "scope": "conversation",
        "historical": True,
        "available": False,
        "content": "",
        "hash": "",
        "chars": 0,
        "truncated": False,
    }
    if not conversation_id:
        out["reason"] = "需要 conversation_id（L0 是回合级数据）"
        return out
    snap, err = _safe_call(lambda: storage.get_l0_snapshot(conversation_id), None)
    if err:
        out["reason"] = f"读取失败: {err}"
        return out

    if snap is None:
        # 区分三种情况，避免把「ID 打错」误述成「这是历史回合」：
        #   ① 回合根本不存在 → 问错了 ID
        #   ② 回合存在但未记录 → 早于 L0 快照功能上线
        #   ③ 存储不支持该查询 → 能力缺失
        exists_fn = getattr(storage, "conversation_exists", None)
        exists = None
        if callable(exists_fn):
            exists, _e = _safe_call(lambda: bool(exists_fn(conversation_id)), None)
        if exists is False:
            out["reason"] = f"回合 {conversation_id} 不存在（请核对 conversation_id）"
        elif exists is True:
            out["reason"] = (
                "该回合未记录 L0（可能是 L0 快照功能上线前的历史回合）"
            )
        else:
            out["reason"] = "未记录 L0（无法确认该回合是否存在）"
        return out

    out["available"] = True
    out["hash"] = snap.get("hash", "")
    out["chars"] = snap.get("chars", 0)
    if snap.get("missing"):
        out["reason"] = "指针存在但快照内容缺失（可能被清理或跨库搬迁）"
        return out
    content, truncated = _clip(snap.get("content", ""), max_chars)
    out["content"] = content
    out["truncated"] = truncated
    return out


def _extract_l1(storage, conversation_id: str, topic_id: str,
                 max_chars: int, max_rounds: int) -> dict:
    """L1：最新对话明细（含工具调用链），回合级。"""
    out = {
        "scope": "conversation",
        "historical": True,
        "available": False,
        "rounds": 0,
        "messages": [],
        "truncated": False,
    }
    if conversation_id:
        rounds, err = _safe_call(lambda: storage.get_rounds(conversation_id) or [], [])
        if err:
            out["reason"] = f"读取失败: {err}"
            return out
    elif topic_id:
        # 未指定回合 → 返回该主题最近的对话（便捷视角，非单回合）
        convs, err = _safe_call(
            lambda: storage.get_conversations(topic_id, limit=1, include_rounds=True) or []
        )
        if err:
            out["reason"] = f"读取失败: {err}"
            return out
        if not convs:
            out["reason"] = f"主题 {topic_id} 下没有对话"
            return out
        rounds = convs[-1].get("rounds_json_parsed") or []
        out["scope"] = "conversation(最近一轮)"
    else:
        out["reason"] = "需要 conversation_id 或 topic_id"
        return out

    if not rounds:
        out["reason"] = "该回合没有轮次记录（可能未启用工具或无落盘数据）"
        return out

    out["available"] = True
    out["rounds"] = len(rounds)
    selected = rounds
    if max_rounds and max_rounds > 0 and len(rounds) > max_rounds:
        selected = rounds[:max_rounds]
        out["truncated"] = True
        out["truncated_note"] = f"仅返回前 {max_rounds} 轮（共 {len(rounds)} 轮）"

    msgs = []
    for r in selected:
        entry = {"role": r.get("role", "")}
        body, cut = _clip(r.get("content", ""), max_chars)
        entry["content"] = body
        if cut:
            out["truncated"] = True
        if r.get("tool_calls"):
            entry["tool_calls"] = [
                tc.get("function", {}).get("name", "?")
                if isinstance(tc, dict) else str(tc)
                for tc in r["tool_calls"]
            ]
        if r.get("tool_call_id"):
            entry["tool_call_id"] = r["tool_call_id"]
        rc = r.get("reasoning_content")
        if rc:
            rc_clip, cut2 = _clip(rc, max_chars)
            entry["reasoning_content"] = rc_clip
            if cut2:
                out["truncated"] = True
        msgs.append(entry)
    out["messages"] = msgs
    return out


def _extract_l2(storage, topic_id: str, max_chars: int) -> dict:
    """L2：近期相关历史（**主题级**，滚动覆盖，非历史版本）。"""
    out = {
        "scope": "topic",
        "historical": False,
        "available": False,
        "entries": 0,
        "items": [],
        "truncated": False,
        "caveat": (
            "L2 是主题级**滚动窗口**（溢出即交 L3 摘要），只反映当前保留的条目，"
            "无法复原某一回合当时的 L2 视图。"
        ),
    }
    if not topic_id:
        out["reason"] = "需要 topic_id（L2 是主题级数据）"
        return out
    level2, err = _safe_call(lambda: storage.get_level2(topic_id) or [], [])
    if err:
        out["reason"] = f"读取失败: {err}"
        return out
    if not level2:
        out["reason"] = "该主题暂无 L2 条目（可能已被摘要或尚未累积）"
        return out

    out["available"] = True
    out["entries"] = len(level2)
    items = []
    for e in level2:
        if not isinstance(e, dict):
            items.append({"raw": _clip(str(e), max_chars)[0]})
            continue
        it = {}
        for k in ("user", "assistant", "thinking"):
            if e.get(k):
                body, cut = _clip(e[k], max_chars)
                it[k] = body
                if cut:
                    out["truncated"] = True
        if e.get("files"):
            it["files"] = e["files"]
        items.append(it)
    out["items"] = items
    return out


def _extract_l3(storage, topic_id: str, max_chars: int) -> dict:
    """L3：压缩摘要（**主题级**，UPSERT 覆盖，非历史版本）。"""
    out = {
        "scope": "topic",
        "historical": False,
        "available": False,
        "semantic_summary": "",
        "tool_chain_summary": "",
        "topic_summary": "",
        "truncated": False,
        "caveat": (
            "此处返回的是 L3 的**当前版本**（每次摘要是 UPSERT 覆盖）。"
            "历史版本可用 action=l3_versions 取（append-only 版本表）；"
            "另注意实测 L3 常为空 —— 摘要需累积到阈值才触发。"
        ),
    }
    if not topic_id:
        out["reason"] = "需要 topic_id（L3 是主题级数据）"
        return out

    fields = {}
    for key, getter in (
        ("semantic_summary", "get_semantic_summary"),
        ("tool_chain_summary", "get_tool_chain_summary"),
        ("topic_summary", "get_topic_summary"),
    ):
        fn = getattr(storage, getter, None)
        if not callable(fn):
            continue
        # 单字段失败不拖垮整层（失败隔离）
        val, _e = _safe_call(lambda f=fn: f(topic_id) or "", "")
        if val:
            body, cut = _clip(val, max_chars)
            fields[key] = body
            if cut:
                out["truncated"] = True
        else:
            fields[key] = ""

    out.update(fields)
    out["available"] = any(fields.values())
    if not out["available"]:
        out["reason"] = "该主题暂无 L3 摘要（尚未触发摘要阈值，或摘要被禁用）"
    return out


# ── 主入口 ──────────────────────────────────────────────────

def toolkit_history_extract(action: str = "extract", topic_id: str = "",
                            conversation_id: str = "", levels=None,
                            max_chars: int = 20000, max_rounds: int = 100) -> str:
    """按会话提取 L0/L1/L2/L3 四级历史（严格审计读取侧）。

    ⚠️ 四级历史作用域不同：
      - L0 / L1 = **回合级**（需 conversation_id）
      - L2 / L3 = **主题级**（需 topic_id），且是**当前滚动值、非历史版本**

    Args:
        action: extract=提取四级 / list_conversations=列出话题下的回合 /
                l0_versions=列出该主题的 L0 版本（内容寻址，可比对差异）/
                levels=仅列出四级历史的作用域说明
        topic_id: 主题 ID；空则取当前活动主题。
        conversation_id: 回合 ID（L0/L1 必需；L1 缺省时回落该主题最近一轮）。
        levels: 要提取的层，如 ["L0","L1"] 或 "L0,L1"；空=全部四级。
        max_chars: 每字段截断上限（0=不限，慎用——L0 可达数十 KB）。
        max_rounds: L1 最多返回的轮数（0=不限）。

    Returns:
        JSON 字符串（结构化结果，含各层可用性与作用域标注）。
    """
    act = (action or "extract").strip().lower()

    if act == "levels":
        return json.dumps({
            "ok": True,
            "levels": {
                "L0": {"scope": "conversation", "historical": True,
                       "desc": "本回合实际发给模型的富化 system 消息（运行时合成）"},
                "L1": {"scope": "conversation", "historical": True,
                       "desc": "最近对话明细（含工具调用链与 reasoning_content）"},
                "L2": {"scope": "topic", "historical": False,
                       "desc": "近期相关历史；主题级滚动窗口，溢出即交 L3"},
                "L3": {"scope": "topic", "historical": False,
                       "desc": "压缩摘要（语义/工具链/话题）；主题级 UPSERT 覆盖"},
            },
            "note": "L2/L3 是主题级当前值，无法复原某一回合当时的历史视图。",
        }, ensure_ascii=False, indent=2)

    storage, source = _resolve_storage()
    if storage is None:
        return json.dumps({"ok": False, "error": "无法定位 Storage 实例"},
                          ensure_ascii=False)

    topic_id = _resolve_topic_id(storage, topic_id)
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = 20000
    try:
        max_rounds = int(max_rounds)
    except (TypeError, ValueError):
        max_rounds = 100

    # ── 列出话题下的回合（便于定位 conversation_id）──
    if act == "list_conversations":
        if not topic_id:
            return json.dumps({"ok": False, "error": "需要 topic_id 或当前活动主题"},
                              ensure_ascii=False)
        try:
            convs = storage.get_conversations(topic_id, limit=0, include_rounds=False) or []
        except Exception as e:
            return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"},
                              ensure_ascii=False)
        items = []
        for cv in convs:
            items.append({
                "conversation_id": cv.get("id", ""),
                "stamp": str(cv.get("stamp", "")),
                "status": cv.get("status", ""),
                "is_func_calling": cv.get("is_func_calling", 0),
                "user_msg": _clip(cv.get("user_msg", ""), 120)[0],
                "ai_msg": _clip(cv.get("ai_msg", ""), 120)[0],
            })
        return json.dumps({"ok": True, "topic_id": topic_id,
                           "count": len(items), "conversations": items},
                          ensure_ascii=False, indent=2)

    # ── 列出 L0 版本（内容寻址；同 topic 逐字节稳定→通常仅少数几份）──
    if act == "l0_versions":
        snaps, err = _safe_call(lambda: storage.list_l0_snapshots(topic_id or "", limit=100), [])
        if err:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
        return json.dumps({
            "ok": True, "topic_id": topic_id, "count": len(snaps),
            "snapshots": snaps,
            "note": "同内容共享同一 hash（内容寻址）；多版本=该主题 L0 曾发生变化。",
        }, ensure_ascii=False, indent=2)

    # ── 列出 L3 历史版本（append-only；回答「T 时刻 Agent 相信什么」）──
    if act == "l3_versions":
        if not topic_id:
            return json.dumps({"ok": False, "error": "需要 topic_id 或当前活动主题"},
                              ensure_ascii=False)
        fn = getattr(storage, "get_l3_versions", None)
        if not callable(fn):
            return json.dumps({
                "ok": False,
                "error": "该 Storage 不支持 L3 版本查询（旧库/替身）",
            }, ensure_ascii=False)
        versions, err = _safe_call(lambda: fn(topic_id, "", 200) or [], [])
        if err:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
        items = []
        for v in versions:
            body, cut = _clip(v.get("content", ""), max_chars)
            items.append({
                "kind": v.get("kind", ""),
                "version": v.get("version", 0),
                "chars": v.get("chars", 0),
                "created_at": str(v.get("created_at", "")),
                "content": body,
                "truncated": cut,
            })
        return json.dumps({
            "ok": True,
            "topic_id": topic_id,
            "count": len(items),
            "versions": items,
            "note": (
                "L3 版本为 append-only：每次**内容实际变化**时新增一版"
                "（同值重写不产生新版本，避免版本号被无意义重复写撑爆）。"
            ),
        }, ensure_ascii=False, indent=2)

    # ── 提取四级 ──
    wanted = _parse_levels(levels)
    result = {
        "ok": True,
        "topic_id": topic_id,
        "conversation_id": conversation_id,
        "storage_source": source,
        "levels_requested": wanted,
        "scope_note": (
            "L0/L1 为回合级；L2/L3 为主题级且是当前滚动值（historical=false），"
            "不能复原某一回合当时的 L2/L3 视图。"
        ),
    }

    extractors = {
        "L0": lambda: _extract_l0(storage, conversation_id, max_chars),
        "L1": lambda: _extract_l1(storage, conversation_id, topic_id,
                                  max_chars, max_rounds),
        "L2": lambda: _extract_l2(storage, topic_id, max_chars),
        "L3": lambda: _extract_l3(storage, topic_id, max_chars),
    }
    # 逐层独立执行：某层失败只标该层不可用（失败隔离），其余层照常返回。
    # 兜底统一走 _safe_call，避免四处复制 try/except。
    for lv in wanted:
        val, err = _safe_call(extractors[lv])
        result[lv] = val if not err else {"available": False, "reason": err}

    # 汇总可用性，便于一眼判断
    result["availability"] = {
        lv: bool(isinstance(result.get(lv), dict) and result[lv].get("available"))
        for lv in wanted
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def meta_toolkit_history_extract() -> dict:
    return {"type": "function", "function": {
        "name": "toolkit_history_extract",
        "description": (
            "按会话提取 L0/L1/L2/L3 四级历史（审计/复盘用）。"
            "L0=本回合实际发给模型的富化 system 消息（回合级）；"
            "L1=最近对话明细含工具链（回合级）；"
            "L2=近期相关历史（主题级滚动窗口）；L3=压缩摘要（主题级当前版本）。"
            "注意 L2/L3 是主题级当前值，无法复原历史版本。"
            "action=extract 提取 / list_conversations 列出回合以定位 conversation_id / "
            "l0_versions 列出该主题的 L0 版本 / levels 查看各层作用域说明。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["extract", "list_conversations", "l0_versions",
                             "l3_versions", "levels"],
                    "description": "extract=提取四级历史; list_conversations=列出话题下回合; l0_versions=列出L0版本; l3_versions=列出L3摘要历史版本; levels=查看各层作用域",
                    "default": "extract",
                },
                "topic_id": {
                    "type": "string",
                    "description": "主题 ID；空则取当前活动主题",
                },
                "conversation_id": {
                    "type": "string",
                    "description": "回合 ID（L0/L1 需要；L1 缺省时回落该主题最近一轮）",
                },
                "levels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要提取的层，如 ['L0','L1']；空=全部四级",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "每字段截断上限（默认 20000；0=不限）",
                    "default": 20000,
                },
                "max_rounds": {
                    "type": "integer",
                    "description": "L1 最多返回轮数（默认 100；0=不限）",
                    "default": 100,
                },
            },
            "required": [],
        },
    }}
