"""工具调用循环执行器 v4.0 — 支持并行工具执行（借鉴 Pi Agent Harness）

新增:
  - ParallelExecutor: 并行工具执行引擎，自动检测依赖关系
  - 混合执行模式：有依赖的串行，无依赖的并行
  - 智能依赖分析：基于工具名和参数推断
  - 原有 LoopDetector 和工具执行逻辑保持不变
"""

import json
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from tea_agent.session.message_queue import (
    drain_steering_items,
    inject_steering_messages,
)

logger = logging.getLogger("session.tool_loop_runner")


def _extract_api_error_detail(exc: Exception) -> str:
    """提取 API 异常中的完整错误体，用于定位 4xx 具体原因。

    OpenAI SDK / httpx 异常通常携带 response 对象，其 body 含服务端返回的
    具体错误信息（如 DeepSeek 400 "must be passed back" / context length /
    invalid tool_calls）。仅 str(exc) 会丢失这些关键细节，导致无法区分
    4xx 类型。此函数尽力提取 status_code + response body，提取失败时
    回退到 str(exc)。

    Args:
        exc: 捕获到的异常对象

    Returns:
        格式化后的错误详情字符串
    """
    parts = [f"{type(exc).__name__}: {exc}"]
    try:
        resp = getattr(exc, "response", None)
        if resp is not None:
            status = getattr(resp, "status_code", None)
            if status is not None:
                parts.append(f"status={status}")
            # 优先结构化 body，其次原始文本
            body = getattr(resp, "text", None)
            if not body:
                body = getattr(resp, "body", None)
            if body:
                body_str = body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
                if len(body_str) > 2000:
                    body_str = body_str[:2000] + "...[截断]"
                parts.append(f"body={body_str}")
    except Exception:
        pass
    return " | ".join(parts)


def _is_rc_passed_back_error(err_str: str) -> bool:
    """识别 DeepSeek thinking 模式 RC 回传 400。

    错误签名（官方/社区一致）：`The reasoning_content in the thinking mode
    must be passed back to the API.` 附带 invalid_request_error / 400。
    err_str 是 str(exc)，SDK 通常把服务端 message 原样带出；同时兼容只含
    message 片段的情况（部分代理网关只透传 message）。
    """
    if not err_str:
        return False
    return (
        "reasoning_content" in err_str
        and "passed back" in err_str
        and "400" in err_str
    )


def _log_rc_diagnostic(session, api_messages: list[dict]) -> None:
    """输出 400 现场诊断：逐条列出 assistant 消息的 RC 状态，定位哪条消息异常。

    覆盖两类风险：
    - 字段缺失（None）→ 发送前防御补全已兜底，但若仍出现说明补全门控未命中
    - 值为空/异常 → 可能是值被改写/截断（如代理网关截断长思考），客户端无法还原
    """
    try:
        lines = [f"  role=assistant 消息清单 (共 {len(api_messages)} 条):"]
        for _i, _m in enumerate(api_messages):
            if _m.get("role") != "assistant":
                continue
            rc = _m.get("reasoning_content")
            _tc = bool(_m.get("tool_calls"))
            _content = _m.get("content") or ""
            if rc is None:
                lines.append(
                    f"  [{_i}] tool_calls={_tc} RC=缺失 content_len={len(_content) if isinstance(_content, str) else '?'}"
                )
            else:
                lines.append(
                    f"  [{_i}] tool_calls={_tc} RC_len={len(rc)}"
                    f" RC_head={rc[:40]!r} content_len={len(_content) if isinstance(_content, str) else '?'}"
                )
        logger.warning("DeepSeek RC 回传 400 现场诊断:\n" + "\n".join(lines))
    except Exception:
        logger.warning("RC 400 现场诊断生成失败", exc_info=True)


# ═══ A8: 上下文溢出防线（max_context_tokens × max_tokens 感知）═══

def _parse_context_overflow(err_str: str) -> dict | None:
    """解析"模型上下文溢出" 400 错误体（输入 + 输出 > 窗口）。

    A8: API（OpenAI/DeepSeek 兼容）在 `input + max_tokens > window` 时返回：
      "This model's maximum context length is {N} tokens. However, you
       requested {M} output tokens and your prompt contains at least {P}
       input tokens, for a total of at least {T} tokens."
    错误同时揭示三件自愈所需的关键信息：模型真实窗口 N、请求的输出 M、
    实际输入 P。部分网关/SDK 只透传片段或通用措辞
    （"maximum context length exceeded" / "context_length_exceeded" /
    "prompt is too long"），命中 400 + 上下文长度签名即视为溢出
    （字段为 None，自愈按配置窗口兜底）。

    Args:
        err_str: str(exc)（SDK 通常原样带出服务端 message）

    Returns:
        None: 非上下文溢出错误（调用方继续原有 4xx 分类）；
        dict: {"max_ctx": int|None, "requested_out": int|None,
               "prompt_tokens": int|None}
    """
    if not err_str:
        return None
    s = err_str.lower()
    is_overflow = (
        "maximum context length" in s
        or "context length exceeded" in s
        or "context_length_exceeded" in s
        or "prompt is too long" in s
        or ("context length" in s and "400" in s)
    )
    if not is_overflow:
        return None
    info: dict = {"max_ctx": None, "requested_out": None, "prompt_tokens": None}
    m = re.search(r"maximum context length is\s+(\d+)\s*tokens?", s)
    if m:
        info["max_ctx"] = int(m.group(1))
    m = re.search(r"requested\s+(\d+)\s*output tokens", s)
    if m:
        info["requested_out"] = int(m.group(1))
    m = re.search(r"contains (?:at least )?(\d+)\s*input tokens", s)
    if m:
        info["prompt_tokens"] = int(m.group(1))
    return info


