"""A8: 上下文溢出防线 — 输出感知预算 + 400 溢出自愈 回归测试。

背景（2026-08 生产事故）：150000 窗口 + max_tokens=65536 时，输入 84465
低于旧 0.8 基线 120000 → 水位线裁剪不触发；但 84465+65536=150001 > 150000
→ 400 "This model's maximum context length is 150000 tokens..."。

A8 三层防线：
  1. 主动（solve_token_budget）：输入预算 = 窗口 - 实际请求输出 - 2% 余量，
     取代固定 0.8 粗估；build_api_messages 记录 _output_cap，工具循环把
     请求 max_tokens 钳制到该上限（_request_max_tokens）；
  2. 发送前护栏（_ensure_within_output_budget）：估算 输入+输出+余量 > 窗口
     → 强制重新裁剪（重置 _loop_trim_done）；
  3. 反应式自愈（_parse_context_overflow + _apply_context_overflow_recovery）：
     解析 400 → 修正误配窗口 → 紧急输入预算（真实输入腰斩）→ 强制最深
     裁剪 + 强制摘要 → 钳制 max_tokens 重试。
"""
from unittest.mock import MagicMock

from tea_agent.onlinesession import OnlineToolSession
from tea_agent.session.context import SessionContext
from tea_agent.session.history_builder import (
    estimate_messages_tokens,
    solve_token_budget,
)
from tea_agent.session.tool_loop_runner import (
    _ensure_within_output_budget,
    _parse_context_overflow,
    _request_max_tokens,
    execute_tool_loop,
)

# ── 生产事故的真实 400 错误体（逐字）──
INCIDENT_ERR = (
    "Error code: 400 - {'error': {'message': \"This model's maximum context length is "
    "150000 tokens. However, you requested 65536 output tokens and your prompt "
    "contains at least 84465 input tokens, for a total of at least 150001 tokens. "
    "Please reduce the length of the input prompt or the number of requested output "
    "tokens. (parameter=input_tokens, value=84465)\", 'type': 'BadRequestError', "
    "'param': 'input_tokens', 'code': 400}}"
)


def _make_session_from_ctx(ctx: SessionContext) -> OnlineToolSession:
    """由自定义 ctx 构建带真实 _build_api_messages 路径的 session（对齐 test_onlinesession）"""
    mock_tk = MagicMock()
    mock_tk.meta_map = {}
    sess = OnlineToolSession(
        toolkit=mock_tk, api_key="sk-test", api_url="https://api.test.com/v1",
        model="test-model", enable_thinking=ctx.enable_thinking, storage=None,
        supports_vision=ctx.supports_vision, supports_reasoning=ctx.supports_reasoning,
        disable_summary=ctx.disable_summary,
    )
    sess.context = ctx
    sess.system_prompt = "You are a test assistant."
    return sess


def _fake_config(max_tokens: int) -> MagicMock:
    """最小 config mock：get_effective_params 返回固定参数"""
    fake_cfg = MagicMock()
    fake_cfg.get_effective_params = lambda mt, mode="mixed": {
        "temperature": 0.7, "max_tokens": max_tokens, "top_p": 0.9,
    }
    return fake_cfg


class _SessionShim:
    """最小 session：仅 helper 所需属性（发送前护栏 / max_tokens 钳制单测用）"""

    def __init__(self, ctx: SessionContext):
        self.context = ctx


# ════════════════════════════════════════════════════════════
# 1. solve_token_budget：按实际请求输出求解输入预算
# ════════════════════════════════════════════════════════════

