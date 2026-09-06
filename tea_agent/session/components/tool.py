"""{name} —— 从 onlinesession.py 拆分（2026-09-06，保持 API 兼容）。"""

import json
import logging
from types import SimpleNamespace
from typing import Any

from tea_agent.basesession import relaxed_json_loads
from tea_agent.session.context import SessionComponent
from tea_agent.tool_hooks import tool_hooks

logger = logging.getLogger("session")

def _summarize_json(value: Any, limit: int = 800) -> str:
    """工具事件摘要：任意值 → 紧凑 JSON 字符串并截断（审计用途，防事件表膨胀）。

    Args:
        value: 任意可序列化值（dict/list/str 等）
        limit: 最大字符数（默认 800，足够 UI 展示且不撑爆事件表）

    Returns:
        截断后的字符串；超长时首尾各保留一半并标注截断信息
    """
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) <= limit:
        return text
    half = max(limit // 2, 1)
    return f"{text[:half]}...[截断 {len(text)}B→{limit}B]...{text[-half:]}"

class ToolComponent(SessionComponent):
    """工具执行组件 — 负责工具调用执行、结果管理、输出截断与追踪。"""

    @property
    def name(self) -> str:
        return "tool"

    def initialize(self) -> None:
        pass

    def build_tools(self) -> list[dict]:
        tools = []
        if self.ctx.toolkit is None:
            logger.warning("toolkit not set, cannot build tool list")
            return tools

        # 仅暴露 LLM 可见工具（排除 harness_schema/export_last_pdf 等人类/外部消费者工具），
        # 名称排序保证工具 Schema 顺序稳定（DeepSeek 前缀缓存命中前提）。
        from tea_agent.tlk import llm_tool_names

        for name in llm_tool_names(self.ctx.toolkit.meta_map.keys()):
            meta = self.ctx.toolkit.meta_map.get(name)
            if meta:
                tools.append(meta)
        return tools

    def execute_tool_call(self, call) -> tuple[str, str, str]:
        import time

        func_name = call.function.name
        call_id = call.id
        start_time = time.time()

        # P2 事件溯源：记录工具调用（所有路径，含失败；args 用原始串摘要）
        self._log_tool_event(
            "tool/call",
            {
                "name": func_name,
                "call_id": call_id,
                "args": _summarize_json(call.function.arguments),
            },
        )

        if self.ctx.toolkit is None:
            err = "错误：toolkit 未设置"
            logger.error(err)
            self.add_tool_result(call_id, err)
            self._record_tool_to_trace(func_name, False, err, start_time)
            self._log_tool_event(
                "tool/result",
                {
                    "name": func_name,
                    "call_id": call_id,
                    "success": False,
                    "error": err,
                },
            )
            return call_id, func_name, err

        if func_name not in self.ctx.toolkit.func_map:
            err = f"错误：未知工具 {func_name}"
            logger.warning(f"tool call failed: unknown function '{func_name}'")
            self.add_tool_result(call_id, err)
            self._record_tool_to_trace(func_name, False, err, start_time)
            self._log_tool_event(
                "tool/result",
                {
                    "name": func_name,
                    "call_id": call_id,
                    "success": False,
                    "error": err,
                },
            )
            return call_id, func_name, err

        try:
            args = relaxed_json_loads(call.function.arguments)
        except json.JSONDecodeError:
            err = "错误：参数解析失败"
            logger.warning(
                f"tool call failed: JSON decode error, func={func_name}, raw_args={call.function.arguments[:300]}"
            )
            self.add_tool_result(call_id, err)
            self._record_tool_to_trace(func_name, False, err, start_time)
            self._log_tool_event(
                "tool/result",
                {
                    "name": func_name,
                    "call_id": call_id,
                    "success": False,
                    "error": err,
                },
            )
            return call_id, func_name, err

        if self.ctx.tool_log:
            self.ctx.tool_log(f"🔧 调用工具: {func_name}({args})")

        success = True
        error_msg = ""
        try:
            # ── pre-execute 瀑布（审批/权限/沙箱决策，默认放行） ──
            allow, deny_reason = tool_hooks.run_pre(func_name, args)
            if not allow:
                result = f"⛔ 工具被拒绝执行: {deny_reason}"
                logger.warning(
                    f"tool blocked by pre-hook: {func_name}, reason={deny_reason}"
                )
                success = False
                error_msg = deny_reason
            else:
                result = self.ctx.toolkit.call_tool(func_name, **args)
                # ── post-execute 瀑布（结果改写 + additionalContexts） ──
                final_result, extra_contexts = tool_hooks.run_post(
                    func_name, args, result
                )
                if extra_contexts:
                    for ctx in extra_contexts:
                        tool_hooks.inject_context(ctx)
                result = final_result
            if self.ctx.tool_log:
                self.ctx.tool_log(f"✅ 结果: {result}")
        except Exception as e:
            result = f"工具执行错误: {e}"
            logger.warning(f"tool execution failed: {func_name}, error={e}")
            success = False
            error_msg = str(e)
            if self.ctx.tool_log:
                self.ctx.tool_log(f"❌ 错误: {e}")

        result_str = str(result)

        # 截断超长工具输出，防止 413 Request Entity Too Large
        max_output = self.ctx.max_tool_output
        result_bytes = len(result_str.encode("utf-8"))
        if result_bytes > max_output:
            # 首尾各保留一半，按换行对齐
            half = max_output // 2
            raw = result_str.encode("utf-8")

            # 前半部分
            head_end = half
            nl = raw.find(b"\n", head_end)
            if nl != -1 and nl < half + 256:
                head_end = nl
            head_text = raw[:head_end].decode("utf-8", errors="replace")

            # 后半部分：向后找第一个换行，tail 保留约 half 字节
            tail_start = len(raw) - half
            nl = raw.find(b"\n", tail_start)
            if nl != -1 and nl < tail_start + 256:
                tail_start = nl + 1
            else:
                nl = raw.rfind(b"\n", 0, tail_start)
                if nl != -1 and nl > tail_start - 256:
                    tail_start = nl + 1
            tail_text = raw[tail_start:].decode("utf-8", errors="replace")

            # 防止 head/tail 窗口重叠（内容仅略大于 max_output 时）
            if head_end > tail_start:
                tail_start = head_end
                tail_text = raw[tail_start:].decode("utf-8", errors="replace")

            result_str = f"{head_text}\n\n... [工具输出截断: {result_bytes}B → {len(head_text.encode('utf-8')) + len(tail_text.encode('utf-8'))}B] ...\n\n{tail_text}"
            logger.info(
                f"tool output truncated: {func_name}, {result_bytes}B → {len(result_str.encode('utf-8'))}B"
            )

        # P2 事件溯源：记录工具结果（成功标志/错误/结果摘要/耗时）
        self._log_tool_event(
            "tool/result",
            {
                "name": func_name,
                "call_id": call_id,
                "success": success,
                "error": error_msg or None,
                "result": _summarize_json(result_str, limit=2000),
                "duration_ms": round((time.time() - start_time) * 1000, 1),
            },
        )

        self.add_tool_result(call_id, result_str)
        self._record_tool_to_trace(func_name, success, error_msg, start_time)
        # 进化触发器：采集工具调用信号
        evolution_trigger = getattr(self.ctx, "evolution_trigger", None)
        if evolution_trigger:
            evolution_trigger.on_tool_result(
                func_name, result, time.time() - start_time
            )
        return call_id, func_name, result_str

    def _record_tool_to_trace(
        self, func_name: str, success: bool, error_msg: str, start_time: float
    ):
        import time

        trace = self.ctx._current_trace
        if trace is None:
            return
        reflection_mgr = self.ctx.reflection_manager
        if reflection_mgr is None:
            return
        duration_ms = (time.time() - start_time) * 1000
        reflection_mgr.record_tool_call(
            trace, func_name, success, error_msg, duration_ms
        )

    def _log_tool_event(self, event_type: str, payload: dict) -> None:
        """P2 事件溯源：记录 tool/call 或 tool/result 事件（异常隔离，不影响主流程）。

        数据来源：session_events 表（append-only），供轨迹视图/审计重放使用。

        Args:
            event_type: "tool/call" | "tool/result"（其他类型忽略）
            payload: 事件负载（name/call_id/args/result 等，已摘要截断）
        """
        if event_type not in ("tool/call", "tool/result"):
            return
        try:
            topic_id = getattr(self, "current_topic_id", None)
            storage = getattr(self.ctx, "storage", None)
            if not (topic_id and storage):
                return
            events = getattr(storage, "events", None)
            if events is None:
                return
            events.append_event(topic_id, event_type, payload)
        except Exception:
            logger.debug("append tool event failed (isolated)", exc_info=True)

    def add_tool_result(self, tool_call_id: str, content: str):
        # S2/缓存友好：入库即压缩到与裁剪阈值一致的定长，消息从出生起定型。
        # 否则实时消息以原始大小（最高 max_tool_output=128KB）入库，滑出
        # 3 轮窗口后被 _solidify_history 替换为占位符 → "完整→占位符"两阶段
        # 翻转会破坏其后全部历史消息的前缀缓存命中。
        try:
            from tea_agent.basesession import BaseChatSession
            from tea_agent.session.history_builder import get_tool_prune_threshold

            max_chars = get_tool_prune_threshold(self.ctx)
            content = BaseChatSession._compress_tool_content(
                content, max_chars=max_chars
            )
        except Exception:
            logger.debug("tool content compression failed, keeping raw", exc_info=True)
        self.ctx.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )

    def collect_tool_call_round(self, call_id: str, result_str: str):
        self.ctx._rounds_collector.append(
            {
                "role": "tool",
                "content": result_str,
                "tool_call_id": call_id,
            }
        )

    def collect_assistant_tool_calls_round(
        self, content: str, tool_calls: list, reasoning_content: str = ""
    ):
        tc_list_for_collector = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]

        entry = {
            "role": "assistant",
            "content": content if content else "",
            "tool_calls": tc_list_for_collector,
        }
        if self.ctx.supports_reasoning:
            # 与 tool_loop_runner 存储一致：RC 字段含空串也必须保留入库，
            # 否则 DB 回放/历史加载后 tool_calls 消息缺 key → 下轮请求 400。
            entry["reasoning_content"] = reasoning_content
        self.ctx._rounds_collector.append(entry)

    def collect_assistant_text_round(self, content: str, reasoning_content: str = ""):
        entry = {
            "role": "assistant",
            "content": content,
        }
        if self.ctx.supports_reasoning:
            entry["reasoning_content"] = reasoning_content
        self.ctx._rounds_collector.append(entry)

    def collect_api_error_round(self, content: str):
        self.ctx._rounds_collector.append(
            {
                "role": "assistant",
                "content": content,
            }
        )

    def collect_max_iterations_round(self, content: str):
        self.ctx._rounds_collector.append(
            {
                "role": "assistant",
                "content": content,
            }
        )

    def collect_interruption_round(self, content: str):
        self.ctx._rounds_collector.append(
            {
                "role": "assistant",
                "content": content,
            }
        )

    def parse_tool_calls_from_stream(self, tool_calls_data: list[dict]) -> list:
        from tea_agent.session.json_sanitizer import normalize_tool_args

        valid_tool_calls = []
        for tc_data in tool_calls_data:
            func_id = tc_data["id"]
            if "name" in tc_data:
                func_name = tc_data["name"]
                func_args = tc_data["arguments"]
            elif "function" in tc_data:
                func_name = tc_data["function"]["name"]
                func_args = tc_data["function"]["arguments"]
            else:
                logger.warning(f"tool call failed: invalid data format, data={tc_data}")
                continue

            # 源头 JSON 校验：截断/非法的 arguments 在入库前修复为完整 JSON，
            # 避免污染 context.messages → 每轮 build_api_messages 重复修复刷屏
            # （对齐 litesession._parse_tool_calls 的 relaxed_json_loads 校验）。
            if isinstance(func_args, str) and func_args.strip():
                func_args = normalize_tool_args(func_name, func_args)
                if func_args is None:
                    continue  # 无法修复的参数，丢弃该 tool_call

            valid_tool_calls.append(
                SimpleNamespace(
                    id=func_id,
                    function=SimpleNamespace(
                        name=func_name,
                        arguments=func_args,
                    ),
                )
            )
        return valid_tool_calls
