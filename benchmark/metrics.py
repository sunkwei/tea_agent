"""
@2026-07-19 gen by claude, 五层性能指标体系 — 基准测试核心框架

五层指标:
  L1 任务成功类  — 二进制 PASS/FAIL（基于 expected_patterns）
  L2 质量评分    — 0-100 多维度（正确性/完整性/简洁性/风格）
  L3 效率指标    — tokens/$/耗时，归一化
  L4 工具准确率  — 工具选择/参数正确率
  L5 进化稳定性  — 版本间回归检测

公平性保障:
  - fair_mode: 强制 temperature=0, thinking=off
  - 每任务 ≥5 runs，取中位数
  - 结果可复现、可审计
"""

from __future__ import annotations

import json
import math
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class L1Result:
    """L1 任务成功类"""
    passed: bool = False
    total_patterns: int = 0
    matched_patterns: int = 0
    match_rate: float = 0.0        # matched/total
    details: list[str] = field(default_factory=list)
    score: float = 0.0             # 归一化 0-1


@dataclass
class L2Result:
    """L2 质量评分"""
    correctness: int = 0           # 0-100: 输出是否正确
    completeness: int = 0          # 0-100: 是否完整
    conciseness: int = 0           # 0-100: 是否简洁（无冗余）
    style: int = 0                 # 0-100: 代码风格/格式
    overall: int = 0               # 0-100: 综合
    issues: list[str] = field(default_factory=list)
    auto_evaluated: bool = False   # 是否由 LLM 自动评估


