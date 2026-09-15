"""
Toolkit 系统核心 — 工具加载/注册/执行引擎。

职责链：
  1. 从 toolkit/*.py 加载工具定义（名称/描述/参数/Python 代码）
  2. 编译代码 → 动态注册为全局 `toolkit_*()` 函数
  3. 构建 LLM 可消费的 func_map（name→function_ref）
  4. 提供 reload/save/rollback/list_versions 版本管理

关键设计：
  - func_map 直绑 Toolkit 实例方法（消除旧的 5 跳间接调用）
  - exec(code, safe_globals) 隔离执行，不污染命名空间
  - rollback_for_llm() 专门给 LLM 调用，内部调 rollback_impl()
"""
import ast
import importlib.util
import inspect
import json
import logging
import os
import os.path as osp
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable

from tea_agent.toolkit.toolkit_set_topic_title import (
    meta_toolkit_set_topic_title,
    toolkit_set_topic_title,
)

logger = logging.getLogger("toolkit")

# ── 模块级 Toolkit 实例（公开发行；由 Agent / APIServer 在初始化时设置）──
# 读取方（lite_agent / subagent / harness_schema）通过 tlk.toolkit 直接访问。
# 历史命名 _toolkit_ 已废弃；新代码请使用 tlk.toolkit。
toolkit = None

# 不暴露给 LLM 的工具（供人类/服务器/外部消费者使用，注册但不出现在 tool 列表）：
# - toolkit_harness_schema: 机器可读能力清单，消费方是 MCP/CI，不是 Agent 自身
# - toolkit_export_last_pdf: 重型 PDF 导出，消费方是人（server 仍直接 import 其函数）
LLM_TOOL_EXCLUDES = {
    "toolkit_harness_schema",
    "toolkit_export_last_pdf",
}


def llm_tool_names(func_map_keys) -> list[str]:
    """返回应暴露给 LLM 的工具名列表（排序稳定，供 build_tools 使用）。

    排序保证工具 JSON Schema 顺序跨进程稳定——这是 DeepSeek 前缀缓存命中的前提。
    """
    return sorted(
        k for k in func_map_keys
        if k.startswith("toolkit_") and k not in LLM_TOOL_EXCLUDES
    )


def meta_toolkit_reload():
    """Meta toolkit reload."""
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
    """Meta toolkit save."""
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

def meta_toolkit_rollback():
    """Meta toolkit rollback."""
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
    """Meta toolkit list versions."""
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

# ========== Skill Document 自动生成 ==========