def _request_max_tokens(session, eff: dict) -> int | None:
    """实际发送的请求 max_tokens（A8：按求解器输出上限钳制）。

    - 求解器已给出上限（context._output_cap，由 build_api_messages 记录）：
      配置 max_tokens 被钳制到其内——窗口小、配置输出大时自动收缩
      （如 150K 窗口 + 65536 输出），保证 输入+输出+余量 ≤ 窗口；
    - 配置 max_tokens 缺失/0：发送求解器上限（而非"不限"），防止
      输出侧无界增长顶爆窗口；
    - 求解器无上限（预算不可解）：回退配置值（原行为）。

    Args:
        session: OnlineToolSession
        eff: session._get_effective_params() 返回的参数 dict

    Returns:
        实际请求的 max_tokens（None=不传，由服务端默认）
    """
    cfg_mt = eff.get("max_tokens") or 0
    cap = int(getattr(session.context, "_output_cap", 0) or 0)
    if cap <= 0:
        return cfg_mt or None
    if cfg_mt <= 0:
        return cap
    return min(int(cfg_mt), cap)


def _ensure_within_output_budget(session) -> None:
    """发送前护栏（A8 主动）：预计 输入+输出 将超窗口时，强制重新裁剪。

    工具循环每轮追加新工具结果，而缓存友好的 _loop_trim_done 使同回合
    后续构建跳过裁剪——一旦输入越过 窗口-输出上限-余量，请求就会 400
    溢出。此处发送前检查：越过安全线即重置"首建即定型"标志，让下一次
    build_api_messages 执行完整裁剪（裁剪决策幂等、前缀仍收敛，仅在
    真的超预算时才破缓存）；若合计已超窗口，再置 _token_exhausted
    让下一回合强制 LLM 增量摘要兜底。

    异常隔离：估算/护栏失败不影响主流程（最坏退回原行为）。
    """
    ctx = session.context
    try:
        from tea_agent.session.history_builder import (
            _budget_margin,
            _resolve_max_ctx,
            estimate_messages_tokens,
        )

        max_ctx = _resolve_max_ctx(ctx)
        out_cap = int(getattr(ctx, "_output_cap", 0) or 0)
        if max_ctx <= 0 or out_cap <= 0:
            return
        est = estimate_messages_tokens(getattr(ctx, "messages", None) or [])
        # 取三源最大值：本轮消息估算 / 上次构建估算 / 上次真实 prompt_tokens
        # （S3 单次值，含 tools/system 全量开销）
        est = max(
            est,
            int(getattr(ctx, "_last_estimate_tokens", 0) or 0),
            int(getattr(ctx, "_last_request_prompt_tokens", 0) or 0),
        )
        if est + out_cap + _budget_margin(max_ctx) <= max_ctx:
            return
        ratio = est / max_ctx
        ctx._loop_max_ratio = max(float(getattr(ctx, "_loop_max_ratio", 0.0)), ratio)
        ctx._loop_trim_done = False
        if est + out_cap >= max_ctx:
            ctx._token_exhausted = True
        logger.warning(
            f"A8 发送前护栏: 估算输入 {est} + 输出 {out_cap} + 余量 > 窗口 {max_ctx}，"
            f"强制重新裁剪"
        )
    except Exception:
        logger.debug("A8 发送前护栏失败（隔离）", exc_info=True)


def _apply_context_overflow_recovery(session, info: dict) -> None:
    """400 上下文溢出自愈（A8）：修正窗口 → 收紧输出 → 强制深裁剪。

    错误揭示模型真实窗口小于配置的 max_context_tokens（如未配置按 1M
    默认 vs 模型实际 150K）时，全部裁剪链（基于配置窗口）全部失效。
    自愈步骤（积极但全部隔离、不阻塞重试）：

    1. 修正窗口：session context + 内存 config（记录日志 + 提示用户把
       修正持久化到 config.yaml——自动改用户文件过于激进，不做）；
    2. 按修正后窗口重新求解 (input_budget, output_cap)；错误揭示的真实
       输入规模若大于求解预算 → 取其一半作为一次性紧急输入预算
       （已知溢出的输入直接腰斩，保证落回安全线）；
    3. 重置水位线单调 clamp 与首建即定型标志 → 下一次构建执行最深
       本地裁剪（Tier3：Snip + 渐进式 Prune）；
    4. 置 _token_exhausted → 下一用户回合强制 LLM 增量摘要；
    5. 尽力立即调用 summarizer 强制摘要（隔离，失败不阻塞重试）。
    """
    ctx = session.context
    max_ctx_reported = int(info.get("max_ctx") or 0)

    # 1) 修正窗口（仅当错误揭示的真实窗口小于配置值时）
    if max_ctx_reported > 0:
        configured = int(getattr(ctx, "max_context_tokens", 0) or 0)
        if configured == 0 or max_ctx_reported < configured:
            if configured > 0:
                logger.warning(
                    f"A8 溢出自愈: 模型真实窗口 {max_ctx_reported} < 配置的 "
                    f"max_context_tokens {configured}（误配/未配会使裁剪链失效），"
                    f"本会话已自动修正，请同步更新 config.yaml"
                )
            else:
                logger.warning(
                    f"A8 溢出自愈: max_context_tokens 未配置，"
                    f"改用模型真实窗口 {max_ctx_reported}"
                )
            ctx.max_context_tokens = max_ctx_reported
            try:
                from tea_agent.config import get_config

                cfg = get_config()
                mm = getattr(cfg, "main_model", None) if cfg is not None else None
                if mm is not None:
                    mm_max = int(getattr(mm, "max_context_tokens", 0) or 0)
                    if mm_max == 0 or max_ctx_reported < mm_max:
                        mm.max_context_tokens = max_ctx_reported
            except Exception:
                logger.debug("A8 内存 config 修正失败（隔离）", exc_info=True)

    # 2) 按修正后窗口求解新预算
    from tea_agent.session.history_builder import (
        _get_effective_max_tokens,
        _resolve_max_ctx,
        solve_token_budget,
    )

    max_ctx = _resolve_max_ctx(ctx)
    requested = int(info.get("requested_out") or 0) or _get_effective_max_tokens(ctx)
    input_budget, out_cap = solve_token_budget(max_ctx, requested)
    prompt_tokens = int(info.get("prompt_tokens") or 0)
    if prompt_tokens > input_budget:
        # 失败的"真实输入"比求解预算还大（估算失准）→ 取一半作紧急预算
        input_budget = max(2048, int(prompt_tokens * 0.5))
    ctx._emergency_input_budget = input_budget
    ctx._output_cap = out_cap

    # 3) 重置单调 clamp 与首建即定型 → 强制下一次构建走最深裁剪
    ctx._loop_max_ratio = max(float(getattr(ctx, "_loop_max_ratio", 0.0)), 1.0)
    ctx._loop_trim_done = False

    # 4) 下一回合强制 LLM 增量摘要（最终兜底）
    ctx._token_exhausted = True

    # 5) 尽力立即强制摘要（隔离：无 storage/topic 时内部直接返回）
    try:
        summarizer = getattr(session, "summarizer_comp", None)
        if summarizer is not None:
            summarizer.summarize_old_history(
                session.api, session._get_summarize_client, force=True
            )
    except Exception:
        logger.debug("A8 紧急强制摘要失败（隔离）", exc_info=True)


