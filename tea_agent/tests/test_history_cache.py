"""
历史消息构造缓存友好性回归测试（DeepSeek 前缀缓存）。

覆盖审查报告中的关键修复：
- S1: 工具循环内相邻请求的公共前缀必须逐字节相同（_progressive_trim 幂等守卫）
- S2: tool 结果入库即压缩定型（add_tool_result / BaseChatSession.add_tool_result）
- A2: system prompt 不重复注入 OS 文本（environment 片段排除）
- S3: 长期记忆移至尾部动态上下文，L3 块只含低频摘要
- A6: 无 _b64_cache/images 内部字段泄漏到 API 消息
"""


from tea_agent.basesession import BaseChatSession
from tea_agent.session.context import SessionContext
from tea_agent.session.history_builder import build_api_messages


class _Sess(BaseChatSession):
    def chat_stream(self, msg, callback):
        return "", False

    @property
    def messages(self):
        return self.context.messages if hasattr(self, "context") else []

    @messages.setter
    def messages(self, v):
        if hasattr(self, "context"):
            self.context.messages = v


def _make_session() -> tuple[SessionContext, _Sess]:
    ctx = SessionContext()
    ctx.model = "deepseek-v3"
    ctx.supports_reasoning = True
    ctx.supports_vision = False
    ctx.max_context_tokens = 128000
    ctx.messages = [{"role": "system", "content": "system prompt"}]
    ctx._injected_os_info_text = "[系统环境信息]\n操作系统: Windows-10-AMD64\n---稳定---"
    ctx._semantic_summary = "用户偏好：修改后立即回复。"
    ctx._tool_chain_summary = "历史工具链：toolkit_file→toolkit_edit。"
    ctx._level2 = [{"user": "什么是缓存", "assistant": "前缀缓存是……", "kind": "full"}]
    sess = _Sess(model="deepseek-v3")
    sess.context = ctx
    return ctx, sess


def _common_prefix_len(a: list[dict], b: list[dict]) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


class TestPrefixStability:
    def test_tool_loop_prefix_byte_identical(self):
        """S1: 工具循环内相邻请求的公共前缀逐字节相同（仅允许末尾新增）。

        动态上下文追加在**消息末尾**（对齐 DSH append-only），因此允许
        最后一条动态消息随工具结果增长而移位；其之前的 L1 历史必须逐字节相同。
        """
        ctx, sess = _make_session()
        sp = "你是一个智能助手"
        sess.add_user_message("帮我审查代码并修复")

        reqs = []
        ctx.messages.append({
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "toolkit_file", "arguments": '{"action": "read"}'}}],
        })
        reqs.append(build_api_messages(ctx, sp))

        sess.add_tool_result("c1", "文件内容 " * 1000)
        ctx.messages.append({
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c2", "type": "function",
                            "function": {"name": "toolkit_edit", "arguments": '{"file": "a.py", "action": "replace_text"}'}}],
        })
        reqs.append(build_api_messages(ctx, sp))

        sess.add_tool_result("c2", "修改成功")
        sess.add_assistant_message("已完成修复。")
        reqs.append(build_api_messages(ctx, sp))

        for i in range(len(reqs) - 1):
            n = _common_prefix_len(reqs[i], reqs[i + 1])
            # 允许最后一条（尾部动态上下文）移位；其余前缀必须逐字节相同
            assert n >= len(reqs[i]) - 1, (
                f"Req{i + 1}->Req{i + 2} 公共前缀被改写: {n}/{len(reqs[i])} "
                f"首处不同: {reqs[i][n] if n < len(reqs[i]) else 'EOF'}"
            )

    def test_tool_result_compressed_at_insert(self):
        """S2: tool 结果入库即压缩到阈值以内，永不触发占位符翻转。"""
        ctx, sess = _make_session()
        sess.add_user_message("读文件")
        sess.add_tool_result("t1", "x" * 10000)
        tool_msg = next(m for m in ctx.messages if m.get("role") == "tool")
        assert len(tool_msg["content"]) <= 65536 + 200
        assert not tool_msg["content"].startswith("[工具结果已省略")


class TestSystemPromptStable:
    def test_os_info_not_duplicated(self):
        """A2: OS 文本在 system prompt 中只出现一次（environment 片段被排除）。"""
        ctx, sess = _make_session()
        msgs = build_api_messages(ctx, "测试系统提示词")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"].count("系统环境信息") == 1

    def test_dynamic_fragments_excluded(self):
        """缓存友好：system prompt 不含每轮必变的动态片段。"""
        ctx, sess = _make_session()
        msgs = build_api_messages(ctx, "测试系统提示词")
        assert "<token_budget>" not in msgs[0]["content"]
        assert "<current_time>" not in msgs[0]["content"]
        assert "<session_budget>" not in msgs[0]["content"]


class TestMemoryPlacement:
    def test_l3_without_memory_dynamic_with_memory(self):
        """S3: L3 块不含记忆；记忆在尾部动态上下文（**追加在消息末尾**）。

        缓存友好（对齐 DSH append-only）：动态上下文（技能/TODO/记忆）随用户
        消息边界重算，必须追加在请求末尾 —— 若插在 L1 历史之前，内容变化会让
        其后全部 L1 历史前缀缓存失效（实测命中率 99% → ~62%，见
        scripts/diag_cache_prefix.py）。
        """
        ctx, sess = _make_session()
        # 模拟 inject_memories pipeline 步骤（pos=20）已注入记忆
        ctx._injected_memories_text = "记忆：用户偏好直接修改而非仅输出文本。"
        sess.add_user_message("你好")
        msgs = build_api_messages(ctx, "测试")
        l3_block = msgs[1]  # system 之后是 L3
        assert "## 长期记忆" not in (l3_block.get("content", "") or "")
        # 仅检查非 system 消息（system 的 AGENTS.md 片段本身可能含"长期记忆"字样）
        dyn_texts = [m.get("content", "") for m in msgs[1:] if isinstance(m.get("content"), str)]
        assert any("## 长期记忆" in t for t in dyn_texts)
        # 动态上下文必须是**最后一条**消息（追加在末尾，历史前缀不受影响）
        assert "## 长期记忆" in (msgs[-1].get("content", "") or "")
        assert msgs[-1]["role"] == "user"


class TestNoInternalFieldLeak:
    def test_no_internal_fields_in_api_messages(self):
        """A6: _b64_cache / images 内部字段不泄漏到 API 消息。"""
        ctx, sess = _make_session()
        ctx.supports_vision = True
        sess.add_user_message("看图")
        ctx.messages[-1]["images"] = []  # 无真实图片文件时保持空
        msgs = build_api_messages(ctx, "测试")
        for m in msgs:
            assert "_b64_cache" not in m
            assert "images" not in m


class TestCacheReport:
    def test_format_cache_hit_rate(self):
        """cache_report 命中率格式化。"""
        from tea_agent.session.cache_report import cache_hit_rate_number, format_cache_hit_rate

        assert format_cache_hit_rate({"prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}) == ""
        assert format_cache_hit_rate({}) == ""
        s = format_cache_hit_rate({"prompt_cache_hit_tokens": 3500, "prompt_cache_miss_tokens": 500})
        assert "87.5%" in s and "3,500" in s and "500" in s
        assert cache_hit_rate_number({"prompt_cache_hit_tokens": 3500, "prompt_cache_miss_tokens": 500}) == 87.5
        assert cache_hit_rate_number({}) is None
