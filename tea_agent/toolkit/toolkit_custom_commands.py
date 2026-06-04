"""
@2026-06-04 19:50:41 gen by glm-5,
Custom Commands 系统 — 借鉴 OpenCode 的可复用命令模板

功能:
  - 用户/项目级自定义命令（Markdown 模板 + YAML front matter）
  - 支持 {{placeholder}} 参数插值
  - 内置命令: init, explain, test, review, plan
  - 命令可被 agent 在对话中自动识别并路由

用法:
  # 添加命令
  toolkit_custom_commands(action='add', name='mycmd', 
    content='## {{title}}\n\n分析 {{file}} 的代码...')
  
  # 列出命令
  toolkit_custom_commands(action='list')
  
  # 执行命令
  toolkit_custom_commands(action='run', name='mycmd', 
    args={'title': '代码审查', 'file': 'main.py'})
"""

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("toolkit")

# ── 存储路径 ────────────────────────────────────────────

def _get_user_commands_dir() -> str:
    """用户级命令目录 ~/.tea_agent/commands/"""
    home = os.path.expanduser("~")
    d = os.path.join(home, ".tea_agent", "commands")
    os.makedirs(d, exist_ok=True)
    return d

def _get_project_commands_dir() -> str:
    """项目级命令目录 .tea_commands/"""
    d = os.path.join(os.getcwd(), ".tea_commands")
    os.makedirs(d, exist_ok=True)
    return d

def _cmd_path(name: str, scope: str = "user") -> str:
    """获取命令文件路径"""
    base = _get_user_commands_dir() if scope == "user" else _get_project_commands_dir()
    safe_name = name.replace(" ", "_").replace("/", "_")
    return os.path.join(base, f"{safe_name}.md")

def _scan_commands() -> List[dict]:
    """扫描所有可用命令"""
    commands = []
    for scope, base in [("user", _get_user_commands_dir()), 
                        ("project", _get_project_commands_dir())]:
        if not os.path.isdir(base):
            continue
        for fname in sorted(os.listdir(base)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(base, fname)
            try:
                cmd = _parse_command_file(fpath)
                if cmd:
                    cmd["scope"] = scope
                    cmd["file"] = fpath
                    commands.append(cmd)
            except Exception as e:
                logger.warning(f"解析命令文件失败 {fpath}: {e}")
    return commands

def _parse_command_file(fpath: str) -> Optional[dict]:
    """解析命令 Markdown 文件，提取 front matter 和正文"""
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    
    name = os.path.splitext(os.path.basename(fpath))[0]
    
    # 解析 YAML front matter (简易版)
    meta = {"description": "", "args": [], "tags": []}
    body = content
    
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            front = parts[1].strip()
            body = parts[2].strip()
            for line in front.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip().lower()
                    val = val.strip().strip('"').strip("'")
                    if key == "description":
                        meta["description"] = val
                    elif key == "tags":
                        meta["tags"] = [t.strip() for t in val.split(",")]
                    elif key == "args":
                        meta["args"] = [a.strip() for a in val.split(",")]
    
    # 提取占位符
    placeholders = re.findall(r"\{\{(\w+)\}\}", body)
    
    return {
        "name": name,
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "args_def": meta.get("args", placeholders),
        "placeholders": placeholders,
        "body": body,
        "content": content,
    }

# ── 内置命令模板 ────────────────────────────────────────

_BUILTIN_COMMANDS = {
    "init": """---
description: 扫描项目上下文，构建初始理解
tags: init, setup, context
args: path
---
## /init — 项目上下文初始化

扫描项目 {{path}}，分析结构、读取关键配置、构建初始上下文。

### 执行流程：
1. 使用 toolkit_explr 构建项目知识库
2. 读取 README.md / pyproject.toml 等关键文件
3. 分析目录结构（深度 2 层）
4. 输出项目概览报告

请先运行 toolkit_explr(build) 构建项目符号索引，然后读取关键配置。
""",
    "explain": """---
description: 解释指定代码文件或函数
tags: explain, code, analysis
args: target
---
## /explain — 代码解释

解释 {{target}} 的功能、结构和用法。

### 分析维度：
1. 整体功能概述
2. 核心类/函数职责
3. 输入输出分析
4. 依赖关系
5. 设计模式识别
""",
    "test": """---
description: 运行测试并分析结果
tags: test, verify
args: pattern
---
## /test — 运行测试

运行匹配 {{pattern}} 的测试，分析结果。

### 流程：
- 使用 toolkit_run_tests 运行测试
- 分析失败原因
- 输出测试覆盖率建议
""",
    "review": """---
description: 审查代码变更
tags: review, diff, code-quality
args: file
---
## /review — 代码审查

审查 {{file}} 的代码质量。

### 审查要点：
1. 代码结构和可读性
2. 错误处理和边界情况
3. 性能考虑
4. 类型安全
5. 测试覆盖
""",
    "plan": """---
description: 根据目标创建执行计划
tags: plan, execute
args: goal
---
## /plan — 创建执行计划

为目标 "{{goal}}" 创建分步执行计划。

### 流程：
1. 使用 toolkit_plan(decompose) 智能分解目标
2. 展示计划并等待确认
3. 确认后使用 toolkit_plan(run) 执行
""",
}

# ── 核心功能 ────────────────────────────────────────────

def _ensure_builtins():
    """确保内置命令存在"""
    cmd_dir = _get_user_commands_dir()
    for name, content in _BUILTIN_COMMANDS.items():
        fpath = os.path.join(cmd_dir, f"{name}.md")
        if not os.path.exists(fpath):
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content.strip())
            logger.info(f"创建内置命令: {name}")

