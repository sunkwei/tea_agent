import ast
from typing import Dict, cast, Callable, Tuple, List, Optional
import json
import os
import os.path as osp
import time
import logging

logger = logging.getLogger("tookit")

def meta_toolkit_reload():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_reload",
            "description": "重新加载所有工具函数，并注册为全局可用的方法，所有方法使用 toolkit_ 为前缀",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            }
        }
    }


def meta_toolkit_save() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_save",
            "description": "存储工具函数，以便以后使用该工具函数，使用 toolkit_reload() 重新加载",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "工具函数名，全局唯一，总是 toolkit_ 作为前缀",
                    },
                    "meta": {
                        "type": "object",
                        "description": "工具函数的元描述，符合 OpenAI tool func schema",
                    },
                    "pycode": {
                        "type": "string",
                        "description": "工具函数的 python 实现代码"
                    }
                }
            }
        }
    }


def toolkit_reload() -> Dict:
    tlk = cast(Toolkit, globals().get("_toolkit_", None))
    return tlk.reload()


def toolkit_save(name: str, meta: dict, pycode: str, version: str = "") -> Tuple[int, str]:
    """
    保存工具函数，支持版本管理。
    
    Args:
        name: 工具函数名
        meta: 工具元数据
        pycode: 工具函数代码
        version: 版本号（可选），不提供则自动递增
        
    Returns:
        Tuple[int, str]: (状态码, 消息)
    """
    tlk = cast(Toolkit, globals().get("_toolkit_", None))
    return tlk.save(name, meta, pycode, version)


def toolkit_rollback(name: str, version: str) -> Tuple[int, str]:
    """回滚工具到指定版本"""
    tlk = cast(Toolkit, globals().get("_toolkit_", None))
    return tlk.rollback(name, version)


def toolkit_list_versions(name: str) -> Tuple[int, List[str]]:
    """列出工具的所有可用版本"""
    tlk = cast(Toolkit, globals().get("_toolkit_", None))
    return tlk.list_versions(name)


def meta_toolkit_rollback():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_rollback",
            "description": "回滚工具到指定版本。用于撤销有问题的工具更新。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "工具函数名，如 toolkit_my_tool"
                    },
                    "version": {
                        "type": "string",
                        "description": "要回滚到的版本号，如 1.0.0"
                    }
                },
                "required": ["name", "version"]
            }
        }
    }


def meta_toolkit_list_versions():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_list_versions",
            "description": "列出工具的所有可用版本。用于查看工具的历史版本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "工具函数名，如 toolkit_my_tool"
                    }
                },
                "required": ["name"]
            }
        }
    }


def toolkit_rollback_impl(name: str, version: str) -> str:
    """回滚工具到指定版本"""
    tlk = cast(Toolkit, globals().get("_toolkit_", None))
    status, msg = tlk.rollback(name, version)
    if status == 0:
        return f"✅ {msg}"
    else:
        return f"❌ {msg}"


def toolkit_list_versions_impl(name: str) -> str:
    """列出工具的所有可用版本"""
    tlk = cast(Toolkit, globals().get("_toolkit_", None))
    status, versions = tlk.list_versions(name)
    if status == 0:
        if not versions:
            return f"工具 {name} 没有历史版本。"
        return f"工具 {name} 的版本：\n" + "\n".join(f"  - v{v}" for v in versions)
    else:
        return f"❌ {versions}"

# ========== Memory 工具函数 ==========