def _auto_generate_skill_doc(name: str, meta: dict, pycode: str, version: str, toolkit_path: str) -> str:
    """工具保存后自动生成 best-skills 风格的 SKILL.md 文档。

    写入路径: {toolkit_path}/../skills/{name}/SKILL.md

    Args:
        name: 工具函数名（如 toolkit_my_tool）
        meta: OpenAI function tool schema
        pycode: Python 源码
        version: 版本号
        toolkit_path: 工具目录路径

    Returns:
        状态消息
    """
    try:
        parent = osp.dirname(toolkit_path)
        skill_dir = osp.join(parent, "skills", name)
        os.makedirs(skill_dir, exist_ok=True)

        # 提取工具描述
        func_meta = meta.get("function", {})
        description = func_meta.get("description", "No description")

        # 提取参数信息
        params = func_meta.get("parameters", {})
        required = params.get("required", [])
        properties = params.get("properties", {})

        # 从 pycode 提取函数签名和 docstring
        try:
            tree = ast.parse(pycode)
            func_node = None
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
                    func_node = node
                    break

            pydoc = ast.get_docstring(func_node) if func_node else ""
            args_list = []
            if func_node:
                for arg in func_node.args.args:
                    args_list.append(arg.arg)
            f"{name}({', '.join(args_list)})" if args_list else f"{name}()"
        except SyntaxError:
            pydoc = ""
            args_list = []

        # 构建 SKILL.md 内容
        now = time.strftime("%Y-%m-%d %H:%M")
        skill_name = name.replace("toolkit_", "").replace("_", " ").title()

        lines = [
            "---",
            f"name: {skill_name}",
            f"description: {description}",
            f"version: {version}",
            f"generated: {now}",
            "---",
            "",
            f"# {skill_name}",
            "",
            f"> **工具函数**: `{name}`  ",
            f"> **版本**: {version}  ",
            f"> **生成时间**: {now}",
            "",
            "## 概述",
            "",
            description,
            "",
        ]

        if pydoc:
            # 缩进 pydoc 以保持可读性
            lines.append("## 详细说明")
            lines.append("")
            for doc_line in pydoc.strip().split("\n"):
                lines.append(doc_line)
            lines.append("")

        # 参数表
        if properties:
            lines.append("## 参数")
            lines.append("")
            lines.append("| 参数名 | 类型 | 必填 | 说明 |")
            lines.append("|--------|------|:----:|------|")
            for pname, pinfo in properties.items():
                ptype = pinfo.get("type", "any")
                is_req = "✅" if pname in required else ""
                pdesc = pinfo.get("description", "").replace("|", "\\|")
                lines.append(f"| `{pname}` | `{ptype}` | {is_req} | {pdesc} |")
            lines.append("")

        # 调用示例
        lines.append("## 调用示例")
        lines.append("")
        lines.append("```python")
        if args_list:
            args_str = ", ".join(f"{a}=..." for a in args_list)
            lines.append(f"# {name}({args_str})")
        else:
            lines.append(f"# {name}()")
        lines.append(f"# → {description[:80]}...")
        lines.append("```")
        lines.append("")

        # 源码位置
        rel_path = osp.relpath(
            osp.join(toolkit_path, f"{name}.py"),
            osp.dirname(toolkit_path)
        )
        lines.append("## 源码")
        lines.append("")
        lines.append(f"`{rel_path}` → function `{name}()` + `meta_{name}()`")
        lines.append("")

        # 写入
        skill_md_path = osp.join(skill_dir, "SKILL.md")
        with open(skill_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return f"SKILL.md → {skill_dir}"

    except Exception as e:
        logger.warning(f"SKILL.md 生成失败: {e}")
        return ""

# ========== Memory 工具函数 ==========

class Toolkit:
    """动态工具加载器 — 管理 75+ 内置工具，支持运行时热加载和版本回滚。"""
    _CACHE_TTL = 30  # 默认缓存 30 秒
    # 工具结果缓存改为**白名单**：仅缓存纯函数（只读、无副作用、30s 内结果可视为不变）。
    # 其余工具一律真实执行——旧黑名单制（默认全缓存）会让 question/todo/screenshot/ocr/
    # clipboard/scheduler 等副作用或时间敏感工具在 TTL 内返回陈旧结果（如 question 重复
    # 返回第一次的答案、screenshot 拿到 30s 前的屏幕）。
    _CACHE_WHITELIST = {
        'toolkit_file',          # read/list（write 单独绕过）
        'toolkit_lsp',           # 静态代码分析（jedi/ruff）
        'toolkit_search',        # 只读搜索（web/code）
        'toolkit_query_chat_history',  # 只读 DB 查询
        'toolkit_list_provider_models',  # 只读 API 查询
        'toolkit_eval_loop',     # 确定性规则评分（无 LLM）
        'toolkit_task_resume',   # 只读状态检查
    }

    def __init__(self, tool_dir=None):
        """初始化 Toolkit 实例，加载内置和用户自定义工具。"""
        self.func_map: dict[str, Callable] = {}
        self.meta_map: dict[str, dict] = {}
        self._cache: dict[tuple, tuple] = {}  # (key, ttl) → (result, expire_time)
        # 工具签名缓存：供 call_tool 入参预检。必须在 reload()/save() 后清空，
        # 否则工具改了签名仍按旧签名校验，会把合法调用误判为非法。
        self._sig_cache: dict = {}
        self._user_created_tools: set[str] = set()  # 用户通过 toolkit_save 创建的工具，默认不缓存

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

    def _binding_error(self, func_name: str, func, kwargs: dict) -> str | None:
        """预检 kwargs 能否绑定到工具签名；不可绑定时返回可自纠的错误文本。

        模型常给工具传「等价但实际不存在」的关键字（线上高频：toolkit_exec 的
        command / arguments）。此前这类调用直接抛
        ``TypeError: got an unexpected keyword argument 'command'`` —— 该文本不含
        合法参数名，模型无从改对，只能反复换写法试错，于是每个畸形形态都再产生
        一条新 warning。51 个工具都可能有此问题，逐个加 **kwargs 是打 51 次补丁；
        在本项目的唯一调用汇聚点检查一次才是修根因。

        ⚠️ 刻意**不静默丢弃**未知参数：丢弃会让「filename 为空」这类莫名错误
        顶替真正的根因（模型写了 file_path 却被悄悄扔掉），比异常更难诊断。

        Args:
            func_name: 工具名（仅用于错误文本）
            func: 工具函数对象
            kwargs: 待绑定参数

        Returns:
            错误文本；None 表示可正常绑定（含取不到签名的内建可调用对象）
        """
        sig = self._sig_cache.get(func_name)
        if sig is None:
            try:
                sig = inspect.signature(func)
            except (TypeError, ValueError):
                return None  # 取不到签名：不拦截，保持原行为
            self._sig_cache[func_name] = sig
        try:
            sig.bind(**kwargs)
        except TypeError as e:
            named = [n for n, p in sig.parameters.items()
                     if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
            required = [n for n, p in sig.parameters.items()
                        if p.default is inspect.Parameter.empty
                        and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
            unknown = sorted(set(map(str, kwargs)) - set(named))
            hints = [f"调用 {func_name} 失败：{e}"]
            if unknown:
                hints.append(f"不支持的参数 {unknown}；该工具只接受: {', '.join(named) or '(无)'}")
            if required:
                hints.append(f"其中必填: {', '.join(required)}")
            hints.append(f"实际收到参数: {sorted(map(str, kwargs))}")
            return " | ".join(hints)
        return None

    def _record_usage(self, func_name: str) -> None:
        """累加工具使用次数（写项目 db 的 tool_usage 表）。

        刻意做成 best-effort 且**不创建 db**：见 store.peek_storage 的说明。
        统计是辅助能力，一次写失败绝不能把工具调用带崩，也不能改变裸用
        Toolkit（无会话/无库）时的建库行为。
        """
        try:
            from tea_agent.store import peek_storage

            st = peek_storage()
            if st is not None:
                st.tool_usage.record_use(func_name)
        except Exception as e:  # noqa: BLE001 — 统计失败不影响调用
            logger.debug("record_usage(%s) 跳过: %s", func_name, e)

    def call_tool(self, func_name: str, **kwargs):
        """带缓存的工具调用代理。

        仅对**白名单**纯函数缓存结果，TTL 默认 30 秒。
        相同工具+相同参数在 TTL 内重复调用直接返回缓存结果。
        用户通过 toolkit_save 创建的工具一律不缓存。

        Args:
            func_name: 工具函数名
            **kwargs: 工具参数

        Returns:
            工具函数返回值

        Raises:
            KeyError: 工具不存在
            TypeError: 参数无法绑定到工具签名（消息点名非法参数并列出合法参数）
        """
        if func_name not in self.func_map:
            raise KeyError(f"Unknown tool: {func_name}")

        # 入参绑定预检：放在最前面，覆盖缓存与非缓存两条路径
        # （toolkit_file 等白名单工具走缓存分支，只检查非缓存分支会恰好漏掉它们）
        bind_err = self._binding_error(func_name, self.func_map[func_name], kwargs)
        if bind_err is not None:
            logger.warning("toolkit 入参绑定失败: %s", bind_err)
            raise TypeError(bind_err)

        # 使用统计（tool_shield 的数据源）：放在缓存判定**之前**——命中缓存同样是
        # 一次真实调用，记在缓存之后就少算，长期会把常用工具误判成"没用过"而屏蔽。
        self._record_usage(func_name)

        # 白名单之外 + 用户创建的工具不缓存（真实执行）
        if func_name not in self._CACHE_WHITELIST or func_name in self._user_created_tools:
            return self.func_map[func_name](**kwargs)

        if func_name == 'toolkit_file' and kwargs.get('action') == 'write':
            return self.func_map[func_name](**kwargs)

        now = time.time()
        cache_key = (func_name, json.dumps(kwargs, sort_keys=True, default=str))

        # 检查缓存
        if cache_key in self._cache:
            result, expire_at = self._cache[cache_key]
            if now < expire_at:
                logger.debug(f"Cache HIT: {func_name} (TTL {expire_at - now:.0f}s)")
                return result
            else:
                del self._cache[cache_key]

        # 执行工具
        result = self.func_map[func_name](**kwargs)

        # 存入缓存
        expire_at = now + self._CACHE_TTL
        self._cache[cache_key] = (result, expire_at)

        # 定期清理过期缓存（概率触发，避免每次都清理）
        if len(self._cache) > 500 or (self._cache and hash(cache_key) % 20 == 0):
            self._purge_cache()

        return result

    def _purge_cache(self):
        """清理过期缓存条目"""
        now = time.time()
        expired = [k for k, (_, exp) in self._cache.items() if now >= exp]
        for k in expired:
            del self._cache[k]
        if expired:
            logger.debug(f"Cache purge: removed {len(expired)} expired entries, {len(self._cache)} remaining")

    def _check_dependencies(self, pycode: str) -> str:
        """自动检测 pycode 中的 import 并安装缺失依赖。

        在 Server 模式下仅报告缺失依赖，不执行 pip install（避免阻塞请求线程）。
        """
        MODULE_MAP = {  # noqa: N806
            'PIL': 'Pillow', 'cv2': 'opencv-python', 'sklearn': 'scikit-learn',
            'yaml': 'PyYAML', 'bs4': 'beautifulsoup4', 'dateutil': 'python-dateutil',
            'jwt': 'PyJWT', 'Crypto': 'pycryptodome', 'Image': 'Pillow'
        }

        try:
            tree = ast.parse(pycode)
        except SyntaxError:
            return ""

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split('.')[0])

        std_libs = getattr(sys, 'stdlib_module_names', set())

        missing = []
        for mod in imports:
            if mod in std_libs:
                continue
            if importlib.util.find_spec(mod) is None:
                pkg_name = MODULE_MAP.get(mod, mod)
                missing.append(pkg_name)

        if not missing:
            return "✅ 依赖已就绪"

        # Server 模式下只报告不安装
        if "tea_agent.server" in sys.modules:
            return f"⚠️ 缺失依赖（Server 模式跳过安装）: {', '.join(missing)}"

        installed = []
        errors = []
        for pkg in missing:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", pkg],
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode == 0:
                    installed.append(pkg)
                else:
                    errors.append(f"{pkg}: {result.stderr[:100]}")
            except Exception as e:
                errors.append(f"{pkg}: {str(e)}")

        msg = f"📦 自动安装依赖: {', '.join(installed)}"
        if errors:
            msg += f" | ❌ 安装失败: {', '.join(errors)}"
        return msg

    def reload(self) -> dict:
        """Reload."""
        result = {
            "valid_tool": {},
            "invalid_tool": [],
        }

        def check_meta(meta) -> bool:
            """校验 meta 字典是否符合 OpenAI function calling schema。"""
            if "type" not in meta or meta["type"] != "function":
                return False
            func = meta.get("function", {})
            return not ("description" not in func or "name" not in func)

        # Load from builtin first, then user dir (user overrides builtin)
        dirs_to_load = []
        if osp.exists(self.builtin_dir):
            dirs_to_load.append(("builtin", self.builtin_dir))
        if osp.exists(self.user_dir):
            dirs_to_load.append(("user", self.user_dir))

        temp_funcs = {}
        temp_metas = {}

        for source, d in dirs_to_load:
            # 排序遍历：工具 JSON Schema 的顺序是 DeepSeek 前缀缓存的一部分，
            # os.listdir 返回文件系统顺序（跨进程不稳定），必须排序保证逐字节稳定。
            for filename in sorted(os.listdir(d)):
                if not (filename.endswith(".py") and filename.startswith("toolkit_")):
                    continue

                name = filename[:-3]
                filepath = osp.join(d, filename)

                try:
                    with open(filepath, encoding="utf-8") as f:
                        code = f.read()

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
        # 工具集已换，签名缓存必须同步失效：否则同名工具改了参数后，
        # call_tool 仍按旧签名做预检，会把合法调用误判为非法（或反之）。
        self._sig_cache.clear()
        for k, v in temp_funcs.items():
            self.func_map[k] = v
            self.meta_map[k] = temp_metas[k]

        # 这几个永远有效 —— 直接绑定 Toolkit 实例方法（去除旧的 5 跳间接）
        self.func_map["toolkit_reload"] = self.reload
        self.meta_map["toolkit_reload"] = meta_toolkit_reload()

        self.func_map["toolkit_save"] = self.save
        self.meta_map["toolkit_save"] = meta_toolkit_save()

        self.func_map["toolkit_rollback"] = self.rollback_for_llm
        self.meta_map["toolkit_rollback"] = meta_toolkit_rollback()

        self.func_map["toolkit_list_versions"] = self.list_versions_for_llm
        self.meta_map["toolkit_list_versions"] = meta_toolkit_list_versions()

        self.func_map["toolkit_set_topic_title"] = toolkit_set_topic_title
        self.meta_map["toolkit_set_topic_title"] = meta_toolkit_set_topic_title()

        result["valid_tool"] = {k: {"func": v, "meta": self.meta_map[k]} for k, v in self.func_map.items() if k not in (
            "toolkit_reload", "toolkit_save", "toolkit_rollback", "toolkit_list_versions", "toolkit_set_topic_title")}

        return result

    def save(self, name: str, meta: dict, pycode: str, version: str = "") -> tuple[int, str]:
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
        is_my_tool = name.endswith("_my")
        if is_my_tool:
            toolkit_path = self.user_dir
            os.makedirs(toolkit_path, exist_ok=True)
        else:
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

        dep_msg = self._check_dependencies(pycode)
        if dep_msg and "❌" in dep_msg:
            logger.warning(f"Dependency check warning: {dep_msg}")
        elif dep_msg:
            logger.info(f"Dependency check: {dep_msg}")

        # 检查是否定义了同名函数
        func_def = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                func_def = node
                break

        if func_def is None:
            return (3, f"Function '{name}' not found in pycode")

        # 3. 版本管理
        # 如果文件已存在，备份旧版本到 .v<旧版本>.bak.py（供 rollback / list_versions 使用）
        if osp.exists(filename):
            with open(filename, encoding="utf-8") as f:
                old_content = f.read()

            old_version = None
            # 自动提取版本号并递增
            if not version:
                version_match = re.search(r'# version:\s*([\d.]+)', old_content)
                if version_match:
                    old_version = version_match.group(1)
                    # 递增最后一位
                    parts = old_version.split('.')
                    parts[-1] = str(int(parts[-1]) + 1)
                    version = '.'.join(parts)
                else:
                    version = "1.0.0"

            # 写版本备份文件（.v<旧版本>.bak.py）
            if old_version:
                backup_name = f"{name}.v{old_version}.bak.py"
                backup_path = osp.join(toolkit_path, backup_name)
                try:
                    with open(backup_path, "w", encoding="utf-8") as bf:
                        bf.write(old_content)
                except OSError:
                    logger.warning(f"写入版本备份失败: {backup_path}")

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

        # 5. 自动生成 best-skills 风格的 SKILL.md 文档
        skill_doc_msg = _auto_generate_skill_doc(name, meta, pycode, version, toolkit_path)
        result_msg = f"ok (v{version})"
        if skill_doc_msg:
            result_msg = f"ok (v{version}); {skill_doc_msg}"

        # 标记为用户创建的工具，后续调用不缓存
        self._user_created_tools.add(name)
        # 该工具的签名即将随 reload 改变，丢弃旧签名缓存避免误判
        self._sig_cache.pop(name, None)

        return (0, result_msg)

    def rollback(self, name: str, version: str) -> tuple[int, str]:
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

        # 备份当前版本
        if osp.exists(filename):
            current_backup = f"{name}.current.bak.py"
            current_backup_path = osp.join(toolkit_path, current_backup)
            shutil.copy2(filename, current_backup_path)

        # 恢复旧版本
        shutil.copy2(backup_path, filename)

        return (0, f"Rolled back {name} to v{version}")

    def list_versions(self, name: str) -> tuple[int, list[str]]:
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

    # ── LLM 友好的格式化版本（供 func_map 直接绑定，去除旧的 toolkit_*_impl 模块级函数）──

    def rollback_for_llm(self, name: str, version: str) -> str:
        """回滚工具到指定版本（LLM 友好输出，含 ✅/❌）。"""
        status, msg = self.rollback(name, version)
        if status == 0:
            return f"✅ {msg}"
        return f"❌ {msg}"

    def list_versions_for_llm(self, name: str) -> str:
        """列出工具的所有可用版本（LLM 友好输出）。"""
        status, versions = self.list_versions(name)
        if status == 0:
            if not versions:
                return f"工具 {name} 没有历史版本。"
            return f"工具 {name} 的版本：\n" + "\n".join(f"  - v{v}" for v in versions)
        return f"❌ {versions}"