# ═══ 并行工具执行引擎 ═══════════════════════════════════

class ParallelExecutor:
    """并行工具执行引擎。

    借鉴 Pi Agent Harness 的并行模式：
    - 自动检测工具调用间的依赖关系
    - 无依赖的工具并行执行
    - 有依赖的工具自动排队串行
    - 混合模式：批次内若含 serial 工具则全批转为顺序
    """

    # 标记为"顺序执行"的工具（读写类，有副作用）
    SERIAL_TOOLS = {
        "toolkit_edit", "toolkit_self_evolve",
        "toolkit_file", "toolkit_exec", "toolkit_git_commit",
        "toolkit_save", "toolkit_reload", "toolkit_diff",
    }

    # 标记为"并行安全"的工具（只读查询类）
    PARALLEL_SAFE = {
        "toolkit_file", "toolkit_search", "toolkit_lsp",
        "toolkit_config",
        "toolkit_memory", "toolkit_kb",
        "toolkit_list_provider_models",
        "toolkit_plan",
        "toolkit_batch_process", "toolkit_code_review",
    }

    def __init__(self, max_workers: int = 4, serial_if_any_serial: bool = True):
        """
        Args:
            max_workers: 最大并行线程数
            serial_if_any_serial: 批次中若有 serial 工具，整批转为顺序
        """
        self.max_workers = max_workers
        self.serial_if_any_serial = serial_if_any_serial

    def analyze_dependencies(self, tool_calls: list) -> list[list]:
        """分析工具调用间的依赖关系，分组为可并行执行的批次。

        借鉴 Pi Agent Harness 的并行模式：
        1. 如果批次中包含 SERIAL_TOOLS 中的工具，整批转为顺序（每个工具独立批次）
        2. 如果全是 PARALLEL_SAFE 工具，合并为一批并行执行
        3. 混合情况：有副作用的同名工具串行，其余并行

        Args:
            tool_calls: 工具调用列表

        Returns:
            批次列表：[[batch1_tools], [batch2_tools], ...]
            同一批次内的工具可并行执行
        """
        if not tool_calls:
            return []

        # 检查是否需要全部顺序执行
        has_serial = any(
            tc.function.name in self.SERIAL_TOOLS
            for tc in tool_calls
        )

        if has_serial and self.serial_if_any_serial:
            return [[tc] for tc in tool_calls]  # 每个工具单独一批

        # 检查是否全部是并行安全工具
        all_parallel_safe = all(
            tc.function.name in self.PARALLEL_SAFE
            for tc in tool_calls
        )

        if all_parallel_safe:
            # 全是只读查询，放一个批次并行执行
            return [list(tool_calls)]

        # 混合情况：按工具名分组
        groups: dict[str, list] = {}
        for tc in tool_calls:
            name = tc.function.name
            if name not in groups:
                groups[name] = []
            groups[name].append(tc)

        # 并行安全的组合并到一个批次，有副作用的各自独立
        batch_all = []
        serial_batches = []
        for name, calls in groups.items():
            if name in self.PARALLEL_SAFE or len(calls) <= 1:
                batch_all.extend(calls)
            else:
                # 多调用且有副作用的，每个单独一批
                for tc in calls:
                    serial_batches.append([tc])

        result = []
        if batch_all:
            result.append(batch_all)
        result.extend(serial_batches)
        return result

    @staticmethod
    def is_serial_tool(tool_name: str) -> bool:
        """判断是否是串行工具。"""
        return tool_name in ParallelExecutor.SERIAL_TOOLS

    @staticmethod
    def is_parallel_safe(tool_name: str) -> bool:
        """判断是否是并行安全工具。"""
        return tool_name in ParallelExecutor.PARALLEL_SAFE


def execute_tools_parallel(
    tool_calls: list,
    executor_func: Callable,
    max_workers: int = 4,
) -> list[dict]:
    """并行执行一批工具调用。

    使用 ThreadPoolExecutor 并行执行，保持结果顺序与输入一致。

    Args:
        tool_calls: 要执行的工具调用列表
        executor_func: 执行单个工具的函数，接受 (tc) 参数，返回 (call_id, func_name, result_str)
        max_workers: 最大并行度

    Returns:
        结果列表，与 tool_calls 顺序一致
    """
    results: list[dict | None] = [None] * len(tool_calls)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {}
        for idx, tc in enumerate(tool_calls):
            future = pool.submit(executor_func, tc)
            future_map[future] = idx

        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                call_id, func_name, result_str = future.result()
                results[idx] = {
                    "call_id": call_id,
                    "func_name": func_name,
                    "result_str": result_str,
                    "success": True,
                }
            except Exception as e:
                results[idx] = {
                    "call_id": getattr(tool_calls[idx], 'id', 'unknown'),
                    "func_name": getattr(tool_calls[idx], 'function.name', 'unknown'),
                    "result_str": json.dumps({"error": str(e)}),
                    "success": False,
                    "error": str(e),
                }

    return results


# ═══ 循环检测器 ═════════════════════════════════════════

