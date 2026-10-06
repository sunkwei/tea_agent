"""turn_meta — turn/step 生命周期与「新请求序列」判定（借鉴 dsh turn/step 语义）。

术语对齐 dsh：
- **step** = 一次模型请求 + 它引发的工具调用（对应本项目 `iterations` +1）
- **turn** = 零个或多个 step，从用户输入进入到无待办为止
- **startsRequestSeries** = 本次请求的消息前缀与上一次不再连续，前缀缓存必然
  重置 —— 对 DeepSeek 这类按前缀缓存计费/计时的供应商，这是关键观测点

判定是纯函数：`prev`（上次请求的 messages）必须是 `current` 的**逐条前缀**，
否则即新序列（历史被压缩/改写/系统提示词变化都会触发）。
配套不变式 `session.prefix_stable`：前缀被改写却未声明新序列，说明有旁路
改写了历史 —— 与 AGENTS.md「自进化不得修改用户对话历史」直接相关。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field

from tea_agent.invariants import InvariantViolation
from tea_agent.invariants import registry as _invariants

logger = logging.getLogger("turn_meta")


def _msg_key(msg: dict, *, ignore_reasoning: bool = False) -> str:
    """单条消息的等价指纹（role + 内容 + 工具标识，忽略无关字段顺序）。

    ignore_reasoning=True 时剥离 ``reasoning_content``：它是模型内部思考链，
    框架在跨块边界有意置空（``_blank_stale_reasoning`` 上下文治理）——这是
    合法的缓存治理动作，不是「对话历史被旁路改写」，不构成 prefix_stable 违例。
    """
    try:
        if ignore_reasoning and isinstance(msg, dict) and "reasoning_content" in msg:
            msg = {k: v for k, v in msg.items() if k != "reasoning_content"}
        raw = json.dumps(msg, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = repr(msg)
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def _same_series(prev: list[dict] | None, current: list[dict] | None, *, ignore_reasoning: bool = False) -> bool:
    """prev 是否为 current 的逐条前缀（内部实现，可切换 reasoning 口径）。"""
    if not prev:
        return False
    cur = current or []
    if len(prev) > len(cur):
        return False
    return all(
        _msg_key(a, ignore_reasoning=ignore_reasoning) == _msg_key(b, ignore_reasoning=ignore_reasoning) for a, b in zip(prev, cur, strict=False)
    )  # cur 可更长（尾部追加）


def same_series(prev: list[dict] | None, current: list[dict] | None) -> bool:
    """prev 是否为 current 的逐条前缀（True=同一请求序列，前缀缓存可延续）。

    纯函数、无副作用；None/空 prev 视为新序列（首个请求无从延续）。
    注：``reasoning_content`` 参与比较——它被置空同样使前缀缓存失效，故按
    新序列计（starts_request_series 口径）；但 prefix_stable 违例判定用
    ``ignore_reasoning=True``（置空是治理，非历史改写），二者口径不同。
    """
    return _same_series(prev, current)


@dataclass
class StepRecord:
    """一次 step 的元信息（观测用，不进对话历史）。"""

    index: int
    starts_request_series: bool
    message_count: int


@dataclass
class TurnMetaTracker:
    """跟踪 turn/step 边界与请求序列连续性。

    `last_violations` 保存不变式违例（旁路观测，永不抛出），调用方决定如何记录。
    """

    turns: int = 0
    steps: list[StepRecord] = field(default_factory=list)
    last_violations: list[InvariantViolation] = field(default_factory=list)
    _prev: list[dict] | None = field(default=None, repr=False)

    def begin_turn(self) -> None:
        """新 turn 开始：step 计数清零，请求序列上下文保留（跨 turn 可延续）。"""
        self.turns += 1
        self.steps.clear()

    def note_request(self, messages: list[dict], *, declared: bool | None = None, **extra) -> bool:
        """记录一次模型请求，返回是否 startsRequestSeries。

        Args:
            messages: 本次请求的完整消息列表
            declared: 调用方显式声明的新序列标志；None=自动判定
            **extra: 透传给不变式检查器的附加上下文

        Returns:
            True = 新请求序列（前缀缓存重置）
        """
        starts = bool(declared) if declared is not None else not same_series(self._prev, messages)
        self.steps.append(
            StepRecord(
                index=len(self.steps),
                starts_request_series=starts,
                message_count=len(messages or ()),
            )
        )
        try:
            self.last_violations = _invariants.run("session.request", prev=self._prev, current=messages, declared=declared, **extra)
        except Exception as e:  # noqa: BLE001 — 不变式检查永不影响请求
            logger.debug("turn_meta invariant 跳过: %s", e)
            self.last_violations = []
        self._prev = list(messages or ())
        return starts

    def summary(self) -> dict:
        """当前 turn 的步进摘要（供 turn_snapshot / 调试用）。"""
        return {
            "turns": self.turns,
            "steps": len(self.steps),
            "request_series_resets": sum(1 for s in self.steps if s.starts_request_series),
        }


def _check_prefix_stable(*, prev, current, declared, **_) -> str | None:
    """前缀被改写（非追加）就必须声明新序列，否则属于未声明的历史改写。

    reasoning_content 不参与语义比较：框架的 ``_blank_stale_reasoning`` 在
    跨块边界有意把旧思考链置空以治理上下文填充，属合法缓存治理，不构成
    「对话历史被旁路改写」——若纳入比较，工具循环每 rc_keep_steps 步就刷
    一条误报 ERROR（实测 prev=123→current=125 即此类噪声）。
    """
    if declared or not prev:
        return None
    if _same_series(prev, current, ignore_reasoning=True):
        return None
    return f"消息前缀被改写但未声明 startsRequestSeries (prev={len(prev)} 条, current={len(current or ())} 条)"


_invariants.install("session.prefix_stable", "session.request", _check_prefix_stable, "历史只允许尾部追加；改写前缀必须声明新请求序列")
