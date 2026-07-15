"""工具调用循环执行器

- execute_tool_loop: 执行工具调用循环（核心对话引擎）
"""

import json
import logging
import time

logger = logging.getLogger("session.tool_loop_runner")

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
        self._tool_hashes: list[str] = []  # 工具调用 hash 序列
        self._contents: list[str] = []     # 输出内容序列
        self._tool_names: list[list[str]] = []  # 工具名序列

    def _hash_tool_call(self, name: str, args: str) -> str:
        """计算工具调用的 hash。"""
        import hashlib
        # 规范化参数（排序 keys）
        try:
            args_dict = json.loads(args) if args else {}
            args_normalized = json.dumps(args_dict, sort_keys=True)
        except (json.JSONDecodeError, TypeError):
            args_normalized = args or ""
        return hashlib.md5(f"{name}:{args_normalized}".encode()).hexdigest()[:12]

    def _text_similarity(self, a: str, b: str) -> float:
        """简单的文本相似度（基于字符级 Jaccard）。"""
        if not a or not b:
            return 0.0
        # 取较短文本的前 500 字符比较
        a, b = a[:500], b[:500]
        set_a = set(a)
        set_b = set(b)
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def check_and_record(self, content: str, tool_calls: list) -> dict:
        """检查当前轮是否循环，并记录。

        支持三种循环模式检测：
        1. AAA..模式：连续相同的工具调用
        2. ABABAB模式：两种工具调用交替
        3. ABCABCABC模式：三种工具调用的循环

        Args:
            content: LLM 输出内容
            tool_calls: 工具调用列表 [(name, args), ...]

        Returns:
            {"is_loop": bool, "type": str|None, "detail": str}
        """
        result = {"is_loop": False, "type": None, "detail": ""}

        # 计算本轮的工具调用 hash
        current_hashes = []
        current_names = []
        for name, args in tool_calls:
            current_hashes.append(self._hash_tool_call(name, args))
            current_names.append(name)

        # ── 检测 1: 工具调用完全重复 ──
        # 注意：只与最近 window-1 轮比较（排除当前轮，且不与自身比较）
        if current_hashes:
            current_hash_str = "|".join(current_hashes)
            # 取最近 window-1 轮（不包括当前轮，因为还没记录）
            compare_range = self._tool_hashes[-(self.window-1):] if self.window > 1 else []
            for i, prev_hash in enumerate(compare_range):
                if current_hash_str == prev_hash:
                    # 计算实际轮次索引
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
        # 支持三种模式：AAA.., ABABAB, ABCABCABC
        # 注意：所有模式都要检查工具名和参数都相同（通过hash比较）
        if not result["is_loop"] and len(self._tool_hashes) >= 3:
            # 将当前轮的工具调用hash转换为字符串
            current_hash_str = "|".join(current_hashes) if current_hashes else ""

            # 模式1: AAA..模式（连续相同的工具调用，包括参数）
            if len(self._tool_hashes) >= 3:
                last_three_hashes = self._tool_hashes[-3:]
                if (len(last_three_hashes) == 3 and
                    current_hash_str and
                    all(h == current_hash_str for h in last_three_hashes)):
                    result = {
                        "is_loop": True,
                        "type": "sequence_loop",
                        "detail": f"检测到连续相同工具调用模式（含参数）: {'→'.join(current_names)}"
                    }

            # 模式2: ABABAB模式（两种工具调用交替，包括参数）
            if not result["is_loop"] and len(self._tool_hashes) >= 4:
                recent_hashes = self._tool_hashes[-3:]  # 最近 3 轮 + 当前
                if (len(recent_hashes) == 3 and
                    current_hash_str and recent_hashes[0] and recent_hashes[1] and recent_hashes[2] and
                    current_hash_str == recent_hashes[0] and recent_hashes[1] == recent_hashes[2] and
                    current_hash_str != recent_hashes[1]):
                    result = {
                        "is_loop": True,
                        "type": "sequence_loop",
                        "detail": f"检测到交替循环模式（含参数）: {'→'.join(current_names)} ↔ {'→'.join(self._tool_names[-3])}"
                    }

            # 模式3: ABCABCABC模式（三种工具调用的循环，包括参数）
            if not result["is_loop"] and len(self._tool_hashes) >= 6:
                recent_hashes = self._tool_hashes[-5:]  # 最近 5 轮 + 当前
                if (len(recent_hashes) == 5 and
                    current_hash_str and recent_hashes[0] and recent_hashes[1] and recent_hashes[2] and recent_hashes[3] and recent_hashes[4] and
                    current_hash_str == recent_hashes[0] == recent_hashes[3] and
                    recent_hashes[1] == recent_hashes[4] and
                    recent_hashes[2] == current_hash_str and  # 第三个应该与当前相同
                    current_hash_str != recent_hashes[1] and recent_hashes[1] != recent_hashes[2]):
                    result = {
                        "is_loop": True,
                        "type": "sequence_loop",
                        "detail": f"检测到三元循环模式（含参数）: {'→'.join(current_names)} → {'→'.join(self._tool_names[-3])} → {'→'.join(self._tool_names[-2])}"
                    }

        # ── 记录本轮 ──
        self._tool_hashes.append("|".join(current_hashes) if current_hashes else "")
        self._contents.append(content or "")
        self._tool_names.append(current_names)

        # 保持窗口大小
        if len(self._tool_hashes) > self.window * 2:
            self._tool_hashes = self._tool_hashes[-self.window:]
            self._contents = self._contents[-self.window:]
            self._tool_names = self._tool_names[-self.window:]

        return result

    def reset(self):
        """重置检测器状态（清空历史窗口）。"""
        self._tool_hashes.clear()
        self._contents.clear()
        self._tool_names.clear()





