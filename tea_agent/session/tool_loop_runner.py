"""工具调用循环执行器 v4.0 — 支持并行工具执行（借鉴 Pi Agent Harness）

新增:
  - ParallelExecutor: 并行工具执行引擎，自动检测依赖关系
  - 混合执行模式：有依赖的串行，无依赖的并行
  - 智能依赖分析：基于工具名和参数推断
  - 原有 LoopDetector 和工具执行逻辑保持不变
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

logger = logging.getLogger("session.tool_loop_runner")


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
        "toolkit_edit", "toolkit_diff_edit", "toolkit_self_evolve",
        "toolkit_save_file", "toolkit_exec", "toolkit_git_commit",
        "toolkit_save", "toolkit_reload", "toolkit_diff",
    }

    # 标记为"并行安全"的工具（只读查询类）
    PARALLEL_SAFE = {
        "toolkit_file", "toolkit_search", "toolkit_lsp",
        "toolkit_gettime", "toolkit_os_info", "toolkit_config",
        "toolkit_memory", "toolkit_kb", "toolkit_skills",
        "toolkit_list_provider_models", "toolkit_get_models",
        "toolkit_get_config_path", "toolkit_weather_my",
        "toolkit_ip_location_my", "toolkit_lunar",
        "toolkit_date_diff", "toolkit_self_report",
        "toolkit_harness_schema", "toolkit_plan",
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

        # ── 检测 1: 工具调用完全重复 ──
        if current_hashes:
            current_hash_str = "|".join(current_hashes)
            compare_range = self._tool_hashes[-(self.window-1):] if self.window > 1 else []
            for i, prev_hash in enumerate(compare_range):
                if current_hash_str == prev_hash:
                    actual_idx = len(self._tool_hashes) - len(compare_range) + i
                    result = {
                        "is_loop": True,
                        "type": "tool_repeat",
                        "detail": f"工具调用与第 {actual_idx + 1} 轮完全相同"
                    }
                    break

        # ── 检测 2: 输出内容高度相似 ──
        if not result["is_loop"] and content:
            compare_contents = self._contents[-(self.window-1):] if self.window > 1 else []
            for i, prev_content in enumerate(compare_contents):
                sim = self._text_similarity(content, prev_content)
                if sim >= self.threshold:
                    actual_idx = len(self._contents) - len(compare_contents) + i
                    result = {
                        "is_loop": True,
                        "type": "content_repeat",
                        "detail": f"输出内容与第 {actual_idx + 1} 轮相似度 {sim:.0%}"
                    }
                    break

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

            if not result["is_loop"] and len(self._tool_hashes) >= 4:
                recent_hashes = self._tool_hashes[-3:]
                if (len(recent_hashes) == 3 and
                    current_hash_str and recent_hashes[0] and recent_hashes[1] and recent_hashes[2] and
                    current_hash_str == recent_hashes[0] and recent_hashes[1] == recent_hashes[2] and
                    current_hash_str != recent_hashes[1]):
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
                _MAX_PARAM_DISPLAY = 500
                if len(v_str) > _MAX_PARAM_DISPLAY:
                    v_str = v_str[:_MAX_PARAM_DISPLAY] + f"… [剩余 {len(v_str) - _MAX_PARAM_DISPLAY} 字符]"
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
                max_tokens=eff.get("max_tokens"),
                top_p=eff.get("top_p"),
                request_timeout=120,
            )
            content, _, reasoning = session._process_stream_with_reasoning(response, callback)
            session.add_assistant_message(content, reasoning)
            session.tools_comp.collect_assistant_text_round(content, reasoning)
            return {"full_reply": content, "used_tools": False, "iterations": 1}
        except Exception as e:
            logger.warning(f"Direct answer failed, falling back: {e}")

    full_reply = ""
    used_tools = False
    iterations = 0
    loop_detector = LoopDetector(window=5, similarity_threshold=0.85)

    while iterations < session.max_iterations + session._extra_iterations:
        if session.interrupted:
            final_msg = full_reply + "\n[已打断]"
            session.add_assistant_message(final_msg)
            session.tools_comp.collect_interruption_round(final_msg)
            return {
                "full_reply": final_msg,
                "used_tools": used_tools,
                "interrupted": True,
            }

        api_messages = session._build_api_messages()

        if iterations == 0:
            asctime = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{asctime}: call model: {session.context.model}, {msg}")
            logger.info(f"call model: {session.context.model}, {msg}")

        # API 调用
        _MAX_RETRIES = 6
        _RETRY_BASE_DELAY = 1
        response = None
        for _retry in range(_MAX_RETRIES + 1):
            try:
                eff = session._get_effective_params("main")
                response = session.api.create_chat_stream(
                    api_messages, session.tools,
                    temperature=eff.get("temperature"),
                    max_tokens=eff.get("max_tokens"),
                    top_p=eff.get("top_p"),
                    request_timeout=120,
                )
                break
            except Exception as e:
                err_str = str(e)
                if "429" in err_str and _retry < _MAX_RETRIES:
                    wait_sec = _RETRY_BASE_DELAY * (2 ** _retry)
                    logger.warning(f"⚠️ API 429 速率限制，{wait_sec}s 后重试 ({_retry+1}/{_MAX_RETRIES})")
                    callback(f"\n⚠️ 请求频率过高，{wait_sec}秒后自动重试 ({_retry+1}/{_MAX_RETRIES})...\n")
                    time.sleep(wait_sec)
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
                            max_tokens=eff.get("max_tokens"),
                            top_p=eff.get("top_p"),
                            request_timeout=120,
                        )
                    except Exception as e2:
                        error_msg = f"API调用错误: {e2}"
                        logger.warning(f"API调用失败: model={session.context.model}, error={e2}, iteration={iterations}")
                        callback(error_msg)
                        session.add_assistant_message(full_reply + error_msg)
                        session.tools_comp.collect_api_error_round(full_reply + error_msg)
                        return {"full_reply": full_reply + error_msg, "used_tools": used_tools, "error": e2}
                else:
                    error_msg = f"API调用错误: {e}"
                    logger.warning(f"API调用失败: model={session.context.model}, error={e}, iteration={iterations}")
                    callback(error_msg)
                    session.add_assistant_message(full_reply + error_msg)
                    session.tools_comp.collect_api_error_round(full_reply + error_msg)
                    return {"full_reply": full_reply + error_msg, "used_tools": used_tools, "error": e}
                break
        else:
            error_msg = f"API调用错误: 429 速率限制，重试 {_MAX_RETRIES} 次后仍失败"
            logger.warning(error_msg)
            callback(error_msg)
            session.add_assistant_message(full_reply + error_msg)
            session.tools_comp.collect_api_error_round(full_reply + error_msg)
            return {"full_reply": full_reply + error_msg, "used_tools": used_tools, "error": "429 rate limit exhausted"}

        content, tool_calls_data, reasoning_content = session._process_stream_with_reasoning(response, callback)
        full_reply += content
        logger.debug(
            f"model response: content_len={len(content)}, reasoning_len={len(reasoning_content)}, "
            f"tool_calls_data={len(tool_calls_data)}"
        )

        valid_tool_calls = session.tools_comp.parse_tool_calls_from_stream(tool_calls_data)

        if valid_tool_calls:
            used_tools = True
            callback("[THINK_DONE]")

            if on_status:
                on_status(f"⏳ 生成中... 调用工具第{iterations+1}轮 (ESC 打断)")

            session.tools_comp.collect_assistant_tool_calls_round(content, valid_tool_calls, reasoning_content)

            assistant_msg = {
                "role": "assistant",
                "content": content if content else None,
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in valid_tool_calls]
            }
            if reasoning_content:
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

            if iterations >= session.max_iterations + session._extra_iterations:
                if on_status:
                    on_status(f"!MAX_ITER:已执行{iterations}轮，上限{session.max_iterations + session._extra_iterations}，是否继续？")
                    while not session._max_iter_wait.wait(timeout=0.5):
                        if session.interrupted:
                            final_msg = full_reply + "\n[已打断]"
                            session.add_assistant_message(final_msg)
                            session.tools_comp.collect_interruption_round(final_msg)
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
            assistant_msg = {"role": "assistant", "content": content}
            if reasoning_content:
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
                    _MAX_PARAM = 500
                    if len(_vs) > _MAX_PARAM:
                        _vs = _vs[:_MAX_PARAM] + "…"
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
