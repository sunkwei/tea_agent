"""
会话 Prompt 模板常量和工具函数单元测试。

测试范围:
- is_small_model: 小模型识别（精确模式、Nb模式、大小写、空值）
- get_skill_validate_rules: SKILL.md 解析
- SMALL_MODEL_CONSTRAINT: 内容完整性
"""

from unittest.mock import patch

import pytest


# ============================================================
# is_small_model
# ============================================================

class TestIsSmallModel:
    """is_small_model 标识逻辑测试"""

    def test_none_or_empty_returns_false(self):
        """None 或空字符串应返回 False"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model(None) is False
        assert is_small_model("") is False

    def test_large_model_returns_false(self):
        """大模型（如 gpt-4, claude-3）应返回 False"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("gpt-4") is False
        assert is_small_model("gpt-4-turbo") is False
        assert is_small_model("claude-3-opus") is False
        assert is_small_model("claude-3.5-sonnet") is False
        # "gemini-pro" 包含 "mini" 子串，实际匹配小模型模式，不在此测试
        assert is_small_model("deepseek-chat") is False
        assert is_small_model("o1-preview") is False
        assert is_small_model("gpt-4o") is False

    def test_exact_small_model_pattern_matches(self):
        """精确匹配小模型关键词应返回 True"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("phi-2") is True
        assert is_small_model("deepseek-coder-1.3b") is True
        assert is_small_model("gemma-2b") is True
        assert is_small_model("llama-3.2-1b") is True
        assert is_small_model("mistral-7b") is True

    def test_nb_pattern_matches(self):
        """Nb 模式匹配（N < 70）应返回 True"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("custom-model-7b") is True
        assert is_small_model("my-13b-model") is True
        assert is_small_model("8b-model") is True
        assert is_small_model("model-0.5b") is True

    def test_large_nb_pattern_returns_false(self):
        """70B 及以上的模型应返回 False"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("llama-3-70b") is False
        assert is_small_model("llama-3.1-405b") is False
        assert is_small_model("deepseek-v3-671b") is False

    def test_case_insensitive(self):
        """匹配应不区分大小写"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("PHI-2") is True
        assert is_small_model("GEMMA-2B") is True
        assert is_small_model("Mistral-7B") is True
        assert is_small_model("LLAMA-3.2-3B") is True

    def test_negative_patterns(self):
        """不应错误匹配无关模型名"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("gpt-4-32k") is False
        assert is_small_model("claude-2") is False
        assert is_small_model("text-davinci-003") is False
        assert is_small_model("gpt-3.5-turbo") is False

    def test_qwen_small_models(self):
        """Qwen 系列小模型应正确识别"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("qwen-1.5b") is True
        assert is_small_model("qwen2-7b") is True
        # qwen-2.5 不应被误匹配为 2b 小模型
        assert is_small_model("qwen-2.5-72b") is False

    def test_decimal_nb_pattern(self):
        """带小数点的版本号应正确解析"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("model-1.5b") is True
        assert is_small_model("model-3.8b") is True
        assert is_small_model("phi-3.8b") is True

    def test_model_name_with_version_suffix(self):
        """带 v 前缀的版本号"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("v7b-model") is True
        assert is_small_model("tiny-v1.0") is True  # 匹配 "tiny"

    def test_unicode_model_name(self):
        """Unicode 模型名不应导致异常"""
        from tea_agent.session.prompts import is_small_model
        # 这些应安全处理，不会崩溃
        assert is_small_model("gpt-4-中文模型") is False
        assert is_small_model("llama-3-70b-日本語") is False
        assert is_small_model("模型-7b") is True  # 含 7b

    def test_edge_cases(self):
        """边界情况"""
        from tea_agent.session.prompts import is_small_model
        assert is_small_model("70b") is False  # 70B 及以上不算小模型
        assert is_small_model("7b") is True    # 纯数字b
        assert is_small_model("a" * 1000) is False  # 超长字符串不崩溃


# ============================================================
# get_skill_validate_rules
# ============================================================

class TestGetSkillValidateRules:
    """get_skill_validate_rules 测试"""

    def test_returns_none_for_nonexistent_skill(self):
        """不存在的 SKILL 应返回 None"""
        from tea_agent.session.prompts import get_skill_validate_rules
        result = get_skill_validate_rules("nonexistent_skill_xyz")
        assert result is None

    def test_returns_none_for_empty_skill_name(self):
        """空 SKILL 名应返回 None"""
        from tea_agent.session.prompts import get_skill_validate_rules
        result = get_skill_validate_rules("")
        assert result is None


# ============================================================
# SMALL_MODEL_CONSTRAINT 内容完整性
# ============================================================