class Toolkit:
    def __init__(self, tool_dir=None):
        
        self.func_map: Dict[str, Callable] = {}
        self.meta_map: Dict[str, dict] = {}

        # User directory for saving and overriding tools
        self.user_dir = osp.join(
            os.path.expanduser("~"), ".tea_agent", "toolkit")
        os.makedirs(self.user_dir, exist_ok=True)

        # Built-in directory (relative to this file)
        self.builtin_dir = osp.join(osp.dirname(__file__), "toolkit")

        # Default save location is user_dir
        self.tool_dir = tool_dir if tool_dir else self.user_dir
        os.makedirs(self.tool_dir, exist_ok=True)

        self.reload()
        logger.info(f"Loaded {len(self.func_map)} toolkit functions from {self.tool_dir}")

    def reload(self) -> Dict:
        result = {
            "valid_tool": {},
            "invalid_tool": [],
        }

        def check_meta(meta) -> bool:
            if "type" not in meta or meta["type"] != "function":
                return False
            func = meta.get("function", {})
            if "description" not in func or "name" not in func:
                return False
            return True

        # Load from builtin first, then user dir (user overrides builtin)
        dirs_to_load = []
        if osp.exists(self.builtin_dir):
            dirs_to_load.append(("builtin", self.builtin_dir))
        if osp.exists(self.user_dir):
            dirs_to_load.append(("user", self.user_dir))

        temp_funcs = {}
        temp_metas = {}

        for source, d in dirs_to_load:
            for filename in os.listdir(d):
                if not (filename.endswith(".py") and filename.startswith("toolkit_")):
                    continue

                name = filename[:-3]
                filepath = osp.join(d, filename)

                try:
                    with open(filepath, encoding="utf-8") as f:
                        code = f.read()