def _format_tool_summary(tool_calls) -> str:
    """构造多行工具调用摘要用于回调显示，含 TOOL_START/DONE 标记。

    格式：
        [TOOL_START:toolkit_exec]
            app=python
            args=["-c", "print('hello')"]
        [TOOL_DONE]

    Args:
        tool_calls: 工具调用列表
    Returns:
        带标记的格式化字符串
    """
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
            # 非 JSON 参数，直接显示
            raw = args_str
            if len(raw) > 500:
                raw = raw[:500] + f"… [剩余 {len(raw) - 500} 字符]"
            lines.append(f"\t{raw}")
        lines.append("[TOOL_DONE]")
    return "\n".join(lines) + "\n\n"


# ── SKILL 校验缓存 ──
_skill_validate_cache: dict = {}


def _get_validate_rules(session) -> dict:
    """从 session context 获取当前生效的校验规则（带缓存）。"""
    _rules = getattr(session.context, '_skill_validate_rules', None) or {}
    if not _rules:
        return {}
    # 缓存 key：session id（如果有的话）
    return _rules


def _validate_tool_call(tool_name: str, rules: dict) -> tuple:
    """工具调用前校验。

    检查：
      - allowed_tools: 工具白名单
      - forbidden_tools: 工具黑名单

    Args:
        tool_name: 工具函数名
        rules: 校验规则 dict（来自 SKILL.md validate 字段）

    Returns:
        (allowed: bool, reason: str)
        allowed=True 表示通过，False 表示违规
    """
    if not rules:
        return True, ""

    # 白名单检查
    allowed = rules.get("allowed_tools")
    if allowed and tool_name not in allowed:
        _allowed_str = ", ".join(allowed)
        return False, f"🚫 工具 '{tool_name}' 不在白名单中。当前允许: {_allowed_str}"

    # 黑名单检查
    forbidden = rules.get("forbidden_tools")
    if forbidden and tool_name in forbidden:
        return False, f"🚫 工具 '{tool_name}' 被黑名单禁止"

    return True, ""


def _validate_output_format(content: str, rules: dict) -> tuple:
    """输出格式校验。

    检查：
      - required_sections: 必须包含的段落
      - forbidden_patterns: 禁止出现的模式
      - output_format: 期望格式（json/text/markdown/code）

    Args:
        content: 模型输出的文本
        rules: 校验规则 dict

    Returns:
        (valid: bool, warnings: list)
    """
    if not rules or not content:
        return True, []

    warnings = []

    # 1. 必含段落检查
    required_sections = rules.get("required_sections", [])
    for section in required_sections:
        if f"【{section}】" not in content and f"## {section}" not in content:
            warnings.append(f"⚠️ 缺少必含段落「{section}」")

    # 2. 禁止模式检查
    forbidden = rules.get("forbidden_patterns", [])
    for pattern in forbidden:
        if pattern in content:
            warnings.append(f"⚠️ 包含禁止模式「{pattern}」")

    # 3. JSON 格式校验
    if rules.get("output_format") == "json":
        try:
            import json as _json
            _json.loads(content)
        except (ValueError, TypeError):
            warnings.append("⚠️ 输出应为 JSON 格式但解析失败")

    return len(warnings) == 0, warnings