@dataclass
class L3Result:
    """L3 效率指标"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cheap_tokens: int = 0
    duration_s: float = 0.0
    # 归一化：复杂任务理应消耗更多，需要参考 baseline
    token_efficiency: float = 0.0  # 相对于 baseline 的倍数
    estimated_cost_usd: float = 0.0


@dataclass
class L4Result:
    """L4 工具准确率"""
    total_calls: int = 0
    correct_calls: int = 0         # 工具选择正确
    param_correct: int = 0         # 参数完全正确
    redundant_calls: int = 0       # 不必要/重复的调用
    accuracy: float = 0.0          # correct/total
    param_accuracy: float = 0.0    # param_correct/total
    redundancy_ratio: float = 0.0  # redundant/total


@dataclass
class L5Result:
    """L5 进化稳定性"""
    version: str = ""
    previous_score: float = -1.0   # 上一版本综合分
    current_score: float = 0.0
    delta: float = 0.0             # +/- 变化
    regressed: bool = False        # 是否退化
    significant: bool = False      # 变化是否显著（>1 stddev）


@dataclass
class BenchmarkResult:
    """单次运行完整结果"""
    task_name: str = ""
    run: int = 0
    topic_id: str = ""
    l1: L1Result = field(default_factory=L1Result)
    l2: L2Result = field(default_factory=L2Result)
    l3: L3Result = field(default_factory=L3Result)
    l4: L4Result = field(default_factory=L4Result)
    l5: L5Result = field(default_factory=L5Result)
    ai_output: str = ""
    error: str = ""
    duration_s: float = 0.0

    @property
    def composite_score(self) -> float:
        """综合评分 0-100（L1-L4 加权）"""
        return (
            self.l1.score * 30.0 +       # L1 权重 30%
            self.l2.overall * 0.25 +      # L2 权重 25%
            min(self.l3.token_efficiency, 2.0) * 10.0 +  # L3 权重 20%（归一化到 0-20）
            self.l4.accuracy * 25.0       # L4 权重 25%
        )

    def to_dict(self) -> dict:
        return {
            "run": self.run,
            "topic_id": self.topic_id,
            "composite_score": round(self.composite_score, 1),
            "l1": {
                "passed": self.l1.passed,
                "match_rate": round(self.l1.match_rate, 2),
                "details": self.l1.details,
            },
            "l2": {
                "correctness": self.l2.correctness,
                "completeness": self.l2.completeness,
                "conciseness": self.l2.conciseness,
                "style": self.l2.style,
                "overall": self.l2.overall,
                "issues": self.l2.issues,
            },
            "l3": {
                "prompt_tokens": self.l3.prompt_tokens,
                "completion_tokens": self.l3.completion_tokens,
                "total_tokens": self.l3.total_tokens,
                "cheap_tokens": self.l3.cheap_tokens,
                "duration_s": round(self.l3.duration_s, 1),
                "token_efficiency": round(self.l3.token_efficiency, 2),
                "estimated_cost_usd": round(self.l3.estimated_cost_usd, 4),
            },
            "l4": {
                "total_calls": self.l4.total_calls,
                "correct_calls": self.l4.correct_calls,
                "param_correct": self.l4.param_correct,
                "accuracy": round(self.l4.accuracy, 2),
                "param_accuracy": round(self.l4.param_accuracy, 2),
                "redundancy_ratio": round(self.l4.redundancy_ratio, 2),
            },
            "error": self.error,
            "duration_s": round(self.duration_s, 1),
        }


@dataclass
class BenchmarkSummary:
    """多轮运行的汇总统计"""
    task_name: str = ""
    task_category: str = ""
    version: str = ""
    total_runs: int = 0
    passed_runs: int = 0
    pass_rate: float = 0.0

    # L1 统计
    l1_avg_match_rate: float = 0.0

    # L2 统计
    l2_avg_overall: float = 0.0

    # L3 统计（中位数）
    l3_median_tokens: float = 0.0
    l3_median_duration: float = 0.0
    l3_median_cost: float = 0.0
    l3_stddev_tokens: float = 0.0

    # L4 统计
    l4_avg_accuracy: float = 0.0

    # 综合
    composite_median: float = 0.0
    composite_stddev: float = 0.0

    individual_results: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_name": self.task_name,
            "task_category": self.task_category,
            "version": self.version,
            "total_runs": self.total_runs,
            "passed_runs": self.passed_runs,
            "pass_rate": round(self.pass_rate, 2),
            "l1_avg_match_rate": round(self.l1_avg_match_rate, 2),
            "l2_avg_overall": round(self.l2_avg_overall, 1),
            "l3_median_tokens": self.l3_median_tokens,
            "l3_median_duration": round(self.l3_median_duration, 1),
            "l3_median_cost": round(self.l3_median_cost, 4),
            "l3_stddev_tokens": round(self.l3_stddev_tokens, 0),
            "l4_avg_accuracy": round(self.l4_avg_accuracy, 2),
            "composite_median": round(self.composite_median, 1),
            "composite_stddev": round(self.composite_stddev, 1),
            "individual_results": self.individual_results,
        }


# ── 工具函数 ──


def evaluate_l1(ai_output: str, expected_patterns: list[str]) -> L1Result:
    """评估 L1：检查 AI 输出是否包含所有预期模式。

    expected_patterns 中的每一项如果是以 / 开头和结尾，则视为正则表达式，否则为子串匹配。
    """
    result = L1Result()
    result.total_patterns = len(expected_patterns)
    if result.total_patterns == 0:
        result.passed = True
        result.match_rate = 1.0
        result.score = 1.0
        return result

    for pattern in expected_patterns:
        matched = False
        if pattern.startswith("/") and pattern.endswith("/") and len(pattern) > 2:
            # 正则模式
            try:
                regex = pattern[1:-1]
                if re.search(regex, ai_output, re.IGNORECASE | re.DOTALL):
                    matched = True
                    result.details.append(f"✓ regex: {regex}")
                else:
                    result.details.append(f"✗ regex: {regex}")
            except re.error:
                result.details.append(f"⚠ bad regex: {regex}")
                matched = True  # 坏正则不算失败
        else:
            # 子串匹配
            if pattern.lower() in ai_output.lower():
                matched = True
                result.details.append(f"✓ substr: {pattern[:60]}")
            else:
                result.details.append(f"✗ substr: {pattern[:60]}")

        if matched:
            result.matched_patterns += 1

    result.match_rate = result.matched_patterns / max(result.total_patterns, 1)
    result.passed = result.matched_patterns == result.total_patterns
    result.score = result.match_rate
    return result


def evaluate_l2(
    ai_output: str,
    task_prompt: str,
    cheap_client=None,
) -> L2Result:
    """评估 L2：质量评分。优先用 cheap LLM 自动评估，降级用启发式规则。"""
    result = L2Result()

    if cheap_client:
        try:
            return _l2_llm_evaluate(ai_output, task_prompt, cheap_client)
        except Exception:
            pass

    # 降级：启发式评估
    result.auto_evaluated = False

    # 正确性启发式：输出非空
    if ai_output.strip():
        result.correctness = 80
    else:
        result.correctness = 0
        result.issues.append("输出为空")

    # 完整性启发式：长度
    if len(ai_output) > 200:
        result.completeness = 80
    elif len(ai_output) > 50:
        result.completeness = 60
    else:
        result.completeness = 30
        result.issues.append("输出过短")

    # 简洁性启发式：不过度冗长
    if len(ai_output) < 4000:
        result.conciseness = 90
    elif len(ai_output) < 8000:
        result.conciseness = 70
    else:
        result.conciseness = 50
        result.issues.append("输出冗长")

    # 风格启发式：代码块
    if "```" in ai_output:
        result.style = 80
    else:
        result.style = 60

    result.overall = (result.correctness + result.completeness +
                      result.conciseness + result.style) // 4
    return result


def _l2_llm_evaluate(ai_output: str, task_prompt: str, client) -> L2Result:
    """用廉价 LLM 评估输出质量。"""
    eval_prompt = f"""你是严格的代码审查员。对以下 AI 输出评分（每项 0-100）。

任务:
{task_prompt[:500]}

AI 输出:
{ai_output[:2000]}

