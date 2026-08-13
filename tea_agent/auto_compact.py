"""
Auto-Compact v3.0 — 自动上下文压缩系统（借鉴 Pi Agent Harness）

增强功能：
  - Retry with exponential backoff（压缩失败自动重试）
  - Configurable compaction settings（可配置阈值/保留轮次/最大token）
  - Branch summarization（分支摘要）
  - CompactionPipeline 集成（可插入 agent pipeline）
  - 更好的 token 估算和诊断

使用：
    from auto_compact import (
        estimate_tokens, should_compact, compact_messages,
        get_max_context_tokens, CompactionSettings, CompactionPipeline
    )

    settings = CompactionSettings(threshold=0.75, keep_recent=5)
    pipeline = CompactionPipeline(settings=settings)
    result = pipeline.run(messages, config)
"""

import json
import logging
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("auto_compact")


# ═══ Token 估算 ═════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """估算 token 数。中文~1.5t/字, 英文~4t/字。"""
    if not text:
        return 0
    cn = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    total = len(text)
    return int(cn / 1.5 + (total - cn) / 4.0) + 4


def estimate_messages_tokens(messages: list) -> int:
    """计算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    total += 85
        elif isinstance(content, str):
            total += estimate_tokens(content)
        if msg.get("tool_calls"):
            total += estimate_tokens(json.dumps(msg["tool_calls"], ensure_ascii=False))
        rc = msg.get("reasoning_content", "")
        if rc:
            total += estimate_tokens(rc)
    return total


def get_max_context_tokens(config) -> int:
    """获取最大上下文 token 数。未知模型默认 128K。

    兼容两类入参：
    - config 对象（有 main_model）→ 从 main_model.max_context_tokens / options 读取
    - SessionContext 等（有 model 字符串）→ 模型名推断
    均未配置时按模型名映射（deepseek/gemini→1M, claude→200K, gpt-4→128K），
    未知模型保守默认 128K——保证任何情况下裁剪链都有可用上限。
    """
    try:
        main = getattr(config, "main_model", None)
        if main is not None:
            if hasattr(main, "max_context_tokens") and main.max_context_tokens:
                return int(main.max_context_tokens)
            val = getattr(main, "options", {}).get("max_context_tokens", 0)
            if val:
                return int(val)
            model = (main.model_name or "").lower()
        else:
            # 直接传入 SessionContext / 任意带 model 属性的对象
            model = (getattr(config, "model", "") or "").lower()
        defaults = {
            "gpt-4": 128000,
            "claude": 200000,
            "deepseek": 1048576,
            "gemini": 1048576,
            "mimo": 1048576,  # Xiaomi MiMo V2.5 (1M context)
        }
        for k, v in defaults.items():
            if k in model:
                return v
        return 128000
    except Exception:
        return 128000


# ═══ 配置 ════════════════════════════════════════════════

@dataclass
class CompactionSettings:
    """Compaction 配置 — 借鉴 Pi 的 DEFAULT_COMPACTION_SETTINGS。"""
    threshold: float = 0.8          # 触发压缩的 token 阈值（占 max_context 的比例）
    budget_warn_ratio: float = 0.15  # token_budget 报警阈值（剩余空间占比低于此值即警告）
    keep_recent: int = 5            # 保留的最新轮次数
    max_summary_length: int = 1500  # 摘要最大字符数
    min_messages_before_compact: int = 10  # 最少消息数才触发压缩
    branch_summary_length: int = 800      # 分支摘要最大字符数
    enabled: bool = True            # 是否启用自动压缩

    # 四级水位线（借鉴 MUR AI 方案，对齐社区共识）
    #   ratio < tier1_ratio                → Tier 0：什么都不做
    #   tier1_ratio ≤ ratio < tier2_ratio  → Tier 1：Snip（轻度截短老工具输出，0 成本）
    #   tier2_ratio ≤ ratio < tier3_ratio  → Tier 2：Prune（占位符替换 + assistant 旧文本裁剪）
    #   ratio ≥ tier3_ratio                → Tier 3：Summarize（增量 LLM 摘要兜底）
    # ratio = 当前 token / max_context（用真实 usage 校准后的估算）
    tier1_ratio: float = 0.60
    tier2_ratio: float = 0.80
    tier3_ratio: float = 0.95
    # Tier 1 Snip 阈值：工具输出字符数超过该值才截短（保留头部摘要行）
    snip_threshold: int = 16384
    # Tier 2/3 删除旧轮次时的 token 保护区大小（最近 N token 内任何消息不参与删除）
    protect_tokens: int = 4096

    # 重试配置
    max_retries: int = 3            # 最大重试次数
    retry_base_delay: float = 1.0   # 初始重试延迟（秒）
    retry_max_delay: float = 30.0   # 最大重试延迟（秒）

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "budget_warn_ratio": self.budget_warn_ratio,
            "keep_recent": self.keep_recent,
            "max_summary_length": self.max_summary_length,
            "enabled": self.enabled,
            "max_retries": self.max_retries,
        }


DEFAULT_COMPACTION_SETTINGS = CompactionSettings()


def classify_waterline(ratio: float, settings: CompactionSettings | None = None) -> int:
    """按 token 水位线分类当前压力等级（借鉴 MUR AI 四级水位线）。

    Args:
        ratio: 当前 token 用量 / 上下文上限（0~1+，用真实 usage 校准后的估算）
        settings: 水位线阈值配置（None=默认 0.6/0.8/0.95）

    Returns:
        0 = 安全（不操作） / 1 = Snip / 2 = Prune / 3 = Summarize
    """
    s = settings or DEFAULT_COMPACTION_SETTINGS
    if ratio >= s.tier3_ratio:
        return 3
    if ratio >= s.tier2_ratio:
        return 2
    if ratio >= s.tier1_ratio:
        return 1
    return 0


def waterline_name(tier: int) -> str:
    """水位线等级名称（供日志/可观测性使用）。"""
    names = {0: "Tier0-安全", 1: "Tier1-Snip", 2: "Tier2-Prune", 3: "Tier3-Summarize"}
    return names.get(tier, "Tier" + str(tier))


# ═══ 核心压缩逻辑 ═══════════════════════════════════════

def should_compact(
    messages: list,
    max_tokens: int,
    threshold: float = 0.8,
    min_messages: int = 10,
) -> tuple[bool, int]:
    """判断是否需要压缩。

    Args:
        messages: 消息列表
        max_tokens: 最大上下文 token 数
        threshold: 触发阈值 (0~1)
        min_messages: 最少消息数

    Returns:
        (needs_compact, current_tokens)
    """
    if max_tokens <= 0:
        return False, 0
    if len(messages) < min_messages:
        return False, 0

    current = estimate_messages_tokens(messages)
    if current >= max_tokens * threshold:
        logger.warning(f"🔔 Compaction trigger: {current}/{max_tokens} tok ({current/max_tokens*100:.0f}%)")
        return True, current
    return False, current


def compact_messages(
    messages: list,
    keep_recent: int = 5,
    summary: str = "",
    max_summary_length: int = 1500,
) -> tuple[list, str]:
    """压缩历史消息。

    保留最近的 keep_recent 轮，将旧消息合并到摘要。

    Args:
        messages: 完整消息列表
        keep_recent: 保留的最近轮次数
        summary: 已有的摘要文本
        max_summary_length: 摘要最大长度

    Returns:
        (compressed_messages, new_summary)
    """
    if not messages:
        return messages, summary

    sys_msgs = [m for m in messages if m.get("role") == "system"]
    others = [m for m in messages if m.get("role") != "system"]

    if len(others) <= keep_recent * 2:
        return messages, summary

    recent = others[-keep_recent * 2:] if keep_recent > 0 else []
    older = others[:-keep_recent * 2] if keep_recent > 0 else others

    # 构建旧消息摘要
    older_text = ""
    for m in older:
        r = m.get("role", "")
        c = m.get("content", "")
        if isinstance(c, str) and c:
            # 只取关键内容的前 200 字符
            older_text += f"[{r}] {c[:200]}\n"
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "text":
                    older_text += f"[{r}] {part.get('text', '')[:200]}\n"
                    break

    # 合并摘要
    if older_text and len(older_text) > 50:
        new_text = older_text[:max_summary_length]
        if summary:
            summary = (summary + "\n---\n" + new_text)[:max_summary_length]
        else:
            summary = new_text

    # 构建压缩后的消息列表
    compressed = list(sys_msgs)
    if summary:
        compressed.append({"role": "system", "content": f"[历史摘要] {summary}"})
    compressed.extend(recent)

    before = len(messages)
    after = len(compressed)
    logger.info(f"📦 Compaction: {before} msgs → {after} msgs (keep_recent={keep_recent})")

    return compressed, summary


# ═══ 重试机制 ════════════════════════════════════════════

def retry_with_backoff(
    func: callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (Exception,),
) -> Any:
    """带指数退避的重试装饰器/执行器。

    Args:
        func: 要执行的函数
        max_retries: 最大重试次数
        base_delay: 初始延迟（秒）
        max_delay: 最大延迟（秒）
        retryable_exceptions: 可重试的异常类型

    Returns:
        函数执行结果
    """
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
                logger.warning(
                    f"🔄 Compaction retry {attempt + 1}/{max_retries} "
                    f"after {delay:.1f}s: {e}"
                )
                time.sleep(delay)
            else:
                logger.error(f"✗ Compaction failed after {max_retries} retries: {e}")
                raise
    raise last_exception  # type: ignore


# ═══ 分支摘要 ════════════════════════════════════════════

def generate_branch_summary(
    messages: list,
    max_length: int = 800,
) -> str:
    """为分支生成摘要。

    当会话在树中切换分支时，为离开的分支生成摘要，
    以便在切换后保持上下文连续性（借鉴 Pi 的 branch-summarization）。

    Args:
        messages: 分支中的消息
        max_length: 摘要最大长度

    Returns:
        摘要文本
    """
    if not messages:
        return ""

    # 提取关键信息：用户问题 + 关键决策 + 结论
    key_points = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )

        if role == "user" and content:
            key_points.append(f"用户: {content[:300]}")
        elif role == "assistant" and content:
            # 只保留助理回复的前 200 字符
            key_points.append(f"助理: {content[:200]}")

    summary = "\n".join(key_points)
    if len(summary) > max_length:
        summary = summary[:max_length] + "..."

    return summary


# ═══ Compaction Pipeline ═════════════════════════════════

class CompactionPipeline:
    """可插入 pipeline 的自动压缩管线。

    用法：
        pipeline = CompactionPipeline(settings=CompactionSettings())
        result = pipeline.run(messages, context)

    返回：
        {
            "compacted": True/False,
            "messages": compressed_messages,  # 仅 compacted=True 时
            "tokens_before": int,
            "tokens_after": int,
            "stats": {...}                    # 统计信息
        }
    """

    def __init__(self, settings: CompactionSettings | None = None):
        self.settings = settings or DEFAULT_COMPACTION_SETTINGS
        self._summary = ""  # 跨调用保持的摘要
        self._compact_count = 0
        self._last_compact_time = 0.0

    def run(
        self,
        messages: list,
        config: Any = None,
        force: bool = False,
    ) -> dict:
        """执行一次压缩检查。

        Args:
            messages: 当前消息列表
            config: 配置对象（从中读取 max_context_tokens）
            force: 是否强制压缩（忽略阈值）

        Returns:
            压缩结果字典
        """
        if not self.settings.enabled and not force:
            return {"compacted": False}

        max_tokens = get_max_context_tokens(config) if config else 128000
        needs, cur = should_compact(
            messages, max_tokens,
            self.settings.threshold if not force else 0.0,
            self.settings.min_messages_before_compact if not force else 0,
        )

        if not needs and not force:
            return {"compacted": False}

        # ── 压缩前 hooks（可记录现场 / 修改消息）──
        hook_ctx = {
            "messages": list(messages),
            "tokens_before": cur,
            "reason": "force" if force else f"threshold_{self.settings.threshold}",
            "settings": self.settings,
        }
        messages = run_pre_compact_hooks(hook_ctx)

        # 执行压缩（带重试）
        def _do_compact():
            compressed, new_summary = compact_messages(
                messages,
                keep_recent=self.settings.keep_recent,
                summary=self._summary,
                max_summary_length=self.settings.max_summary_length,
            )
            self._summary = new_summary
            self._compact_count += 1
            self._last_compact_time = time.time()
            return compressed

        try:
            if self.settings.max_retries > 0:
                compressed = retry_with_backoff(
                    _do_compact,
                    max_retries=self.settings.max_retries,
                    base_delay=self.settings.retry_base_delay,
                    max_delay=self.settings.retry_max_delay,
                )
            else:
                compressed = _do_compact()

            after_tokens = estimate_messages_tokens(compressed)

            result = {
                "compacted": True,
                "messages": compressed,
                "summary": self._summary,
                "tokens_before": cur,
                "tokens_after": after_tokens,
                "saved_tokens": cur - after_tokens,
                "stats": {
                    "compact_count": self._compact_count,
                },
            }
            # ── 压缩后 hooks（可校验 / 上报结果）──
            result = run_post_compact_hooks(result)
            return result

        except Exception as e:
            logger.error(f"✗ CompactionPipeline failed: {e}")
            return {
                "compacted": False,
                "error": str(e)[:300],
                "tokens_before": cur,
            }

    def reset(self):
        """重置 pipeline 状态。"""
        self._summary = ""
        self._compact_count = 0
        self._last_compact_time = 0.0

    @property
    def summary(self) -> str:
        """获取当前累积摘要。"""
        return self._summary

    @summary.setter
    def summary(self, value: str):
        self._summary = value


# ═══ 兼容旧版 API ═══════════════════════════════════════

class AutoCompactStep:
    """兼容旧版的可调用压缩步骤。

    用法与之前相同：
        step = AutoCompactStep(threshold=0.8, keep_recent=5)
        result = step(context, messages)
    """

    def __init__(self, threshold: float = 0.8, keep_recent: int = 5):
        self._pipeline = CompactionPipeline(
            settings=CompactionSettings(
                threshold=threshold,
                keep_recent=keep_recent,
        ))

    def __call__(self, context, messages, **kw):
        return self._pipeline.run(messages, config=context.config if hasattr(context, 'config') else None)

    @property
    def summary(self) -> str:
        return self._pipeline.summary

    def reset(self):
        self._pipeline.reset()


# ═══ 压缩 Hooks 扩展点（借鉴 Codex run_pre/post_compact_hooks）═══

# 模块级 hook 注册表（全局共享，跨 CompactionPipeline 实例）
_pre_compact_hooks: list[Callable[[dict], Any]] = []
_post_compact_hooks: list[Callable[[dict], Any]] = []


def register_pre_compact_hook(fn: Callable[[dict], Any]) -> None:
    """注册压缩前 hook。

    hook 签名: fn(ctx: dict) -> list | None
      - ctx 含 messages/tokens_before/reason/settings
      - 返回 list 可替换待压缩的消息；返回 None 表示不修改

    Args:
        fn: hook 函数
    """
    if fn not in _pre_compact_hooks:
        _pre_compact_hooks.append(fn)


def register_post_compact_hook(fn: Callable[[dict], Any]) -> None:
    """注册压缩后 hook。

    hook 签名: fn(result: dict) -> dict | None
      - result 含 compacted/messages/summary/tokens_*/saved_tokens
      - 返回 dict 可修改结果；返回 None 表示不修改

    Args:
        fn: hook 函数
    """
    if fn not in _post_compact_hooks:
        _post_compact_hooks.append(fn)


def unregister_pre_compact_hook(fn: Callable[[dict], Any]) -> None:
    """注销压缩前 hook。"""
    if fn in _pre_compact_hooks:
        _pre_compact_hooks.remove(fn)


def unregister_post_compact_hook(fn: Callable[[dict], Any]) -> None:
    """注销压缩后 hook。"""
    if fn in _post_compact_hooks:
        _post_compact_hooks.remove(fn)


def clear_compact_hooks() -> None:
    """清空所有压缩 hooks。"""
    _pre_compact_hooks.clear()
    _post_compact_hooks.clear()


def run_pre_compact_hooks(ctx: dict) -> list:
    """执行所有压缩前 hooks（失败隔离，单个异常不影响整体）。

    Args:
        ctx: 压缩前上下文（messages/tokens_before/reason/settings）

    Returns:
        待压缩的消息列表（可能被 hook 修改）
    """
    messages = ctx.get("messages", [])
    for fn in list(_pre_compact_hooks):
        try:
            result = fn(ctx)
            if isinstance(result, list):
                messages = result
                ctx["messages"] = messages
        except Exception as e:
            logger.warning(f"pre_compact_hook {getattr(fn, '__name__', fn)} 失败: {e}")
    return messages


def run_post_compact_hooks(result: dict) -> dict:
    """执行所有压缩后 hooks（失败隔离）。

    Args:
        result: 压缩结果字典

    Returns:
        可能被 hook 修改的结果字典
    """
    for fn in list(_post_compact_hooks):
        try:
            modified = fn(result)
            if isinstance(modified, dict):
                result = modified
        except Exception as e:
            logger.warning(f"post_compact_hook {getattr(fn, '__name__', fn)} 失败: {e}")
    return result
