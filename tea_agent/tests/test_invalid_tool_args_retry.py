"""参数非法 tool_call 的「反馈自纠重试」回归测试。

背景（2026-09-28 生产案例）：一轮 batch 长参数（内嵌多行 Python 代码）流式
截断，修复链无法恢复 → 旧实现直接 return error=invalid_tool_call_args 终止
回合，模型零自纠机会，用户必须手动重发整轮操作。

契约（钉行为而非实现细节）：
1. 首个畸形轮不终止回合：注入含失败原因的 user 反馈，模型获得重发机会；
2. 重发成功 → 回合正常完成，结果无 error；
3. 连续畸形超上限（2 次自纠重试）→ 终止并返回 error=invalid_tool_call_args，
   告警文案含处置指引；
4. 自纠重试计入迭代预算（max_iterations 耗尽后不再额外请求模型）。
"""

from unittest.mock import MagicMock

from tea_agent.onlinesession import OnlineToolSession
from tea_agent.session.tool_loop_runner import execute_tool_loop

# 复刻生产日志中被丢弃的畸形参数形态（batch + 多行代码 + 截断）
_BAD_TC = [
    {
        "id": "call_bad_1",
        "name": "toolkit_exec",
        "arguments": ('{"action": "batch", "commands": [{"app": "python", "args": ["-c", "import pathlib\\ns=pathlib.Path(\'t'),
    }
]


def _make_session() -> OnlineToolSession:
    mock_tk = MagicMock()
    mock_tk.meta_map = {}
    mock_tk.call_tool.return_value = "mock_result"
    mock_tk.get_config.return_value = None
    sess = OnlineToolSession(
        toolkit=mock_tk,
        api_key="sk-test",
        api_url="https://api.test.com/v1",
        model="test-model",
        enable_thinking=False,
        storage=None,
        no_stream_chunk=True,
    )
    sess._build_api_messages = MagicMock(return_value=[{"role": "user", "content": "test"}])
    sess.api = MagicMock()
    sess.api.create_chat_stream.return_value = None
    sess.tools_comp = MagicMock()
    # 修复链输出：全部 tool_call 参数不可修复 → 返回空列表
    sess.tools_comp.parse_tool_calls_from_stream.return_value = []
    sess.context.messages = [{"role": "user", "content": "test"}]
    return sess


class TestInvalidToolArgsSelfCorrection:
    def test_malformed_round_retries_then_recovers(self):
        """契约1+2：畸形轮注入反馈 → 模型重发合法调用 → 回合正常完成"""
        sess = _make_session()
        # 第1轮返回畸形 tool_call；第2轮（收到反馈后）正常作答
        sess._process_stream_with_reasoning = MagicMock(
            side_effect=[
                ("", _BAD_TC, ""),
                ("重发自纠成功", [], ""),
            ]
        )

        notes: list[str] = []
        result = execute_tool_loop(sess, {"msg": "test", "callback": notes.append})

        # 回合正常完成：无 error、最终回复含恢复文本
        assert result.get("error") is None
        assert "重发自纠成功" in result["full_reply"]
        # 契约1：注入了含失败原因的 user 反馈（而非直接终止）
        feedback_msgs = [m for m in sess.context.messages if m.get("role") == "user" and "不是合法 JSON" in str(m.get("content", ""))]
        assert len(feedback_msgs) == 1
        # 反馈携带失败参数片段，模型可据此自纠
        assert "失败参数片段" in feedback_msgs[0]["content"]
        # 模型确实被再次请求（自纠轮发生）
        assert sess.api.create_chat_stream.call_count == 2
        sess.close()

    def test_persistent_malform_terminates_with_error(self):
        """契约3：连续畸形超上限 → 终止并返回可诊断 error"""
        sess = _make_session()
        sess._process_stream_with_reasoning = MagicMock(return_value=("", _BAD_TC, ""))

        notes: list[str] = []
        result = execute_tool_loop(sess, {"msg": "test", "callback": notes.append})

        assert result.get("error") == "invalid_tool_call_args"
        # 告警文案含处置指引（对齐旧实现的用户可见行为）
        assert "请重新发起该操作" in result["full_reply"]
        assert any("不是合法 JSON" in n for n in notes)
        # 初始轮 + 2 次自纠重试 = 3 次模型请求，不会无限重试
        assert sess.api.create_chat_stream.call_count == 3
        # 两次自纠反馈注入，第 3 次畸形才终止
        feedback_count = sum(1 for m in sess.context.messages if m.get("role") == "user" and "不是合法 JSON" in str(m.get("content", "")))
        assert feedback_count == 2
        sess.close()

    def test_retry_counts_against_iteration_budget(self):
        """契约4：自纠重试计入迭代预算（不会绕过 max_iterations 守卫）"""
        sess = _make_session()
        sess.max_iterations = 1
        sess._extra_iterations = 0
        sess._process_stream_with_reasoning = MagicMock(return_value=("", _BAD_TC, ""))

        notes: list[str] = []
        result = execute_tool_loop(sess, {"msg": "test", "callback": notes.append})

        # 预算耗尽：畸形轮消耗 1 次迭代后不再请求模型
        assert sess.api.create_chat_stream.call_count == 1
        assert result.get("error") is None  # 循环退出而非 error 终止
        sess.close()
