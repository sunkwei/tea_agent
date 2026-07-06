"""
任务评估器 — 自动评估任务执行质量。

设计灵感:
  EvoAgentX 的内置评估系统 + GenericAgent 的 Skill 结晶逻辑

功能:
  - 评估任务成功/失败
  - 计算质量评分 (0-100)
  - 评估 token 效率
  - 提取经验教训
  - 决定是否结晶为 Skill

用法:
    from tea_agent.evaluation import TaskEvaluator

    evaluator = TaskEvaluator()
    result = evaluator.evaluate(
        task="重构 gui.py 添加类型注解",
        rounds=rounds_data,
        tools_used=["toolkit_file", "toolkit_edit", "toolkit_lsp"],
        token_cost=15000,
        time_seconds=120
    )

    print(result)
    # EvalResult(success=True, quality_score=85, should_crystallize=True, ...)
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    """评估结果"""
    success: bool                        # 任务是否成功
    quality_score: int = 0               # 质量评分 0-100
    token_efficiency: float = 0.0        # token 效率 (任务复杂度/token消耗)
    time_efficiency: float = 0.0         # 时间效率 (任务复杂度/耗时)
    issues: list[str] = field(default_factory=list)       # 发现的问题
    lessons: list[str] = field(default_factory=list)      # 经验教训
    suggestions: list[str] = field(default_factory=list)  # 改进建议
    should_crystallize: bool = False     # 是否应该结晶为 Skill
    should_retry: bool = False           # 是否建议重试
    summary: str = ""                    # 评估摘要

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "quality_score": self.quality_score,
            "token_efficiency": self.token_efficiency,
            "time_efficiency": self.time_efficiency,
            "issues": self.issues,
            "lessons": self.lessons,
            "suggestions": self.suggestions,
            "should_crystallize": self.should_crystallize,
            "should_retry": self.should_retry,
            "summary": self.summary,
        }


class TaskEvaluator:
    """任务评估器"""

    # 任务复杂度估算规则
    COMPLEXITY_KEYWORDS = {
        "high": ["重构", "refactor", "迁移", "migrate", "架构", "architecture",
                "多文件", "multi-file", "批量", "batch"],
        "medium": ["添加", "add", "修改", "modify", "修复", "fix", "优化", "optimize",
                  "测试", "test", "文档", "doc"],
        "low": ["查看", "view", "读取", "read", "搜索", "search", "查询", "query",
               "列出", "list", "统计", "count"],
    }

    # 成功信号
    SUCCESS_SIGNALS = [
        "成功", "完成", "通过", "success", "done", "pass",
        "已添加", "已修改", "已修复", "已创建", "已删除",
    ]

    # 失败信号
    FAILURE_SIGNALS = [
        "失败", "错误", "失败", "error", "fail", "exception",
        "无法", "不能", "unable", "cannot",
    ]

    def __init__(self):
        pass

    def evaluate(
        self,
        task: str,
        rounds: list[dict] | None = None,
        tools_used: list[str] | None = None,
        token_cost: int = 0,
        time_seconds: float = 0,
        error: str | None = None,
    ) -> EvalResult:
        """
        评估任务执行结果。

        Args:
            task: 任务描述
            rounds: 对话轮次数据
            tools_used: 使用的工具列表
            token_cost: token 消耗
            time_seconds: 耗时
            error: 错误信息 (如果有)

        Returns:
            评估结果
        """
        if tools_used is None:
            tools_used = []
        if rounds is None:
            rounds = []

        # 1. 判断成功/失败
        success = self._determine_success(rounds, error)

        # 2. 估算任务复杂度
        complexity = self._estimate_complexity(task)

        # 3. 计算质量评分
        quality_score = self._compute_quality_score(
            success, complexity, rounds, tools_used, token_cost, time_seconds
        )

        # 4. 计算效率指标
        token_efficiency = self._compute_token_efficiency(complexity, token_cost)
        time_efficiency = self._compute_time_efficiency(complexity, time_seconds)

        # 5. 提取问题
        issues = self._extract_issues(rounds, error)

        # 6. 提取经验教训
        lessons = self._extract_lessons(rounds, success, issues)

        # 7. 生成改进建议
        suggestions = self._generate_suggestions(
            success, quality_score, token_efficiency, time_efficiency, issues
        )

        # 8. 决定是否结晶
        should_crystallize = self._should_crystallize(
            success, quality_score, complexity, tools_used
        )

        # 9. 决定是否重试
        should_retry = self._should_retry(success, quality_score, issues)

        # 10. 生成摘要
        summary = self._generate_summary(
            task, success, quality_score, token_cost, time_seconds
        )

        result = EvalResult(
            success=success,
            quality_score=quality_score,
            token_efficiency=token_efficiency,
            time_efficiency=time_efficiency,
            issues=issues,
            lessons=lessons,
            suggestions=suggestions,
            should_crystallize=should_crystallize,
            should_retry=should_retry,
            summary=summary,
        )

        logger.info(f"📊 评估完成: {'✅' if success else '❌'} "
                    f"质量={quality_score}, 结晶={'是' if should_crystallize else '否'}")

        return result

    def _determine_success(self, rounds: list[dict], error: str | None) -> bool:
        """判断任务是否成功"""
        # 有明确错误 → 失败
        if error:
            return False

        if not rounds:
            return False

        # 检查最后一轮回复
        last_round = rounds[-1] if rounds else {}
        content = last_round.get("content", "").lower()

        # 检查失败信号
        for signal in self.FAILURE_SIGNALS:
            if signal in content:
                return False

        # 检查成功信号
        for signal in self.SUCCESS_SIGNALS:
            if signal in content:
                return True

        # 默认认为成功（如果没有明确的失败信号）
        return True

    def _estimate_complexity(self, task: str) -> str:
        """估算任务复杂度"""
        task_lower = task.lower()

        for level, keywords in self.COMPLEXITY_KEYWORDS.items():
            if any(kw in task_lower for kw in keywords):
                return level

        # 默认中等复杂度
        return "medium"

    def _compute_quality_score(
        self,
        success: bool,
        complexity: str,
        rounds: list[dict],
        tools_used: list[str],
        token_cost: int,
        time_seconds: float,
    ) -> int:
        """计算质量评分 (0-100)"""
        score = 50  # 基础分

        # 成功/失败
        if success:
            score += 30
        else:
            score -= 30

        # 工具使用效率
        if tools_used:
            # 使用合适的工具加分
            if "toolkit_lsp" in tools_used and "类型" in str(rounds):
                score += 10
            if "toolkit_run_tests" in tools_used:
                score += 5

        # Token 效率
        complexity_multiplier = {"high": 20000, "medium": 10000, "low": 5000}
        expected_tokens = complexity_multiplier.get(complexity, 10000)
        if token_cost > 0:
            efficiency = expected_tokens / token_cost
            if efficiency > 1.5:
                score += 10  # 高效
            elif efficiency < 0.5:
                score -= 10  # 低效

        # 时间效率
        complexity_time = {"high": 300, "medium": 120, "low": 60}
        expected_time = complexity_time.get(complexity, 120)
        if time_seconds > 0:
            efficiency = expected_time / time_seconds
            if efficiency > 1.5:
                score += 5
            elif efficiency < 0.3:
                score -= 5

        # 限制范围
        return max(0, min(100, score))

    def _compute_token_efficiency(self, complexity: str, token_cost: int) -> float:
        """计算 token 效率"""
        if token_cost == 0:
            return 0.0

        complexity_multiplier = {"high": 20000, "medium": 10000, "low": 5000}
        expected_tokens = complexity_multiplier.get(complexity, 10000)

        return expected_tokens / token_cost

    def _compute_time_efficiency(self, complexity: str, time_seconds: float) -> float:
        """计算时间效率"""
        if time_seconds == 0:
            return 0.0

        complexity_time = {"high": 300, "medium": 120, "low": 60}
        expected_time = complexity_time.get(complexity, 120)

        return expected_time / time_seconds

    def _extract_issues(self, rounds: list[dict], error: str | None) -> list[str]:
        """提取问题"""
        issues = []

        if error:
            issues.append(f"执行错误: {error[:100]}")

        # 检查轮次中的问题信号
        for i, round_data in enumerate(rounds):
            content = round_data.get("content", "").lower()

            # 检查重试
            if "重试" in content or "retry" in content:
                issues.append(f"第 {i+1} 轮出现重试")

            # 检查困惑
            if "抱歉" in content or "sorry" in content or "sorry" in content:
                issues.append(f"第 {i+1} 轮 AI 表示困惑")

            # 检查多次工具调用
            tool_calls = round_data.get("tool_calls", [])
            if len(tool_calls) > 5:
                issues.append(f"第 {i+1} 轮工具调用过多 ({len(tool_calls)} 次)")

        return issues

    def _extract_lessons(
        self, rounds: list[dict], success: bool, issues: list[str]
    ) -> list[str]:
        """提取经验教训"""
        lessons = []

        if not success:
            lessons.append("任务失败，需要分析失败原因")

        if len(issues) > 3:
            lessons.append("执行过程中问题较多，建议简化任务或分步执行")

        # 检查工具使用模式
        all_tools = []
        for round_data in rounds:
            for tc in round_data.get("tool_calls", []):
                func_name = tc.get("function", {}).get("name", "")
                if func_name:
                    all_tools.append(func_name)

        if all_tools:
            # 统计工具使用频率
            from collections import Counter
            tool_counts = Counter(all_tools)
            most_used = tool_counts.most_common(1)[0]
            if most_used[1] > 5:
                lessons.append(f"频繁使用 {most_used[0]}，考虑封装为 Skill")

        return lessons

    def _generate_suggestions(
        self,
        success: bool,
        quality_score: int,
        token_efficiency: float,
        time_efficiency: float,
        issues: list[str],
    ) -> list[str]:
        """生成改进建议"""
        suggestions = []

        if not success:
            suggestions.append("分析失败原因，考虑重试或修改方案")

        if quality_score < 50:
            suggestions.append("质量评分较低，建议优化执行策略")

        if token_efficiency < 0.5:
            suggestions.append("Token 消耗过高，考虑简化任务或使用更精确的工具")

        if time_efficiency < 0.3:
            suggestions.append("耗时过长，考虑并行执行或分步处理")

        if len(issues) > 2:
            suggestions.append("执行过程问题较多，建议增加前置检查")

        return suggestions

    def _should_crystallize(
        self,
        success: bool,
        quality_score: int,
        complexity: str,
        tools_used: list[str],
    ) -> bool:
        """决定是否应该结晶为 Skill"""
        # 必须成功
        if not success:
            return False

        # 质量必须达标
        if quality_score < 60:
            return False

        # 必须使用工具
        if not tools_used:
            return False

        # 复杂度不能太低
        if complexity == "low":
            return False

        # 至少使用 2 个工具
        return not len(tools_used) < 2

    def _should_retry(
        self, success: bool, quality_score: int, issues: list[str]
    ) -> bool:
        """决定是否建议重试"""
        if success:
            return False

        if quality_score >= 40:
            return True  # 接近成功，可以重试

        if len(issues) <= 2:
            return True  # 问题不多，可以重试

        return False

    def _generate_summary(
        self,
        task: str,
        success: bool,
        quality_score: int,
        token_cost: int,
        time_seconds: float,
    ) -> str:
        """生成评估摘要"""
        status = "✅ 成功" if success else "❌ 失败"
        task_short = task[:30] + "..." if len(task) > 30 else task

        parts = [
            f"{status}: {task_short}",
            f"质量评分: {quality_score}/100",
        ]

        if token_cost > 0:
            parts.append(f"Token: {token_cost:,}")

        if time_seconds > 0:
            if time_seconds < 60:
                parts.append(f"耗时: {time_seconds:.1f}s")
            else:
                parts.append(f"耗时: {time_seconds/60:.1f}min")

        return " | ".join(parts)