class LoopDetector:
    """循环检测器 - 检测 LLM 重复输出/工具调用。

    检测维度：
    1. 工具调用重复：相同工具 + 相同参数
    2. 输出内容重复：连续几轮输出高度相似
    3. 工具序列循环：A→B→A→B 模式
    """

    def __init__(self, window: int = 5, similarity_threshold: float = 0.85):
        """
        Args:
            window: 检测窗口大小（最近 N 轮）
            similarity_threshold: 相似度阈值 (0~1)，超过此值视为重复
        """
        self.window = window
        self.threshold = similarity_threshold
        self._tool_hashes: list[str] = []
        self._contents: list[str] = []
        self._tool_names: list[list[str]] = []

    def _hash_tool_call(self, name: str, args: str) -> str:
        import hashlib
        try:
            args_dict = json.loads(args) if args else {}
            args_normalized = json.dumps(args_dict, sort_keys=True)
        except (json.JSONDecodeError, TypeError):
            args_normalized = args or ""
        return hashlib.md5(f"{name}:{args_normalized}".encode()).hexdigest()[:12]

    def _text_similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        a, b = a[:500], b[:500]
        set_a = set(a)
        set_b = set(b)
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def check_and_record(self, content: str, tool_calls: list) -> dict:
        """检查当前轮是否循环，并记录。"""
        result = {"is_loop": False, "type": None, "detail": ""}

        current_hashes = []
        current_names = []
        for name, args in tool_calls:
            current_hashes.append(self._hash_tool_call(name, args))
            current_names.append(name)

        # ── 检测 1: 工具调用完全重复（仅与上一轮比较） ──
        # 至少两条相邻消息完全相同才判定循环，避免隔轮相同（A→B→A）被误判。
        if current_hashes:
            current_hash_str = "|".join(current_hashes)
            if self._tool_hashes and current_hash_str == self._tool_hashes[-1]:
                result = {
                    "is_loop": True,
                    "type": "tool_repeat",
                    "detail": "工具调用与上一轮完全相同（连续重复）"
                }

        # ── 检测 2: 输出内容与上一轮高度相似 ──
        if not result["is_loop"] and content and self._contents:
            sim = self._text_similarity(content, self._contents[-1])
            if sim >= self.threshold:
                result = {
                    "is_loop": True,
                    "type": "content_repeat",
                    "detail": f"输出内容与上一轮相似度 {sim:.0%}"
                }

        # ── 检测 3: 工具序列循环 ──
        if not result["is_loop"] and len(self._tool_hashes) >= 3:
            current_hash_str = "|".join(current_hashes) if current_hashes else ""

            if not result["is_loop"] and len(self._tool_hashes) >= 3:
                last_three_hashes = self._tool_hashes[-3:]
                if (len(last_three_hashes) == 3 and
                    current_hash_str and
                    all(h == current_hash_str for h in last_three_hashes)):
                    result = {
                        "is_loop": True,
                        "type": "sequence_loop",
                        "detail": f"检测到连续相同工具调用模式: {'→'.join(current_names)}"
                    }

            if not result["is_loop"] and len(self._tool_hashes) >= 3:
                recent_hashes = self._tool_hashes[-3:]
                if (len(recent_hashes) == 3 and
                    current_hash_str and recent_hashes[0] and recent_hashes[1] and recent_hashes[2] and
                    current_hash_str == recent_hashes[1] and recent_hashes[0] == recent_hashes[2] and
                    current_hash_str != recent_hashes[2]):
                    result = {
                        "is_loop": True,
                        "type": "sequence_loop",
                        "detail": f"检测到交替循环模式: {'→'.join(current_names)} ↔ {'→'.join(self._tool_names[-3])}"
                    }

            if not result["is_loop"] and len(self._tool_hashes) >= 6:
                recent_hashes = self._tool_hashes[-5:]
                if (len(recent_hashes) == 5 and
                    current_hash_str and recent_hashes[0] and recent_hashes[1] and recent_hashes[2] and recent_hashes[3] and recent_hashes[4] and
                    current_hash_str == recent_hashes[0] == recent_hashes[3] and
                    recent_hashes[1] == recent_hashes[4] and
                    recent_hashes[2] == current_hash_str and
                    current_hash_str != recent_hashes[1] and recent_hashes[1] != recent_hashes[2]):
                    result = {
                        "is_loop": True,
                        "type": "sequence_loop",
                        "detail": f"检测到三元循环模式: {'→'.join(current_names)} → {'→'.join(self._tool_names[-3])} → {'→'.join(self._tool_names[-2])}"
                    }

        # ── 记录本轮 ──
        self._tool_hashes.append("|".join(current_hashes) if current_hashes else "")
        self._contents.append(content or "")
        self._tool_names.append(current_names)

        if len(self._tool_hashes) > self.window * 2:
            self._tool_hashes = self._tool_hashes[-self.window:]
            self._contents = self._contents[-self.window:]
            self._tool_names = self._tool_names[-self.window:]

        return result

    def reset(self):
        self._tool_hashes.clear()
        self._contents.clear()
        self._tool_names.clear()


# ═══ 工具摘要格式化 ═════════════════════════════════════

def _format_tool_summary(tool_calls) -> str:
    """构造多行工具调用摘要用于回调显示。"""
    lines = []
    for tc in tool_calls:
        fn = tc.function.name
        lines.append(f"[TOOL_START:{fn}]")
        args_str = tc.function.arguments or "{}"
        try:
            args_dict = json.loads(args_str)
            for k, v in args_dict.items():
                v_str = str(v)
                max_param_display = 500
                if len(v_str) > max_param_display:
                    v_str = v_str[:max_param_display] + f"… [剩余 {len(v_str) - max_param_display} 字符]"
                lines.append(f"\t{k}={v_str}")
        except (json.JSONDecodeError, TypeError):
            raw = args_str
            if len(raw) > 500:
                raw = raw[:500] + f"… [剩余 {len(raw) - 500} 字符]"
            lines.append(f"\t{raw}")
        lines.append("[TOOL_DONE]")
    return "\n".join(lines) + "\n\n"


# ── SKILL 校验 ──

_skill_validate_cache: dict = {}

def _get_validate_rules(session) -> dict:
    _rules = getattr(session.context, '_skill_validate_rules', None) or {}
    return _rules

def _validate_tool_call(tool_name: str, rules: dict) -> tuple:
    if not rules:
        return True, ""
    return True, ""