class TestSolveTokenBudget:
    def test_incident_case_150k_window_65536_out(self):
        """事故案例：150K 窗口 + 65536 输出 → 输入预算 81464（< 旧 0.8 基线 120000）"""
        inb, out = solve_token_budget(150000, 65536)
        assert out == 65536
        assert inb == 150000 - 65536 - 3000  # margin = 2% = 3000
        assert inb + out + 3000 <= 150000
        # 比旧固定 0.8 基线更积极：事故的 84465 输入现在会触发裁剪
        assert inb < 150000 * 0.8
        assert 84465 > inb
        # 下限保证基本工作空间
        assert inb >= max(2048, int(150000 * 0.10))

    def test_1m_window_131072_out(self):
        """1M 窗口（未配置默认）+ 131072 输出 → 预算比旧 0.8 基线更精确（不多裁）"""
        inb, out = solve_token_budget(1048576, 131072)
        margin = max(1024, int(1048576 * 0.02))
        assert out == 131072  # 131072 < 80% 窗口 → 不钳制
        assert inb + out + margin <= 1048576
        assert inb > 1048576 * 0.8

    def test_requested_over_80pct_clamped_to_50pct(self):
        """请求输出 > 80% 窗口 → 钳制到 50%（原值数学上无法与输入共存）"""
        inb, out = solve_token_budget(150000, 200000)
        margin = max(1024, int(150000 * 0.02))
        assert out == 75000
        assert inb + out + margin <= 150000

    def test_unknown_output_uses_20pct_baseline(self):
        """max_tokens 未知（0）→ 20% 基线（旧行为，保守不变）"""
        inb, out = solve_token_budget(150000, 0)
        margin = max(1024, int(150000 * 0.02))
        assert out == 30000
        assert inb + out + margin <= 150000

    def test_tiny_window_reclamp(self):
        """极小窗口：下限介入导致总和超窗口 → 收缩输出，恒保证 总和 ≤ 窗口"""
        inb, out = solve_token_budget(4096, 100000)
        margin = max(1024, int(4096 * 0.02))
        assert inb + out + margin <= 4096
        assert inb >= 2048 and out >= 1024

    def test_invalid_window_fallback(self):
        """max_ctx ≤ 0 → 128K 保守兜底，不变式仍成立"""
        inb, out = solve_token_budget(0, 0)
        margin = max(1024, int(128000 * 0.02))
        assert inb + out + margin <= 128000


# ════════════════════════════════════════════════════════════
# 2. _parse_context_overflow：400 错误体解析
# ════════════════════════════════════════════════════════════

class TestParseContextOverflow:
    def test_incident_string(self):
        """事故原文：三个关键字段全部解析出"""
        info = _parse_context_overflow(INCIDENT_ERR)
        assert info is not None
        assert info["max_ctx"] == 150000
        assert info["requested_out"] == 65536
        assert info["prompt_tokens"] == 84465

    def test_generic_400_overflow_signature(self):
        """网关/SDK 只透传通用措辞 → 识别为溢出（字段 None，自愈按配置兜底）"""
        info = _parse_context_overflow("Error code: 400 - maximum context length exceeded")
        assert info is not None
        assert info["max_ctx"] is None
        assert info["requested_out"] is None
        assert info["prompt_tokens"] is None

    def test_gateway_code_variants(self):
        for s in ("context_length_exceeded: prompt too long", "HTTP 400: prompt is too long"):
            assert _parse_context_overflow(s) is not None

    def test_non_overflow_returns_none(self):
        """非溢出错误（RC 回传 400 / 连接错误 / 空串）不得误判"""
        assert _parse_context_overflow("") is None
        assert _parse_context_overflow("API connection error: timeout") is None
        rc_err = (
            "Error code: 400 - {'error': {'message': 'The reasoning_content in the "
            "thinking mode must be passed back to the API.', 'code': 400}}"
        )
        assert _parse_context_overflow(rc_err) is None


# ════════════════════════════════════════════════════════════
# 3. _request_max_tokens：请求 max_tokens 钳制
# ════════════════════════════════════════════════════════════

class TestRequestMaxTokens:
    def test_clamped_to_solver_cap(self):
        """配置输出 > 求解上限 → 钳制到上限（150K 窗口场景的关键防线）"""
        ctx = SessionContext()
        ctx._output_cap = 65536
        assert _request_max_tokens(_SessionShim(ctx), {"max_tokens": 131072}) == 65536

    def test_small_config_untouched(self):
        ctx = SessionContext()
        ctx._output_cap = 65536
        assert _request_max_tokens(_SessionShim(ctx), {"max_tokens": 8192}) == 8192

    def test_missing_config_uses_cap(self):
        """配置缺失/0 → 发送求解上限而非"不限"（防输出侧无界增长）"""
        ctx = SessionContext()
        ctx._output_cap = 65536
        assert _request_max_tokens(_SessionShim(ctx), {"max_tokens": 0}) == 65536

    def test_no_cap_falls_back_to_config(self):
        """求解无上限（不可解）→ 回退配置值（原行为）"""
        ctx = SessionContext()
        ctx._output_cap = 0
        assert _request_max_tokens(_SessionShim(ctx), {"max_tokens": 4096}) == 4096

    def test_no_cap_no_config_returns_none(self):
        ctx = SessionContext()
        assert _request_max_tokens(_SessionShim(ctx), {}) is None


