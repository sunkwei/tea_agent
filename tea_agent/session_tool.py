"""
会话工具执行模块
负责工具调用执行、结果收集等功能
"""

import json
from typing import List, Dict, Tuple, Any, Optional, Callable
from types import SimpleNamespace


class SessionToolMixin:
    """
    工具执行 mixin 类。
    期望使用者提供以下属性：
    - toolkit: Toolkit 实例
    - tool_log: 可选日志回调
    - _rounds_collector: 轮次收集器列表
    - messages: 消息列表
    """

    def __init__(self):
        self.toolkit = None
        self.tool_log: Optional[Callable[[str], None]] = None
        self._rounds_collector: List[Dict] = []
        self.messages: List[Dict] = []

    def _build_tools(self) -> List[Dict]:
        """构建工具定义列表"""
        tools = []
        for name, meta in self.toolkit.meta_map.items():
            tools.append(meta)
        return tools

    def _execute_tool_call(self, call) -> Tuple[str, str, str]:
        """
        执行单个工具调用。

        Args:
            call: 工具调用对象（需有 .id, .function.name, .function.arguments）

        Returns:
            Tuple[str, str, str]: (call_id, func_name, result_string)
        """
        func_name = call.function.name
        call_id = call.id

        if func_name not in self.toolkit.func_map:
            err = f"错误：未知工具 {func_name}"
            self._add_tool_result(call_id, err)
            return call_id, func_name, err

        try:
            args = json.loads(call.function.arguments)
        except json.JSONDecodeError:
            err = "错误：参数解析失败"
            self._add_tool_result(call_id, err)
            return call_id, func_name, err

        if self.tool_log:
            self.tool_log(f"🔧 调用工具: {func_name}({args})")

        try:
            result = self.toolkit.func_map[func_name](**args)
            if self.tool_log:
                self.tool_log(f"✅ 结果: {result}")
        except Exception as e:
            result = f"工具执行错误: {e}"
            if self.tool_log:
                self.tool_log(f"❌ 错误: {e}")

        result_str = str(result)
        self._add_tool_result(call_id, result_str)
        return call_id, func_name, result_str

    def _add_tool_result(self, tool_call_id: str, content: str):
        """添加工具执行结果到消息列表"""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })

    def _collect_tool_call_round(self, call_id: str, result_str: str):
        """收集 tool result 到 rounds 收集器"""
        self._rounds_collector.append({
            "role": "tool",
            "content": result_str,
            "tool_call_id": call_id,
        })

    def _collect_assistant_tool_calls_round(self, content: str, tool_calls: list):
        """收集 assistant tool_calls 到 rounds 收集器"""
        tc_list_for_collector = [{
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments
            }
        } for tc in tool_calls]

        self._rounds_collector.append({
            "role": "assistant",
            "content": content if content else "",
            "tool_calls": tc_list_for_collector,
        })

    def _collect_assistant_text_round(self, content: str):
        """收集最终 assistant 文本回答到 rounds 收集器"""
        self._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def _collect_api_error_round(self, content: str):
        """收集 API 错误到 rounds 收集器"""
        self._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def _collect_max_iterations_round(self, content: str):
        """收集迭代超限警告到 rounds 收集器"""
        self._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def _collect_interruption_round(self, content: str):
        """收集打断消息到 rounds 收集器"""
        self._rounds_collector.append({
            "role": "assistant",
            "content": content,
        })

    def _parse_tool_calls_from_stream(self, tool_calls_data: List[Dict]) -> list:
        """
        将流式解析中的工具调用数据转为有效的工具调用对象列表。

        Args:
            tool_calls_data: 流式累积的工具调用数据

        Returns:
            有效的工具调用对象列表（SimpleNamespace）
        """
        valid_tool_calls = []
        for tc_data in tool_calls_data:
            if tc_data["id"] and tc_data["name"]:
                valid_tool_calls.append(SimpleNamespace(
                    id=tc_data["id"],
                    function=SimpleNamespace(
                        name=tc_data["name"],
                        arguments=tc_data["arguments"]
                    )
                ))
        return valid_tool_calls

    def _accumulate_tool_calls_from_delta(self, delta, tool_calls_data: List[Dict]):
        """
        从流式 chunk 的 delta 中累积工具调用数据。

        Args:
            delta: 流式响应的 delta 对象
            tool_calls_data: 用于累积的工具调用数据列表
        """
        if not delta.tool_calls:
            return

        for tc in delta.tool_calls:
            idx = tc.index

            # 扩展列表
            while len(tool_calls_data) <= idx:
                tool_calls_data.append({
                    "id": "",
                    "name": "",
                    "arguments": ""
                })

            if tc.id:
                tool_calls_data[idx]["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    tool_calls_data[idx]["name"] = tc.function.name
                if tc.function.arguments:
                    tool_calls_data[idx]["arguments"] += tc.function.arguments