def _validate_output_format(content: str, rules: dict) -> tuple:
    if not rules or not content:
        return True, []
    warnings = []
    required_sections = rules.get("required_sections", [])
    for section in required_sections:
        if f"【{section}】" not in content and f"## {section}" not in content:
            warnings.append(f"⚠️ 缺少必含段落「{section}」")
    forbidden = rules.get("forbidden_patterns", [])
    for pattern in forbidden:
        if pattern in content:
            warnings.append(f"⚠️ 包含禁止模式「{pattern}」")
    if rules.get("output_format") == "json":
        try:
            import json as _json
            _json.loads(content)
        except (ValueError, TypeError):
            warnings.append("⚠️ 输出应为 JSON 格式但解析失败")
    return len(warnings) == 0, warnings


# ═══ 主工具循环 ═════════════════════════════════════════

def _record_interruption_anchor(session, iterations: int, last_tool_names: list, full_reply: str) -> None:
    """M1/M2/M4: 记录打断锚点到内存（session._last_interruption）+ 持久化事件表。

    供 chat_stream 下一条消息进入时注入「打断知识」：
    - corrected（有后续指令） / abandoned（换话题） 的判定基础
    - 内存级不阻塞打断返回路径；DB 写入失败仅记日志不冒泡。
    - M2: 生成 event_id，若有 storage 则持久化到 interruption_events 表
      （status='pending'，分类结果由下一条消息进入时回写）。
    - M4: 读取 interruption.partial_reply_max（截断）与 persist_events（持久化开关）。
    """
    import uuid as _uuid

    try:
        # M4: 读配置（失败用默认值）
        try:
            from tea_agent.config import get_config

            icfg = get_config().interruption
            partial_max = int(icfg.get("partial_reply_max", 2000))
            persist = bool(icfg.get("persist_events", True))
        except Exception:
            partial_max, persist = 2000, True

        event_id = str(_uuid.uuid4())
        topic_id = getattr(session, "current_topic_id", "") or ""
        ev = {
            "id": event_id,
            "topic_id": topic_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "iteration": iterations,
            "tool_name": ",".join(last_tool_names)[:200] if last_tool_names else None,
            "partial_reply": (full_reply or "")[-partial_max:],
            "phase": "tool_loop",
            "status": "pending",
        }
        session._last_interruption = ev
        # M2/M4: 持久化（persist_events=false 时跳过；失败仅记日志，不阻塞打断返回路径）
        storage = getattr(session, "storage", None)
        if storage is not None and persist:
            try:
                storage.insert_interruption_event(ev)
            except Exception:
                logger.exception("persist interruption event failed")
    except Exception:
        logger.exception("record_interruption_anchor failed")