# ════════════════════════════════════════════════════════════
# 4. _ensure_within_output_budget：发送前护栏
# ════════════════════════════════════════════════════════════

class TestPresendGuard:
    def _ctx(self, **kw) -> SessionContext:
        ctx = SessionContext(model="m", supports_reasoning=False)
        ctx.max_context_tokens = 150000
        ctx._output_cap = 65536
        ctx._loop_trim_done = True
        for k, v in kw.items():
            setattr(ctx, k, v)
        return ctx

    def test_guard_fires_on_overflow_estimate(self):
        """真实输入 84465：84465+65536=150001 ≥ 窗口 → 强制重裁 + 置摘要标志"""
        ctx = self._ctx(_last_request_prompt_tokens=84465, messages=[{"role": "user", "content": "x"}])
        _ensure_within_output_budget(_SessionShim(ctx))
        assert ctx._loop_trim_done is False  # 重置"首建即定型" → 下次构建执行完整裁剪
        assert ctx._loop_max_ratio >= 84465 / 150000 - 1e-9
        assert ctx._token_exhausted is True  # 合计已超窗口 → 下一轮强制增量 LLM 摘要

    def test_guard_noop_when_within_budget(self):
        """未越线 → 零成本 no-op（保持缓存友好，不破坏裁剪定型）"""
        ctx = self._ctx(_last_request_prompt_tokens=40000, messages=[{"role": "user", "content": "x"}])
        _ensure_within_output_budget(_SessionShim(ctx))
        assert ctx._loop_trim_done is True
        assert ctx._token_exhausted is False


# ════════════════════════════════════════════════════════════
# 5. build_api_messages：记录输出上限 + 按输出感知预算更早裁剪
# ════════════════════════════════════════════════════════════

class TestBuildOutputAwareBudget:
    def test_records_output_cap_and_trims_to_budget(self, monkeypatch):
        """150K 窗口 + 65536 输出：预算 81464（< 旧 120000）→ 大历史裁到预算内"""
        monkeypatch.setattr("tea_agent.config.get_config", lambda: _fake_config(65536))
        ctx = SessionContext(model="test-model", enable_thinking=False, supports_reasoning=False)
        ctx.max_context_tokens = 150000
        for _i in range(300):  # ~131k tokens：越过新预算（旧 0.8 基线也会裁，但新预算更紧）
            ctx.messages.append({"role": "user", "content": "Q" * 200})
            ctx.messages.append({"role": "assistant", "content": "A" * 500})
            ctx.messages.append({"role": "tool", "content": "R" * 1000})
        sess = _make_session_from_ctx(ctx)
        result = sess._build_api_messages()

        budget, out_cap = solve_token_budget(150000, 65536)
        assert out_cap == 65536 and budget < 150000 * 0.8
        # 构建记录求解器输出上限（工具循环据此钳制请求 max_tokens）
        assert ctx._output_cap == out_cap
        # 裁剪后总量 ≤ 输入预算（旧 0.8 基线 120000 不保证：84465+65536 > 150000）
        assert estimate_messages_tokens(result) <= budget
        # 最近轮次保留（过滤末尾自动注入的动态上下文，对齐 test_onlinesession 约定）
        real_msgs = [m for m in result
                     if not (m.get("role") == "user"
                             and str(m.get("content", "")).startswith("[动态上下文"))]
        last_user = [m for m in real_msgs if m.get("role") == "user"]
        assert last_user and str(last_user[-1]["content"]).startswith("Q")
        assert ctx._loop_trim_done is True
        sess.close()

    def test_emergency_budget_consumed_and_deep_trim(self, monkeypatch):
        """400 自愈的一次性紧急预算（真实输入 84465 → 腰斩 42232）→ 本次构建裁得更深"""
        monkeypatch.setattr("tea_agent.config.get_config", lambda: _fake_config(65536))
        ctx = SessionContext(model="test-model", enable_thinking=False, supports_reasoning=False)
        ctx.max_context_tokens = 150000
        for _i in range(100):  # ~44k tokens：超紧急 42232、低于常规 81464
            ctx.messages.append({"role": "user", "content": "Q" * 200})
            ctx.messages.append({"role": "assistant", "content": "A" * 500})
            ctx.messages.append({"role": "tool", "content": "R" * 1000})
        emergency = max(2048, int(84465 * 0.5))  # 42232（_apply_context_overflow_recovery 所设）
        ctx._emergency_input_budget = emergency
        sess = _make_session_from_ctx(ctx)
        result = sess._build_api_messages()

        assert ctx._emergency_input_budget == 0  # 用后即焚
        assert ctx._loop_max_ratio >= 1.0 - 1e-9  # 紧急 → 直接满水位（Tier3）
        assert ctx._token_exhausted is True       # 下一轮强制 LLM 增量摘要
        assert estimate_messages_tokens(result) <= emergency
        sess.close()


