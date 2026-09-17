"""数组 content 被端点拒绝的 400 → 当轮自愈（且**不得**永久降级视觉）回归测试。

背景（2026-09-17 生产日志，逐字）：

    API调用失败: model=deepseek-flash, iteration=1,
    detail=BadRequestError: Error code: 400 - {'error': {'message':
      'Failed to deserialize the JSON body into the target type:
       messages[175]: invalid type: sequence, expected a string at line 1 column 448698'}}

该 400 表示"某条消息里出现了本该是字符串的数组"。`to_multimodal` 是唯一会产出数组的
路径，因此按同一条自愈分支处理：本会话关 vision → 重建消息（数组拼回纯文本）→ 重试一次，
把"整轮硬失败"降级为"本轮丢图但有答案"。

**关键边界（2026-09-17 实测修正）**：不能由这条 400 推断"端点不支持视觉" —— 实测
`deepseek-flash` 官方端点接受 `content: [{type:text},{type:image_url}]`（HTTP 200，
图片 token 正常计入，prompt_tokens 221 vs 纯文本 35）。所以：

1. 自愈只作用于**本回合**（session.context.supports_vision=False）；
2. **不得**做端点/模型级永久降级 —— 否则一次误判会把一个支持视觉的端点的图片永久丢掉。

第 2 条由 `test_next_session_still_sends_multimodal` 作为反向契约钉住。
"""

from unittest.mock import MagicMock

import pytest

from tea_agent.onlinesession import OnlineToolSession
from tea_agent.session.context import SessionContext
from tea_agent.session.history_builder import build_api_messages
from tea_agent.session.tool_loop_runner import (
    _is_multimodal_content_rejected,
    _log_content_type_diagnostic,
    _parse_messages_index,
    execute_tool_loop,
)

# ── 生产日志里的真实 400（逐字，仅去掉最外层 logger 前缀）──
INCIDENT_ERR = (
    "Error code: 400 - {'error': {'message': 'Failed to deserialize the JSON body into "
    "the target type: messages[175]: invalid type: sequence, expected a string at line 1 "
    "column 448698', 'type': 'invalid_request_error', 'param': None, "
    "'code': 'invalid_request_error'}}"
)

# 其他类型 400：绝不能被当成多模态问题（否则会把正常能力误降级）
OVERFLOW_ERR = (
    "Error code: 400 - {'error': {'message': \"This model's maximum context length is "
    "150000 tokens. However, you requested 65536 output tokens and your prompt contains "
    "at least 84465 input tokens.\", 'type': 'BadRequestError', 'code': 400}}"
)
RC_ERR = (
    "Error code: 400 - {'error': {'message': 'The reasoning_content in the thinking mode "
    "must be passed back to the API.', 'type': 'invalid_request_error', 'code': 400}}"
)

ENDPOINT = "https://api.deepseek.com"
MODEL = "deepseek-flash"
DATA_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="


def _ctx(*, supports_vision: bool = True, images: list | None = None) -> SessionContext:
    ctx = SessionContext(model=MODEL, supports_reasoning=False, supports_vision=supports_vision)
    ctx.max_context_tokens = 1_000_000
    ctx.client = MagicMock(base_url=ENDPOINT)
    ctx.messages = [{"role": "system", "content": "sys"}]
    user: dict = {"role": "user", "content": "看图"}
    if images:
        user["images"] = images
    ctx.messages.append(user)
    return ctx


def _find_image_message(msgs: list[dict]) -> dict:
    """取出带图的那条用户消息（末尾还会有动态上下文注入的 user 消息）。"""
    for m in msgs:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, list) or "看图" in str(content):
            return m
    raise AssertionError(f"未找到带图用户消息：{msgs}")


def _fake_config(max_tokens: int = 8192) -> MagicMock:
    fake_cfg = MagicMock()
    fake_cfg.get_effective_params = lambda mt, mode="mixed": {
        "temperature": 0.7,
        "max_tokens": max_tokens,
        "top_p": 0.9,
    }
    return fake_cfg