def execute_tool_loop(session, context: dict) -> dict:
    """执行工具调用循环 v4.0 — 支持并行工具执行。

    核心对话引擎：调用 LLM → 解析工具调用 → 执行工具 → 循环直到无工具调用。
    新增并行执行：使用 ParallelExecutor 自动检测依赖并并行执行无冲突的工具。

    Args:
        session: OnlineToolSession 实例
        context: Pipeline 上下文

    Returns:
        dict: {full_reply, used_tools, iterations, ...}
    """
    msg = context.get("msg", "")
    callback = context.get("callback", lambda x: None)
    on_status = context.get("on_status")

    # 是否启用并行执行（默认启用）
    enable_parallel = context.get("enable_parallel", True)
    max_parallel_workers = context.get("max_parallel_workers", 4)

    # 初始化并行执行器
    parallel_executor = ParallelExecutor(max_workers=max_parallel_workers) if enable_parallel else None

    # Level 1: 动态跳过
    if context.get("skip_tool_loop"):
        logger.info("[Pipe Dynamic] Skipping tool loop (chat intent)")
        try:
            api_messages = session._build_api_messages()
            eff = session._get_effective_params("main")
            response = session.api.create_chat_stream(
                api_messages, tools=[],
                temperature=eff.get("temperature"),
                max_tokens=_request_max_tokens(session, eff),
                top_p=eff.get("top_p"),
                request_timeout=120,
            )
            content, _, reasoning = session._process_stream_with_reasoning(
                response, callback,
                retry_factory=lambda: session.api.create_chat_stream(
                    api_messages, tools=[],
                    temperature=eff.get("temperature"),
                    max_tokens=_request_max_tokens(session, eff),
                    top_p=eff.get("top_p"),
                    request_timeout=120,
                ),
            )
            session.add_assistant_message(content, reasoning)
            session.tools_comp.collect_assistant_text_round(content, reasoning)
            return {"full_reply": content, "used_tools": False, "iterations": 1}
        except Exception as e:
            logger.warning(f"Direct answer failed, falling back: {e}")

    full_reply = ""
    used_tools = False
    iterations = 0
    loop_detector = LoopDetector(window=5, similarity_threshold=0.85)
    # M1: 跟踪最近调用的工具名，供打断锚点记录
    last_tool_names: list = []
    # 本轮全部调用过的工具名（去重保序），供 server 摘要输出
    all_tool_names: list[str] = []
    # 本回合已触发过 RC 400 自愈（关闭 thinking 重试）。声明在 while 循环层，
    # 使自愈后**所有**工具轮次（含后续 iteration）都显式带 disable_thinking；
    # 与 ctx._rc400_recovery 内部兜底互为冗余，保证降级彻底生效。
    rc_recovery_used = False
    # A8: 本回合已触发过 400 溢出自愈（修正窗口 + 强制深裁剪 + 钳制 max_tokens
    # 重试）。只自愈一次，再次溢出说明本地手段用尽，走错误返回并附处置提示。
    ctx_overflow_recovery_used = False

    while iterations < session.max_iterations + session._extra_iterations:
        if session.interrupted:
            final_msg = full_reply + "\n[已打断]"
            session.add_assistant_message(final_msg)
            session.tools_comp.collect_interruption_round(final_msg)
            # M1: 记录打断锚点，供下一条消息注入打断知识
            _record_interruption_anchor(session, iterations, last_tool_names, full_reply)
            return {
                "full_reply": final_msg,
                "used_tools": used_tools,
                "interrupted": True,
            }

        # ⭐ 插话注入：消费排队内容 → 注入下一轮模型请求（steering，不打断当前批次）
        # 用户在当前工具执行期间输入的消息，在此轮边界生效，无需等待会话结束。
        try:
            _steering_items = drain_steering_items(session)
            if _steering_items:
                _n = inject_steering_messages(session, _steering_items)
                if _n and on_status:
                    on_status(f"⚡ 已注入 {_n} 条插话，下一轮生效")
        except Exception:
            logger.exception("steering injection failed")

        # A8 发送前护栏：构建前检查"估算输入 + 输出上限"，越过安全线时强制
        # 重新裁剪（比"等 400 再处理"更积极；未越线时零成本 no-op）
        _ensure_within_output_budget(session)
        api_messages = session._build_api_messages()

        if iterations == 0:
            asctime = time.strftime("%Y-%m-%d %H:%M:%S")
            logger.debug(f"{asctime}: call model: {session.context.model}, {msg}")

        # API 调用
        max_retries = 6
        retry_base_delay = 1
        response = None
        for _retry in range(max_retries + 1):
            try:
                eff = session._get_effective_params("main")
                response = session.api.create_chat_stream(
                    api_messages, session.tools,
                    temperature=eff.get("temperature"),
                    max_tokens=_request_max_tokens(session, eff),
                    top_p=eff.get("top_p"),
                    request_timeout=120,
                    disable_thinking=rc_recovery_used,
                )
                break
            except Exception as e:
                err_str = str(e)
                if "429" in err_str and _retry < max_retries:
                    wait_sec = retry_base_delay * (2 ** _retry)
                    logger.warning(f"⚠️ API 429 速率限制，{wait_sec}s 后重试 ({_retry+1}/{max_retries})")
                    callback(f"\n⚠️ 请求频率过高，{wait_sec}秒后自动重试 ({_retry+1}/{max_retries})...\n")
                    time.sleep(wait_sec)
                    continue
                ovf = _parse_context_overflow(err_str)
                if ovf is not None and not ctx_overflow_recovery_used:
                    # A8: 400 上下文溢出自愈：修正误配窗口 → 收紧输出上限 →
                    # 一次性紧急输入预算（强制最深本地裁剪）+ 强制摘要，
                    # 重建消息并以钳制后的 max_tokens 重试。
                    ctx_overflow_recovery_used = True
                    _apply_context_overflow_recovery(session, ovf)
                    _cap = int(getattr(session.context, "_output_cap", 0) or 0)
                    callback(
                        f"\n⚠️ 上下文溢出（输入+输出超过模型窗口）："
                        f"已自动修正窗口并激进压缩历史，max_tokens 钳制到 {_cap} 重试…\n"
                    )
                    api_messages = session._build_api_messages()
                    continue
                if "image input" in err_str.lower() and session.context.supports_vision:
                    logger.warning(f"模型端点不支持图片输入，自动回退纯文本模式: {e}")
                    callback("\n⚠️ 当前 API 端点不支持图片输入，已自动切换为纯文本模式。\n")
                    session.context.supports_vision = False
                    api_messages = session._build_api_messages()
                    try:
                        eff = session._get_effective_params("main")
                        response = session.api.create_chat_stream(
                            api_messages, session.tools,
                            temperature=eff.get("temperature"),
                            max_tokens=_request_max_tokens(session, eff),
                            top_p=eff.get("top_p"),
                            request_timeout=120,
                            disable_thinking=rc_recovery_used,
                        )
                    except Exception as e2:
                        error_msg = f"API调用错误: {e2}"
                        logger.warning(
                            f"API调用失败: model={session.context.model}, iteration={iterations}, "
                            f"detail={_extract_api_error_detail(e2)}"
                        )
                        callback(error_msg)
                        session.add_assistant_message(full_reply + error_msg)
                        session.tools_comp.collect_api_error_round(full_reply + error_msg)
                        return {"full_reply": full_reply + error_msg, "used_tools": used_tools, "error": e2}
                elif _is_rc_passed_back_error(err_str) and not rc_recovery_used:
                    # DeepSeek thinking 模式 RC 回传 400 自愈：
                    # 历史 assistant 消息的 reasoning_content 值一旦丢失/被改写，
                    # 客户端无法凭空还原精确值，继续 thinking 会反复 400。
                    # 策略：记录诊断 → 强制关闭 thinking 重试一次（DeepSeek 不再
                    # 要求 RC 回传），并置 ctx._rc400_recovery 让本回合剩余请求
                    # 全部降级；下一用户回合 reset_session_state 自动恢复。
                    _log_rc_diagnostic(session, api_messages)
                    rc_recovery_used = True
                    session.context._rc400_recovery = True
                    logger.warning(
                        f"DeepSeek RC 回传 400 (iteration={iterations})："
                        f"自动降级为无思考重试（本回合剩余请求保持 thinking 关闭）"
                    )
                    callback("\n⚠️ DeepSeek 思考模式 RC 校验失败，已自动降级为无思考模式重试…\n")
                    continue
                else:
                    error_msg = f"API调用错误: {e}"
                    if (
                        _parse_context_overflow(err_str) is not None
                        and ctx_overflow_recovery_used
                    ):
                        # 自愈后仍溢出：本地裁剪手段已用尽，给出可操作的处置提示
                        error_msg += (
                            "（上下文溢出自愈后仍失败：请调小 config 的 max_tokens / "
                            "max_context_tokens，或开启新会话继续）"
                        )
                    logger.warning(
                        f"API调用失败: model={session.context.model}, iteration={iterations}, "
                        f"detail={_extract_api_error_detail(e)}"
                    )
                    callback(error_msg)
                    session.add_assistant_message(full_reply + error_msg)
                    session.tools_comp.collect_api_error_round(full_reply + error_msg)
                    return {"full_reply": full_reply + error_msg, "used_tools": used_tools, "error": e}
                break
        else:
            error_msg = f"API调用错误: 429 速率限制，重试 {max_retries} 次后仍失败"
            logger.warning(error_msg)
            callback(error_msg)
            session.add_assistant_message(full_reply + error_msg)
            session.tools_comp.collect_api_error_round(full_reply + error_msg)
            return {"full_reply": full_reply + error_msg, "used_tools": used_tools, "error": "429 rate limit exhausted"}

        content, tool_calls_data, reasoning_content = session._process_stream_with_reasoning(
            response, callback,
            retry_factory=lambda: session.api.create_chat_stream(
                api_messages, session.tools,
                temperature=eff.get("temperature"),
                max_tokens=_request_max_tokens(session, eff),
                top_p=eff.get("top_p"),
                request_timeout=120,
                disable_thinking=rc_recovery_used,
            ),
        )
        full_reply += content
        logger.debug(
            f"model response: content_len={len(content)}, reasoning_len={len(reasoning_content)}, "
            f"tool_calls_data={len(tool_calls_data)}"
        )

        valid_tool_calls = session.tools_comp.parse_tool_calls_from_stream(tool_calls_data)

        # M1: 记录最近调用的工具名，供打断锚点记录
        if valid_tool_calls:
            last_tool_names = [tc.function.name for tc in valid_tool_calls]
            for _name in last_tool_names:
                if _name not in all_tool_names:
                    all_tool_names.append(_name)

        if valid_tool_calls:
            used_tools = True
            callback("[THINK_DONE]")

            if on_status:
                on_status(f"⏳ 生成中... 调用工具第{iterations+1}轮 (ESC 打断)")

            session.tools_comp.collect_assistant_tool_calls_round(content, valid_tool_calls, reasoning_content)

            assistant_msg = {
                "role": "assistant",
                "content": session._cap_message_text(content) if content else None,
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in valid_tool_calls]
            }
            if session.context.supports_reasoning:
                # DeepSeek V4 思考模式要求：带 tools 的请求必须把 reasoning_content
                # 完整回传，否则 400 ("must be passed back")。因此**不得截断/改写**——
                # 截断后的 RC 与原值不一致同样会触发 400。
                # 注意：V4 在部分 tool_call 轮次会返回 reasoning_content=""（空字符串），
                # 若因值为空而丢弃该字段（旧实现 `if reasoning_content:`），下轮请求
                # 会触发 400，且 build_api_messages 防御校验会持续告警。
                # 正确做法：字段只要模型返回过就必须保留（含空串），原样入库回传。
                assistant_msg["reasoning_content"] = reasoning_content

            session.context.messages.append(assistant_msg)

            has_reload = any(tc.function.name == "toolkit_reload" for tc in valid_tool_calls)

            # ═══ 新：并行工具执行 ═══════════════════════
            if enable_parallel and parallel_executor:
                # 分析依赖，分组为可并行批次
                batches = parallel_executor.analyze_dependencies(valid_tool_calls)
                logger.info(f"🔀 工具执行计划: {len(batches)} 批次, "
                           f"总 {len(valid_tool_calls)} 个工具调用")

                for batch_idx, batch in enumerate(batches):
                    if len(batch) == 1:
                        # 单工具 — 顺序执行
                        tc = batch[0]
                        call_id, func_name, result_str = _execute_single_tool(
                            session, tc, callback, iterations, on_status
                        )
                        session.tools_comp.collect_tool_call_round(call_id, result_str)
                        _emit_tool_results(callback, result_str)
                    else:
                        # 多工具 — 并行执行
                        logger.info(f"⚡ 并行执行批次 {batch_idx + 1}: "
                                   f"{[tc.function.name for tc in batch]}")
                        callback(f"[PARALLEL:{','.join(tc.function.name for tc in batch)}]")

                        results = execute_tools_parallel(
                            batch,
                            lambda tc: _execute_single_tool(
                                session, tc, callback, iterations, on_status
                            ),
                            max_workers=parallel_executor.max_workers,
                        )

                        for r_idx, result in enumerate(results):
                            if result["success"]:
                                session.tools_comp.collect_tool_call_round(
                                    result["call_id"], result["result_str"]
                                )
                                _emit_tool_results(callback, result["result_str"])
                            else:
                                session.tools_comp.collect_tool_call_round(
                                    result["call_id"],
                                    json.dumps({"error": result.get("error", "Unknown error")})
                                )
                                callback(f"[TOOL_RESULT:ERROR:{result.get('error', '')[:120]}]")
                            callback("[TOOL_DONE]")
            else:
                # ═══ 旧版：顺序执行 ═══════════════════════
                for tc in valid_tool_calls:
                    call_id, func_name, result_str = _execute_single_tool(
                        session, tc, callback, iterations, on_status
                    )
                    session.tools_comp.collect_tool_call_round(call_id, result_str)
                    _emit_tool_results(callback, result_str)

            if has_reload:
                session._build_tools()

            # ── 循环检测 ──
            tool_calls_for_check = [(tc.function.name, tc.function.arguments) for tc in valid_tool_calls]
            loop_result = loop_detector.check_and_record(content, tool_calls_for_check)
            if loop_result["is_loop"]:
                loop_count = getattr(session, '_loop_count', 0) + 1
                session._loop_count = loop_count
                logger.warning(f"检测到循环: {loop_result['type']} - {loop_result['detail']} (连续第 {loop_count} 次)")

                if loop_count >= 3:
                    warning = f"\n\n[循环检测] 检测到重复输出 ({loop_result['detail']})，已自动跳出"
                    callback(warning)
                    full_reply += warning
                    session.add_assistant_message(full_reply)
                    session.tools_comp.collect_max_iterations_round(full_reply)
                    return {"full_reply": full_reply, "used_tools": used_tools, "loop_detected": True}
                elif loop_count >= 2:
                    callback("\n⚠️ 检测到重复输出，请尝试不同方法...\n")
            else:
                session._loop_count = 0

            iterations += 1

            # ── additionalContexts 消费（修复 S1：只存不取的断链） ──
            # 工具执行的 post-hook 可注入上下文，这里在下一轮请求组装前
            # 统一 drain（FIFO），作为 user 消息注入模型请求。
            try:
                pending_ctxs = session.tool_hooks.drain_contexts() if hasattr(session, "tool_hooks") else []
            except Exception:
                pending_ctxs = []
            if pending_ctxs:
                injected_text = "\n\n".join(
                    f"[上下文注入] {c}" if isinstance(c, str) else f"[上下文注入] {c}"
                    for c in pending_ctxs
                )
                # S2: 注入文本入库定型，防止超长注入进入 _progressive_trim 二次改写候选
                session.context.messages.append({
                    "role": "user",
                    "content": session._cap_message_text(injected_text) if injected_text else injected_text,
                })
                logger.info(f"additionalContexts 注入 {len(pending_ctxs)} 条 → 下一轮模型请求")

            if iterations >= session.max_iterations + session._extra_iterations:
                if on_status:
                    on_status(f"!MAX_ITER:已执行{iterations}轮，上限{session.max_iterations + session._extra_iterations}，是否继续？")
                    while not session._max_iter_wait.wait(timeout=0.5):
                        if session.interrupted:
                            final_msg = full_reply + "\n[已打断]"
                            session.add_assistant_message(final_msg)
                            session.tools_comp.collect_interruption_round(final_msg)
                            # M1: 记录打断锚点，供下一条消息注入打断知识
                            _record_interruption_anchor(session, iterations, last_tool_names, full_reply)
                            return {"full_reply": final_msg, "used_tools": used_tools, "interrupted": True}
                    if not session._continue_after_max:
                        warning = f"\n\n[用户选择终止，已执行 {iterations} 轮工具调用]"
                        callback(warning)
                        full_reply += warning
                        session.add_assistant_message(full_reply)
                        session.tools_comp.collect_max_iterations_round(full_reply)
                        break
                    session._extra_iterations += session.context.extra_iterations_on_continue
                    session._continue_after_max = False
                    session._max_iter_wait.clear()
                    extra = session.context.extra_iterations_on_continue
                    on_status(f"⏳ 已续命{extra}轮，继续生成... (ESC 打断)")
                    continue
                else:
                    warning = f"\n\n[警告：已达到最大迭代次数 {session.max_iterations}，对话终止]"
                    callback(warning)
                    full_reply += warning
                    session.add_assistant_message(full_reply)
                    session.tools_comp.collect_max_iterations_round(full_reply)
                    break

            if content:
                callback("")
            continue

        elif content:
            iterations += 1
            assistant_msg = {"role": "assistant", "content": session._cap_message_text(content)}
            if session.context.supports_reasoning:
                # 完整回传 reasoning_content（DeepSeek V4 thinking 模式要求，截断会 400）。
                # 含空串也原样保留，与工具调用轮一致（API 对无 tool_calls 的 assistant
                # 忽略 RC，保留无害且保证 DB 回放一致）。
                assistant_msg["reasoning_content"] = reasoning_content
            session.context.messages.append(assistant_msg)
            session.tools_comp.collect_assistant_text_round(content, reasoning_content)
            break
        else:
            break

    # ── 最终输出格式检查 ──
    _rules = _get_validate_rules(session)
    if _rules and full_reply:
        _valid, _warnings = _validate_output_format(full_reply, _rules)
        if _warnings:
            _warn_text = "\n\n---\n⚠️ **输出规范提醒**：\n" + "\n".join(_warnings)
            logger.info(f"输出规范校验: {'通过' if _valid else '有警告'}, {len(_warnings)} 条")
            full_reply += _warn_text
            if on_status:
                on_status(f"⏳ 输出规范校验完成 ({'✅' if _valid else '⚠️'})")

    return {
        "full_reply": full_reply,
        "used_tools": used_tools,
        "iterations": iterations,
        "parallel_enabled": enable_parallel,
        "tool_names": all_tool_names,
    }


