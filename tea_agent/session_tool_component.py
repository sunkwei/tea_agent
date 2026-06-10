"""
工具执行组件

负责工具调用执行、结果收集、rounds 持久化等功能。
从 SessionToolMixin 重构而来，使用组合模式替代 Mixin。
"""

import json
import logging
from typing import List, Dict, Tuple, Any, Optional
from types import SimpleNamespace
from .session_context import SessionComponent, SessionContext

logger = logging.getLogger("session.tool")

# ── 模块级纯函数（原 session_tools_builder）──

ESSENTIAL_TOOLS = {"toolkit_memory", "toolkit_kb"}
"""始终保留的必要工具集合。"""


def filter_tools(tools: list, tool_filter: list = None) -> list:
    """根据 tool_filter 过滤工具列表，始终保留 ESSENTIAL_TOOLS。"""
    if tool_filter:
        allowed = set(tool_filter) | ESSENTIAL_TOOLS
        return [t for t in tools if t["function"]["name"] in allowed]
    return tools


def has_tool(tools: list, name: str) -> bool:
    """检查指定工具是否存在。"""
    return any(t.get("function", {}).get("name") == name for t in tools)


class ToolComponent(SessionComponent):
    """
    工具执行组件。
    
    通过 self.ctx 访问共享状态（toolkit, tool_log, messages, _rounds_collector）。
    """
    
    @property
    def name(self) -> str:
        """Name."""
        return "tool"
    
    def initialize(self) -> None:
        """工具组件无需特殊初始化"""
        pass
    
    def build_tools(self) -> List[Dict]:
        """构建工具定义列表"""
        tools = []
        if self.ctx.toolkit is None:
            logger.warning("toolkit 未设置，无法构建工具列表")
            return tools
        
        for name, meta in self.ctx.toolkit.meta_map.items():
            tools.append(meta)
        return tools

    def execute_tool_call(self, call) -> Tuple[str, str, str]:
        """
        执行单个工具调用。

        Args:
            call: 工具调用对象（需有 .id, .function.name, .function.arguments）

        Returns:
            Tuple[str, str, str]: (call_id, func_name, result_string)
        """
        import time
        func_name = call.function.name
        call_id = call.id
        start_time = time.time()

        if self.ctx.toolkit is None:
            err = "错误：toolkit 未设置"
            logger.error(err)
            self.add_tool_result(call_id, err)
            self._record_tool_to_trace(func_name, False, err, start_time)
            return call_id, func_name, err

        if func_name not in self.ctx.toolkit.func_map:
            err = f"错误：未知工具 {func_name}"
            logger.warning(f"tool call failed: unknown function '{func_name}'")
            self.add_tool_result(call_id, err)
            self._record_tool_to_trace(func_name, False, err, start_time)
            return call_id, func_name, err

        try:
            args = json.loads(call.function.arguments)
        except json.JSONDecodeError:
            err = "错误：参数解析失败"
            logger.warning(f"tool call failed: JSON decode error, func={func_name}, raw_args={call.function.arguments[:200]}")
            self.add_tool_result(call_id, err)
            self._record_tool_to_trace(func_name, False, err, start_time)
            return call_id, func_name, err

        if self.ctx.tool_log:
            self.ctx.tool_log(f"🔧 调用工具: {func_name}({args})")

        success = True
        error_msg = ""
        try:
            result = self.ctx.toolkit.call_tool(func_name, **args)
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
            nl = raw.find(b'\n', head_end)
            if nl != -1 and nl < half + 256:
                head_end = nl
            head_text = raw[:head_end].decode("utf-8", errors="replace")
            
            # 后半部分
            tail_start = len(raw) - half
            nl = raw.rfind(b'\n', tail_start, len(raw))
            if nl != -1 and nl > tail_start - 256:
                tail_start = nl + 1
            tail_text = raw[tail_start:].decode("utf-8", errors="replace")
            
            result_str = f"{head_text}\n\n... [工具输出截断: {result_bytes}B → {len(head_text.encode('utf-8')) + len(tail_text.encode('utf-8'))}B] ...\n\n{tail_text}"
            logger.info(f"tool output truncated: {func_name}, {result_bytes}B → {len(result_str.encode('utf-8'))}B")
        
        self.add_tool_result(call_id, result_str)
        self._record_tool_to_trace(func_name, success, error_msg, start_time)
        return call_id, func_name, result_str

    def _record_tool_to_trace(self, func_name: str, success: bool, error_msg: str, start_time: float):
        """记录工具调用到当前反思追踪"""
        import time
        trace = self.ctx._current_trace
        if trace is None:
            return
        reflection_mgr = self.ctx.reflection_manager
        if reflection_mgr is None:
            return
        duration_ms = (time.time() - start_time) * 1000
        reflection_mgr.record_tool_call(trace, func_name, success, error_msg, duration_ms)

    def add_tool_result(self, tool_call_id: str, content: str):
        """添加工具执行结果到消息列表"""
        self.ctx.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })

    def collect_tool_call_round(self, call_id: str, result_str: str):
        """收集 tool result 到 rounds 收集器"""
        self.ctx._rounds_collector.append({
            "role": "tool",
            "content": result_str,
            "tool_call_id": call_id,
        })

    def collect_assistant_tool_calls_round(self, content: str, tool_calls: list, reasoning_content: str = ""):
        """收集 assistant tool_calls 到 rounds 收集器"""
        tc_list_for_collector = [{
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments
            }
        } for tc in tool_calls]

        entry = {
            "role": "assistant",
            "content": content if content else "",
            "tool_calls": tc_list_for_collector,
        }
        if reasoning_content:
            entry["reasoning_content"] = reasoning_content
        self.ctx._rounds_collector.append(entry)

    def collect_assistant_text_round(self, content: str, reasoning_content: str = ""):
        """收集最终 assistant 文本回答到 rounds 收集器"""
        entry = {
            "role": "assistant",
            "content": content,
        }
        if reasoning_content:
            entry["reasoning_content"] = reasoning_content
        self.ctx._rounds_collector.append(entry)

    def collect_api_error_round(self, content: str):
        """收集 API 错误到 rounds 收集器"""
        self.ctx._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def collect_max_iterations_round(self, content: str):
        """收集迭代超限警告到 rounds 收集器"""
        self.ctx._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def collect_interruption_round(self, content: str):
        """收集打断消息到 rounds 收集器"""
        self.ctx._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def parse_tool_calls_from_stream(self, tool_calls_data: List[Dict]) -> list:
        """
        将流式解析中的工具调用数据转为有效的工具调用对象列表。
        """
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
                print(f"parse_tool_calls_from_stream: tool call failed: invalid data format, data={tc_data}")
                continue

            valid_tool_calls.append(SimpleNamespace(
                id=func_id,
                function=SimpleNamespace(
                    name=func_name,
                    arguments=func_args,
                )
            ))
        return valid_tool_calls
