"""
工具调用循环执行器

从 onlinesession.py 提取的独立功能：
- execute_tool_loop: 执行工具调用循环（核心对话引擎）
"""

import json
import time
import logging
from typing import Dict, Callable, Optional, Any

logger = logging.getLogger("session.tool_loop_runner")


def _format_tool_summary(tool_calls) -> str:
    """构造多行工具调用摘要用于回调显示。"""
    tool_lines = []
    for tc in tool_calls:
        fn = tc.function.name
        tool_lines.append(f" -- 正在执行工具：{fn}")
        args_str = tc.function.arguments or "{}"
        try:
            args_dict = json.loads(args_str)
            for k, v in args_dict.items():
                v_str = str(v)
                if len(v_str.encode("utf-8")) > 32:
                    v_str = v_str[:32] + "…"
                tool_lines.append(f"\t{k}: {v_str}")
        except (json.JSONDecodeError, TypeError):
            pass
    return "\n".join(tool_lines) + "\n\n"


def execute_tool_loop(session, context: Dict) -> Dict:
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
    on_status = context.get("on_status", None)

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

    while iterations < session.max_iterations + session._extra_iterations:
        # ── 中断检查 ──
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

        # ── 首轮日志 ──
        if iterations == 0:
            asctime = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{asctime}: call model: {session.context.model}, {msg}")
            logger.info(f"call model: {session.context.model}, {msg}")

        # ── API 调用（含 429 重试 + 视觉回退） ──
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
                break  # 成功
            except Exception as e:
                err_str = str(e)
                # 429 速率限制：等待后重试
                if "429" in err_str and _retry < _MAX_RETRIES:
                    wait_sec = _RETRY_BASE_DELAY * (_retry + 1)
                    logger.warning(f"⚠️ API 429 速率限制，{wait_sec}s 后重试 ({_retry+1}/{_MAX_RETRIES})")
                    callback(f"\n⚠️ 请求频率过高，{wait_sec}秒后自动重试 ({_retry+1}/{_MAX_RETRIES})...\n")
                    time.sleep(wait_sec)
                    continue
                # 非 429 或重试耗尽
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
                break  # 非 429 错误，跳出重试循环
        else:
            # 所有重试都失败（429 耗尽）
            error_msg = f"API调用错误: 429 速率限制，重试 {_MAX_RETRIES} 次后仍失败"
            logger.warning(error_msg)
            callback(error_msg)
            session.add_assistant_message(full_reply + error_msg)
            session.tools_comp.collect_api_error_round(full_reply + error_msg)
            return {"full_reply": full_reply + error_msg, "used_tools": used_tools, "error": "429 rate limit exhausted"}

        # ── 处理流式响应 ──
        content, tool_calls_data, reasoning_content = session._process_stream_with_reasoning(response, callback)
        full_reply += content
        logger.debug(
            f"model response: content_len={len(content)}, reasoning_len={len(reasoning_content)}, "
            f"tool_calls_data={len(tool_calls_data)}, usage={session.context._last_usage}"
        )

        # ── 解析工具调用 ──
        valid_tool_calls = session.tools_comp.parse_tool_calls_from_stream(tool_calls_data)

        if valid_tool_calls:
            used_tools = True
            callback("[THINK_DONE]")

            if on_status:
                on_status(f"⏳ 生成中... 调用工具第{iterations+1}轮 (ESC 打断)")

            # 收集 assistant tool_calls
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

            # 执行每个工具调用
            for call in valid_tool_calls:
                _asctime = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"{_asctime}: \t#{iterations+1}: 调用工具:{call.function.name}")
                logger.info(f"    tool call #{iterations+1}: {call.function.name}, args_len={len(call.function.arguments)}")
                call_id, func_name, result_str = session.tools_comp.execute_tool_call(call)
                logger.debug(f"tool result #{iterations+1}: {func_name}, result_len={len(result_str) if result_str else 0}")
                session.tools_comp.collect_tool_call_round(call_id, result_str)

            if has_reload:
                session._build_tools()

            iterations += 1

            # ── 最大迭代检查 ──
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

            # 工具调用摘要回调
            if content:
                callback(_format_tool_summary(valid_tool_calls))
            continue

        elif content:
            # ── AI 最终回复（无工具调用） ──
            iterations += 1
            assistant_msg = {"role": "assistant", "content": content}
            if reasoning_content:
                assistant_msg["reasoning_content"] = reasoning_content
            session.context.messages.append(assistant_msg)
            session.tools_comp.collect_assistant_text_round(content, reasoning_content)
            break
        else:
            break

    return {
        "full_reply": full_reply,
        "used_tools": used_tools,
        "iterations": iterations,
    }
