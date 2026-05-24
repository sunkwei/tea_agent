"""
# @2026-05-27 gen by Tea Agent, 多Agent委派工具

toolkit_delegate: 主Agent将子任务委派给子Agent的工具。
此工具会被注入到主Agent的工具列表中，使主Agent能主动使用子Agent。

用法:
    toolkit_delegate(agent_name="coder_1", task="审查 ./src/main.py")
"""

import logging
import threading
from typing import Dict, Optional, Any

logger = logging.getLogger("toolkit.delegate")

_orchestrator: Optional[Any] = None
_lock = threading.Lock()


def set_orchestrator(orchestrator):
    """
    设置全局编排器引用。

    Args:
        orchestrator: MultiAgentOrchestrator 实例
    """
    global _orchestrator
    with _lock:
        _orchestrator = orchestrator
    logger.info("toolkit_delegate: 编排器已绑定")


def get_orchestrator():
    """
    获取全局编排器引用。

    Returns:
        MultiAgentOrchestrator 或 None
    """
    return _orchestrator


def toolkit_delegate(
    agent_name: str = "",
    task: str = "",
    agent_type: str = "general",
    timeout: int = 120,
) -> str:
    """
    将子任务委派给指定的子Agent执行。

    主Agent调用此工具将子任务分配给子Agent。
    支持同步等待和异步模式。

    Args:
        agent_name: 目标子Agent的名称（如 "coder_1", "reviewer_2"）
        task: 要委派的任务描述
        agent_type: 如果agent_name不存在，按此类型自动创建Agent
        timeout: 超时秒数，默认120秒

    Returns:
        子Agent的执行结果
    """
    if not task:
        return "❌ 错误: 必须提供 task 参数"
    
    orch = get_orchestrator()
    if orch is None:
        return "❌ 错误: 编排器未初始化，无法委派任务。请先初始化 MultiAgentOrchestrator。"
    
    try:
        agent = orch.pool.get_agent(agent_name) if agent_name else None
        
        if agent is None:
            if not agent_name:
                import uuid
                agent_name = f"sub_{uuid.uuid4().hex[:8]}"
            
            agent_type = agent_type or "general"
            agent = orch.pool.create_agent(
                agent_name=agent_name,
                type_name=agent_type,
            )
        
        if agent is None:
            return f"❌ 无法创建Agent: {agent_name}"
        
        logger.info(f"委派任务到 {agent_name}: {task[:80]}...")
        result = agent.run(task)
        
        logger.info(f"Agent {agent_name} 完成，结果长度: {len(result)}")
        return result
        
    except Exception as e:
        logger.error(f"委派任务失败 ({agent_name}): {e}")
        return f"❌ 委派任务失败: {e}"


def meta_toolkit_delegate() -> dict:
    """
    返回 toolkit_delegate 工具的元数据（OpenAI function schema）。

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_delegate",
            "description": (
                "将子任务委派给子Agent执行。"
                "多个独立的子任务可以同时委派以实现并行处理。"
                "子Agent会使用自己的工具和配置独立完成任务。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "目标子Agent名称。如果不存在，将自动创建。第一次委派时可为空。"
                    },
                    "task": {
                        "type": "string",
                        "description": "要委派的任务描述。越详细越好，包括期望的输出格式。"
                    },
                    "agent_type": {
                        "type": "string",
                        "enum": ["general", "coder", "reviewer", "analyst", "researcher"],
                        "description": "Agent类型，仅在创建新Agent时使用。默认 general。"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数，默认120秒。"
                    }
                },
                "required": ["task"],
            },
        },
    }
