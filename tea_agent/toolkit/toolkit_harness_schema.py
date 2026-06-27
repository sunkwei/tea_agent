"""
Harness JSON Schema v1.0 — Tea Agent 机器可读能力清单

生成符合标准格式的能力描述，供其他 Agent、MCP 客户端、CI/CD 工具消费。
兼容 best-of-Agent-Harnesses 的 harnesses.json 格式，并扩展 Tea Agent 特有能力。

输出字段：
  - schema_version: 本 schema 版本
  - agent: 基础信息（名称、版本、描述、作者）
  - capabilities: 能力矩阵（bool + 详情）
  - tools: 全部注册工具（含 OpenAI tool schema）
  - skills: 可用技能列表
  - memory: 记忆系统详情
  - subagent: 子 Agent 详情
  - protocols: 支持的协议（ACP, MCP, stdio）
  - transport: 通信方式
  - security: 安全能力
  - config: 可配置参数摘要
"""

import json
import os
import sys
import logging
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("harness_schema")


def _get_agent_info() -> Dict:
    """获取 Agent 基础信息"""
    try:
        from tea_agent import __init__ as agent_mod
        version = getattr(agent_mod, "__version__", "0.10.0")
    except Exception:
        version = "0.10.0"

    return {
        "name": "Tea Agent",
        "version": version,
        "description": "A self-evolving AI agent with dynamic toolkit management, skills system, and sub-agent spawning",
        "author": "Hetin",
        "homepage": "https://github.com/Hetin/tea_agent",
        "language": "Python",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "requires_python": ">=3.10",
    }


def _get_capabilities() -> Dict:
    """获取能力矩阵"""
    caps = {
        "streaming": {
            "supported": True,
            "detail": "SSE 流式输出，支持 tool_calls 实时推送",
        },
        "tool_execution": {
            "supported": True,
            "detail": "60+ 内置工具 + 运行时动态创建工具",
            "tools_count": None,  # 运行时填充
            "dynamic_tool_creation": True,
            "self_describing_schemas": True,
        },
        "session_management": {
            "supported": True,
            "detail": "多会话管理，持久化到 SQLite 数据库",
            "persistence": "SQLite",
            "resume_support": True,
        },
        "skills_system": {
            "supported": True,
            "detail": "Skills .md 体系，兼容 anthropics/skills 格式",
            "anthropics_compatible": True,
            "skill_format": "SKILL.md (YAML front matter)",
            "scan_paths": [
                "~/.tea_agent/skills/<name>/SKILL.md (user)",
                "~/.claude/skills/<name>/SKILL.md (compat)",
                "~/.agents/skills/<name>/SKILL.md (compat)",
                "<project>/.tea_agent/skills/<name>/SKILL.md (project)",
                "<project>/.claude/skills/<name>/SKILL.md (project)",
            ],
            "skill_command_system": True,  # custom_commands
            "skill_crystallization": True,  # 自动从执行轨迹提取技能
        },
        "memory": {
            "supported": True,
            "detail": "持久记忆引擎，混合检索（关键词 + Embedding 语义）",
            "embedding_based": True,
            "keyword_search": True,
            "hybrid_weight": "keyword: 40%, embedding: 60%",
            "vector_cache": True,
            "dynamic_forgetting": True,
            "cross_session": True,
            "extraction": True,  # auto_extract from conversations
        },
        "sub_agent": {
            "supported": True,
            "detail": "隔离上下文窗口的子 Agent 生成",
            "isolated_context": True,
            "independent_tool_use": True,
            "async_spawn": True,
            "sync_spawn": True,
            "concurrent_execution": True,
            "dag_decomposition": True,
            "context_injection": True,
        },
        "mcp_support": {
            "supported": True,
            "detail": "MCP (Model Context Protocol) 客户端",
            "transport": ["stdio", "sse"],
            "server_management": True,
            "tool_discovery": True,
        },
        "self_evolution": {
            "supported": True,
            "detail": "后台自进化引擎，每小时自动优化",
            "automatic_optimization": True,
            "tool_usage_analysis": True,
            "skill_extraction": True,
            "memory_extraction": True,
            "docs_sync": True,
        },
        "code_intelligence": {
            "supported": True,
            "detail": "LSP 实时代码智能（Jedi + Ruff）",
            "diagnostics": True,
            "completion": True,
            "definition": True,
            "references": True,
            "hover": True,
            "context_analysis": True,
        },
        "knowledge_base": {
            "supported": True,
            "detail": "Markdown 知识库 + 项目知识图谱",
            "kb_format": "Markdown",
            "project_knowledge_graph": True,
            "ast_call_graph": True,
            "semantic_search": True,
        },
        "multi_modal": {
            "supported": True,
            "detail": "截图 + OCR 文字识别",
            "screenshot": True,
            "ocr": True,
            "browser_automation": True,
        },
        "planning": {
            "supported": True,
            "detail": "Plan → Execute → Verify 三步工作流",
            "plan_types": ["create", "decompose", "step", "verify", "run"],
            "dynamic_replan": True,
        },
        "permission_control": {
            "supported": True,
            "detail": "五层安全体系",
            "layers": ["git snapshot", "file backup", "compile verify", "LSP check", "test rollback"],
            "sudo_elevation": True,
        },
        "custom_commands": {
            "supported": True,
            "detail": "自定义命令模板系统",
            "placeholders": True,
            "user_level": True,
            "project_level": True,
            "builtin_commands": ["init", "explain", "test", "review", "plan"],
        },
        "monitoring": {
            "supported": True,
            "detail": "后台监控 + 桌面通知",
            "background_thread": True,
            "system_notifications": True,
            "scheduler_support": True,
        },
    }
    return caps