def execute_tool_loop(session, context: dict) -> dict:
    """执行工具调用循环。

    核心对话引擎：调用 LLM → 解析工具调用 → 执行工具 → 循环直到无工具调用。
    支持中断、最大迭代限制、续命机制。

    Args:
        session: OnlineToolSession 实例（通过 self 传入）
        context: Pipeline 上下文，包含 msg, callback, on_status 等

    Returns:
        dict: {full_reply, used_tools, iterations, [interrupted], [error]}
    """
    msg = context.get("msg", "")
    callback = context.get("callback", lambda x: None)
    on_status = context.get("on_status")

    # Level 1: 动态跳过（纯聊天意图，不走工具循环）
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

        # API 调用（含 429 重试 + 视觉回退）
        _MAX_RETRIES = 3
        _RETRY_BASE_DELAY = 5  # 秒，递增: 5s, 10s, 15s
        response = None
        for _retry in range(_MAX_RETRIES + 1):
            try:
                eff = session._get_effective_params("main")
                response = session.api.create_chat_stream(
                    api_messages, session.tools,
                    temperature=eff.get("temperature"),
                    max_tokens=eff.get("max_tokens"),
                    top_p=eff.get("top_p"),
                )
                break
            except Exception as e:
                err_str = str(e)
                # 429 速率限制：等待后重试
                if "429" in err_str and _retry < _MAX_RETRIES:
                    wait_sec = _RETRY_BASE_DELAY * (_retry + 1)
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
                        )
                    except Exception as e2:
                        error_msg = f"API调用错误: {e2}"
                        logger.warning(f"API调用失败(重试): model={session.context.model}, error={e2}, iteration={iterations}")
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
            # 所有重试都失败（429 耗尽）
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
            f"tool_calls_data={len(tool_calls_data)}, usage={session.context._last_usage}"
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

            for call in valid_tool_calls:
                _asctime = time.strftime("%Y-%m-%d %H:%M:%S")
                # 发送 TOOL_START 标记（前端据此创建工具调用块）
                callback(f"[TOOL_START:{call.function.name}]")
                # 发送参数信息到工具块（[TOOL_ARG:json] 格式，避免泄露到聊天文本）
                if call.function.arguments:
                    try:
                        import json as _json
                        _args = _json.loads(call.function.arguments) if isinstance(call.function.arguments, str) else call.function.arguments
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
                        _raw = str(call.function.arguments)
                        if len(_raw) > 120:
                            _raw = _raw[:120] + "…"
                        callback(f"[TOOL_ARG:{_raw}]")
                logger.info(f"    tool call #{iterations+1}: {call.function.name}, args_len={len(call.function.arguments)}")

                # ── SKILL 校验：工具调用前检查白名单 ──
                _rules = _get_validate_rules(session)
                _allowed, _reason = _validate_tool_call(call.function.name, _rules)
                if not _allowed:
                    logger.warning(f"SKILL 校验拦截: {call.function.name} — {_reason}")
                    callback(f"\n⚠️ {_reason}\n")
                    # 注入虚假结果让模型知道被拦截了
                    _blocked_result = json.dumps({
                        "error": "tool_call_blocked",
                        "reason": _reason,
                        "message": "该工具调用被当前 SKILL.md 规则拦截。请检查 allowed_tools 配置。"
                    })
                    call_id, func_name = call.id, call.function.name
                    result_str = _blocked_result
                    session.tools_comp.collect_tool_call_round(call_id, result_str)
                    callback("[TOOL_DONE]")
                    continue  # 跳过执行

                call_id, func_name, result_str = session.tools_comp.execute_tool_call(call)
                logger.debug(f"tool result #{iterations+1}: {func_name}, result_len={len(result_str) if result_str else 0}")
                session.tools_comp.collect_tool_call_round(call_id, result_str)
                # 发送 TOOL_RESULT（返回值，120 字节截断）
                _res = result_str or ""
                if len(_res) > 120:
                    _res = _res[:120] + "…"
                callback(f"[TOOL_RESULT:{_res}]")
                # 发送 TOOL_DONE 标记
                callback("[TOOL_DONE]")

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
                    # 连续 3 次循环，强制跳出
                    warning = f"\n\n[循环检测] 检测到重复输出 ({loop_result['detail']})，已自动跳出"
                    callback(warning)
                    full_reply += warning
                    session.add_assistant_message(full_reply)
                    session.tools_comp.collect_max_iterations_round(full_reply)
                    return {"full_reply": full_reply, "used_tools": used_tools, "loop_detected": True}
                elif loop_count >= 2:
                    # 第 2 次循环，注入提示
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

    # ── SKILL 校验：最终输出格式检查 ──
    _rules = _get_validate_rules(session)
    if _rules and full_reply:
        _valid, _warnings = _validate_output_format(full_reply, _rules)
        if _warnings:
            _warn_text = "\n\n---\n⚠️ **输出规范提醒**：\n" + "\n".join(_warnings)
            logger.info(f"输出规范校验: {'通过' if _valid else '有警告'}, {len(_warnings)} 条")
            # 警告附在回复末尾（不阻断，仅提醒）
            full_reply += _warn_text
            if on_status:
                on_status(f"⏳ 输出规范校验完成 ({'✅' if _valid else '⚠️'})")

    return {
        "full_reply": full_reply,
        "used_tools": used_tools,
        "iterations": iterations,
    }
