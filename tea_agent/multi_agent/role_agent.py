"""
RoleAgent — 角色化 Agent 类。

借鉴 CrewAI 的角色设计理念，赋予子 Agent 明确的身份、目标和背景故事。
每个 RoleAgent 有自己的角色、可用工具白名单、结构化输出能力。

核心设计:
  - role + goal + backstory → 构建专属 System Prompt
  - tools whitelist → 限定子 Agent 能调用的工具
  - structured output → 支持 Pydantic 模型输出
  - 基于 LiteSession 实现真实 LLM 调用

用法:
    from tea_agent.multi_agent import RoleAgent

    analyst = RoleAgent(
        role="资深代码审查员",
        goal="分析代码质量问题并给出改进建议",
        backstory="你有 15 年后端架构经验，擅长发现代码坏味道",
    )
    result = analyst.execute("审查 dispatcher.py 的设计")
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from tea_agent.litesession import LiteSession

logger = logging.getLogger(__name__)

# Phase 3: Checkpoint & Trace（延迟导入，避免循环依赖）
_checkpoint_manager = None
_trace_engine = None


def _get_checkpoint_manager():
    global _checkpoint_manager
    if _checkpoint_manager is None:
        from .checkpoint_manager import CheckpointManager
        _checkpoint_manager = CheckpointManager.get_instance()
    return _checkpoint_manager


def _get_trace_engine():
    global _trace_engine
    if _trace_engine is None:
        from .trace_engine import TraceEngine
        _trace_engine = TraceEngine.get_instance()
    return _trace_engine


class AgentStatus(Enum):
    """Agent 执行状态"""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"  # 等待前置条件


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    output: str
    structured: dict | None = None
    error: str | None = None
    tool_calls: int = 0
    time_seconds: float = 0.0
    agent_name: str = ""


class RoleAgent:
    """
    角色化 Agent。

    每个 Agent 实例代表一个特定角色，有专属的身份描述和能力边界。
    """

    def __init__(
        self,
        role: str,
        goal: str,
        backstory: str = "",
        tools: list[str] | None = None,
        llm_config: dict | None = None,
        max_iterations: int = 20,
        enable_thinking: bool = False,
        verbose: bool = True,
    ):
        """
        Args:
            role: Agent 角色名称，如 "高级Python工程师"
            goal: Agent 的目标描述
            backstory: Agent 的背景故事，让角色更立体
            tools: 可用工具白名单（None = 全部可用）
            llm_config: 模型配置（默认使用主模型）
            max_iterations: 工具调用最大迭代次数
            enable_thinking: 是否启用思考推理
            verbose: 是否输出详细日志
        """
        self.role = role
        self.goal = goal
        self.backstory = backstory
        self.tools = tools or []
        self.llm_config = llm_config or {}
        self.max_iterations = max_iterations
        self.enable_thinking = enable_thinking
        self.verbose = verbose
        # Phase 3: 唯一 agent_id（用于 checkpoint / trace）
        self.agent_id = f"roleagent-{uuid.uuid4().hex[:8]}"
        # Phase 3: 当前 trace_id（如果有）
        self._trace_id: str | None = None
        self._span_id: str | None = None

        self.status = AgentStatus.IDLE
        self.last_result: AgentResult | None = None
        self._session: LiteSession | None = None
        self._toolkit = None

    # ───────────────────────────────────────────────
    # 公共 API
    # ───────────────────────────────────────────────

    def execute(
        self,
        task: str,
        context: dict[str, str] | None = None,
        output_model: type | None = None,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> AgentResult:
        """
        执行任务（含 Checkpoint + Trace 集成）。

        Args:
            task: 任务描述
            context: 上下文信息（如前置结果）
            output_model: Pydantic 模型类，指定后强制结构化输出
            trace_id: [Phase 3] 所属 trace_id（自动创建 trace 如果未提供）
            parent_span_id: [Phase 3] 父 span_id

        Returns:
            AgentResult
        """
        self.status = AgentStatus.RUNNING
        start = datetime.now()
        agent_name = f"{self.role}({self.goal[:20]}...)"

        if self.verbose:
            logger.info(f"🎭 [{agent_name}] 开始执行: {task[:100]}")

        # ── Phase 3: Trace ──────────────────────
        te = _get_trace_engine()
        self._trace_id = trace_id or te.start_trace(
            agent_id=self.agent_id,
            task=task,
            agent_role=self.role,
        )
        self._span_id = te.start_span(
            trace_id=self._trace_id,
            parent_span_id=parent_span_id,
            name=self.role,
            agent_id=self.agent_id,
            agent_role=self.role,
            task=task,
        )

        # ── Phase 3: Checkpoint ─────────────────
        cpm = _get_checkpoint_manager()
        cpm.save({
            'agent_id': self.agent_id,
            'role': self.role,
            'goal': self.goal[:200],
            'task': task[:500],
            'context': context or {},
            'status': 'running',
            'trace_id': self._trace_id,
        })

        try:
            # 1. 构建系统提示
            system_prompt = self._build_system_prompt(output_model)

            # 2. 构建用户消息
            user_msg = self._build_user_message(task, context)

            # 3. 获取模型配置
            cfg = self._get_llm_config()
            main_m = cfg.main_model

            # 4. 创建 LiteSession
            sess = LiteSession(
                toolkit=self._get_toolkit(),
                api_key=str(main_m.api_key or ""),
                api_url=str(main_m.api_url or ""),
                model=str(main_m.model_name or ""),
                system_prompt=system_prompt,
                enable_thinking=self.enable_thinking,
                max_iterations=self.max_iterations,
            )
            self._session = sess

            # 5. 执行
            result = sess.chat(user_msg)
            assistant = result.get("assistant", "")
            tool_calls = result.get("tool_calls", 0)
            error = result.get("error")

            elapsed = (datetime.now() - start).total_seconds()

            if error:
                self.status = AgentStatus.FAILED
                self.last_result = AgentResult(
                    success=False,
                    output=f"[执行失败] {error}",
                    error=error,
                    tool_calls=tool_calls,
                    time_seconds=elapsed,
                    agent_name=agent_name,
                )
                if self.verbose:
                    logger.error(f"❌ [{agent_name}] 失败: {error}")

                # ── Phase 3: Trace 失败 ──
                te.end_span(self._span_id, 'failed',
                            error=error, tool_calls=tool_calls)
                cpm.update_status(self.agent_id, 'failed',
                                  error=error, tool_calls=tool_calls)
                return self.last_result

            # 6. 如果指定了 output_model，尝试解析结构化输出
            structured_data = None
            if output_model and assistant:
                try:
                    structured_data = self._parse_structured_output(assistant, output_model)
                except Exception as e:
                    logger.warning(f"⚠️ 结构化解析失败: {e}，保留原始输出")

            self.status = AgentStatus.COMPLETED
            self.last_result = AgentResult(
                success=True,
                output=assistant,
                structured=structured_data,
                tool_calls=tool_calls,
                time_seconds=elapsed,
                agent_name=agent_name,
            )

            if self.verbose:
                logger.info(f"✅ [{agent_name}] 完成 ({elapsed:.1f}s, {tool_calls} 次工具调用)")

            # ── Phase 3: Trace 完成 ──
            te.end_span(self._span_id, 'completed',
                        result=assistant[:500], tool_calls=tool_calls)
            cpm.update_status(self.agent_id, 'completed',
                              result=assistant[:500], tool_calls=tool_calls)
            return self.last_result

        except Exception as e:
            elapsed = (datetime.now() - start).total_seconds()
            self.status = AgentStatus.FAILED
            self.last_result = AgentResult(
                success=False,
                output=str(e),
                error=str(e),
                time_seconds=elapsed,
                agent_name=agent_name,
            )
            if self.verbose:
                logger.error(f"❌ [{agent_name}] 异常: {e}")

            # ── Phase 3: Trace 异常 ──
            try:
                if self._span_id:
                    te.end_span(self._span_id, 'failed',
                                error=str(e)[:500])
                cpm.update_status(self.agent_id, 'failed', error=str(e)[:500])
            except Exception:
                pass
            return self.last_result

    def reset(self):
        """重置 Agent 状态，准备下一轮执行。"""
        self.status = AgentStatus.IDLE
        self.last_result = None
        self._session = None

    # ── Phase 3: Checkpoint / Trace ─────────────────

    def get_trace(self) -> dict | None:
        """获取当前 trace（如果存在）。"""
        if not self._trace_id:
            return None
        te = _get_trace_engine()
        return te.get_trace(self._trace_id)

    def get_checkpoint(self) -> dict | None:
        """获取最新 checkpoint。"""
        cpm = _get_checkpoint_manager()
        return cpm.load(self.agent_id)

    @classmethod
    def recover(cls, agent_id: str) -> 'RoleAgent | None':
        """
        从 checkpoint 恢复 RoleAgent。

        先加载 checkpoint，然后重建 RoleAgent 实例。
        如果 checkpoint 状态为 'running' 或 'failed'，
        可以决定是否继续执行或重新执行。
        """
        cpm = _get_checkpoint_manager()
        cp = cpm.load(agent_id)
        if not cp:
            logger.warning(f"⚠️ 未找到 checkpoint: {agent_id}")
            return None

        agent = cls(
            role=cp.get('role', '恢复的 Agent'),
            goal=cp.get('goal', '继续未完成的任务'),
            verbose=True,
        )
        agent.agent_id = agent_id
        agent.status = AgentStatus(cp.get('status', 'idle'))

        logger.info(
            f"🔄 从 checkpoint 恢复 [{agent_id}]: "
            f"status={agent.status.value}, task={cp.get('task', '')[:80]}"
        )
        return agent

    @classmethod
    def list_checkpoints(cls, status: str | None = None) -> list[dict]:
        """列出所有检查点。"""
        cpm = _get_checkpoint_manager()
        if status:
            return cpm.load_by_status(status)
        return cpm.list_recent()

    # ───────────────────────────────────────────────
    # 内部方法
    # ───────────────────────────────────────────────

    def _build_system_prompt(self, output_model: type | None = None) -> str:
        """构建角色化的系统提示词。"""
        parts = [
            f"## 你的角色\n{self.role}",
        ]

        if self.backstory:
            parts.append(f"## 背景\n{self.backstory}")

        parts.append(f"## 你的目标\n{self.goal}")

        if self.tools:
            tools_str = "\n".join(f"- {t}" for t in self.tools)
            parts.append(f"## 可用工具\n以下工具你可以调用：\n{tools_str}\n\n不在列表中的工具不允许使用。")
        else:
            parts.append("## 可用工具\n你可以使用所有可用工具。")

        # 输出格式要求
        output_instructions = [
            "## 输出要求",
            "1. 直接执行任务，不要询问确认",
            "2. 完成后输出简明的结果摘要",
            "3. 如果遇到错误，尝试修复一次；仍失败则报告具体错误",
        ]
        if output_model:
            model_schema = self._get_model_schema(output_model)
            output_instructions.append(
                f"4. 你的最终回复必须符合以下 JSON Schema：\n```json\n{model_schema}\n```\n"
                f"   确保输出可以被 json.loads 解析为符合该 schema 的 JSON 对象。"
            )
        parts.append("\n".join(output_instructions))

        return "\n\n".join(parts)

    def _build_user_message(self, task: str, context: dict[str, str] | None) -> str:
        """构建用户消息（含上下文注入）。"""
        if not context:
            return task

        context_parts = []
        for key, value in context.items():
            context_parts.append(f"【{key}】\n{value}")

        return (
            "## 上下文信息\n"
            + "\n\n".join(context_parts)
            + f"\n\n## 当前任务\n{task}"
        )

    def _get_llm_config(self):
        """获取模型配置。"""
        if self.llm_config:
            # 支持自定义配置
            from types import SimpleNamespace
            config = SimpleNamespace()
            config.main_model = SimpleNamespace()
            config.main_model.api_key = self.llm_config.get("api_key")
            config.main_model.api_url = self.llm_config.get("api_url")
            config.main_model.model_name = self.llm_config.get("model")
            return config
        from tea_agent.config import load_config
        return load_config()

    def _get_toolkit(self):
        """获取 Toolkit 实例。"""
        if self._toolkit is None:
            from tea_agent import tlk
            self._toolkit = tlk.toolkit
        return self._toolkit

    def _get_model_schema(self, model: type) -> str:
        """获取 Pydantic 模型的 JSON Schema。"""
        try:
            return json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False)
        except AttributeError:
            return json.dumps(model.schema(), indent=2, ensure_ascii=False)

    def _parse_structured_output(self, text: str, model: type) -> dict:
        """
        从 LLM 回复中提取结构化数据。

        策略（按优先级）：
        1. 尝试直接 json.loads(text)
        2. 尝试从 ```json ... ``` 代码块中提取
        3. 尝试从 ``` ... ``` 代码块中提取
        4. 尝试用 model.model_validate_json()
        """
        # 策略 1: 直接解析
        text = text.strip()
        try:
            data = json.loads(text)
            return model.model_validate(data).model_dump()
        except (json.JSONDecodeError, Exception):
            pass

        # 策略 2: json 代码块
        import re
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1).strip())
                return model.model_validate(data).model_dump()
            except (json.JSONDecodeError, Exception):
                pass

        # 策略 3: 尝试提取第一对 {} 或 []
        brace_match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if brace_match:
            try:
                data = json.loads(brace_match.group(0))
                return model.model_validate(data).model_dump()
            except (json.JSONDecodeError, Exception):
                pass

        raise ValueError(f"无法从输出中提取有效的结构化数据（{model.__name__}）")

    def __repr__(self) -> str:
        return f"RoleAgent(role={self.role!r}, status={self.status.value})"


# ───────────────────────────────────────────────
# 快捷创建函数
# ───────────────────────────────────────────────

def create_analyst(verbose: bool = True) -> RoleAgent:
    """创建代码分析 Agent。"""
    return RoleAgent(
        role="资深代码分析专家",
        goal="分析代码结构、识别设计问题和代码坏味道",
        backstory=(
            "你拥有 15 年软件架构经验，精通各种设计模式和重构技术。"
            "你能快速从代码中识别出潜在问题，并给出具体的改进建议。"
        ),
        verbose=verbose,
    )


def create_coder(verbose: bool = True) -> RoleAgent:
    """创建代码实现 Agent。"""
    return RoleAgent(
        role="高级软件工程师",
        goal="高效实现功能需求和代码修改",
        backstory=(
            "你擅长编写高质量、可维护的 Python 代码。"
            "你熟悉 SOLID 原则、类型注解、测试驱动开发。"
            "你总是编写带有类型注解和文档字符串的干净代码。"
        ),
        verbose=verbose,
    )


def create_tester(verbose: bool = True) -> RoleAgent:
    """创建测试 Agent。"""
    return RoleAgent(
        role="专业测试工程师",
        goal="编写全面的测试用例，确保代码质量",
        backstory=(
            "你精通 pytest 和各种测试技术，包括单元测试、集成测试和 Mock。"
            "你追求高覆盖率，但也知道哪些代码真正需要测试。"
        ),
        verbose=verbose,
    )


def create_reviewer(verbose: bool = True) -> RoleAgent:
    """创建代码审查 Agent。"""
    return RoleAgent(
        role="严格的代码审查员",
        goal="审查代码质量，确保符合最佳实践",
        backstory=(
            "你以严苛著称，对代码质量零容忍。"
            "你会检查类型安全、错误处理、性能问题、可维护性等各个方面。"
        ),
        verbose=verbose,
    )
