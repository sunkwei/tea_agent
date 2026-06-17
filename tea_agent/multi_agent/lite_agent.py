"""
轻量 Agent — 用于子任务执行。

设计灵感:
  GenericAgent 的极简 Agent Loop (~100 行)

特点:
  - 无存储、无长期记忆
  - 复用主 Agent 的配置
  - 专注于执行特定任务
  - 轻量级上下文管理

用法:
    from tea_agent.multi_agent import LiteAgent
    
    agent = LiteAgent(tools=["toolkit_file", "toolkit_edit"])
    result = await agent.execute(
        goal="为 gui.py 添加类型注解"
    )
"""

import asyncio
import json
from typing import List, Dict, Optional, Any
from datetime import datetime

import logging

logger = logging.getLogger(__name__)


class LiteAgent:
    """轻量 Agent"""
    
    def __init__(
        self,
        tools: Optional[List[str]] = None,
        context: Optional[Dict] = None,
        max_iterations: int = 20,
        use_cheap_model: bool = True,
    ):
        """
        Args:
            tools: 可用工具列表
            context: 上下文信息
            max_iterations: 最大迭代次数
            use_cheap_model: 是否使用便宜模型
        """
        self.tools = tools or []
        self.context = context or {}
        self.max_iterations = max_iterations
        self.use_cheap_model = use_cheap_model
        
        # 内部状态
        self._iterations = 0
        self._token_cost = 0
    
    async def execute(
        self,
        goal: str,
        tools: Optional[List[str]] = None,
    ) -> str:
        """
        执行任务。
        
        Args:
            goal: 任务目标
            tools: 可用工具列表 (覆盖初始化时的配置)
            
        Returns:
            执行结果文本
        """
        effective_tools = tools or self.tools
        
        logger.info(f"🚀 LiteAgent 开始执行: {goal[:50]}...")
        
        try:
            # 1. 构建系统提示
            system_prompt = self._build_system_prompt(goal, effective_tools)
            
            # 2. 构建初始消息
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": goal},
            ]
            
            # 3. 执行 Agent Loop
            result = await self._agent_loop(messages, effective_tools)
            
            logger.info(f"✅ LiteAgent 完成: {goal[:50]}... (iterations={self._iterations})")
            return result
            
        except Exception as e:
            logger.error(f"❌ LiteAgent 失败: {e}")
            raise
    
    def _build_system_prompt(self, goal: str, tools: List[str]) -> str:
        """构建系统提示"""
        tools_desc = self._format_tools(tools)
        
        return f"""你是一个轻量级执行 Agent，专注于完成特定任务。

## 目标
{goal}

## 可用工具
{tools_desc}

## 规则
1. 只使用列出的工具
2. 每次工具调用后等待结果
3. 如果遇到错误，尝试修复或报告
4. 完成后返回最终结果

## 输出格式
完成任务后，请返回清晰的结果摘要。
"""
    
    def _format_tools(self, tools: List[str]) -> str:
        """格式化工具描述"""
        tool_descriptions = {
            "toolkit_file": "文件读写和目录列表",
            "toolkit_edit": "高级代码编辑",
            "toolkit_search": "搜索工具",
            "toolkit_lsp": "LSP 代码智能",
            "toolkit_exec": "执行系统命令",
            "toolkit_run_tests": "运行测试",
            "toolkit_pkg": "包管理",
        }
        
        lines = []
        for tool in tools:
            desc = tool_descriptions.get(tool, "工具")
            lines.append(f"- {tool}: {desc}")
        
        return "\n".join(lines)
    
    async def _agent_loop(self, messages: List[Dict], tools: List[str]) -> str:
        """Agent 执行循环"""
        from tea_agent.agent import Agent
        
        # 创建轻量 Agent
        agent = Agent(
            mode="lite",
            use_tools=True,
            enable_thinking=False,  # 禁用思考以提高速度
            use_cheap_model=self.use_cheap_model,
        )
        
        # 构建工具列表
        tool_defs = self._build_tool_defs(tools)
        
        # 执行循环
        while self._iterations < self.max_iterations:
            self._iterations += 1
            
            try:
                # 调用 LLM
                response = await self._call_llm(messages, tool_defs)
                
                # 检查是否有工具调用
                if response.get("tool_calls"):
                    # 执行工具调用
                    tool_results = await self._execute_tools(
                        response["tool_calls"],
                        tools
                    )
                    
                    # 添加到消息
                    messages.append({
                        "role": "assistant",
                        "content": response.get("content", ""),
                        "tool_calls": response["tool_calls"]
                    })
                    
                    for result in tool_results:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": result["tool_call_id"],
                            "content": result["content"]
                        })
                else:
                    # 没有工具调用，返回结果
                    return response.get("content", "")
                    
            except Exception as e:
                logger.error(f"Agent loop error: {e}")
                raise
        
        # 达到最大迭代次数
        return "达到最大迭代次数，任务可能未完全完成"
    
    async def _call_llm(self, messages: List[Dict], tools: List[Dict]) -> Dict:
        """调用 LLM"""
        # 这里应该调用实际的 LLM API
        # 为了简化，这里返回一个模拟响应
        # 实际实现应该调用配置的模型
        
        # TODO: 实际调用 LLM API
        # 目前返回一个简单的响应
        return {
            "content": "任务执行完成",
            "tool_calls": None
        }
    
    async def _execute_tools(self, tool_calls: List[Dict], available_tools: List[str]) -> List[Dict]:
        """执行工具调用"""
        results = []
        
        for tc in tool_calls:
            func_name = tc.get("function", {}).get("name", "")
            func_args = tc.get("function", {}).get("arguments", "{}")
            tool_call_id = tc.get("id", "")
            
            # 检查工具是否可用
            if func_name not in available_tools:
                results.append({
                    "tool_call_id": tool_call_id,
                    "content": f"错误: 工具 {func_name} 不可用"
                })
                continue
            
            try:
                # 解析参数
                args = json.loads(func_args) if isinstance(func_args, str) else func_args
                
                # 执行工具
                result = await self._run_tool(func_name, args)
                
                results.append({
                    "tool_call_id": tool_call_id,
                    "content": str(result)
                })
                
            except Exception as e:
                results.append({
                    "tool_call_id": tool_call_id,
                    "content": f"工具执行错误: {e}"
                })
        
        return results
    
    async def _run_tool(self, tool_name: str, args: Dict) -> Any:
        """执行单个工具"""
        # 这里应该调用实际的工具实现
        # 为了简化，这里返回一个模拟响应
        
        # TODO: 实际执行工具
        # 目前返回一个简单的响应
        return f"工具 {tool_name} 执行完成"
    
    def _build_tool_defs(self, tools: List[str]) -> List[Dict]:
        """构建工具定义"""
        # 这里应该从工具注册表获取定义
        # 为了简化，这里返回空列表
        
        # TODO: 实际构建工具定义
        return []