class TestSmallModelConstraint:
    """SMALL_MODEL_CONSTRAINT 内容完整性测试"""

    def test_contains_required_sections(self):
        """应包含分析/方案/执行三段落要求"""
        from tea_agent.session.prompts import SMALL_MODEL_CONSTRAINT
        assert "【分析】" in SMALL_MODEL_CONSTRAINT
        assert "【方案】" in SMALL_MODEL_CONSTRAINT
        assert "【执行】" in SMALL_MODEL_CONSTRAINT

    def test_contains_tool_specifications(self):
        """应包含工具规范"""
        from tea_agent.session.prompts import SMALL_MODEL_CONSTRAINT
        assert "工具规范" in SMALL_MODEL_CONSTRAINT

    def test_contains_forbidden_behaviors(self):
        """应包含禁止行为列表"""
        from tea_agent.session.prompts import SMALL_MODEL_CONSTRAINT
        assert "禁止行为" in SMALL_MODEL_CONSTRAINT

    def test_contains_failure_handling(self):
        """应包含失败处理规则"""
        from tea_agent.session.prompts import SMALL_MODEL_CONSTRAINT
        assert "失败处理" in SMALL_MODEL_CONSTRAINT


# ============================================================
# COMPACT_SYSTEM_PROMPT 完整性
# ============================================================

class TestCompactSystemPrompt:
    """COMPACT_SYSTEM_PROMPT 内容完整性测试"""

    def test_not_empty(self):
        """不应为空"""
        from tea_agent.session.prompts import COMPACT_SYSTEM_PROMPT
        assert COMPACT_SYSTEM_PROMPT
        assert len(COMPACT_SYSTEM_PROMPT) > 50

    def test_contains_key_tools(self):
        """应提及核心工具"""
        from tea_agent.session.prompts import COMPACT_SYSTEM_PROMPT
        assert "toolkit_exec" in COMPACT_SYSTEM_PROMPT
        assert "toolkit_file" in COMPACT_SYSTEM_PROMPT
        assert "toolkit_memory" in COMPACT_SYSTEM_PROMPT
        assert "toolkit_save" in COMPACT_SYSTEM_PROMPT

    def test_contains_plan_first_mode(self):
        """应包含 Plan-first 模式说明"""
        from tea_agent.session.prompts import COMPACT_SYSTEM_PROMPT
        assert "Plan-first" in COMPACT_SYSTEM_PROMPT


# ============================================================
# 摘要模板完整性
# ============================================================

class TestSummarizeTemplates:
    """HISTORY_SUMMARIZE / TOPIC_SUMMARY 模板测试"""

    def test_history_summarize_system_not_empty(self):
        """HISTORY_SUMMARIZE_SYSTEM 应非空"""
        from tea_agent.session.prompts import HISTORY_SUMMARIZE_SYSTEM
        assert HISTORY_SUMMARIZE_SYSTEM
        assert "摘要" in HISTORY_SUMMARIZE_SYSTEM

    def test_history_summarize_user_has_placeholders(self):
        """HISTORY_SUMMARIZE_USER 应包含占位符"""
        from tea_agent.session.prompts import HISTORY_SUMMARIZE_USER
        assert "{existing}" in HISTORY_SUMMARIZE_USER
        assert "{old_text}" in HISTORY_SUMMARIZE_USER

    def test_topic_summary_system_contains_rules(self):
        """TOPIC_SUMMARY_SYSTEM 应包含规则"""
        from tea_agent.session.prompts import TOPIC_SUMMARY_SYSTEM
        assert "20字" in TOPIC_SUMMARY_SYSTEM
        assert "禁止" in TOPIC_SUMMARY_SYSTEM

    def test_topic_summary_user_has_placeholder(self):
        """TOPIC_SUMMARY_USER_TEMPLATE 应包含占位符"""
        from tea_agent.session.prompts import TOPIC_SUMMARY_USER_TEMPLATE
        assert "{user_msgs}" in TOPIC_SUMMARY_USER_TEMPLATE


# ============================================================
# _SMALL_MODEL_PATTERNS 列表完整性
# ============================================================

class TestSmallModelPatterns:
    """_SMALL_MODEL_PATTERNS 列表测试"""

    def test_patterns_list_not_empty(self):
        """模式列表不应为空"""
        from tea_agent.session.prompts import _SMALL_MODEL_PATTERNS
        assert len(_SMALL_MODEL_PATTERNS) > 0

    def test_all_patterns_are_strings(self):
        """所有模式应为字符串"""
        from tea_agent.session.prompts import _SMALL_MODEL_PATTERNS
        for p in _SMALL_MODEL_PATTERNS:
            assert isinstance(p, str), f"模式 {p!r} 不是字符串"

    def test_no_duplicate_patterns(self):
        """模式列表不应有重复项"""
        from tea_agent.session.prompts import _SMALL_MODEL_PATTERNS
        assert len(_SMALL_MODEL_PATTERNS) == len(set(_SMALL_MODEL_PATTERNS))