# NOTE: 2026-05-01 15:15:56, self-evolved by tea_agent --- 修复 toolkit 加载时 exec 导致函数 __globals__ 缺少 import 符号的问题
                    # 使用受限的 globals 避免污染
                    safe_globals = {
                        "__builtins__": __builtins__,
                    }
                    local_vars = {}
                    exec(code, safe_globals, local_vars)
                    # merge local_vars into safe_globals so that function __globals__
                    # can see imports (e.g. from tea_agent.config import get_config)
                    safe_globals.update(local_vars)

                    func = local_vars.get(name)
                    func_meta = local_vars.get(f"meta_{name}")

                    if not callable(func):
                        result["invalid_tool"].append(
                            {"name": name, "reason": f"{name} is NOT callable"})
                        continue
                    if not callable(func_meta):
                        result["invalid_tool"].append(
                            {"name": name, "reason": f"meta_{name} not callable"})
                        continue

                    meta = func_meta()
                    if not check_meta(meta):
                        result["invalid_tool"].append(
                            {"name": name, "reason": "meta invalid"})
                        continue

                    # Override logic: later dirs win
                    temp_funcs[name] = func
                    temp_metas[name] = meta

                except Exception as e:
                    result["invalid_tool"].append(
                        {"name": name, "reason": f"{e} ({source}: {filename})"})

        self.func_map.clear()
        self.meta_map.clear()
        for k, v in temp_funcs.items():
            self.func_map[k] = v
            self.meta_map[k] = temp_metas[k]

        # 这几个永远有效
        self.func_map["toolkit_reload"] = toolkit_reload
        self.meta_map["toolkit_reload"] = meta_toolkit_reload()

        self.func_map["toolkit_save"] = toolkit_save
        self.meta_map["toolkit_save"] = meta_toolkit_save()

        self.func_map["toolkit_rollback"] = toolkit_rollback_impl
        self.meta_map["toolkit_rollback"] = meta_toolkit_rollback()

        self.func_map["toolkit_list_versions"] = toolkit_list_versions_impl
        self.meta_map["toolkit_list_versions"] = meta_toolkit_list_versions()

        result["valid_tool"] = {k: {"func": v, "meta": self.meta_map[k]} for k, v in self.func_map.items() if k not in (
            "toolkit_reload", "toolkit_save", "toolkit_rollback", "toolkit_list_versions")}

        return result

    def save(self, name: str, meta: dict, pycode: str, version: str = "") -> Tuple[int, str]:
        """
        保存工具函数到文件，支持版本管理。
        
        Args:
            name: 工具函数名
            meta: 工具元数据
            pycode: 工具函数代码
            version: 版本号（可选），格式如 "1.0.0"。如果不提供，自动递增
            
        Returns:
            Tuple[int, str]: (状态码, 消息)
        """
        meta_exam = {
            "type": "function",
            "function": {
                "name": "<工具函数名>",
                "description": "<工具函数简介>",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "param1": {
                            "type": "string",
                            "description": "参数1的说明",
                        },
                        "param2": {
                            "type": "number",
                            "description": "参数2的说明",
                        }
                    },
                    "required": ["param1"],
                }
            }
        }

        meta_exam_str = json.dumps(meta_exam, ensure_ascii=False)
        toolkit_path = self.tool_dir
        filename = osp.join(toolkit_path, f"{name}.py")

        # 1. 校验 meta 有效性
        if not isinstance(meta, dict):
            return (2, "meta must be a dict")

        if meta.get("type") != "function":
            return (2, f"meta.type must be 'function', 完整的 meta 参考：{meta_exam_str}")

        if "function" not in meta:
            return (2, f"meta.function is required, 完整的 meta 参考：{meta_exam_str}")

        func = meta["function"]

        if "name" not in func:
            return (2, f"meta.function.name is required, 完整的 meta 参考：{meta_exam_str}")

        if func["name"] != name:
            return (2, f"meta.function.name '{func['name']}' does not match tool name '{name}'")

        if not name.startswith("toolkit_"):
            return (2, "tool name must start with 'toolkit_' prefix for security")

        # 2. 校验 pycode 可执行性
        try:
            tree = ast.parse(pycode)
        except SyntaxError as e:
            return (3, f"Syntax error in pycode: {e}")

        # 检查是否定义了同名函数
        func_def = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                func_def = node
                break

        if func_def is None:
            return (3, f"Function '{name}' not found in pycode")

        # 3. 版本管理
        # 如果文件已存在，备份旧版本
        if osp.exists(filename):
            # 读取现有文件的版本号
            with open(filename, "r", encoding="utf-8") as f:
                old_content = f.read()
            
            # 自动提取版本号并递增
            if not version:
                import re
                version_match = re.search(r'# version:\s*([\d.]+)', old_content)
                if version_match:
                    old_version = version_match.group(1)
                    # 递增最后一位
                    parts = old_version.split('.')
                    parts[-1] = str(int(parts[-1]) + 1)
                    version = '.'.join(parts)
                else:
                    version = "1.0.0"
            
            # 创建备份
            backup_name = f"{name}.v{version}.bak.py"
            backup_path = osp.join(toolkit_path, backup_name)
            import shutil
            shutil.copy2(filename, backup_path)
        
        # 如果没有提供版本号，使用默认的 "1.0.0"
        if not version:
            version = "1.0.0"

        # 4. 通过校验，写入文件（带版本注释）
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"## llm generated tool func, created {time.asctime()}\n")
            f.write(f"# version: {version}\n\n")
            f.write(pycode)
            f.write("\n\n")
            f.write(f"def meta_{name}() -> dict:\n")
            f.write(f"    return {json.dumps(meta, ensure_ascii=False)}\n")

        logger.warning(f"save toolkit function: {name}, version:{version}\n==> meta:\n{json.dumps(meta, indent=4)}\n==> pycode:\n{pycode}\n")

        return (0, f"ok (v{version})")
    
    def rollback(self, name: str, version: str) -> Tuple[int, str]:
        """
        回滚工具到指定版本。
        
        Args:
            name: 工具函数名
            version: 要回滚到的版本号
            
        Returns:
            Tuple[int, str]: (状态码, 消息)
        """
        toolkit_path = self.tool_dir
        backup_name = f"{name}.v{version}.bak.py"
        backup_path = osp.join(toolkit_path, backup_name)
        filename = osp.join(toolkit_path, f"{name}.py")
        
        if not osp.exists(backup_path):
            return (1, f"Version {version} backup not found for {name}")
        
        import shutil
        # 备份当前版本
        if osp.exists(filename):
            current_backup = f"{name}.current.bak.py"
            current_backup_path = osp.join(toolkit_path, current_backup)
            shutil.copy2(filename, current_backup_path)
        
        # 恢复旧版本
        shutil.copy2(backup_path, filename)
        
        return (0, f"Rolled back {name} to v{version}")
    
    def list_versions(self, name: str) -> Tuple[int, List[str]]:
        """
        列出工具的所有可用版本。
        
        Args:
            name: 工具函数名
            
        Returns:
            Tuple[int, List[str]]: (状态码, 版本列表)
        """
        toolkit_path = self.tool_dir
        versions = []
        
        # 查找所有备份文件
        pattern = f"{name}.v"
        for filename in os.listdir(toolkit_path):
            if filename.startswith(pattern) and filename.endswith(".bak.py"):
                # 提取版本号
                version = filename[len(pattern):-len(".bak.py")]
                versions.append(version)
        
        # 排序版本号
        versions.sort(key=lambda v: [int(x) for x in v.split('.')])
        
        return (0, versions)
