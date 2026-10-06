"""Muse/Spark inline-thinking 合成 —— 从正文抽取思考预览。

背景
────
Muse Spark 经 opencode 代理时不返回 ``delta.reasoning_content``，思考内容混在
``content`` 里。本模块从正文前置片段合成一段思考预览，供前端思考面板显示；
**正文不被截断**（原文仍完整保留在回复中）。

抽取动机
────────
该逻辑原先内联在 ``OnlineToolSession._process_stream_with_reasoning`` 的流式热循环
里，用四个布尔量交叉判断（其中 ``_has_real_rc`` 是赋值后再未读取的死代码），既难读
也难单测。现收敛为「一个纯函数 + 一个有状态小对象」，流式与非流式共用同一套判定常量。

口径（与重构前逐条对应，纯提取、不改行为）
────────────────────────────────────────
- 触发前提：模型名含 ``muse``/``spark``；流式还要求 ``enable_thinking``。
- 原生 reasoning 优先：已收到真实 reasoning 时**永不**用正文合成。
- 流式预算：合成思考最多 :data:`THINK_BUDGET` 字符；正文累计超 :data:`CONTENT_GUARD`
  后停止合成；累计达 :data:`THINK_DONE_AT`（或遇到 ``### 第一步``）即闭合思考面板。
- 流式起步：正文累计 < :data:`CONTENT_EARLY` 视为「开头」，首包超过
  :data:`MIN_CONTENT_LEN` 才起合成；否则须首包自带思考标记。
- 收尾兜底：流结束时若已产出思考但未闭合，补发 ``[THINK_DONE]``。重构前该兜底
  **只对 ``muse`` 生效、不含 ``spark``**，此处按原样保留（不在本次重构中改口径）。
"""

from __future__ import annotations

__all__ = [
    "CONTENT_EARLY",
    "CONTENT_GUARD",
    "MIN_CONTENT_LEN",
    "NONSTREAM_MIN_LEN",
    "NONSTREAM_SYNTH_BUDGET",
    "THINK_BUDGET",
    "THINK_DONE_AT",
    "MuseThinkingSynthesizer",
    "is_muse_model",
    "synth_nonstream_thinking",
]

THINK_BUDGET = 1600  # 流式合成思考字符上限
THINK_DONE_AT = 1200  # 累计达此长度即闭合思考面板
CONTENT_GUARD = 2200  # 正文累计超此长度 → 不再合成
CONTENT_EARLY = 600  # 正文累计 < 此长度视为「开头」，可起合成
MIN_CONTENT_LEN = 20  # 开头短包（≤ 此长度）不足以判定为思考
NONSTREAM_SYNTH_BUDGET = 1600  # 非流式合成思考字符上限
NONSTREAM_MIN_LEN = 200  # 非流式：短正文须命中关键词才合成

# 非流式判据：正文够长，或含下列任一思考痕迹词
_MUSE_MARKERS = ("思考", "推理", "逐步", "分析", "think")


def is_muse_model(model: str) -> bool:
    """模型名是否属于 Muse/Spark 系（这类模型的思考写在 content 里）。

    Args:
        model: 模型名（大小写不敏感，允许 ``None``/空串）。

    Returns:
        名称含 ``muse`` 或 ``spark`` 时为 ``True``。
    """
    name = (model or "").lower()
    return "muse" in name or "spark" in name


def _looks_like_thinking(text: str) -> bool:
    """首包是否自带思考标记（``### 思考`` 或短前缀含「思考/推理」）。"""
    if text.lstrip().startswith("### 思考"):
        return True
    return "思考" in text[:160] or "逐步推理" in text[:160] or "推理" in text[:80]


def synth_nonstream_thinking(model: str, content: str) -> str:
    """非流式：从完整正文合成思考预览。

    Args:
        model: 模型名。
        content: 非流式响应的完整正文。

    Returns:
        合成出的思考文本；模型不符 / 正文为空 / 正文不像思考时返回 ``""``。
    """
    if not content or not is_muse_model(model):
        return ""
    if len(content) <= NONSTREAM_MIN_LEN and not any(k in content for k in _MUSE_MARKERS):
        return ""  # 短回答不足以判定为思考，宁可不合成也不误报
    return content[:NONSTREAM_SYNTH_BUDGET]


class MuseThinkingSynthesizer:
    """流式 Muse inline-thinking 合成器（每轮请求新建一个实例）。

    调用方在流式热循环里对每个 ``delta.content`` 调 :meth:`feed`，把返回的文本追加进
    reasoning 缓冲并回调 ``[THINK]``；``done`` 为真时补发 ``[THINK_DONE]``。流结束时调
    :meth:`needs_final_done` 决定是否补闭合，然后丢弃实例。
    """

    def __init__(self, model: str, enable_thinking: bool) -> None:
        """
        Args:
            model: 模型名。
            enable_thinking: 会话是否启用思考（关闭时不做任何合成）。
        """
        self.model = model or ""
        self._synth_capable = bool(enable_thinking) and is_muse_model(self.model)
        # 收尾兜底口径：重构前只对 "muse" 生效（不含 spark），按原样保留
        self._final_done_applies = "muse" in self.model.lower()
        self._native_rc_seen = False  # 是否收到过原生 reasoning_content
        self.active = False  # 已越过首包判定、进入合成
        self.done = False  # 已发出 [THINK_DONE]

    def note_native_reasoning(self) -> None:
        """告知合成器：本轮已收到原生 ``reasoning_content``。

        原生 reasoning 与正文合成互斥 —— 有真思考就不该再拿正文冒充。由调用方在收到
        reasoning 增量时显式通知，而不是让合成器从「reasoning 缓冲区非空」反推：缓冲区
        非空也可能来自合成自身，反推会把调用顺序变成隐藏契约。
        """
        self._native_rc_seen = True

    def feed(self, delta_content: str, reasoning_len: int, content_len: int) -> tuple[str, bool]:
        """消费一个正文增量，判定是否合成思考。

        Args:
            delta_content: 本增量正文（空则不计）。
            reasoning_len: **本增量之前**已累计的 reasoning 字符数。
            content_len: **本增量之前**已累计的正文（content）字符数。

        Returns:
            ``(合成思考文本, 是否应发出 [THINK_DONE])``；不合成时为 ``("", False)``。
        """
        if self.done or not self._synth_capable or not delta_content:
            return "", False
        if reasoning_len >= THINK_BUDGET or content_len >= CONTENT_GUARD:
            return "", False
        # 已有原生 reasoning → 正文不是思考，绝不再合成
        if self._native_rc_seen:
            return "", False
        if not (self.active or _looks_like_thinking(delta_content) or (content_len < CONTENT_EARLY and len(delta_content) > MIN_CONTENT_LEN)):
            return "", False

        self.active = True
        budget_left = THINK_BUDGET - reasoning_len
        take = delta_content[:budget_left] if budget_left > 0 else ""
        if not take:
            return "", False
        total = reasoning_len + len(take)
        if total >= THINK_DONE_AT or "### 第一步" in delta_content or total >= THINK_BUDGET:
            self.done = True
            return take, True
        return take, False

    def needs_final_done(self, has_reasoning: bool) -> bool:
        """流结束兜底：已产出思考但未闭合时是否需要补发 ``[THINK_DONE]``。

        Args:
            has_reasoning: 本轮是否已累计到任何 reasoning 内容。

        Returns:
            需要补发 ``[THINK_DONE]`` 时为 ``True``。
        """
        return bool(has_reasoning) and self._final_done_applies and not self.done
