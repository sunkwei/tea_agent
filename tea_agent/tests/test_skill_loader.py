"""
测试：Skill 按需加载评估器（skill_loader.py）
覆盖：
  - 扫描 SKILL.md 索引
  - 必要性/充分性双维计算
  - 决策矩阵（load / already_covered / irrelevant）
  - evaluate_and_load 集成（证据轮数 / 去重 / 截断）
  - 知识结晶废除验证（history_builder 不再引用 SkillRegistry）
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.skill_loader import (
    NECESSITY_THRESHOLD,
    SUFFICIENCY_THRESHOLD,
    SKILL_DOMAINS,
    SkillLoadEvaluator,
    clear_cache,
    evaluate_and_load,
    get_evaluator,
)
from tea_agent.session.context import SessionContext

# 真实 skills 目录（17 个内置 SKILL.md）
SKILLS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "skills")
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个测试前清空评估器缓存。"""
    clear_cache()
    yield
    clear_cache()


def _make_context(messages: list[dict], tools: set[str] | None = None) -> SessionContext:
    """构造带消息与可选工具的测试上下文。"""
    ctx = SessionContext()
    ctx.messages = messages
    if tools is not None:
        class _FakeToolkit:
            def __init__(self, names):
                self.func_map = {n: lambda *a, **k: None for n in names}
        ctx.toolkit = _FakeToolkit(tools)
    return ctx


# ── 1. 扫描 ──

def test_scan_discovers_all_skills():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    items = ev.scan(force=True)
    names = {m["name"] for m in items}
    assert len(items) >= 17
    # 关键 skill 都在
    for expected in ("agent-browser", "optimize-sql", "caveman", "writing-style",
                     "process-excel", "manage-docker", "output-format-constraint"):
        assert expected in names


def test_scan_parses_front_matter():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    items = ev.scan(force=True)
    browser = next(m for m in items if m["name"] == "agent-browser")
    assert "browser" in browser.get("description", "").lower()


# ── 2. 必要性 / 充分性 ──

def test_necessity_high_for_related_task():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    n = ev._necessity("optimize-sql", "帮我看看这条 SQL 为什么慢，索引怎么优化")
    assert n >= NECESSITY_THRESHOLD
    n2 = ev._necessity("agent-browser", "用浏览器打开网页填表单")
    assert n2 >= NECESSITY_THRESHOLD


def test_necessity_low_for_unrelated_task():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    n = ev._necessity("optimize-sql", "写一个 Python 冒泡排序")
    assert n < NECESSITY_THRESHOLD


def test_sufficiency_covered_by_tools():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    tools = {"toolkit_browser_tab", "toolkit_js_fetch", "toolkit_screen_read",
             "toolkit_input", "toolkit_screenshot", "toolkit_ocr"}
    s = ev._sufficiency("agent-browser", tools)
    assert s >= SUFFICIENCY_THRESHOLD


def test_sufficiency_zero_without_tools():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    s = ev._sufficiency("agent-browser", set())
    assert s == 0.0


# ── 3. 决策矩阵 ──

def test_decision_load_when_necessary_and_insufficient():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    decs = ev.evaluate("用户要求用 docker 优化镜像瘦身", available_tools=set())
    by_name = {d.name: d for d in decs}
    assert by_name["manage-docker"].action == "load"


def test_decision_no_load_when_already_covered():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    tools = {"toolkit_browser_tab", "toolkit_js_fetch", "toolkit_screen_read",
             "toolkit_input", "toolkit_screenshot", "toolkit_ocr"}
    decs = ev.evaluate("帮我在浏览器里自动填表并截图", available_tools=tools)
    by_name = {d.name: d for d in decs}
    assert by_name["agent-browser"].action == "no_load"
    assert by_name["agent-browser"].reason == "already_covered"


def test_decision_irrelevant():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    decs = ev.evaluate("帮我做一份煎蛋三明治", available_tools=set())
    assert all(d.action == "no_load" for d in decs)


def test_output_format_constraint_skipped():
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    decs = ev.evaluate("小模型输出规范 output-format-constraint", available_tools=set())
    assert all(d.name != "output-format-constraint" for d in decs)


# ── 4. evaluate_and_load 集成 ──

def test_eval_load_insufficient_evidence_returns_none():
    ctx = _make_context([{"role": "user", "content": "优化一下 SQL 慢查询"}])
    assert evaluate_and_load(ctx) is None  # 只有 1 轮证据


def test_eval_load_with_evidence_loads_skill():
    ctx = _make_context([
        {"role": "user", "content": "先看下项目的 Excel 报表"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "帮我清洗这个 Excel，合并单元格很多"},
    ])
    result = evaluate_and_load(ctx)
    assert result is not None
    assert "process-excel" in result
    assert "<loaded_skill" in result


def test_eval_load_dedup_not_reinjected():
    ctx = _make_context([
        {"role": "user", "content": "处理一下 excel 多表合并"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "继续清洗 excel 数据"},
    ])
    first = evaluate_and_load(ctx)
    assert first is not None
    # 已加载的 skill 记录在 context，第二轮不再重复注入
    assert "process-excel" in getattr(ctx, "_skill_loaded", set())
    second = evaluate_and_load(ctx)
    assert second is None or "process-excel" not in second


def test_eval_load_respects_max_per_round():
    # 同时涉及多个领域 → 最多加载 MAX_LOAD_PER_ROUND 个
    ctx = _make_context([
        {"role": "user", "content": "帮我用 docker 和 sql 优化两件事"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "docker 镜像瘦身 + 慢查询索引优化"},
    ])
    result = evaluate_and_load(ctx)
    if result is not None:
        assert result.count("<loaded_skill") <= 2


# ── 5. 知识结晶废除验证 ──

def test_knowledge_crystallization_deprecated():
    """history_builder 不再引用 SkillRegistry.recommend（废除知识结晶推荐）。"""
    hb_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "session", "history_builder.py")
    )
    with open(hb_path, encoding="utf-8") as f:
        src = f.read()
    assert "SkillRegistry" not in src
    assert "skill_registry" not in src
    # 新机制已被引用
    assert "skill_loader" in src


def test_skill_domains_cover_all_builtin_skills():
    """SKILL_DOMAINS 元数据覆盖全部 17 个内置 skill。"""
    ev = SkillLoadEvaluator(skills_dir=SKILLS_DIR)
    names = {m["name"] for m in ev.scan(force=True)}
    # 排除小模型专用（自动触发）
    assert names - {"output-format-constraint"} <= set(SKILL_DOMAINS.keys())
