"""
测试：上下文片段系统 + AGENTS.md 加载 + 压缩 Hooks + Token 预算配置
覆盖改进：
  #1 Token 预算感知注入（context_fragments.token_budget）
  #2 系统提示词片段化（ContextFragment + 注册表 + 组装器）
  #3 压缩 hooks 扩展点（auto_compact hooks）
  #4 AGENTS.md 分层加载 + 字节预算（agents_md_loader）
  #5 模型级 token budget 配置（config.ModelConfig.token_budget）
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tea_agent.agents_md_loader import (  # noqa: E402
    DEFAULT_MAX_BYTES,
    LoadedAgentsMd,
    collect_project_agents_md,
    find_project_root,
    load_agents_md,
    load_user_agents_md,
)
from tea_agent.auto_compact import (  # noqa: E402
    CompactionPipeline,
    clear_compact_hooks,
    register_post_compact_hook,
    register_pre_compact_hook,
    run_post_compact_hooks,
    run_pre_compact_hooks,
    unregister_post_compact_hook,
    unregister_pre_compact_hook,
)
from tea_agent.config import ModelConfig, load_config  # noqa: E402
from tea_agent.context_fragments import (  # noqa: E402
    ContextFragment,
    assemble_fragments,
    clear_fragments,
    get_fragment,
    list_fragments,
    register_fragment,
    unregister_fragment,
)
from tea_agent.session.context import SessionContext  # noqa: E402


# ═══ Fixtures ═════════════════════════════════════════

def make_context(**kwargs) -> SessionContext:
    ctx = SessionContext()
    ctx.max_context_tokens = kwargs.pop("max_context_tokens", 1_048_576)
    ctx.model = kwargs.pop("model", "deepseek-v3")
    ctx._current_mode = kwargs.pop("mode", "develop")
    ctx.messages = kwargs.pop("messages", [{"role": "user", "content": "测试消息"}])
    for k, v in kwargs.items():
        setattr(ctx, k, v)
    return ctx


# ═══ #1 Token 预算感知 ═════════════════════════════════

class TestTokenBudgetFragment:
    """token_budget 片段已禁用（上下文 token 评估存在偏差，2026-08-04 用户要求关闭）。"""

    def test_disabled_returns_none(self):
        ctx = make_context(max_context_tokens=1_000_000)
        frag = get_fragment("token_budget", ctx)
        assert frag is None

    def test_not_in_assemble_default(self):
        ctx = make_context()
        text = assemble_fragments(ctx)
        assert "<token_budget>" not in text


# ═══ #2 上下文片段系统 ═════════════════════════════════

class TestContextFragments:
    def test_assemble_includes_builtin(self):
        ctx = make_context()
        text = assemble_fragments(ctx)
        assert "<token_budget>" not in text
        assert "<current_time>" in text
        assert "[系统状态" in text

    def test_custom_fragment_registration(self):
        register_fragment(
            "test_custom",
            lambda ctx: ContextFragment(name="test_custom", body="自定义片段内容"),
        )
        try:
            assert "test_custom" in list_fragments()
            ctx = make_context()
            text = assemble_fragments(ctx)
            assert "自定义片段内容" in text
        finally:
            unregister_fragment("test_custom")

    def test_exclude_skips_fragment(self):
        ctx = make_context()
        text = assemble_fragments(ctx, exclude=["token_budget"])
        assert "<token_budget>" not in text
        assert "<current_time>" in text

    def test_names_filter(self):
        ctx = make_context()
        text = assemble_fragments(ctx, names=["current_time"])
        assert "<current_time>" in text
        assert "<token_budget>" not in text

    def test_factory_returning_none_skipped(self):
        register_fragment("test_none", lambda ctx: None)
        try:
            ctx = make_context()
            text = assemble_fragments(ctx)
            assert "test_none" not in text
        finally:
            unregister_fragment("test_none")

    def test_max_chars_budget(self):
        ctx = make_context()
        text = assemble_fragments(ctx, max_chars=50)
        assert len(text) <= 200  # 预算截断生效

    def test_failure_isolation(self):
        def bad_factory(ctx):
            raise RuntimeError("boom")

        register_fragment("test_bad", bad_factory)
        try:
            ctx = make_context()
            text = assemble_fragments(ctx)  # 不应抛异常
            assert text
        finally:
            unregister_fragment("test_bad")

    def test_clear_fragments_keeps_builtin(self):
        register_fragment("test_tmp", lambda ctx: ContextFragment("test_tmp", "x"))
        clear_fragments()
        assert "test_tmp" not in list_fragments()
        assert "token_budget" not in list_fragments()  # 已禁用


# ═══ #3 压缩 Hooks ═════════════════════════════════════

class TestCompactHooks:
    def setup_method(self):
        clear_compact_hooks()

    def test_register_and_run_pre(self):
        calls = []

        def hook(ctx):
            calls.append(ctx["reason"])
            return None  # 不修改消息

        register_pre_compact_hook(hook)
        msgs = run_pre_compact_hooks({"messages": [{"role": "user", "content": "x"}], "reason": "test"})
        assert len(msgs) == 1
        assert calls == ["test"]

    def test_pre_hook_can_replace_messages(self):
        def hook(ctx):
            return [{"role": "user", "content": "替换后"}]

        register_pre_compact_hook(hook)
        msgs = run_pre_compact_hooks({"messages": [{"role": "user", "content": "原始"}], "reason": "r"})
        assert msgs[0]["content"] == "替换后"

    def test_post_hook_can_modify_result(self):
        def hook(result):
            result["custom_flag"] = True
            return result

        register_post_compact_hook(hook)
        result = run_post_compact_hooks({"compacted": True, "saved_tokens": 10})
        assert result["custom_flag"] is True

    def test_hook_failure_isolation(self):
        def bad_hook(ctx):
            raise RuntimeError("hook fail")

        register_pre_compact_hook(bad_hook)
        msgs = run_pre_compact_hooks({"messages": [{"role": "user", "content": "x"}], "reason": "r"})
        assert len(msgs) == 1  # 失败不阻断

    def test_unregister(self):
        def hook(ctx):
            return None

        register_pre_compact_hook(hook)
        unregister_pre_compact_hook(hook)
        assert hook not in __import__("tea_agent.auto_compact", fromlist=["_pre_compact_hooks"])._pre_compact_hooks

    def test_pipeline_invokes_hooks(self):
        calls = []

        def pre(ctx):
            calls.append("pre")

        def post(result):
            calls.append("post")
            return result

        register_pre_compact_hook(pre)
        register_post_compact_hook(post)

        # 构造超过阈值的消息触发压缩
        big_msg = [{"role": "user", "content": "长" * 5000} for _ in range(12)]
        pipeline = CompactionPipeline()
        result = pipeline.run(big_msg, config=None, force=True)
        assert result["compacted"] is True
        assert "pre" in calls and "post" in calls


# ═══ #4 AGENTS.md 分层加载 ═════════════════════════════

class TestAgentsMdLoader:
    def test_find_project_root_git(self, tmp_path):
        proj = tmp_path / "proj"
        (proj / ".git").mkdir(parents=True)
        (proj / "sub").mkdir()
        assert find_project_root(str(proj / "sub")) == str(proj)

    def test_find_project_root_no_marker(self, tmp_path):
        d = tmp_path / "no_marker"
        d.mkdir()
        assert find_project_root(str(d)) == str(d)

    def test_collect_agents_md_hierarchy(self, tmp_path):
        proj = tmp_path / "proj"
        (proj / ".git").mkdir(parents=True)
        (proj / "sub").mkdir()
        (proj / "AGENTS.md").write_text("root rules", encoding="utf-8")
        (proj / "sub" / "AGENTS.md").write_text("sub rules", encoding="utf-8")

        files = collect_project_agents_md(str(proj / "sub"))
        # 根级优先，子级在后
        assert len(files) == 2
        assert str(proj / "AGENTS.md") in files
        assert str(proj / "sub" / "AGENTS.md") in files

    def test_load_agents_md_concatenation(self, tmp_path):
        proj = tmp_path / "proj"
        (proj / ".git").mkdir(parents=True)
        (proj / "AGENTS.md").write_text("# 项目规范\n遵守测试规范", encoding="utf-8")

        loaded = load_agents_md(cwd=str(proj), max_bytes=DEFAULT_MAX_BYTES, include_user=False)
        assert isinstance(loaded, LoadedAgentsMd)
        assert "项目规范" in loaded.text
        assert len(loaded.sources) == 1

    def test_byte_budget_truncation(self, tmp_path):
        proj = tmp_path / "proj"
        (proj / ".git").mkdir(parents=True)
        (proj / "AGENTS.md").write_text("A" * 5000, encoding="utf-8")

        loaded = load_agents_md(cwd=str(proj), max_bytes=1000, include_user=False)
        assert loaded.total_bytes <= 1200
        assert loaded.truncated is True

    def test_override_file_appended(self, tmp_path):
        proj = tmp_path / "proj"
        (proj / ".git").mkdir(parents=True)
        (proj / "AGENTS.md").write_text("base", encoding="utf-8")
        (proj / "AGENTS.override.md").write_text("override rules", encoding="utf-8")

        loaded = load_agents_md(cwd=str(proj), max_bytes=DEFAULT_MAX_BYTES, include_user=False)
        assert "override rules" in loaded.text
        assert loaded.sources[-1].endswith("AGENTS.override.md")

    def test_empty_when_no_files(self, tmp_path):
        loaded = load_agents_md(cwd=str(tmp_path), include_user=False, include_project=True)
        assert loaded.text == ""


# ═══ #5 模型级 token budget 配置 ═══════════════════════

class TestTokenBudgetConfig:
    def test_model_config_field_default(self):
        m = ModelConfig()
        assert m.token_budget == {}
        assert m.get_token_budget("reminder_threshold") is None

    def test_get_token_budget_value(self):
        m = ModelConfig(token_budget={"reminder_threshold": 0.2})
        assert m.get_token_budget("reminder_threshold") == 0.2
        assert m.get_token_budget("missing", 42) == 42

    def test_parse_from_yaml(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            "main_model:\n"
            "  api_key: test-key\n"
            "  api_url: https://api.test.com/v1\n"
            "  model_name: deepseek-v3\n"
            "  max_context_tokens: 1048576\n"
            "  token_budget:\n"
            "    reminder_threshold: 0.15\n"
            "    fallback_buffer_tokens: 20000\n",
            encoding="utf-8",
        )
        cfg = load_config(str(yaml_file))
        assert cfg.main_model.max_context_tokens == 1048576
        assert cfg.main_model.token_budget.get("reminder_threshold") == 0.15
        assert cfg.main_model.token_budget.get("fallback_buffer_tokens") == 20000


# ═══ 集成：history_builder 注入 ════════════════════════

class TestHistoryBuilderIntegration:
    def test_system_prompt_stable_no_dynamic_fragments(self):
        """缓存友好：system prompt 不注入动态片段（时间/预算/轮次）。

        动态片段（current_time/token_budget/session_budget）每次请求必变，
        注入 system prompt 会导致 DeepSeek 前缀缓存 100% 失效。
        """
        from tea_agent.session.history_builder import build_api_messages

        ctx = make_context()
        msgs = build_api_messages(ctx, "测试系统提示词")
        assert msgs[0]["role"] == "system"
        assert "测试系统提示词" in msgs[0]["content"]
        assert "<token_budget>" not in msgs[0]["content"]
        assert "<current_time>" not in msgs[0]["content"]

    def test_dynamic_status_injected_to_user_message(self):
        """动态状态注入到 user 消息（add_user_message 入库定格）"""
        from tea_agent.basesession import BaseChatSession

        class _FS(BaseChatSession):
            def chat_stream(self, msg, callback):
                return "", False

        ctx = make_context()
        fs = _FS(model="test")
        fs.context = ctx
        fs.add_user_message("你好")
        assert "[运行状态" in fs.messages[-1]["content"]
        assert "<token_budget>" not in fs.messages[-1]["content"]

    def test_disable_summary_system_prompt_stable(self):
        from tea_agent.session.history_builder import build_api_messages

        ctx = make_context()
        ctx.disable_summary = True
        msgs = build_api_messages(ctx, "测试")
        assert "<token_budget>" not in msgs[0]["content"]