# ═══ 辅助函数 ═══════════════════════════════════════════

def _execute_single_tool(session, tc, callback, iterations, on_status) -> tuple:
    """执行单个工具调用。"""
    _asctime = time.strftime("%Y-%m-%d %H:%M:%S")
    callback(f"[TOOL_START:{tc.function.name}]")

    # 发送参数信息
    if tc.function.arguments:
        try:
            import json as _json
            _args = _json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
            if isinstance(_args, dict):
                _parts = []
                for _k, _v in _args.items():
                    _vs = str(_v)
                    max_param = 500
                    if len(_vs) > max_param:
                        _vs = _vs[:max_param] + "…"
                    _parts.append(f"{_k}: {_vs}")
                callback(f"[TOOL_ARG:{', '.join(_parts)}]")
            else:
                _vs = str(_args)
                if len(_vs) > 120:
                    _vs = _vs[:120] + "…"
                callback(f"[TOOL_ARG:{_vs}]")
        except Exception:
            _raw = str(tc.function.arguments)
            if len(_raw) > 120:
                _raw = _raw[:120] + "…"
            callback(f"[TOOL_ARG:{_raw}]")

    logger.info(f"    tool call #{iterations+1}: {tc.function.name}, args_len={len(tc.function.arguments)}")

    # SKILL 校验
    _rules = _get_validate_rules(session)
    _allowed, _reason = _validate_tool_call(tc.function.name, _rules)
    if not _allowed:
        logger.warning(f"SKILL 校验拦截: {tc.function.name} — {_reason}")
        callback(f"\n⚠️ {_reason}\n")
        _blocked_result = json.dumps({
            "error": "tool_call_blocked",
            "reason": _reason,
            "message": "该工具调用被当前 SKILL.md 规则拦截。"
        })
        callback("[TOOL_DONE]")
        return tc.id, tc.function.name, _blocked_result

    call_id, func_name, result_str = session.tools_comp.execute_tool_call(tc)
    logger.debug(f"tool result #{iterations+1}: {func_name}, result_len={len(result_str) if result_str else 0}")

    # DAG 可视化检测
    try:
        import ast as _ast_mod
        _parsed = _ast_mod.literal_eval(result_str) if isinstance(result_str, str) else result_str
        if isinstance(_parsed, dict) and _parsed.get("dag_viz_id"):
            callback(f"[DAG_VIZ:{_parsed['dag_viz_id']}]")
    except Exception:
        pass

    return call_id, func_name, result_str


def _emit_tool_results(callback, result_str):
    """发送 TOOL_RESULT 标记。"""
    _res = result_str or ""
    if len(_res) > 120:
        _res = _res[:120] + "…"
    callback(f"[TOOL_RESULT:{_res}]")
    callback("[TOOL_DONE]")
