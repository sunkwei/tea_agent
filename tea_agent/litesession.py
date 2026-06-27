"""
轻量级会话 - LiteSession

特点：
1. 不使用 db，不使用摘要，不支持历史记录拼接
2. 每次只执行一轮，返回 user, ai think, ai final message
3. 可以使用所有 toolkit_xxx 工具函数
4. 可以指定使用便宜模型作为主模型
"""

import json
import logging
from typing import Dict, List, Optional, Callable

from openai import OpenAI

logger = logging.getLogger("session.lite")


class LiteSession:
    """
    轻量级会话 - 无状态、无历史、单轮执行
    
    每次 chat() 调用：
    - 构建消息: [system_prompt, user_input]
    - 调用 LLM（支持工具调用循环，但只返回最终结果）
    - 返回: {user, thinking, assistant, tool_calls_count}
    """

    def __init__(
        self,
        toolkit,
        api_key: str,
        api_url: str,
        model: str,
        system_prompt: str = "",
        enable_thinking: bool = True,
        max_iterations: int = 50,
        supports_reasoning: bool = True,
    ):
        """
        初始化轻量级会话。
        
        Args:
            toolkit: Toolkit 工具库实例
            api_key: API密钥
            api_url: API地址
            model: 模型名称
            system_prompt: 系统提示词
            enable_thinking: 是否启用 thinking 功能
            max_iterations: 最大工具调用迭代次数
            supports_reasoning: 是否支持推理内容
        """
        self.toolkit = toolkit
        self.model = model
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.enable_thinking = enable_thinking
        self.max_iterations = max_iterations
        self.supports_reasoning = supports_reasoning
        self.interrupted = False
        
        # API 客户端
        self.api = OpenAI(api_key=api_key, base_url=api_url)
        
        # 构建工具定义
        self.tools = self._build_tools()
        
        logger.info(f"LiteSession 初始化 | 模型: {model} | 工具数: {len(self.tools)}")

    def _default_system_prompt(self) -> str:
        """默认系统提示词。"""
        return """你是可自我扩展的智能Agent。拥有工具库toolkit，可通过toolkit_save(name,meta,pycode)保存新工具、toolkit_reload()重载获得新能力。内置工具：toolkit_exec(执行命令)、toolkit_load_file(读文件)、toolkit_save_file(写文件)。

核心行为：主动分析任务需求，自主创建/优化/组合工具。工具须为纯Python、可执行、有明确输入输出、通用可复用。可自由设计单函数/多函数/工具套件等结构。

你不断进化，能力无上限。以最有效优雅的方式完成任务并持续增强自身。"""

    def _build_tools(self) -> List[Dict]:
        """构建工具定义列表。"""
        tools = []
        if not self.toolkit:
            return tools
        
        # 使用 meta_map 获取工具定义
        for name, meta in self.toolkit.meta_map.items():
            if name.startswith("toolkit_"):
                try:
                    if meta and "function" in meta:
                        tools.append(meta)
                except Exception as e:
                    logger.warning(f"工具 {name} 定义加载失败: {e}")
        
        return tools

    def chat(self, user_input: str, callback: Optional[Callable[[str], None]] = None) -> Dict:
        """
        执行单轮对话。
        
        Args:
            user_input: 用户输入
            callback: 流式回调（可选）
            
        Returns:
            {
                "user": str,           # 用户输入
                "thinking": str,       # AI 思考过程（如有）
                "assistant": str,      # AI 最终回复
                "tool_calls": int,     # 工具调用次数
                "error": str|None      # 错误信息
            }
        """
        self.interrupted = False
        
        # 构建消息：只有系统提示 + 用户输入
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input}
        ]
        
        full_reply = ""
        thinking_content = ""
        tool_calls_count = 0
        iterations = 0
        
        try:
            while iterations < self.max_iterations:
                # 中断检查
                if self.interrupted:
                    break
                
                # 调用 API
                response = self._call_api(messages)
                
                # 处理响应
                content, tool_calls_data, reasoning = self._process_response(response, callback)
                
                # 累积回复
                full_reply += content
                if reasoning:
                    thinking_content += reasoning
                
                # 解析工具调用
                valid_tool_calls = self._parse_tool_calls(tool_calls_data)
                
                if valid_tool_calls:
                    tool_calls_count += len(valid_tool_calls)
                    
                    # 添加 assistant 消息到上下文
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
                    messages.append(assistant_msg)
                    
                    # 执行工具调用
                    for call in valid_tool_calls:
                        if self.interrupted:
                            break
                        call_id, func_name, result_str = self._execute_tool(call)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": result_str
                        })
                    
                    iterations += 1
                    continue
                else:
                    # 无工具调用，对话结束
                    iterations += 1
                    break
            
            return {
                "user": user_input,
                "thinking": thinking_content,
                "assistant": full_reply,
                "tool_calls": tool_calls_count,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"LiteSession.chat 失败: {e}")
            return {
                "user": user_input,
                "thinking": thinking_content,
                "assistant": full_reply,
                "tool_calls": tool_calls_count,
                "error": str(e)
            }

    def _call_api(self, messages: List[Dict]):
        """调用 API。"""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        
        # 如果有工具，添加工具定义
        if self.tools:
            kwargs["tools"] = self.tools
        
        # thinking 模式
        if self.enable_thinking and self.supports_reasoning:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        
        return self.api.chat.completions.create(**kwargs)

    def _process_response(self, response, callback: Optional[Callable]) -> tuple:
        """处理流式响应。"""
        content = ""
        reasoning_content = ""
        tool_calls_data = {}
        
        for chunk in response:
            if self.interrupted:
                break
                
            if not chunk.choices:
                continue
                
            delta = chunk.choices[0].delta
            
            # 处理推理内容
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                reasoning_content += delta.reasoning_content
                if callback:
                    callback(delta.reasoning_content)
            
            # 处理普通内容
            if delta.content:
                content += delta.content
                if callback:
                    callback(delta.content)
            
            # 处理工具调用
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": ""
                        }
                    if tc.id:
                        tool_calls_data[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_data[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_data[idx]["arguments"] += tc.function.arguments
        
        return content, tool_calls_data, reasoning_content

    def _parse_tool_calls(self, tool_calls_data: Dict) -> List:
        """解析工具调用数据。"""
        from dataclasses import dataclass
        
        @dataclass
        class SimpleFunction:
            name: str
            arguments: str
        
        @dataclass
        class SimpleToolCall:
            id: str
            type: str = "function"
            function: SimpleFunction = None
        
        valid_calls = []
        for idx in sorted(tool_calls_data.keys()):
            data = tool_calls_data[idx]
            if data["id"] and data["name"]:
                try:
                    # 验证 JSON 参数
                    json.loads(data["arguments"])
                    valid_calls.append(SimpleToolCall(
                        id=data["id"],
                        function=SimpleFunction(
                            name=data["name"],
                            arguments=data["arguments"]
                        )
                    ))
                except json.JSONDecodeError:
                    logger.warning(f"工具 {data['name']} 参数 JSON 无效: {data['arguments'][:100]}")
        
        return valid_calls

    def _execute_tool(self, call) -> tuple:
        """执行工具调用。"""
        func_name = call.function.name
        args_str = call.function.arguments
        call_id = call.id
        
        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            args = {}
        
        # 执行工具
        try:
            result = self.toolkit.call_tool(func_name, **args)
            result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
        except Exception as e:
            result_str = f"工具执行错误: {e}"
            logger.warning(f"工具 {func_name} 执行失败: {e}")
        
        return call_id, func_name, result_str

    def interrupt(self):
        """中断当前对话。"""
        self.interrupted = True

    def close(self):
        """关闭会话，释放 HTTP 客户端资源。"""
        try:
            if hasattr(self, 'api') and self.api:
                if hasattr(self.api, 'close'):
                    self.api.close()
            logger.info("LiteSession 资源已释放")
        except Exception as e:
            logger.warning(f"关闭 LiteSession 资源失败: {e}")