# ════════════════════════════════════════════════════════════
# 6. execute_tool_loop：400 溢出自愈（修正窗口 + 激进压缩 + 钳制重试）
# ════════════════════════════════════════════════════════════

class TestExecuteToolLoopOverflowRecovery:
    def _make_session(self) -> OnlineToolSession:
        mock_tk = MagicMock()
        mock_tk.meta_map = {}
        mock_tk.call_tool.return_value = "mock_result"
        mock_tk.get_config.return_value = None
        sess = OnlineToolSession(
            toolkit=mock_tk, api_key="sk-test", api_url="https://api.test.com/v1",
            model="test-model", enable_thinking=False, storage=None,
            no_stream_chunk=True,
        )
        sess._build_api_messages = MagicMock(return_value=[{"role": "user", "content": "test"}])
        sess.api = MagicMock()
        sess.api.create_chat_stream.return_value = None
        sess._process_stream_with_reasoning = MagicMock(return_value=("Done", [], ""))
        sess.tools_comp = MagicMock()
        return sess

    def test_overflow_self_heal_then_success(self, monkeypatch):
        """首次 400 溢出 → 自愈（窗口 0→150K、紧急预算、钳制 max_tokens）→ 重试成功"""
        monkeypatch.setattr("tea_agent.config.get_config", lambda: _fake_config(65536))
        sess = self._make_session()
        ctx = sess.context
        ctx.max_context_tokens = 0  # 误配（未配置 → 默认 1M）vs 模型实际 150K
        ctx.messages = [{"role": "user", "content": "test"}]

        calls: list[dict] = []

        def fake_stream(api_messages, tools, **kw):
            calls.append(kw)
            if len(calls) == 1:
                raise Exception(INCIDENT_ERR)
            return None  # 第二次调用成功（流处理已 mock）

        sess.api.create_chat_stream.side_effect = fake_stream

        notes: list[str] = []
        result = execute_tool_loop(sess, {"msg": "test", "callback": notes.append})

        # 自愈成功：最终回复无 API 错误
        assert "API调用错误" not in result["full_reply"]
        assert "Done" in result["full_reply"]
        assert len(calls) >= 2  # 失败 → 自愈 → 重试
        # 1) 窗口修正：0 → 150000（错误揭示的真实窗口）
        assert ctx.max_context_tokens == 150000
        # 2) 一次性紧急输入预算 = 真实输入腰斩（42232）
        assert ctx._emergency_input_budget == max(2048, int(84465 * 0.5))
        # 3) 输出上限置位（65536 ≤ 80% 窗口 → 原样保留）；实际请求 max_tokens 与之对齐
        assert ctx._output_cap == 65536
        assert all(c.get("max_tokens") == 65536 for c in calls)
        # 4) 单调 clamp 顶满（强制最深裁剪档）+ 下一轮强制增量摘要
        assert ctx._loop_max_ratio >= 1.0 - 1e-9
        assert ctx._token_exhausted is True
        # 5) 用户获知自愈
        assert any("上下文溢出" in n for n in notes)
        sess.close()

    def test_overflow_recovery_exhausted_surfaces_hint(self, monkeypatch):
        """自愈用尽后再次溢出 → 返回错误并附可操作的处置提示"""
        monkeypatch.setattr("tea_agent.config.get_config", lambda: _fake_config(65536))
        sess = self._make_session()
        ctx = sess.context
        ctx.max_context_tokens = 150000  # 窗口已正确；裁剪手段用尽仍溢出
        ctx.messages = [{"role": "user", "content": "test"}]

        sess.api.create_chat_stream.side_effect = Exception(INCIDENT_ERR)  # 恒溢出

        notes: list[str] = []
        result = execute_tool_loop(sess, {"msg": "test", "callback": notes.append})

        assert "API调用错误" in result["full_reply"]
        assert "上下文溢出自愈后仍失败" in result["full_reply"]
        assert len(notes) >= 1  # 至少一次自愈提示
        sess.close()