def _get_tools_schemas() -> List[Dict]:
    """获取所有注册工具的 JSON Schema"""
    try:
        from tea_agent import tlk
        toolkit = tlk._toolkit_
        if not toolkit:
            return []

        tools = []
        for name, func in toolkit._tools.items():
            if not name.startswith("toolkit_"):
                continue
            try:
                meta = getattr(func, "__meta__", None) or getattr(func, "meta", None)
                if meta:
                    if isinstance(meta, dict):
                        tools.append(meta)
                    elif hasattr(meta, "model_dump"):
                        tools.append(meta.model_dump())
                    else:
                        tools.append({"name": name, "description": func.__doc__[:100] if func.__doc__ else ""})
            except Exception:
                tools.append({"name": name, "description": func.__doc__[:100] if func.__doc__ else ""})

        return tools
    except Exception as e:
        logger.warning(f"获取工具列表失败: {e}")
        return []


def _get_skills_summary() -> List[Dict]:
    """获取技能摘要"""
    try:
        from tea_agent.toolkit.toolkit_skills import toolkit_skills
        r = toolkit_skills(action="list")
        return r.get("skills", [])
    except Exception:
        return []


def _get_memory_info() -> Dict:
    """获取记忆系统详情"""
    return {
        "engine": "memory.py + session_memory_component.py",
        "storage": "SQLite + Embedding vectors",
        "search_modes": ["keyword", "semantic", "hybrid"],
        "extraction": "auto_extract from conversations",
        "reflection": "元认知反思",
        "categories": ["instruction", "preference", "fact", "reminder", "general"],
        "importance_levels": "1-5",
        "expiration": "支持时间过期",
    }


def _get_subagent_info() -> Dict:
    """获取子 Agent 详情"""
    return {
        "engine": "LiteSession with isolated context window",
        "spawn_modes": ["async", "sync"],
        "context_isolation": True,
        "independent_tools": True,
        "concurrent_limit": 5,
        "task_decomposition": "DAG-based",
        "registry": "in-memory thread-safe dict",
    }


def _get_protocols() -> Dict:
    """获取支持的协议"""
    return {
        "acp": {
            "supported": True,
            "version": "1.0",
            "endpoints": [
                "GET  /health",
                "GET  /v1/agents",
                "GET  /v1/agents/tea-agent",
                "POST /v1/agents/tea-agent/chat",
                "CRUD /v1/sessions",
                "GET  /v1/sessions/{id}/messages",
            ],
            "capabilities": ["streaming", "tool_execution", "session_management"],
        },
        "mcp_client": {
            "supported": True,
            "transport": ["stdio", "sse"],
        },
    }