def toolkit_custom_commands(
    action: str,
    name: str = None,
    content: str = None,
    args: Dict[str, str] = None,
    scope: str = "user",
    query: str = None,
    tag: str = None,
) -> dict:
    """
    Custom Commands 系统 — OpenCode 式可复用命令模板。
    
    Args:
        action: add/list/show/run/delete/search/builtin
        name: 命令名称
        content: [add] 命令 Markdown 内容
        args: [run] 参数键值对
        scope: [add/delete] user/project
        query: [search] 搜索关键词
        tag: [search] 按标签筛选
    """
    try:
        # 确保内置命令
        _ensure_builtins()
        
        if action == "add":
            if not name or not content:
                return {"ok": False, "error": "add 需要 name 和 content 参数"}
            fpath = _cmd_path(name, scope)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True, "name": name, "scope": scope, "path": fpath,
                    "msg": f"命令 '{name}' 已添加 ({scope}级)"}
        
        elif action == "list":
            cmds = _scan_commands()
            if tag:
                cmds = [c for c in cmds if tag in c.get("tags", [])]
            return {
                "ok": True,
                "total": len(cmds),
                "commands": [{
                    "name": c["name"],
                    "description": c["description"][:100],
                    "scope": c["scope"],
                    "tags": c.get("tags", []),
                    "args": c.get("args_def", []),
                } for c in cmds],
            }
        
        elif action == "show":
            if not name:
                return {"ok": False, "error": "show 需要 name 参数"}
            cmds = _scan_commands()
            for c in cmds:
                if c["name"] == name:
                    return {"ok": True, "command": c}
            return {"ok": False, "error": f"命令 '{name}' 不存在"}
        
        elif action == "run":
            if not name:
                return {"ok": False, "error": "run 需要 name 参数"}
            cmds = _scan_commands()
            cmd = next((c for c in cmds if c["name"] == name), None)
            if not cmd:
                return {"ok": False, "error": f"命令 '{name}' 不存在"}
            
            body = cmd["body"]
            resolved_args = args or {}
            
            # 参数插值
            for ph in cmd.get("placeholders", []):
                val = resolved_args.get(ph, "")
                if val:
                    body = body.replace("{{" + ph + "}}", val)
            
            # 检查未替换的占位符
            unresolved = re.findall(r"\{\{(\w+)\}\}", body)
            
            return {
                "ok": True,
                "name": name,
                "description": cmd.get("description", ""),
                "resolved_prompt": body,
                "unresolved_placeholders": unresolved,
                "hint": "将 resolved_prompt 作为指令执行" if not unresolved 
                        else f"请提供参数: {', '.join(unresolved)}",
            }
        
        elif action == "delete":
            if not name:
                return {"ok": False, "error": "delete 需要 name 参数"}
            deleted = False
            for scope_try in ("user", "project"):
                fpath = _cmd_path(name, scope_try)
                if os.path.exists(fpath):
                    os.remove(fpath)
                    deleted = True
                    break
            return {"ok": deleted, "name": name, 
                    "msg": f"命令 '{name}' 已删除" if deleted else f"命令 '{name}' 不存在"}
        
        elif action == "search":
            cmds = _scan_commands()
            results = []
            q = (query or "").lower()
            for c in cmds:
                if q and q not in c["name"].lower() and q not in c.get("description", "").lower():
                    continue
                if tag and tag not in c.get("tags", []):
                    continue
                results.append({
                    "name": c["name"],
                    "description": c.get("description", "")[:100],
                    "scope": c["scope"],
                    "tags": c.get("tags", []),
                })
            return {"ok": True, "total": len(results), "commands": results}
        
        elif action == "builtin":
            """重新生成所有内置命令"""
            count = 0
            for name, content in _BUILTIN_COMMANDS.items():
                fpath = os.path.join(_get_user_commands_dir(), f"{name}.md")
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content.strip())
                count += 1
            return {"ok": True, "count": count, "msg": f"已重置 {count} 个内置命令"}
        
        else:
            return {"ok": False, "error": f"未知 action: {action}"}
    
    except Exception as e:
        logger.exception(f"toolkit_custom_commands: {e}")
        return {"ok": False, "error": str(e)[:300]}


def meta_toolkit_custom_commands():
    """Meta data for tool registration"""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_custom_commands",
            "description": "Custom Commands 系统 — 借鉴 OpenCode 的可复用命令模板。支持 add(添加), list(列表), show(查看), run(执行), delete(删除), search(搜索), builtin(重置内置命令)。内置命令: init, explain, test, review, plan。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "show", "run", "delete", "search", "builtin"],
                        "description": "操作类型"
                    },
                    "name": {
                        "type": "string",
                        "description": "[add/show/run/delete] 命令名称"
                    },
                    "content": {
                        "type": "string",
                        "description": "[add] 命令 Markdown 内容（支持 YAML front matter 和 {{placeholder}}）"
                    },
                    "args": {
                        "type": "object",
                        "description": "[run] 参数键值对，如 {'file': 'main.py', 'title': 'code review'}"
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["user", "project"],
                        "description": "[add] 存储范围: user=~/.tea_agent/commands/, project=.tea_commands/",
                        "default": "user"
                    },
                    "query": {
                        "type": "string",
                        "description": "[search] 搜索关键词"
                    },
                    "tag": {
                        "type": "string",
                        "description": "[search] 按标签筛选"
                    },
                },
                "required": ["action"],
            },
        },
    }