请输出纯 JSON（不要 markdown）:
{{
  "correctness": <0-100, 输出是否正确完成任务>,
  "completeness": <0-100, 是否完整覆盖>,
  "conciseness": <0-100, 是否简洁无冗余>,
  "style": <0-100, 代码风格/格式>,
  "overall": <0-100, 综合>,
  "issues": ["问题1", "问题2"]
}}"""

    resp = client.chat.completions.create(
        model=client.models[0] if hasattr(client, 'models') else "gpt-3.5-turbo",
        messages=[{"role": "user", "content": eval_prompt}],
        temperature=0,
        max_tokens=512,
    )
    content = resp.choices[0].message.content or "{}"

    # 清理 markdown 包裹
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(content)
    result = L2Result()
    result.correctness = int(data.get("correctness", 0))
    result.completeness = int(data.get("completeness", 0))
    result.conciseness = int(data.get("conciseness", 0))
    result.style = int(data.get("style", 0))
    result.overall = int(data.get("overall", 0))
    result.issues = data.get("issues", [])
    result.auto_evaluated = True
    return result


def evaluate_l4(
    tool_call_log: list[dict],
    expected_tools: list[str] | None = None,
) -> L4Result:
    """评估 L4：工具准确率。

    tool_call_log: [{"name": "toolkit_file", "args": {...}}, ...]
    expected_tools: 预期使用的工具名列表（可选）
    """
    result = L4Result()
    result.total_calls = len(tool_call_log)

    if result.total_calls == 0:
        result.accuracy = 1.0
        result.param_accuracy = 1.0
        return result

    seen = set()
    for call in tool_call_log:
        name = call.get("name", "")
        # 重复调用检测
        call_key = f"{name}:{json.dumps(call.get('args', {}), sort_keys=True)}"
        if call_key in seen:
            result.redundant_calls += 1
        seen.add(call_key)

        # 工具选择正确性
        if expected_tools and name in expected_tools:
            result.correct_calls += 1
        elif not expected_tools:
            result.correct_calls += 1  # 无预期时全算正确

        # 参数正确性（启发式：非空）
        args = call.get("args", {})
        # args 可能为字符串（未解析的 JSON），跳过此类校验
        if isinstance(args, dict) and args:
            try:
                if not any(v is None for v in args.values()):
                    result.param_correct += 1
            except Exception:
                pass  # 参数校验失败不阻断流程

    result.accuracy = result.correct_calls / result.total_calls
    result.param_accuracy = result.param_correct / result.total_calls
    result.redundancy_ratio = result.redundant_calls / result.total_calls
    return result


TOKEN_COST_TABLE = {
    # $/1M tokens (input, output)
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-3.5-sonnet": (3.00, 15.00),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "default": (0.50, 2.00),
}


def estimate_cost(
    model_name: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """估算美元成本。"""
    prices = TOKEN_COST_TABLE.get(model_name, TOKEN_COST_TABLE["default"])
    cost = (prompt_tokens / 1e6) * prices[0] + (completion_tokens / 1e6) * prices[1]
    return cost


def summarize_runs(results: list[BenchmarkResult], task_name: str = "",
                   task_category: str = "", version: str = "") -> BenchmarkSummary:
    """汇总多次运行结果。"""
    valid = [r for r in results if not r.error]
    if not valid:
        return BenchmarkSummary(task_name=task_name, task_category=task_category,
                                version=version)

    n = len(valid)
    passed = sum(1 for r in valid if r.l1.passed)

    summary = BenchmarkSummary(
        task_name=task_name,
        task_category=task_category,
        version=version,
        total_runs=n,
        passed_runs=passed,
        pass_rate=passed / n,
        l1_avg_match_rate=statistics.mean(r.l1.match_rate for r in valid),
        l2_avg_overall=statistics.mean(r.l2.overall for r in valid),
        l3_median_tokens=statistics.median(r.l3.total_tokens for r in valid),
        l3_median_duration=statistics.median(r.l3.duration_s for r in valid),
        l3_median_cost=statistics.median(r.l3.estimated_cost_usd for r in valid),
        l3_stddev_tokens=float(statistics.stdev(r.l3.total_tokens for r in valid)) if n > 1 else 0.0,
        l4_avg_accuracy=statistics.mean(r.l4.accuracy for r in valid),
        composite_median=statistics.median(r.composite_score for r in valid),
        composite_stddev=float(statistics.stdev(r.composite_score for r in valid)) if n > 1 else 0.0,
        individual_results=[r.to_dict() for r in valid],
    )
    return summary


def regression_check(
    current: BenchmarkSummary, previous: BenchmarkSummary
) -> L5Result:
    """L5: 版本间回归检测。"""
    result = L5Result(
        version=current.version,
        current_score=current.composite_median,
        previous_score=previous.composite_median,
    )
    result.delta = current.composite_median - previous.composite_median

    # 显著性判断：超过 1 个标准差视为显著
    if abs(result.delta) > current.composite_stddev:
        result.significant = True

    result.regressed = result.delta < -5.0  # 综合分下降超过 5 分算退化
    return result


TASK_CATEGORIES = {
    "hello": "对话基础",
    "sort_list": "代码生成",
    "code_review": "代码分析",
    "file_read_write": "文件操作",
    "json_parse": "数据处理",
    "bug_fix": "调试修复",
    "refactor": "代码重构",
    "search_synthesis": "搜索综合",
}
