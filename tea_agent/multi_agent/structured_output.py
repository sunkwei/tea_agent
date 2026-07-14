"""
StructuredOutput — 结构化输出支持。

基于 Pydantic 定义常见任务的输出结构。
让 Agent 的回复不再是自由文本，而是可解析、可验证的结构化数据。

用法:
    from tea_agent.multi_agent import StructuredOutput, AnalysisReport, CodeChangePlan

    # 1. 在 RoleAgent 中使用
    report = analyst.execute(
        "分析 dispatcher.py",
        output_model=AnalysisReport,
    )
    print(report.structured["issues"])

    # 2. 自定义输出模型
    class MyOutput(StructuredOutput):
        summary: str
        score: float

    agent.execute("评估代码质量", output_model=MyOutput)
"""

from pydantic import BaseModel, Field
from typing import Any


class StructuredOutput(BaseModel):
    """所有结构化输出的基类。"""
    pass


# ───────────────────────────────────────────────
# 代码分析
# ───────────────────────────────────────────────

class CodeIssue(BaseModel):
    """代码问题。"""
    severity: str = Field(description="严重级别: critical/high/medium/low")
    file: str = Field(default="", description="文件路径")
    line: int = Field(default=0, description="行号")
    category: str = Field(description="类别: bug/security/performance/style/design")
    title: str = Field(description="问题标题")
    description: str = Field(description="问题详细描述")
    suggestion: str = Field(default="", description="改进建议")


class AnalysisReport(StructuredOutput):
    """代码分析报告。"""
    summary: str = Field(description="总体分析摘要")
    quality_score: float = Field(default=0.0, description="质量评分 0-100", ge=0, le=100)
    issues: list[CodeIssue] = Field(default_factory=list, description="发现的问题列表")
    strengths: list[str] = Field(default_factory=list, description="代码优点")
    recommendations: list[str] = Field(default_factory=list, description="改进建议列表")


# ───────────────────────────────────────────────
# 代码修改计划
# ───────────────────────────────────────────────

class ChangeItem(BaseModel):
    """单个修改项。"""
    file: str = Field(description="文件路径")
    description: str = Field(description="修改描述")
    change_type: str = Field(default="modify", description="修改类型: add/modify/delete/refactor")
    risk: str = Field(default="low", description="风险: high/medium/low")


class CodeChangePlan(StructuredOutput):
    """代码修改计划。"""
    goal: str = Field(description="修改目标")
    files_to_change: list[ChangeItem] = Field(description="需要修改的文件列表")
    estimated_effort: str = Field(default="", description="预估工作量")
    risks: list[str] = Field(default_factory=list, description="潜在风险")
    testing_strategy: str = Field(default="", description="测试策略")


# ───────────────────────────────────────────────
# 测试相关
# ───────────────────────────────────────────────

class TestCase(BaseModel):
    """测试用例。"""
    name: str = Field(description="测试名称")
    description: str = Field(description="测试目标")
    input: str = Field(default="", description="测试输入")
    expected_output: str = Field(default="", description="预期输出")
    test_type: str = Field(default="unit", description="测试类型: unit/integration/e2e")


class TestPlan(StructuredOutput):
    """测试计划。"""
    files_to_test: list[str] = Field(description="需要测试的文件")
    test_cases: list[TestCase] = Field(description="测试用例列表")
    coverage_target: float = Field(default=0.8, description="覆盖率目标")
    notes: list[str] = Field(default_factory=list, description="备注")


class TestResult(StructuredOutput):
    """测试结果摘要。"""
    passed: int = Field(default=0, description="通过的测试数")
    failed: int = Field(default=0, description="失败的测试数")
    errors: list[str] = Field(default_factory=list, description="错误详情")
    coverage: float = Field(default=0.0, description="代码覆盖率")
    duration_seconds: float = Field(default=0.0, description="测试耗时")


# ───────────────────────────────────────────────
# 架构设计
# ───────────────────────────────────────────────

class Component(BaseModel):
    """架构组件。"""
    name: str = Field(description="组件名")
    responsibility: str = Field(description="职责描述")
    dependencies: list[str] = Field(default_factory=list, description="依赖的其他组件")


class ArchitectureDesign(StructuredOutput):
    """架构设计方案。"""
    title: str = Field(description="架构设计标题")
    overview: str = Field(description="总体概述")
    components: list[Component] = Field(description="组件列表")
    data_flow: str = Field(default="", description="数据流描述")
    design_rationale: str = Field(default="", description="设计理由")


# ───────────────────────────────────────────────
# 审查反馈
# ───────────────────────────────────────────────

class ReviewComment(BaseModel):
    """审查意见。"""
    file: str = Field(default="", description="文件")
    line: int = Field(default=0, description="行号")
    severity: str = Field(default="info", description="严重度: error/warning/info")
    message: str = Field(description="意见内容")
    suggestion: str = Field(default="", description="修改建议")


class CodeReview(StructuredOutput):
    """代码审查结果。"""
    overall_assessment: str = Field(description="总体评价")
    approval: bool = Field(default=False, description="是否批准")
    comments: list[ReviewComment] = Field(default_factory=list, description="审查意见列表")
    summary: str = Field(default="", description="总结")
