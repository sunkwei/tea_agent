"""spill — 大文本落盘引用（借鉴 dsh spill 子系统：SpillRef/SpillLocator）。

问题：toolkit_exec/文件读取产出的大输出直接进上下文 → 上下文爆炸、前缀缓存
抖动。策略：超过阈值的文本落盘，返回**短引用 + 头尾摘要**，模型按需读取。

- 纯 Python，落盘目录走 storage_scope（临时回退可见，不硬编码路径）
- fail-open：落盘失败绝不影响主调用，回退为原样截断
- SpillRef 自带 locator，可直接用 toolkit_file 读回
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger("spill")

# 单条文本超过该字符数即落盘（可用 TEA_SPILL_THRESHOLD 覆盖）
DEFAULT_THRESHOLD = 30_000
# 落盘后返回的头/尾摘要各保留字符数
HEAD_CHARS = 2_000
TAIL_CHARS = 1_000


def spill_threshold() -> int:
    raw = os.environ.get("TEA_SPILL_THRESHOLD", "").strip()
    if not raw:
        return DEFAULT_THRESHOLD
    try:
        v = int(float(raw))
    except (ValueError, OverflowError):
        return DEFAULT_THRESHOLD
    return v if v > 0 else DEFAULT_THRESHOLD


def _spill_dir() -> str | None:
    """spill 落盘目录：<项目 db 同级>/spill；无库时 None（回退截断）。"""
    try:
        from tea_agent.store import peek_storage

        st = peek_storage()
        if st is None:
            return None
        base = os.path.dirname(os.path.abspath(st.db_path))
        d = os.path.join(base, "spill")
        os.makedirs(d, exist_ok=True)
        return d
    except Exception as e:  # noqa: BLE001 — 无库/只读环境静默回退
        logger.debug("spill: 取目录失败，回退截断: %s", e)
        return None


def _truncate(text: str, threshold: int) -> dict:
    """不落盘的回退形态：截断 + 头尾摘要。"""
    return {
        "spilled": False,
        "truncated": True,
        "locator": "",
        "chars": len(text),
        "preview": (
            text[:HEAD_CHARS] + f"\n...[输出过长，已截断：共 {len(text)} 字符，阈值 {threshold}，仅保留头 {HEAD_CHARS}]...\n" + text[-TAIL_CHARS:]
        ),
    }


def spill_text(text: str, *, source: str = "", threshold: int | None = None) -> dict:
    """大文本落盘并返回 SpillRef 形态（供工具结果引用化）。

    Args:
        text: 待处理文本
        source: 来源标注（如 "toolkit_exec.stdout"），仅用于日志
        threshold: 覆盖默认阈值

    Returns:
        {"spilled": bool, "truncated": bool, "locator": str, "chars": int,
         "preview": str} —— locator 非空表示完整内容落盘路径
    """
    limit = threshold if threshold is not None else spill_threshold()
    if len(text) <= limit:
        return {"spilled": False, "truncated": False, "locator": "", "chars": len(text), "preview": text}

    d = _spill_dir()
    if d is None:
        return _truncate(text, limit)
    try:
        name = f"spill_{int(time.time() * 1000)}_{abs(hash(source + str(len(text)))) % 100000}.txt"
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return {
            "spilled": True,
            "truncated": False,
            "locator": path,
            "chars": len(text),
            "preview": (
                text[:HEAD_CHARS] + f"\n...[输出过长，已落盘：共 {len(text)} 字符，"
                f"完整内容见 locator，可用 toolkit_file(action='read') 读取]...\n" + text[-TAIL_CHARS:]
            ),
        }
    except Exception as e:  # noqa: BLE001 — 落盘失败回退截断，绝不影响主调用
        logger.warning("spill: 落盘失败(%s)，回退截断", e)
        return _truncate(text, limit)


def maybe_spill(text: str, *, source: str = "", threshold: int | None = None) -> str:
    """便捷入口：小文本原样返回，大文本返回引用化 preview。"""
    if len(text) <= (threshold if threshold is not None else spill_threshold()):
        return text
    return spill_text(text, source=source, threshold=threshold)["preview"]
