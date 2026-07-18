"""
自进化流水线 — 事件驱动的 Trigger → Analyze → Act 闭环。

设计原则：
- Trigger: 轻量信号采集，不调 LLM，在每次工具调用后同步执行
- Analyze: 会话结束时串行调一次廉价 LLM，产出行动建议
- Act: 调用已有 toolkit_* 工具执行进化
- 不自建循环，不搞后台线程，不阻塞主交互流程
"""

import json
import logging
import time
from typing import Any

logger = logging.getLogger("agent.evolution")


# ═══════════════════════════════════════════════════════════════
#  Trigger — 轻量信号采集
# ═══════════════════════════════════════════════════════════════

class EvolutionTrigger:
    """自进化触发器 — 采集工具调用信号，不调 LLM。

    用法：在每次 Toolkit.call_tool() 返回后调用 on_tool_result()。
    """

    def __init__(self, max_log: int = 50, consecutive_failure_threshold: int = 3):
        self.tool_call_log: list[dict] = []
        self.evolution_events: list[dict] = []
        self.max_log = max_log
        # 连续失败阈值：同一工具连续 N 次失败触发事件
        self.consecutive_failure_threshold = consecutive_failure_threshold

    def on_tool_result(self, tool_name: str, result: Any, duration: float):
        """每次工具调用后采集信号。"""
        ok = True
        error = ""
        if isinstance(result, dict):
            ok = result.get("ok", True)
            error = result.get("error", "") or result.get("stderr", "") or ""
        elif isinstance(result, tuple) and len(result) >= 2:
            ok = result[0] == 0
            error = str(result[-1]) if not ok else ""

        entry = {
            "tool": tool_name,
            "ok": ok,
            "error": error[:200],
            "duration": duration,
            "ts": time.time(),
        }
        self.tool_call_log.append(entry)
        if len(self.tool_call_log) > self.max_log:
            self.tool_call_log.pop(0)

        if ok:
            return

        recent = [e for e in self.tool_call_log if e["tool"] == tool_name][-self.consecutive_failure_threshold:]
        if len(recent) >= self.consecutive_failure_threshold and all(not e["ok"] for e in recent):
            self.evolution_events.append({
                "type": "tool_failure",
                "tool": tool_name,
                "recent_errors": [e["error"] for e in recent],
                "count": len(recent),
                "ts": time.time(),
            })
            logger.info(f"evolution: 检测到 {tool_name} 连续 {self.consecutive_failure_threshold} 次失败")

    def get_pending_events(self) -> list[dict]:
        return self.evolution_events

    def clear_events(self):
        self.evolution_events.clear()


# ═══════════════════════════════════════════════════════════════
#  Analyze — 用廉价 LLM 分析信号，产出行动建议
# ═══════════════════════════════════════════════════════════════

class EvolutionAnalyzer:
    """进化分析器 — 会话结束后分析信号，输出行动建议。"""

    ANALYZE_PROMPT = """你是一个 Agent 自进化分析器。分析以下进化信号和记忆上下文，输出 JSON 行动建议。

进化信号：{events_json}
记忆上下文：{memory_summary}

可能的行动类型：
- evolve_code: 修复高频报错的工具代码。target 填工具文件路径，reason 说明修复方向
- evolve_prompt: 优化系统提示词。target 填 "system_prompt"，reason 填优化建议
- solidify: 记录成功模式为技能。target 填技能名，reason 填任务描述
- none: 无需行动

返回格式：
{{"actions": [{{"action": "evolve_code", "target": "tea_agent/toolkit/toolkit_xxx.py", "reason": "..."}}]}}

只输出 JSON，不要额外说明。"""

    def __init__(self, cheap_client=None, cheap_model: str = ""):
        self._cheap_client = cheap_client
        self._cheap_model = cheap_model or "gpt-4o-mini"

    def analyze(self, events: list[dict], memory_summary: str = "") -> list[dict]:
        """分析信号 → 输出行动建议列表。"""
        if not events:
            return []
        if not self._cheap_client:
            return []

        try:
            prompt = self.ANALYZE_PROMPT.format(
                events_json=json.dumps(events, ensure_ascii=False),
                memory_summary=memory_summary or "(无)",
            )
            resp = self._cheap_client.chat.completions.create(
                model=self._cheap_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
            data = json.loads(content)
            actions = data.get("actions", [])
            logger.info(f"evolution: 分析完成，建议 {len(actions)} 个行动: {[a.get('action') for a in actions]}")
            return actions
        except Exception as e:
            logger.warning(f"evolution: 分析失败: {e}")
            return []


# ═══════════════════════════════════════════════════════════════
#  Act — 执行进化行动
# ═══════════════════════════════════════════════════════════════

class EvolutionActor:
    """进化执行器 — 调用已有 toolkit_* 工具执行分析建议。"""

    def __init__(self, toolkit):
        self.tk = toolkit

    def execute(self, actions: list[dict]) -> list[dict]:
        """执行行动列表，返回执行结果。"""
        results = []
        for act in actions:
            action_type = act.get("action", "none")
            target = act.get("target", "")
            reason = act.get("reason", "")

            if action_type == "none" or not action_type:
                continue

            try:
                result = self._execute_one(action_type, target, reason)
                results.append({"action": action_type, "target": target, "ok": result.get("ok", False)})
                logger.info(f"evolution: 执行 {action_type} -> {target}: ok={result.get('ok')}")
            except Exception as e:
                results.append({"action": action_type, "target": target, "ok": False, "error": str(e)})
                logger.warning(f"evolution: 执行 {action_type} 失败: {e}")

        return results

    def _execute_one(self, action_type: str, target: str, reason: str) -> dict:
        if action_type == "evolve_code":
            return self._evolve_code(target, reason)
        elif action_type == "evolve_prompt":
            return self._evolve_prompt(reason)
        elif action_type == "solidify":
            return self._solidify(reason)
        return {"ok": False, "error": f"unknown_action:{action_type}"}

    def _evolve_code(self, file_path: str, reason: str) -> dict:
        """修复工具代码 — 委托给 toolkit_self_evolve 的 5 层安全机制。"""
        if not self.tk or "toolkit_self_evolve" not in self.tk.func_map:
            return {"ok": False, "error": "toolkit_self_evolve 不可用"}
        try:
            content = self.tk.call_tool("toolkit_file", file_path=file_path)
        except Exception:
            content = ""
        return self.tk.call_tool("toolkit_self_evolve",
            file_path=file_path,
            description=reason,
            old_code=content if isinstance(content, str) else "",
            new_code="<!-- evolution: 等待 LLM 在下轮修复 -->",
        )

    def _evolve_prompt(self, suggestion: str) -> dict:
        """优化提示词 — 委托给 toolkit_prompt_evolve。"""
        if not self.tk or "toolkit_prompt_evolve" not in self.tk.func_map:
            return {"ok": False, "error": "toolkit_prompt_evolve 不可用"}
        return self.tk.call_tool("toolkit_prompt_evolve",
            action="evolve",
            suggestion=suggestion,
        )

    def _solidify(self, task: str) -> dict:
        """固化经验 — 委托给 toolkit_experience_solidify。"""
        if not self.tk or "toolkit_experience_solidify" not in self.tk.func_map:
            return {"ok": False, "error": "toolkit_experience_solidify 不可用"}
        return self.tk.call_tool("toolkit_experience_solidify",
            action="auto",
            task=task,
            success=True,
        )
