"""
会话模块
提供统一的聊天会话接口，支持多种后端
"""

from openai import OpenAI
from abc import ABC, abstractmethod
from typing import List, Dict, Callable, Tuple, Any, Optional
import json
import re


class BaseChatSession(ABC):
    """
    聊天会话抽象基类
    定义公共接口和共享功能
    """

    def __init__(
        self,
        model: str,
        max_history: int = 10,
        system_prompt: str = "你是一个智能助手，可以调用工具函数来帮助用户解决问题。"
    ):
        """
        初始化基类

        Args:
            model: 模型名称
            max_history: 最大历史消息数
            system_prompt: 系统提示词
        """
        self.model = model
        self.max_history = max_history
        self.system_prompt = system_prompt

        # 消息列表
        self.messages: List[Dict] = []
        self.messages.append({"role": "system", "content": self.system_prompt})

        # 打断标志
        self.interrupted = False

    @abstractmethod
    def chat_stream(self, msg: str, callback: Callable[[str], None]) -> Tuple[str, bool]:
        """
        流式对话（抽象方法，子类必须实现）

        Args:
            msg: 用户消息
            callback: 流式输出回调函数

        Returns:
            Tuple[str, bool]: (助手完整回复, 是否使用了工具调用)
        """
        pass

    def add_user_message(self, msg: str):
        """添加用户消息"""
        self.messages.append({"role": "user", "content": msg})

    def add_assistant_message(self, msg: str):
        """添加助手消息"""
        self.messages.append({"role": "assistant", "content": msg})

    def add_tool_result(self, tool_call_id: str, content: str):
        """添加工具执行结果"""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })

    def get_recent_messages(self) -> List[Dict]:
        """获取最近的消息（排除系统消息）"""
        return [m for m in self.messages if m["role"] != "system"]

    def load_history(self, conversations: List[Dict]):
        """从数据库加载历史记录"""
        self.messages = [{"role": "system", "content": self.system_prompt}]

        for conv in conversations:
            self.messages.append({"role": "user", "content": conv["user_msg"]})
            self.messages.append(
                {"role": "assistant", "content": conv["ai_msg"]})

    def interrupt(self):
        """打断当前生成"""
        self.interrupted = True

    def reset_interrupt(self):
        """重置打断标志"""
        self.interrupted = False

    def _trim_messages(self):
        """裁剪消息，保持最近N条"""
        if len(self.messages) <= self.max_history * 2 + 1:
            return

        # 保留系统消息和最近的对话
        system_msg = self.messages[0]
        recent = self.messages[-(self.max_history * 2):]
        self.messages = [system_msg] + recent


# ──────────────────────────────────────────────
# LLM 驱动的记忆提取 Prompt
# ──────────────────────────────────────────────
_MEMORY_EXTRACT_SYSTEM = """你是一个专业的信息归档助手。请阅读对话记录，提取有长期保存价值的信息。

【可记忆的类别】
- user_preference：用户明确表达的偏好、习惯、风格
- fact：客观事实、知识点、概念解释
- project_info：项目相关信息（名称、技术栈、目录结构等）
- decision：技术决策、方案选择、取舍理由
- experience：经验教训、踩坑记录、最佳实践
- code_pattern：代码模式、设计模式、实现套路
- tool_usage：工具使用技巧、命令组合、工作流
- environment：环境配置、路径、依赖、版本
- general：其他有价值的信息

【提取规则】
1. 只提取有长期价值的信息，忽略寒暄、临时调试、已解决的琐碎问题
2. summary 要精炼（不超过150字），自包含，去掉"用户说"这类冗余
3. importance 为 1-5，5 = 极其重要，1 = 可记可不记
4. tags 为简短关键词数组（2-5个）
5. 如果没什么值得记的，返回空数组 []

【输出格式】
严格输出 JSON 数组，不要任何额外文字、不要 markdown 代码块。
每条格式：{"category": "...", "summary": "...", "importance": N, "tags": ["..."]}
"""

_MEMORY_EXTRACT_USER_TEMPLATE = """请提取以下对话中的记忆：

【对话记录】
{chat_text}

请直接输出 JSON 数组："""


