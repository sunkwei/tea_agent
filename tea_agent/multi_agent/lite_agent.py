"""
# @2026-06-01 gen by Tea Agent, 轻量级 Agent

LiteAgent: 独立的轻量级 LLM Agent，零数据库依赖。

设计要点：
- 从 YAML 配置文件加载 LLM 连接参数（api_key, api_url, model_name 等）
- 纯内存运行：对话历史仅存储在内存列表中，不写数据库
- 支持 OpenAI-compatible Function Calling（工具调用）
- 工具通过简单的 register_tool(name, func, schema) 注册
- 支持流式回调（stream_callback）
- 支持多轮对话（max_iterations 限制工具调用轮数）

与 SubAgentWrapper 的区别：
- SubAgentWrapper 封装 OnlineToolSession，依赖 Storage/DB
- LiteAgent 完全自包含，只需一个 YAML 配置文件即可运行

用法:
    agent = LiteAgent(config_path="lite_agent_config.yaml")
    agent.register_tool("hello", lambda name: f"Hello {name}!", {...})
    result = agent.run("用hello工具向World打招呼")
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("multi_agent.lite_agent")

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


# ---------------------------------------------------------------------------
# 配置数据类
# ---------------------------------------------------------------------------

@dataclass
class LiteAgentModelConfig:
    """单个模型配置（对应 YAML 中的 main_model / cheap_model）。"""

    api_key: str = ""
    api_url: str = ""
    model_name: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    extra_options: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_url and self.model_name)


@dataclass
class LiteAgentConfig:
    """
    LiteAgent 的完整配置。

    可通过 YAML 文件或字典加载。
    如果字段未设置，回退到合理的默认值。
    """

    # ── 模型 ──
    main_model: LiteAgentModelConfig = field(default_factory=LiteAgentModelConfig)

    # ── 行为 ──
    system_prompt: str = ""
    max_iterations: int = 15          # 工具调用最大轮数
    keep_turns: int = 5               # 保留最近 N 轮对话
    max_tool_output: int = 32 * 1024  # 工具输出截断长度

    # ── 工具 ──
    tool_whitelist: Optional[List[str]] = None
    tool_blacklist: Optional[List[str]] = None

    # ── 兼容字段（YAML 展平用） ──
    api_key: str = ""
    api_url: str = ""
    model_name: str = ""


# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------

class ToolRegistry:
    """轻量工具注册表：name → (callable, openai_schema)"""

    def __init__(self):
        self._tools: Dict[str, tuple] = {}

    def register(self, name: str, func: Callable, schema: Dict[str, Any]):
        """注册一个工具。"""
        self._tools[name] = (func, schema)
        logger.debug(f"注册工具: {name}")

    def unregister(self, name: str):
        """移除工具。"""
        self._tools.pop(name, None)

    def get_func(self, name: str) -> Optional[Callable]:
        entry = self._tools.get(name)
        return entry[0] if entry else None

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """返回 OpenAI function calling 格式的工具列表。"""
        tools = []
        for name, (_, schema) in self._tools.items():
            tool_def = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": schema.get("description", ""),
                    "parameters": schema.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            tools.append(tool_def)
        return tools

    def apply_filter(self, whitelist: Optional[List[str]], blacklist: Optional[List[str]]):
        """应用白名单/黑名单过滤。"""
        if whitelist is not None:
            to_remove = [n for n in self._tools if n not in whitelist]
            for n in to_remove:
                self._tools.pop(n, None)

        if blacklist is not None:
            for n in blacklist:
                self._tools.pop(n, None)

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    def __len__(self):
        return len(self._tools)


# ---------------------------------------------------------------------------
# LiteAgent
# ---------------------------------------------------------------------------

class LiteAgent:
    """
    轻量级 LLM Agent — 零数据库依赖。

    核心流程:
        1. 用户任务 → run(task)
        2. 构建 messages: [system] + history + [user: task]
        3. 调用 LLM
        4. 如果 LLM 返回 tool_calls → 执行工具 → 追加结果 → 回到步骤 3
        5. 如果 LLM 返回 content → 返回给用户

    对话历史:
        仅保存在 self._history（内存列表），
        超过 keep_turns 轮自动滚动窗口。
    """

    DEFAULT_SYSTEM_PROMPT = (
        "你是一个智能助手，可以使用提供的工具来完成任务。\n"
        "使用工具时请遵循工具的参数要求。\n"
        "完成任务后，请返回清晰的最终结果。"
    )

    def __init__(
        self,
        config_path: Optional[str] = None,
        config_dict: Optional[Dict[str, Any]] = None,
        config: Optional[LiteAgentConfig] = None,
    ):
        """
        初始化 LiteAgent。

        配置优先级: config > config_dict > config_path > 默认值

        Args:
            config_path: YAML 配置文件路径
            config_dict: 配置字典
            config: LiteAgentConfig 实例
        """
        # ── 解析配置 ──
        if config:
            self._cfg = config
        elif config_dict:
            self._cfg = self._parse_config_dict(config_dict)
        elif config_path:
            self._cfg = self._load_config_yaml(config_path)
        else:
            self._cfg = LiteAgentConfig()

        # ── 验证必需参数 ──
        if not self._cfg.main_model.is_configured:
            raise ValueError(
                "LiteAgent 需要配置 main_model (api_key, api_url, model_name)。"
                "请提供 config_path、config_dict 或 config 参数。"
            )

        # ── 初始化 OpenAI 客户端 ──
        if not HAS_OPENAI:
            raise ImportError("LiteAgent 需要 openai 包。请执行: pip install openai")

        mc = self._cfg.main_model
        client_kwargs = {
            "api_key": mc.api_key,
            "base_url": mc.api_url,
        }
        if mc.extra_options:
            client_kwargs["default_headers"] = mc.extra_options.pop("default_headers", None)
            # 移除 None 值
            client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}

        self._client = OpenAI(**client_kwargs)
        self._model = mc.model_name
        self._temperature = mc.temperature
        self._max_tokens = mc.max_tokens
        self._model_extra = mc.extra_options

        # ── 工具 ──
        self._registry = ToolRegistry()
        if self._cfg.tool_whitelist or self._cfg.tool_blacklist:
            # 将在 register_tool 之后应用
            self._pending_filter = (
                self._cfg.tool_whitelist,
                self._cfg.tool_blacklist,
            )
        else:
            self._pending_filter = None

        # ── 对话历史（纯内存） ──
        self._history: List[Dict[str, Any]] = []
        self._system_prompt = self._cfg.system_prompt or self.DEFAULT_SYSTEM_PROMPT

        # ── 状态 ──
        self._running = False
        self._interrupted = False

        logger.info(
            f"LiteAgent 初始化完成 (model={self._model}, "
            f"max_iter={self._cfg.max_iterations}, keep_turns={self._cfg.keep_turns})"
        )

    # ------------------------------------------------------------------
    # 配置加载
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config_yaml(path: str) -> LiteAgentConfig:
        """从 YAML 文件加载配置。"""
        try:
            import yaml
        except ImportError:
            raise ImportError("需要 PyYAML 来读取配置文件。请执行: pip install pyyaml")

        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"配置文件不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return LiteAgent._parse_config_dict(data)

    @staticmethod
    def _parse_config_dict(data: Dict[str, Any]) -> LiteAgentConfig:
        """从字典解析配置。支持 YAML 展平键和嵌套键。"""
        cfg = LiteAgentConfig()

        # ── 主模型 ──
        main = data.get("main_model", {})
        if isinstance(main, dict):
            cfg.main_model = LiteAgentModelConfig(
                api_key=main.get("api_key", ""),
                api_url=main.get("api_url", ""),
                model_name=main.get("model_name", ""),
                temperature=float(main.get("temperature", 0.7)),
                max_tokens=int(main.get("max_tokens", 4096)),
                extra_options=main.get("options", {}),
            )

        # ── 展平键兼容（顶层 api_key 等） ──
        for flat_key in ("api_key", "api_url", "model_name"):
            if not getattr(cfg.main_model, flat_key) and data.get(flat_key):
                setattr(cfg.main_model, flat_key, data[flat_key])

        # ── 行为 ──
        cfg.system_prompt = data.get("system_prompt", "")
        cfg.max_iterations = int(data.get("max_iterations", 15))
        cfg.keep_turns = int(data.get("keep_turns", 5))
        cfg.max_tool_output = int(data.get("max_tool_output", 32 * 1024))

        # ── 工具 ──
        cfg.tool_whitelist = data.get("tool_whitelist")
        cfg.tool_blacklist = data.get("tool_blacklist")

        return cfg

    # ------------------------------------------------------------------
    # 工具管理
    # ------------------------------------------------------------------

    def register_tool(self, name: str, func: Callable, schema: Dict[str, Any]):
        """
        注册一个工具。

        Args:
            name: 工具名称（需唯一）
            func: 工具函数 callable(*args, **kwargs) → str
            schema: OpenAI function schema，至少包含 description 和 parameters
        """
        self._registry.register(name, func, schema)

    def register_tools_from_module(self, module, whitelist: Optional[List[str]] = None):
        """
        从一个 Python 模块批量注册工具。

        模块中需包含：
            toolkit_xxx(...)  → 工具实现函数
            meta_toolkit_xxx() → 返回 OpenAI schema dict

        符合 tea_agent toolkit 约定。

        Args:
            module: Python 模块对象
            whitelist: 工具名白名单（仅注册列表中的工具）
        """
        import inspect

        for attr_name in dir(module):
            if not attr_name.startswith("toolkit_"):
                continue

            func = getattr(module, attr_name, None)
            if not callable(func):
                continue

            meta_name = "meta_" + attr_name
            meta_func = getattr(module, meta_name, None)
            if not callable(meta_func):
                continue

            try:
                schema = meta_func()
            except Exception:
                continue

            name = schema.get("function", {}).get("name", attr_name)
            if whitelist and name not in whitelist:
                continue

            self._registry.register(name, func, schema)

    def _get_filtered_tools(self) -> List[Dict[str, Any]]:
        """获取过滤后的工具列表。"""
        tools = self._registry.get_openai_tools()

        # 应用初始黑白名单
        whitelist = self._cfg.tool_whitelist
        blacklist = self._cfg.tool_blacklist

        if whitelist:
            tools = [t for t in tools if t["function"]["name"] in whitelist]
        if blacklist:
            tools = [t for t in tools if t["function"]["name"] not in blacklist]

        return tools

    # ------------------------------------------------------------------
    # 核心执行
    # ------------------------------------------------------------------

    def run(
        self,
        task: str,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        执行任务，返回最终结果。

        Args:
            task: 用户任务描述
            stream_callback: 可选，每收到 delta 文本时调用 callback(text)

        Returns:
            Agent 的最终回复
        """
        self._running = True
        self._interrupted = False

        try:
            # 构建消息列表
            messages = self._build_messages(task)
            tools = self._get_filtered_tools()

            result = self._chat_loop(messages, tools, stream_callback)

            # 更新历史
            self._append_to_history("user", task)
            self._append_to_history("assistant", result)
            self._trim_history()

            return result

        except Exception as e:
            logger.error(f"LiteAgent 执行失败: {e}", exc_info=True)
            return f"[LiteAgent 错误] {e}"
        finally:
            self._running = False

    def _chat_loop(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        stream_callback: Optional[Callable[[str], None]],
    ) -> str:
        """
        核心对话循环：LLM ↔ 工具调用。

        Args:
            messages: 初始消息列表（会被原地修改）
            tools: 工具定义列表
            stream_callback: 流式回调

        Returns:
            最终文本回复
        """
        max_iter = self._cfg.max_iterations
        max_tool_out = self._cfg.max_tool_output

        for _ in range(max_iter):
            if self._interrupted:
                return "[已中断]"

            # 调用 LLM
            try:
                response = self._call_llm(messages, tools, stream_callback)
            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                return f"[LLM 调用错误] {e}"

            choice = response.choices[0]
            msg = choice.message

            # ── 有工具调用 ──
            if msg.tool_calls:
                # 将 assistant 消息（含 tool_calls）加入 messages
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })

                # 逐个执行工具
                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    tool_args_str = tc.function.arguments

                    # 解析参数
                    try:
                        tool_args = json.loads(tool_args_str) if tool_args_str else {}
                    except json.JSONDecodeError:
                        tool_args = {}

                    # 执行工具
                    tool_result = self._execute_tool(tool_name, tool_args)

                    # 截断
                    if len(tool_result) > max_tool_out:
                        tool_result = tool_result[:max_tool_out] + "\n... [输出已截断]"

                    # 追加 tool 消息
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    })

                # 继续循环，让 LLM 看到工具结果
                continue

            # ── 普通文本回复 ──
            content = msg.content or ""
            return content

        # 达到最大迭代次数
        return "[达到最大迭代次数，未获得最终结果]"

    def _call_llm(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        stream_callback: Optional[Callable[[str], None]],
    ):
        """
        调用 LLM API（支持流式和非流式）。

        Args:
            messages: 消息列表
            tools: 工具定义
            stream_callback: 流式回调（非 None 时启用 streaming）

        Returns:
            OpenAI ChatCompletion 对象
        """
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # 模型额外选项
        if self._model_extra:
            for k, v in self._model_extra.items():
                if k not in kwargs:
                    kwargs[k] = v

        if stream_callback is not None:
            # 流式模式
            kwargs["stream"] = True
            stream = self._client.chat.completions.create(**kwargs)

            # 手动聚合流式响应
            collected_content = ""
            collected_tool_calls: List[Any] = []
            final_choice = None

            for chunk in stream:
                if self._interrupted:
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    collected_content += delta.content
                    stream_callback(delta.content)

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        # 确保列表足够长
                        while len(collected_tool_calls) <= tc_delta.index:
                            collected_tool_calls.append({
                                "id": "",
                                "function": {"name": "", "arguments": ""},
                            })
                        entry = collected_tool_calls[tc_delta.index]
                        if tc_delta.id:
                            entry["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                entry["function"]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                entry["function"]["arguments"] += tc_delta.function.arguments

            # 构造一个模拟的 non-streaming response
            from types import SimpleNamespace

            tool_call_objs = []
            for tc in collected_tool_calls:
                tool_call_objs.append(SimpleNamespace(
                    id=tc["id"],
                    type="function",
                    function=SimpleNamespace(
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"],
                    ),
                ))

            msg_obj = SimpleNamespace(
                content=collected_content or None,
                tool_calls=tool_call_objs if tool_call_objs else None,
            )
            choice_obj = SimpleNamespace(message=msg_obj)
            return SimpleNamespace(choices=[choice_obj])

        else:
            # 非流式模式
            return self._client.chat.completions.create(**kwargs)

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """
        执行工具并返回结果字符串。

        Args:
            name: 工具名
            args: 参数字典

        Returns:
            工具执行结果
        """
        func = self._registry.get_func(name)
        if func is None:
            return f"❌ 未知工具: {name}"

        try:
            result = func(**args)
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"工具 {name} 执行失败: {e}")
            return f"❌ 工具执行错误: {e}"

    # ------------------------------------------------------------------
    # 对话历史管理
    # ------------------------------------------------------------------

    def _build_messages(self, task: str) -> List[Dict[str, Any]]:
        """构建发送给 LLM 的消息列表。"""
        messages: List[Dict[str, Any]] = []

        # 系统提示词
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})

        # 历史对话
        messages.extend(self._history)

        # 当前任务
        messages.append({"role": "user", "content": task})

        return messages

    def _append_to_history(self, role: str, content: str):
        """追加一条消息到历史。"""
        if content:
            self._history.append({"role": role, "content": content})

    def _trim_history(self):
        """按 keep_turns 滚动窗口，保留最近 N 轮。"""
        max_msgs = self._cfg.keep_turns * 2  # user + assistant 各算一条
        if len(self._history) > max_msgs:
            self._history = self._history[-max_msgs:]

    def reset_history(self):
        """清空对话历史。"""
        self._history.clear()

    def interrupt(self):
        """中断正在运行的任务。"""
        self._interrupted = True
        self._running = False

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def history(self) -> List[Dict[str, Any]]:
        return list(self._history)

    @property
    def tools(self) -> List[str]:
        return self._registry.tool_names

    @property
    def config(self) -> LiteAgentConfig:
        return self._cfg