def _make_loop_session(ctx: SessionContext) -> OnlineToolSession:
    mock_tk = MagicMock()
    mock_tk.meta_map = {}
    mock_tk.call_tool.return_value = "mock_result"
    mock_tk.get_config.return_value = None
    sess = OnlineToolSession(
        toolkit=mock_tk,
        api_key="sk-test",
        api_url=ENDPOINT,
        model=MODEL,
        enable_thinking=False,
        storage=None,
        no_stream_chunk=True,
        supports_vision=True,
        supports_reasoning=False,
    )
    sess.context = ctx  # 用带 client/端点信息的 ctx
    sess.system_prompt = "You are a test assistant."
    sess._build_api_messages = MagicMock(return_value=[{"role": "user", "content": "test"}])
    sess.api = MagicMock()
    sess._process_stream_with_reasoning = MagicMock(return_value=("Done", [], ""))
    sess.tools_comp = MagicMock()
    return sess


# ════════════════════════════════════════════════════════════
# 1. 错误分类：只认"序列当字符串用"的签名
# ════════════════════════════════════════════════════════════


class TestSequenceContentErrorClassifier:
    def test_matches_incident_error(self):
        assert _is_multimodal_content_rejected(INCIDENT_ERR) is True

    @pytest.mark.parametrize(
        "err",
        [
            "messages[1]: invalid type: sequence, expected a string",
            '{"error": {"message": "content must be a string"}}',
            "invalid type: sequence, expected a string at line 1 column 42",
        ],
    )
    def test_matches_variants(self, err):
        assert _is_multimodal_content_rejected(err) is True

    @pytest.mark.parametrize(
        "err",
        [
            OVERFLOW_ERR,
            RC_ERR,
            "",
            "Error code: 400 - invalid tool_calls format",
            "Error code: 401 - Authentication Fails",
        ],
    )
    def test_does_not_match_other_errors(self, err):
        assert _is_multimodal_content_rejected(err) is False


# ════════════════════════════════════════════════════════════
# 2. 现场诊断：把 400 给的下标翻译成 role + 字段类型
# ════════════════════════════════════════════════════════════


class TestPayloadDiagnostic:
    def test_parse_index(self):
        assert _parse_messages_index(INCIDENT_ERR) == 175
        assert _parse_messages_index("messages[0]: whatever") == 0
        assert _parse_messages_index("no index here") is None
        assert _parse_messages_index("") is None

    def test_logs_role_and_fields_of_offending_index(self, caplog):
        """payload[2] 是 assistant 且 arguments 是数组 → 日志必须点名下标/角色/字段。"""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "t", "arguments": ["a"]}}],
            },
        ]
        with caplog.at_level("WARNING", logger="session.tool_loop_runner"):
            _log_content_type_diagnostic(msgs, "messages[2]: invalid type: sequence, expected a string")
        text = caplog.text
        assert "messages[2]" in text
        assert "role=assistant" in text
        assert "tool_calls.arguments=list" in text

    def test_logs_clean_payload_honestly(self, caplog):
        """payload 干净时也要说清楚（别让下一次排查又扑空）。"""
        msgs = [{"role": "user", "content": "hi"}]
        with caplog.at_level("WARNING", logger="session.tool_loop_runner"):
            _log_content_type_diagnostic(msgs, INCIDENT_ERR)
        assert "payload 共 1 条" in caplog.text
        assert "messages[175]" in caplog.text  # 下标越界也要如实记录
        assert "（无 —— payload 里没有类型异常的字段）" in caplog.text

    def test_never_raises_on_broken_input(self):
        _log_content_type_diagnostic(None, "messages[3]: invalid type: sequence")  # type: ignore[arg-type]
        _log_content_type_diagnostic([{"role": "user", "content": ["not", "blocks"]}], "")


# ════════════════════════════════════════════════════════════
# 3. 反向契约：不做端点级永久降级（实测端点支持视觉）
# ════════════════════════════════════════════════════════════