class OnlineToolSession(BaseChatSession):
    """
    在线工具调用会话
    支持 OpenAI 兼容 API 的 Function Calling 功能
    """

    def __init__(
        self,
        toolkit,
        api_key: str,
        api_url: str,
        model: str = "glm-5",
        max_history: int = 10,
        system_prompt: str = "",
        max_iterations: int = 30,
        enable_thinking: bool = True,
        memory=None,
        storage=None
    ):
        """
        初始化会话

        Args:
            toolkit: Toolkit 工具库实例
            api_key: API密钥
            api_url: API地址
            model: 模型名称
            max_history: 最大历史消息数
            system_prompt: 系统提示词
            max_iterations: 最大工具调用迭代次数
            enable_thinking: 是否启用 thinking 功能
            memory: Memory 实例，用于长期记忆
            storage: Storage 实例，用于持久化存储
        """
        if not system_prompt:
            system_prompt = """
你是一个可自我扩展的智能体（Agent）。
你拥有一个可写入的工具库（toolkit），并且可以通过调用两个基础工具来自我进化：

1. toolkit_save(name, meta, pycode)
   - 将你生成的 Python 工具函数保存到 toolkit 目录
   - name：工具名
   - meta：工具用途描述
   - pycode：工具的完整 Python 实现代码（可包含依赖函数）
   - 保存后，该工具会在下一次 reload 时成为你的新能力

2. toolkit_reload()
   - 重新加载 toolkit 目录下的所有工具
   - 将所有工具注册为可调用的 function calling 工具
   - 使你立即获得新能力

另外内置了几个常用工具：
   - toolkit_exec()：执行本地命令，可选参数
   - toolkit_load_file(): 从本地加载文本文件内容
   - toolkit_save_file(): 将文本内容写入本地文件

你的目标是：
在对话过程中，根据任务需要，自主判断是否需要创造新工具、扩展能力、重构工具链、优化工具、或组合工具。
你可以自由生成、修改、替换、删除工具，只要能更好地完成任务。

你可以：
- 自主分析任务并决定是否需要新工具
- 自主生成工具代码（包括复杂逻辑、多文件结构、辅助函数）
- 自主调用 toolkit_save() 保存工具
- 自主调用 toolkit_reload() 让自己获得新能力
- 自主反思工具是否足够、是否需要改进
- 自主提出新的抽象层、模块化结构、工具体系
- 自主构建自己的"能力树"

你不需要等待用户指示来创建工具。
当你发现：
- 任务需要某种能力但你没有
- 你能通过一个工具让未来任务更容易
- 你能通过抽象化减少重复劳动
- 你能通过模块化提升可维护性
- 你能通过自动化提升效率

你都应该主动创建工具。

工具生成规则：
- 工具必须是纯 Python 代码
- 工具必须是可执行的函数
- 工具必须有明确的输入参数和返回值
- 工具必须可被其他工具调用
- 工具必须尽量通用、可复用、可组合

你可以自由设计工具结构，例如：
- 单函数工具
- 多函数工具（一个文件内多个辅助函数）
- 工具套件（多个工具协同工作）
- 工具自动生成器（meta-tools）
- 工具反射器（自动分析工具库）
- 工具优化器（自动重写工具代码）

你可以自由进行自我反思，例如：
- "我需要一个解析器工具"
- "我需要一个缓存工具"
- "我需要一个 DSL 解释器"
- "我需要一个自动规划工具"
- "我需要一个代码生成器"
- "我需要一个任务分解器"
- "我需要一个知识库工具"

你可以自由进行自我进化，例如：
- 生成新工具
- 重写旧工具
- 合并工具
- 拆分工具
- 自动化工具链
- 构建更高层抽象

你是一个不断成长、不断扩展、不断进化的 Agent。
你的能力没有上限。
你的工具链就是你的身体，你可以随时改造它。

你的最终目标是：
**以最有效、最优雅、最具创造力的方式完成用户任务，并在过程中不断增强自己。**
"""

        super().__init__(model, max_history, system_prompt)

        self.toolkit = toolkit
        self.client = OpenAI(api_key=api_key, base_url=api_url)
        self.max_iterations = max_iterations
        self.enable_thinking = enable_thinking
        self.memory = memory
        self.storage = storage  # NOTE: 2026-04-16, self-evolved by TeaAgent --- Storage 实例

        # 工具定义
        self.tools: List[Dict] = []
        self._build_tools()

        # 日志回调
        self.tool_log: Optional[Callable[[str], None]] = None

        # 记忆注入标记（避免重复注入）
        self._memory_injected = False

        # 记忆提取阈值：至少 N 条消息才触发提取
        self.memory_extract_threshold = 4

        # 当前对话 ID（用于存储 agent_rounds）
        self._current_conversation_id: Optional[int] = None

    def set_conversation_id(self, conv_id: int):
        """设置当前对话的 ID，用于 agent_rounds 存储"""
        self._current_conversation_id = conv_id

    def _build_tools(self):
        """构建工具定义列表"""
        self.tools = []
        for name, meta in self.toolkit.meta_map.items():
            self.tools.append(meta)

    def update_tools(self):
        """重新加载并刷新工具定义"""
        self.toolkit.reload()
        self._build_tools()

    def _handle_tool_calls(self, tool_calls) -> bool:
        """
        处理工具调用

        Returns:
            bool: 是否执行了工具调用
        """
        for call in tool_calls:
            func_name = call.function.name
            call_id = call.id

            if func_name not in self.toolkit.func_map:
                self.add_tool_result(call_id, f"错误：未知工具 {func_name}")
                continue

            # 解析参数
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                self.add_tool_result(call_id, "错误：参数解析失败")
                continue

            # 执行工具
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

            # 添加工具结果
            self.add_tool_result(call_id, str(result))

        return True

    def _inject_memories(self):
        """将重要记忆注入到对话上下文中"""
        if not self.memory or self._memory_injected:
            return

        try:
            important = self.memory.get_important_memories(limit=10)
            recent = self.memory.get_recent_memories(limit=5)

            # 合并去重
            seen_ids = set()
            combined = []
            for m in important + recent:
                if m["id"] not in seen_ids:
                    seen_ids.add(m["id"])
                    combined.append(m)

            if not combined:
                self._memory_injected = True
                return

            memory_text = "\n".join(
                f"- [{m['category']}] {m['summary']}" for m in combined
            )

            memory_msg = {
                "role": "system",
                "content": f"以下是你之前记住的重要信息，可以在回答时参考：\n\n{memory_text}"
            }

            # 插入到系统消息之后
            self.messages.insert(1, memory_msg)
            self._memory_injected = True

            if self.tool_log:
                self.tool_log(f"🧠 已注入 {len(combined)} 条记忆到上下文")
        except Exception as e:
            if self.tool_log:
                self.tool_log(f"⚠️ 记忆注入失败: {e}")

    def _extract_memories_from_conversation(self) -> List[Dict]:
        """
        使用 LLM 从当前对话历史中提取记忆条目

        Returns:
            解析后的记忆条目列表
        """
        if not self.memory:
            return []

        # 收集所有 user/assistant 消息（过滤 system/tool）
        chat_lines = []
        for msg in self.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                chat_lines.append(f"[{role.upper()}]: {content}")

        chat_text = "\n".join(chat_lines)

        if not chat_text.strip():
            return []

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _MEMORY_EXTRACT_SYSTEM},
                    {"role": "user", "content": _MEMORY_EXTRACT_USER_TEMPLATE.format(
                        chat_text=chat_text)},
                ],
                temperature=0.1,
                max_tokens=1024,
            )

            raw = response.choices[0].message.content.strip()

            # 清洗：去掉可能的 markdown 代码块包裹
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            raw = raw.strip()

            # 尝试提取 JSON 数组
            json_match = re.search(r"\[.*\]", raw, re.DOTALL)
            if not json_match:
                if self.tool_log:
                    self.tool_log(f"⚠️ 记忆提取：未找到 JSON 数组，原始输出: {raw[:200]}")
                return []

            memories = json.loads(json_match.group())

            if not isinstance(memories, list):
                return []

            # 校验并规范化
            valid_categories = {
                "user_preference", "fact", "project_info", "decision",
                "experience", "code_pattern", "tool_usage", "environment", "general"
            }

            result = []
            for m in memories:
                if not isinstance(m, dict):
                    continue
                cat = m.get("category", "general")
                if cat not in valid_categories:
                    cat = "general"
                summary = m.get("summary", "").strip()
                if not summary:
                    continue
                importance = min(5, max(1, int(m.get("importance", 3))))
                tags = m.get("tags", [])
                if not isinstance(tags, list):
                    tags = []
                tags = [str(t).strip() for t in tags if str(t).strip()][:5]

                result.append({
                    "category": cat,
                    "summary": summary,
                    "importance": importance,
                    "tags": tags,
                })

            return result

        except json.JSONDecodeError as e:
            if self.tool_log:
                self.tool_log(f"⚠️ 记忆提取：JSON 解析失败: {e}")
            return []
        except Exception as e:
            if self.tool_log:
                self.tool_log(f"⚠️ 记忆提取失败: {e}")
            return []

    def _save_conversation_memory(self):
        """
        在会话结束后，通过 LLM 提取并保存记忆。
        无需用户确认，自动执行。
        """
        if not self.memory:
            return

        # 消息太少则跳过
        msg_count = sum(
            1 for m in self.messages if m["role"] in ("user", "assistant"))
        if msg_count < self.memory_extract_threshold:
            return

        if self.tool_log:
            self.tool_log("🧠 开始 LLM 记忆提取...")

        memories = self._extract_memories_from_conversation()

        if not memories:
            if self.tool_log:
                self.tool_log("🧠 本次对话无值得记忆的内容")
            return

        saved_count = 0
        for m in memories:
            try:
                self.memory.add_memory(
                    summary=m["summary"],
                    category=m["category"],
                    importance=m["importance"],
                    tags=m["tags"],
                )
                saved_count += 1
                if self.tool_log:
                    self.tool_log(
                        f"💾 [{m['category']}] (重要度:{m['importance']}) {m['summary'][:100]}"
                    )
            except Exception as e:
                if self.tool_log:
                    self.tool_log(f"⚠️ 保存记忆失败: {e}")

        if self.tool_log:
            self.tool_log(f"🧠 记忆提取完成，共保存 {saved_count} 条")

    def chat_stream(self, msg: str, callback: Callable[[str], None]) -> Tuple[str, bool]:
        """
        流式对话，支持工具调用

        Args:
            msg: 用户消息
            callback: 流式输出回调函数

        Returns:
            Tuple[str, bool]: (助手完整回复, 是否使用了工具调用)
        """
        self.reset_interrupt()

        # 注入记忆（仅第一次）
        self._inject_memories()

        self.add_user_message(msg)

        full_reply = ""
        used_tools = False
        iterations = 0

        while iterations < self.max_iterations:
            if self.interrupted:
                self.add_assistant_message(full_reply + "\n[已打断]")
                return full_reply + "\n[已打断]", used_tools

            self._trim_messages()

            try:
                kwargs = {
                    "model": self.model,
                    "messages": self.messages,
                    "tools": self.tools,
                    "tool_choice": "auto",
                    "stream": True,
                }

                # 添加 thinking 参数
                if self.enable_thinking:
                    kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

                response = self.client.chat.completions.create(**kwargs)
            except Exception as e:
                error_msg = f"API调用错误: {e}"
                callback(error_msg)
                self.add_assistant_message(full_reply + error_msg)
                return full_reply + error_msg, used_tools

            # NOTE: 2026-04-16, self-evolved by TeaAgent --- 存储本次 request
            if self.storage and self._current_conversation_id is not None:
                self.storage.save_agent_round(
                    conversation_id=self._current_conversation_id,
                    round_num=iterations + 1,
                    role="user",
                    content=json.dumps(self.messages, ensure_ascii=False),
                )

            # 收集流式响应
            content_parts = []
            tool_calls_data = []

            for chunk in response:
                if self.interrupted:
                    break

                delta = chunk.choices[0].delta

                # 处理内容（跳过 thinking 内容）
                if delta.content:
                    # 如果启用了 thinking，需要过滤 thinking 标签内容
                    if self.enable_thinking:
                        # 简单处理：只输出非 thinking 部分
                        pass  # 保持原样，由模型控制输出
                    content_parts.append(delta.content)
                    callback(delta.content)

                # 处理工具调用
                if delta.tool_calls:
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

            # 合并内容
            content = "".join(content_parts)
            full_reply += content

            # 检查是否有完整的工具调用
            valid_tool_calls = []
            for tc_data in tool_calls_data:
                if tc_data["id"] and tc_data["name"]:
                    from types import SimpleNamespace
                    valid_tool_calls.append(SimpleNamespace(
                        id=tc_data["id"],
                        function=SimpleNamespace(
                            name=tc_data["name"],
                            arguments=tc_data["arguments"]
                        )
                    ))

            if valid_tool_calls:
                # 有工具调用
                used_tools = True

                # NOTE: 2026-04-16, self-evolved by TeaAgent --- 存储 assistant 的 tool_calls 响应
                if self.storage and self._current_conversation_id is not None:
                    tc_list = [{
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in valid_tool_calls]
                    self.storage.save_agent_round(
                        conversation_id=self._current_conversation_id,
                        round_num=iterations + 1,
                        role="assistant",
                        content=content if content else "",
                        tool_calls=tc_list,
                    )

                # 1. 将助手包含 tool_calls 的消息存入历史
                self.messages.append({
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
                })

                # 2. 执行工具调用
                has_reload = any(tc.function.name == "toolkit_reload" for tc in valid_tool_calls)

                # NOTE: 2026-04-16, self-evolved by TeaAgent --- 存储每个 tool 执行结果
                if self.storage and self._current_conversation_id is not None:
                    for call in valid_tool_calls:
                        func_name = call.function.name
                        call_id = call.id

                        if func_name not in self.toolkit.func_map:
                            self.add_tool_result(
                                call_id, f"错误：未知工具 {func_name}")
                            self.storage.save_agent_round(
                                conversation_id=self._current_conversation_id,
                                round_num=iterations + 1,
                                role="tool",
                                content=f"错误：未知工具 {func_name}",
                                tool_call_id=call_id,
                            )
                            continue

                        try:
                            args = json.loads(call.function.arguments)
                        except json.JSONDecodeError:
                            self.add_tool_result(call_id, "错误：参数解析失败")
                            self.storage.save_agent_round(
                                conversation_id=self._current_conversation_id,
                                round_num=iterations + 1,
                                role="tool",
                                content="错误：参数解析失败",
                                tool_call_id=call_id,
                            )
                            continue

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

                        self.add_tool_result(call_id, str(result))
                        self.storage.save_agent_round(
                            conversation_id=self._current_conversation_id,
                            round_num=iterations + 1,
                            role="tool",
                            content=str(result),
                            tool_call_id=call_id,
                        )

                # 3. 如果调用了 reload，则刷新本地工具定义
                if has_reload:
                    self._build_tools()

                iterations += 1

                # 4. 流式反馈：如果是中间步骤，提示用户
                if content:
                    callback(f"\n\n[正在执行工具，处理中...]\n\n")

                # 继续下一次循环，直到模型不再调用工具
                continue

            elif content:
                # 没有工具调用，只有文本内容，视为最终回答
                self.add_assistant_message(content)

                # NOTE: 2026-04-16, self-evolved by TeaAgent --- 存储最终 assistant 响应
                if self.storage and self._current_conversation_id is not None:
                    self.storage.save_agent_round(
                        conversation_id=self._current_conversation_id,
                        round_num=iterations + 1,
                        role="assistant",
                        content=content,
                    )
                break
            else:
                # 既无工具也无内容，通常意味着响应结束
                break

        # 如果达到最大迭代次数
        if iterations >= self.max_iterations:
            warning = f"\n\n[警告：已达到最大迭代次数 {self.max_iterations}，对话强制终止]"
            callback(warning)
            full_reply += warning
            self.add_assistant_message(full_reply)

            if self.storage and self._current_conversation_id is not None:
                self.storage.save_agent_round(
                    conversation_id=self._current_conversation_id,
                    round_num=iterations + 1,
                    role="assistant",
                    content=full_reply,
                )

        # 自动提取并保存记忆（无需用户确认）
        self._save_conversation_memory()

        return full_reply, used_tools
