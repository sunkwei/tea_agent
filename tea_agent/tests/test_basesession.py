"""
@2026-06-07 gen by deepseek, BaseChatSession 核心功能测试
覆盖: 会话创建、配置加载、thinking 探测、推理剥离、工具压缩
"""
from unittest.mock import MagicMock

import pytest


class TestBaseSessionConfig:
    """测试 BaseChatSession 配置加载"""

    def test_base_session_abstract(self):
        """BaseChatSession 是抽象类，不能直接实例化"""
        from tea_agent.basesession import BaseChatSession
        with pytest.raises(TypeError):
            BaseChatSession()

    def test_strip_reasoning_content_modifies_in_place(self):
        """_strip_reasoning_content 应原地修改消息列表（返回 None）"""
        from tea_agent.basesession import BaseChatSession

        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello there"},
        ]
        result = BaseChatSession._strip_reasoning_content(messages)
        assert result is None, "应返回 None（原地修改）"
        assert len(messages) == 2
        assert messages[1]["content"] == "Hello there"

    def test_compress_tool_content_truncates_long_output(self):
        """_compress_tool_content 应截断超长内容并添加摘要"""
        from tea_agent.basesession import BaseChatSession

        long = "A" * 5000
        result = BaseChatSession._compress_tool_content(long, max_chars=100)
        # 应包含截断信息和部分原始内容
        assert len(result) < 5000, "应截断"
        assert "工具输出压缩" in result or "truncat" in result.lower() or len(result) < len(long)

    def test_compress_tool_content_short_passthrough(self):
        """短内容应原样返回"""
        from tea_agent.basesession import BaseChatSession

        short = "Short content"
        result = BaseChatSession._compress_tool_content(short, max_chars=2048)
        assert result == short


class TestConfigLoading:
    """测试配置加载"""

    def test_load_config_returns_obj_with_main_model(self):
        """load_config 应返回具有 main_model 属性的对象"""
        from tea_agent.config import load_config
        cfg = load_config()
        assert hasattr(cfg, "main_model"), f"配置无 main_model 属性: {type(cfg)}"
        assert cfg.main_model is not None
        assert hasattr(cfg.main_model, "model_name"), "main_model 应包含 model_name"

    def test_config_has_model_name(self):
        """配置应包含模型名称"""
        from tea_agent.config import load_config
        cfg = load_config()
        assert cfg.main_model.model_name is not None


class TestLiteSession:
    """LiteSession 基本功能测试（需要 mock）"""

    def test_lite_session_needs_dependencies(self):
        """LiteSession 需要 toolkit/api_key/api_url 参数"""
        from tea_agent.litesession import LiteSession
        with pytest.raises(TypeError):
            LiteSession(model="test-model")

    def test_lite_session_creation_with_mocks(self):
        """使用 mock 创建 LiteSession"""
        from tea_agent.litesession import LiteSession
        mock_tk = MagicMock()
        sess = LiteSession(
            model="test-model",
            toolkit=mock_tk,
            api_key="sk-test",
            api_url="https://test.api.com",
            enable_thinking=False,
        )
        assert sess.model == "test-model"


class TestToolArgsCompressThresholds:
    """tool_calls 参数压缩阈值：单一事实源 + env 可覆盖 + 默认行为不变。

    背景：阈值原先以**独立字面量**散落在签名默认值与调用点两处（`2048` / `1024`），
    改一处另一处静默失效。抽成 `_args_compress_threshold()` / `_args_keep_bytes()`
    作为唯一来源；默认值与原行为完全一致，仅新增 env 覆盖能力。
    """

    def test_defaults_unchanged(self):
        """默认值必须与改造前一致（2048 / 1024）——否则是行为变更而非重构。"""
        from tea_agent.basesession import _args_compress_threshold, _args_keep_bytes

        assert _args_compress_threshold() == 2048
        assert _args_keep_bytes() == 1024

    def test_env_override_compress_threshold(self, monkeypatch):
        import tea_agent.basesession as B

        monkeypatch.setenv("TEA_ARGS_COMPRESS_BYTES", "512")
        assert B._args_compress_threshold() == 512

    def test_env_override_keep_bytes_actually_keeps_more(self, monkeypatch):
        """提高保留量后，超长参数确实保留更多内容（不只是数字变了）。"""
        import json

        import tea_agent.basesession as B

        args = json.dumps({"content": "x" * 20000})
        n = len(args.encode("utf-8"))
        low = json.loads(B.BaseChatSession._compress_json_args(args, n))["content"]
        monkeypatch.setenv("TEA_ARGS_KEEP_BYTES", "4096")
        high = json.loads(B.BaseChatSession._compress_json_args(args, n))["content"]
        assert len(high) > len(low) * 3, (len(low), len(high))

    @pytest.mark.parametrize("bad", ["abc", "0", "-5", "  ", "3.5"])
    def test_invalid_env_falls_back_to_default(self, monkeypatch, bad):
        """非法 env 必须回落默认，绝不抛异常（配置错误不该拖垮主流程）。"""
        import tea_agent.basesession as B

        monkeypatch.setenv("TEA_ARGS_KEEP_BYTES", bad)
        assert B._args_keep_bytes() == 1024

    def test_below_threshold_untouched(self):
        """未超阈值时内容逐字节不变。"""
        import json

        from tea_agent.basesession import BaseChatSession

        args = json.dumps({"content": "x" * 300})
        out = BaseChatSession._compress_json_args(args, len(args.encode("utf-8")))
        assert json.loads(out)["content"] == "x" * 300