class TestNoPermanentVisionDemotion:
    def test_declared_vision_still_sends_image_blocks(self):
        """只要配置声明支持视觉，就该照常发 image_url 数组（官方端点实测接受）。"""
        msgs = build_api_messages(_ctx(images=[DATA_URL]), "sys")
        content = _find_image_message(msgs)["content"]
        assert isinstance(content, list), "配置声明支持视觉时不应擅自改成纯文本"
        assert any(p.get("type") == "image_url" for p in content)

    def test_next_session_still_sends_multimodal(self, monkeypatch):
        """一次 400 之后，**新会话**（新 ctx/新 session）仍按配置发数组。

        （旧实现把 (端点,模型) 记忆为"仅文本"，会永久吞掉图片 —— 该行为已撤销。）
        """
        monkeypatch.setattr("tea_agent.config.get_config", lambda: _fake_config())
        ctx1 = _ctx(images=[DATA_URL])
        sess1 = _make_loop_session(ctx1)
        sess1.api.create_chat_stream.side_effect = [Exception(INCIDENT_ERR), None]
        execute_tool_loop(sess1, {"msg": "看图", "callback": lambda x: None})
        assert ctx1.supports_vision is False, "本会话应已关 vision"
        sess1.close()

        # 同一端点的下一个会话：配置声明仍然生效 → 继续发多模态数组
        msgs = build_api_messages(_ctx(images=[DATA_URL]), "sys")
        assert isinstance(_find_image_message(msgs)["content"], list)


# ════════════════════════════════════════════════════════════
# 4. execute_tool_loop：当轮自愈
# ════════════════════════════════════════════════════════════


class TestExecuteToolLoopVisionHeal:
    def test_sequence_content_400_self_heals_this_turn(self, monkeypatch):
        """首次 400 → 本会话关 vision + 重建消息 + 重试成功（回合不再硬失败）。"""
        monkeypatch.setattr("tea_agent.config.get_config", lambda: _fake_config())
        ctx = _ctx(images=[DATA_URL])
        sess = _make_loop_session(ctx)
        calls: list = []

        def fake_stream(api_messages, tools, **kw):
            calls.append(api_messages)
            if len(calls) == 1:
                raise Exception(INCIDENT_ERR)
            return None  # 第二次成功（流处理已 mock）

        sess.api.create_chat_stream.side_effect = fake_stream
        notes: list[str] = []
        result = execute_tool_loop(sess, {"msg": "看图", "callback": notes.append})

        assert "API调用错误" not in result["full_reply"], result["full_reply"]
        assert "Done" in result["full_reply"]
        assert len(calls) >= 2, "未重试"
        assert ctx.supports_vision is False, "未关闭本会话 vision"
        assert sess._build_api_messages.call_count >= 2, "未重建消息"
        assert any("多模态" in n for n in notes), notes
        sess.close()

    def test_other_400_is_not_treated_as_vision_problem(self, monkeypatch):
        """非多模态 400 不得误降级 vision（宁可报错，不可静默丢图能力）。"""
        monkeypatch.setattr("tea_agent.config.get_config", lambda: _fake_config())
        ctx = _ctx(images=[DATA_URL])
        sess = _make_loop_session(ctx)
        sess.api.create_chat_stream.side_effect = Exception("Error code: 400 - {'error': {'message': 'invalid tool_calls format'}}")

        notes: list[str] = []
        result = execute_tool_loop(sess, {"msg": "看图", "callback": notes.append})

        assert "API调用错误" in result["full_reply"]
        assert ctx.supports_vision is True, "非多模态错误误关了 vision"
        sess.close()

    def test_heal_disabled_when_no_vision_declared(self, monkeypatch):
        """未声明 vision（本来就不发数组）→ 该 400 按原样报错，不当自愈对象。"""
        monkeypatch.setattr("tea_agent.config.get_config", lambda: _fake_config())
        ctx = _ctx(supports_vision=False, images=[DATA_URL])
        sess = _make_loop_session(ctx)
        sess.api.create_chat_stream.side_effect = Exception(INCIDENT_ERR)

        notes: list[str] = []
        result = execute_tool_loop(sess, {"msg": "看图", "callback": notes.append})

        assert "API调用错误" in result["full_reply"]
        sess.close()
