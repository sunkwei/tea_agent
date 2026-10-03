"""搜索引用收集 — 回合结束时列出本回合参考过的 http(s) 链接。

设计要点
--------
1. **纯函数**：``extract_refs`` / ``merge_refs`` / ``format_refs_text`` 无 IO、
   无全局状态，可秒级单测覆盖（对齐 AGENTS.md「时间/随机/环境相关逻辑抽成纯函数」）。
2. **只读工具白名单**：仅从明确产出网络来源的工具结果里取 URL
   （``toolkit_search`` 的 web/github 结果、``toolkit_js_fetch`` 的目标页）。
   不做「扫全量工具输出里的裸 URL」—— 那会把 ``toolkit_exec`` 的 stdout、
   代码搜索结果等**非参考来源**误当引用列出，噪声大于价值。
3. **fail-open**：任何解析异常返回空列表，绝不把工具调用带崩
   （AGENTS.md「辅助能力不绑架主流程」）。
4. **不入库**：展示文本经 ``callback`` 直达 UI，不并入 ``full_reply`` ——
   后者会被 server 持久化进对话历史（见 ``OnlineToolSession._finalize_turn_reply``
   的不变式）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("search_refs")

# 产出「网络参考来源」的工具 → 该工具结果里 URL 的语义
SEARCH_REF_TOOLS: frozenset[str] = frozenset({
    "toolkit_search",
    "toolkit_js_fetch",
})

# 单次回合最多列出的链接数（超出折叠为「…等 N 条」）
MAX_DISPLAY_REFS: int = 20

# 单条链接在展示里的最大条数（防止一次搜索 50 条全塞进 UI）
_HEADER = "🔗 本回合参考链接"


def _clean_url(value: Any) -> str:
    """归一化候选 URL：仅接受 http/https，去空白，去尾随标点。"""
    if not isinstance(value, str):
        return ""
    url = value.strip().strip("<>")
    if not url.lower().startswith(("http://", "https://")):
        return ""
    # 去掉从 Markdown/JSON 里带出来的尾随标点
    return url.rstrip(",;)】》\"'")


def _clean_title(value: Any, fallback: str) -> str:
    """归一化标题：单行、限长；空则用 fallback。"""
    if not isinstance(value, str):
        return fallback
    title = " ".join(value.split())
    if not title:
        return fallback
    if len(title) > 80:
        title = title[:77] + "…"
    # 标题里出现 ] 或 ) 会破坏 Markdown 链接语法
    return title.replace("]", "").replace("[", "").replace("(", "（").replace(")", "）")


def extract_refs(tool_name: str, args: dict | None, result: Any) -> list[dict]:
    """从一次工具调用的结果中提取参考链接。

    Args:
        tool_name: 工具名（不在 ``SEARCH_REF_TOOLS`` 内直接返回空）
        args: 工具入参（``toolkit_js_fetch`` 的目标 URL 只能从这里取）
        result: 工具返回值（dict / str / 任意）

    Returns:
        ``[{"url": str, "title": str, "source": tool_name}, ...]``；异常时 ``[]``
    """
    if tool_name not in SEARCH_REF_TOOLS:
        return []
    try:
        refs: list[dict] = []

        if tool_name == "toolkit_js_fetch":
            # 抓取型工具：参考来源就是目标页本身（结果里通常无 url 字段）
            url = _clean_url((args or {}).get("url"))
            if url:
                title = ""
                if isinstance(result, dict):
                    title = str(result.get("title") or "")
                refs.append({"url": url, "title": _clean_title(title, url), "source": tool_name})
            return refs

        # toolkit_search：仅网络类搜索有参考意义（code/symbol 搜的是本地文件）
        st = str((args or {}).get("search_type") or "web").lower()
        if st not in ("web", "github"):
            return []

        items: list[Any] = []
        if isinstance(result, dict):
            if result.get("ok") is False:
                return []
            raw = result.get("results")
            if isinstance(raw, list):
                items = raw
        elif isinstance(result, list):
            items = result

        for item in items:
            if not isinstance(item, dict):
                continue
            url = _clean_url(item.get("url"))
            if not url:
                continue
            refs.append({
                "url": url,
                "title": _clean_title(item.get("title"), url),
                "source": tool_name,
            })
        return refs
    except Exception:  # noqa: BLE001 — 旁路采集不得影响工具执行
        logger.debug("extract_refs failed (isolated)", exc_info=True)
        return []


def merge_refs(existing: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """合并两批引用，按 URL 去重（保留首次出现的顺序与标题）。"""
    out: list[dict] = []
    seen: set[str] = set()
    for batch in (existing or [], new or []):
        for ref in batch:
            if not isinstance(ref, dict):
                continue
            url = str(ref.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({
                "url": url,
                "title": str(ref.get("title") or url),
                "source": str(ref.get("source") or ""),
            })
    return out


def format_refs_text(refs: list[dict] | None, max_items: int = MAX_DISPLAY_REFS) -> str:
    """渲染回合末的参考链接提示；无引用返回空串。

    Args:
        refs: ``extract_refs`` / ``merge_refs`` 产出的引用列表
        max_items: 最多展示条数，超出折叠为「…等 N 条」

    Returns:
        Markdown 文本（前端 ``formatMarkdown`` 会渲染成可点击链接）；空则 ``""``
    """
    if not refs:
        return ""
    items = [r for r in refs if isinstance(r, dict) and r.get("url")]
    if not items:
        return ""
    limit = max_items if max_items and max_items > 0 else len(items)
    shown = items[:limit]
    lines = [f"{_HEADER}（{len(items)}）"]
    for i, ref in enumerate(shown, 1):
        url = str(ref["url"])
        title = _clean_title(ref.get("title"), url) or url
        lines.append(f"{i}. [{title}]({url})")
    if len(items) > len(shown):
        lines.append(f"… 等 {len(items) - len(shown)} 条")
    return "\n".join(lines)