def _get_security() -> Dict:
    """获取安全能力"""
    return {
        "permission_layers": [
            {"name": "Layer 0", "detail": "Git snapshot — 干净工作区自动快照"},
            {"name": "Layer 1", "detail": "File backup — 时间戳 .bak 备份"},
            {"name": "Layer 2", "detail": "Compile verify — 编译验证，失败自动回滚"},
            {"name": "Layer 2.5", "detail": "LSP check — 影响分析 + lint + 签名对比"},
            {"name": "Layer 3", "detail": "Test rollback — 测试失败自动 git reset --hard"},
        ],
        "sudo_elevation": "Cross-platform GUI password prompt",
        "tool_permissions": "Multi-level accessory control",
    }


def _get_config_summary() -> Dict:
    """获取可配置参数摘要"""
    try:
        from tea_agent.config import load_config
        cfg = load_config()
        return {
            "main_model": str(cfg.main_model.model_name) if hasattr(cfg.main_model, "model_name") else "unknown",
            "cheap_model": str(cfg.cheap_model.model_name) if hasattr(cfg.cheap_model, "model_name") else "unknown",
            "max_iterations": getattr(cfg, "max_iterations", 25),
            "keep_turns": getattr(cfg, "keep_turns", 50),
            "enable_thinking": getattr(cfg, "enable_thinking", True),
        }
    except Exception:
        return {}


def generate_harness_schema(include_tools: bool = True) -> Dict:
    """生成完整的 Harness JSON Schema"""
    schema = {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "agent": _get_agent_info(),
        "capabilities": _get_capabilities(),
        "skills": _get_skills_summary(),
        "memory": _get_memory_info(),
        "subagent": _get_subagent_info(),
        "protocols": _get_protocols(),
        "security": _get_security(),
        "config": _get_config_summary(),
    }

    # 工具列表（可选，可能较大）
    if include_tools:
        tools = _get_tools_schemas()
        schema["tools"] = tools
        schema["tools_count"] = len(tools)
        # 更新能力中的工具计数
        if "tool_execution" in schema["capabilities"]:
            schema["capabilities"]["tool_execution"]["tools_count"] = len(tools)

    return schema


def toolkit_harness_schema(action: str = "generate", format: str = "json") -> Dict:
    """
    Harness JSON Schema — Tea Agent 机器可读能力清单

    生成符合标准格式的能力描述，供其他 Agent / MCP / CI 工具消费。

    Args:
        action: generate=生成 schema, summary=摘要, tools=仅工具列表
        format: json（默认）

    Returns:
        能力清单字典
    """
    if action == "summary":
        schema = generate_harness_schema(include_tools=False)
        return {
            "agent": schema["agent"]["name"] + " v" + schema["agent"]["version"],
            "capabilities": list(schema["capabilities"].keys()),
            "skills_count": len(schema["skills"]),
            "protocols": list(schema["protocols"].keys()),
            "generated_at": schema["generated_at"],
        }

    elif action == "tools":
        return {"tools": _get_tools_schemas(), "total": 0}

    else:  # generate
        return generate_harness_schema(include_tools=True)


# ── Meta for toolkit registration ──────────────────────

def meta_toolkit_harness_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_harness_schema",
            "description": "Harness JSON Schema — Tea Agent 机器可读能力清单。生成符合标准格式的能力描述，含 Agent 信息、15+ 能力矩阵、工具列表、技能、记忆、子 Agent、协议、安全等。供其他 Agent / MCP / CI 工具消费。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate", "summary", "tools"],
                        "description": "generate=完整 schema, summary=摘要, tools=仅工具列表"
                    },
                    "format": {"type": "string", "description": "输出格式", "default": "json"},
                },
                "required": ["action"],
            },
        },
    }
