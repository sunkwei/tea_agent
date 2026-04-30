# @2026-04-30 gen by deepseek-v4-pro, ReflectionManager: 元认知反思—分析工具调用、生成改进建议、存储反思记录
"""
反思管理器 (ReflectionManager)

在每次对话结束后触发，分析：
- 工具调用成功率、耗时
- 策略有效性（是否达成目标）
- 改进建议（需要调整的配置、提示词等）

反思结果存储到 reflections 表，可被 SystemPromptManager 和配置调优引用。
"""

import json
import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("ReflectionManager")


@dataclass
class ToolCallRecord:
    """单次工具调用记录"""
    name: str
    success: bool
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class SessionTrace:
    """一次会话的完整追踪"""
    topic_id: int = -1
    user_msg: str = ""
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    total_iterations: int = 0
    used_tools: bool = False
    interrupted: bool = False
    error: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def success_rate(self) -> float:
        if not self.tool_calls:
            return 1.0
        successes = sum(1 for tc in self.tool_calls if tc.success)
        return successes / len(self.tool_calls)

    @property
    def duration_seconds(self) -> float:
        return self.end_time - self.start_time if self.end_time > 0 else 0


class ReflectionManager:
    """反思管理器"""

    REFLECTION_SYSTEM_PROMPT = """你是一个 Agent 元认知分析器。分析以下会话追踪数据，生成反思报告。

分析维度：
1. **工具调用质量**：哪些工具成功/失败？失败原因是什么？
2. **策略有效性**：Agent 的解题路径是否高效？有没有绕弯路？
3. **改进建议**：具体可操作的建议——
   - 配置调整：是否需要修改 max_iterations、keep_turns 等？
   - 提示词优化：系统提示词是否需要补充指引？
   - 工具改进：是否有工具需要修复或优化？
4. **值得记忆的经验**：哪些经验应该存入长期记忆？

输出 JSON 格式：
{
  "summary": "一句话总结本次反思",
  "details": "详细分析",
  "suggestions": ["建议1", "建议2"],
  "prompt_adjustment": "如果需要调整系统提示词，写出调整后的完整提示词；否则为 null",
  "config_adjustments": [{"key": "配置键", "value": "新值", "reason": "原因"}],
  "new_memories": [{"content": "值得记住的经验", "category": "fact", "priority": 2, "importance": 3}]
}

只输出 JSON，不要额外说明。"""

    def __init__(self, storage, cheap_client=None, cheap_model: str = ""):
        """
        Args:
            storage: Storage 实例
            cheap_client: 便宜模型客户端（用于生成反思）
            cheap_model: 便宜模型名称
        """
        self.storage = storage
        self._cheap_client = cheap_client
        self._cheap_model = cheap_model
        self._pending_traces: List[SessionTrace] = []

    def start_trace(self, topic_id: int, user_msg: str) -> SessionTrace:
        """开始追踪一次会话"""
        trace = SessionTrace(
            topic_id=topic_id,
            user_msg=user_msg,
            start_time=time.time(),
        )
        self._pending_traces.append(trace)
        return trace

    def record_tool_call(self, trace: SessionTrace, name: str, success: bool, error: str = "", duration_ms: float = 0.0):
        """记录一次工具调用"""
        trace.tool_calls.append(ToolCallRecord(
            name=name,
            success=success,
            error=error,
            duration_ms=duration_ms,
        ))

    def finish_trace(self, trace: SessionTrace, total_iterations: int = 0, used_tools: bool = False,
                     interrupted: bool = False, error: Optional[str] = None):
        """结束追踪"""
        trace.end_time = time.time()
        trace.total_iterations = total_iterations
        trace.used_tools = used_tools
        trace.interrupted = interrupted
        trace.error = error

    def should_reflect(self) -> bool:
        """
        判断是否应该触发反思。

        触发条件（满足任一）：
        - 累积了 3+ 个待反思的 trace
        - 有失败的 tool call
        - 距离上次反思超过 10 条对话
        """
        if not self._pending_traces:
            return False

        # 检查是否有失败的工具调用
        for trace in self._pending_traces:
            if any(not tc.success for tc in trace.tool_calls):
                return True

        # 累积 3+ 条
        if len(self._pending_traces) >= 3:
            return True

        return False

    def build_reflection_prompt(self) -> Tuple[str, List[Dict]]:
        """构建反思 prompt，返回 (文本, API messages)"""
        if not self._pending_traces:
            return "", []

        lines = []
        for i, trace in enumerate(self._pending_traces):
            lines.append(f"### 会话 {i+1} (topic_id={trace.topic_id})")
            lines.append(f"用户消息: {trace.user_msg[:200]}")
            lines.append(f"总迭代: {trace.total_iterations}, 使用工具: {trace.used_tools}, 打断: {trace.interrupted}")
            lines.append(f"耗时: {trace.duration_seconds:.1f}s")
            if trace.error:
                lines.append(f"错误: {trace.error}")
            if trace.tool_calls:
                lines.append("工具调用:")
                for tc in trace.tool_calls:
                    status = "✅" if tc.success else "❌"
                    lines.append(f"  {status} {tc.name} ({tc.duration_ms:.0f}ms)" + (f" 错误:{tc.error}" if tc.error else ""))
            lines.append("")

        prompt_text = "\n".join(lines)

        messages = [
            {"role": "system", "content": self.REFLECTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"分析以下会话追踪数据并生成反思报告：\n\n{prompt_text}"}
        ]

        return prompt_text, messages

    def parse_reflection_result(self, result_text: str) -> Optional[Dict]:
        """解析 LLM 反思结果"""
        try:
            text = result_text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

    def generate_reflection(self) -> Optional[int]:
        """
        触发反思：调用 LLM 分析 pending traces，存储反思记录。

        Returns:
            反思记录 ID，失败返回 None
        """
        if not self._pending_traces:
            return None

        prompt_text, messages = self.build_reflection_prompt()
        if not prompt_text:
            return None

        if not self._cheap_client:
            logger.info("无便宜模型客户端，跳过反思生成")
            return None

        try:
            response = self._cheap_client.chat.completions.create(
                model=self._cheap_model,
                messages=messages,
                temperature=0.3,
                max_tokens=1000,
                extra_body={"thinking": {"type": "disabled"}},
            )
            result_text = response.choices[0].message.content or ""
            parsed = self.parse_reflection_result(result_text)

            if not parsed:
                logger.warning("反思结果解析失败")
                return None

            # 存储反思记录
            reflection_id = self.storage.add_reflection(
                summary=parsed.get("summary", ""),
                details=parsed.get("details", prompt_text),
                tool_stats=self._build_tool_stats(),
                suggestions=parsed.get("suggestions", []),
                topic_id=self._pending_traces[0].topic_id if self._pending_traces else None,
            )

            # 处理建议：config_adjustments
            config_adjustments = parsed.get("config_adjustments", [])
            for adj in config_adjustments:
                if isinstance(adj, dict):
                    self.storage.add_config_change(
                        key=adj.get("key", ""),
                        new_value=str(adj.get("value", "")),
                        reason=adj.get("reason", ""),
                        source_reflection_id=reflection_id,
                    )

            # 处理新记忆
            new_memories = parsed.get("new_memories", [])
            for mem in new_memories:
                if isinstance(mem, dict) and mem.get("content"):
                    try:
                        self.storage.add_memory(
                            content=mem["content"],
                            category=mem.get("category", "general"),
                            priority=mem.get("priority", 2),
                            importance=mem.get("importance", 3),
                        )
                    except Exception:
                        pass

            # 返回 prompt_adjustment 供 SystemPromptManager 使用
            prompt_adjustment = parsed.get("prompt_adjustment")
            if prompt_adjustment and isinstance(prompt_adjustment, str) and len(prompt_adjustment) > 20:
                self._last_prompt_suggestion = prompt_adjustment
            else:
                self._last_prompt_suggestion = None

            # 清空已处理的 traces
            self._pending_traces.clear()

            logger.info(f"反思完成: reflection_id={reflection_id}, summary={parsed.get('summary', '')[:50]}")
            return reflection_id

        except Exception as e:
            logger.warning(f"反思生成失败: {e}")
            return None

    def _build_tool_stats(self) -> Dict:
        """构建工具统计"""
        stats: Dict[str, Dict] = {}
        for trace in self._pending_traces:
            for tc in trace.tool_calls:
                if tc.name not in stats:
                    stats[tc.name] = {"total": 0, "success": 0, "fail": 0, "errors": []}
                stats[tc.name]["total"] += 1
                if tc.success:
                    stats[tc.name]["success"] += 1
                else:
                    stats[tc.name]["fail"] += 1
                    if tc.error:
                        stats[tc.name]["errors"].append(tc.error)
        return stats

    @property
    def last_prompt_suggestion(self) -> Optional[str]:
        """获取最近一次反思生成的提示词建议"""
        return getattr(self, '_last_prompt_suggestion', None)

    def get_stats(self) -> Dict:
        """获取反思统计"""
        return self.storage.get_reflection_stats()
