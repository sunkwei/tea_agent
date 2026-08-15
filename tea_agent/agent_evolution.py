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

可选评估字段（rubric）：若行动可量化评估（如 evolve_code），可附加 rubric 规则列表，
系统会用它执行"改进前评分→改进→改进后重评→仅分数提升才保留"的闭环。
rubric 格式（规则项支持 match: regex/contains/line/line_contains）：
[{"pattern": "...", "match": "regex", "description": "检查点说明"}]
示例：检查代码包含函数签名和文档字符串、避免硬编码路径等。
不提供 rubric 则跳过评估，保持原流程。

返回格式：
{{"actions": [{{"action": "evolve_code", "target": "tea_agent/toolkit/toolkit_xxx.py", "reason": "...", "rubric": [], "threshold": 0.0}}]}}

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
            from tea_agent.api_retry import call_with_retry

            prompt = self.ANALYZE_PROMPT.format(
                events_json=json.dumps(events, ensure_ascii=False),
                memory_summary=memory_summary or "(无)",
            )
            resp = call_with_retry(
                self._cheap_client.chat.completions.create,
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
            content = self.tk.call_tool("toolkit_file", action="read", filename=file_path)
        except Exception:
            content = ""
        if not isinstance(content, str) or not content.strip():
            return {"ok": False, "error": f"读取文件失败或内容为空: {file_path}"}
        if content.startswith("Error:") or content.startswith("❌"):
            return {"ok": False, "error": f"读取文件失败: {content[:200]}"}
        # 缺少 LLM 生成的新代码时，不得提交占位符（HTML 注释非合法 Python）
        return {"ok": False, "error": "evolve_code 需要 LLM 生成 new_code，当前无有效新代码，已跳过"}

    def _evolve_prompt(self, suggestion: str) -> dict:
        """优化提示词 — 委托给 toolkit_prompt_evolve。"""
        if not self.tk or "toolkit_prompt_evolve" not in self.tk.func_map:
            return {"ok": False, "error": "toolkit_prompt_evolve 不可用"}
        return self.tk.call_tool("toolkit_prompt_evolve",
            action="evolve",
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


# ═══════════════════════════════════════════════════════════════
#  Evaluate — 评分闭环（借鉴 PenguinHarness self-evolve 机制）
# ═══════════════════════════════════════════════════════════════

class EvolutionEvaluator:
    """进化评估器 — 在 Analyze → Act 之间插入 Evaluate 阶段。

    借鉴 penguin-harness examples/self-improving-agent/self-evolve.ts：
    改进前打基线分 → 执行改进 → 改进后重评 → 平均分提升才保留，否则回滚。

    设计原则：
    - 可选参与：仅当 Analyze 输出的 action 带 rubric 规则时才启用，
      无 rubric 的流程行为完全不变（向后兼容）
    - 轻量确定性：委托 toolkit_eval_loop（纯代码评分，无 LLM 参与）
    - 决策：compare 返回 keep / rollback / no_change；rollback 用 git 恢复
    """

    def __init__(self, toolkit):
        self.tk = toolkit

    def available(self) -> bool:
        """toolkit_eval_loop 是否已注册可用。"""
        return bool(self.tk and "toolkit_eval_loop" in self.tk.func_map)

    def _call_eval_loop(self, **kwargs) -> dict | None:
        """调用 toolkit_eval_loop，失败返回 None（不阻断主流程）。"""
        if not self.available():
            return None
        try:
            return self.tk.call_tool("toolkit_eval_loop", **kwargs)
        except Exception as e:
            logger.warning(f"evolution: evaluate 调用失败: {e}")
            return None

    def extract_eval_actions(self, actions: list[dict]) -> list[dict]:
        """从行动列表中提取带 rubric 的可评估行动（有 target + rubric）。"""
        return [
            a for a in actions
            if a.get("action") not in ("none", "") and a.get("target") and a.get("rubric")
        ]

    def evaluate_target(self, target: str, rules, runs: int = 3) -> dict | None:
        """读取目标文件内容并用 rubric 评分（改进前后通用）。

        runs 轮文本重复取平均（对抗评分抖动）；实际改进前后各读一次文件。
        """
        try:
            with open(target, encoding="utf-8") as f:
                artifact = f.read()
        except Exception as e:
            logger.warning(f"evolution: 读取评估目标失败 {target}: {e}")
            return None
        return self._call_eval_loop(action="evaluate", texts=[artifact] * runs, rules=rules)

    def decide(self, baseline: dict | None, candidate: dict | None, threshold: float = 0.0) -> dict:
        """keep-or-rollback 决策。基线/候选不可用时保守返回 no_change。"""
        if not baseline or not candidate or not baseline.get("ok") or not candidate.get("ok"):
            return {"ok": False, "decision": "no_change", "verdict": "评估数据不可用，保持现状"}
        r = self._call_eval_loop(
            action="compare",
            baseline={"mean_score": baseline.get("mean_score", 0.0)},
            candidate={"mean_score": candidate.get("mean_score", 0.0)},
            threshold=threshold,
        )
        return r or {"ok": False, "decision": "no_change", "verdict": "决策调用失败，保持现状"}

    def rollback(self, target: str) -> bool:
        """回滚目标文件到改进前（git checkout）。优先当前目录，失败则尝试目标目录。"""
        try:
            import subprocess
            r = subprocess.run(
                ["git", "checkout", "--", target],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                import os
                d = os.path.dirname(os.path.abspath(target))
                r = subprocess.run(
                    ["git", "checkout", "--", os.path.basename(target)],
                    capture_output=True, text=True, timeout=30, cwd=d,
                )
            return r.returncode == 0
        except Exception as e:
            logger.warning(f"evolution: 回滚失败 {target}: {e}")
            return False
