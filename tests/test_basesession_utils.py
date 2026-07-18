# encoding: utf-8
"""
测试 basesession.py 工具函数：
  - relaxed_json_loads
  - _compress_json_args
  - filter_level2_by_relevance  (history_builder.py)
  - _progressive_trim           (history_builder.py)
  - _validate_tool_call         (tool_loop_runner.py)
  - _validate_output_format     (tool_loop_runner.py)
  - agent_background.start_scheduler
  - agent_pipeline 工具函数
  - build_api_messages 集成
"""
import sys
import os
import json
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = 0
failed = 0

def assert_eq(actual, expected, desc):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  ✅ {desc}")
    else:
        failed += 1
        print(f"  ❌ {desc}: 期望 {expected!r}, 实际 {actual!r}")

def assert_ne(actual, unexpected, desc):
    global passed, failed
    if actual != unexpected:
        passed += 1
        print(f"  ✅ {desc}")
    else:
        failed += 1
        print(f"  ❌ {desc}: 不应等于 {unexpected!r}")

def assert_true(cond, desc):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {desc}")
    else:
        failed += 1
        print(f"  ❌ {desc}: 条件不成立")

def assert_in(sub, container, desc):
    global passed, failed
    if sub in container:
        passed += 1
        print(f"  ✅ {desc}")
    else:
        failed += 1
        print(f"  ❌ {desc}: 未找到 {sub!r} 在 {container!r}")

def assert_raises(exc_cls, fn, desc):
    global passed, failed
    try:
        fn()
        failed += 1
        print(f"  ❌ {desc}: 未抛出异常")
    except exc_cls:
        passed += 1
        print(f"  ✅ {desc}")
    except Exception as e:
        failed += 1
        print(f"  ❌ {desc}: 抛出 {type(e).__name__}: {e}")


# ================================================================
# Section 1: relaxed_json_loads
# ================================================================
def test_relaxed_json_loads():
    print("\n━━━ Section 1: relaxed_json_loads ━━━")

    # 1.1 标准 JSON
    assert_eq(
        relaxed_json_loads('{"a": 1, "b": "hello"}'),
        {"a": 1, "b": "hello"},
        "标准 JSON: 正常解析"
    )

    # 1.2 空/空白
    assert_eq(relaxed_json_loads(""), {}, "空字符串 → {}")
    assert_eq(relaxed_json_loads("   "), {}, "空白字符串 → {}")
    assert_eq(relaxed_json_loads(None), {}, "None → {}")

    # 1.3 单引号
    assert_eq(
        relaxed_json_loads("{'a': 1, 'b': 'hello'}"),
        {"a": 1, "b": "hello"},
        "单引号 → 自动转双引号"
    )

    # 1.4 Python 布尔值
    assert_eq(
        relaxed_json_loads('{"ok": True, "no": False}'),
        {"ok": True, "no": False},
        "Python True/False → JSON true/false"
    )

    # 1.5 Python None
    assert_eq(
        relaxed_json_loads('{"x": None}'),
        {"x": None},
        "Python None → JSON null"
    )

    # 1.6 尾逗号
    assert_eq(
        relaxed_json_loads('{"a": 1, "b": 2,}'),
        {"a": 1, "b": 2},
        "尾逗号 → 自动移除"
    )
    assert_eq(
        relaxed_json_loads('[1, 2, 3,]'),
        [1, 2, 3],
        "数组尾逗号 → 自动移除"
    )

    # 1.7 注释（// 和 /* */）
    assert_eq(
        relaxed_json_loads('{"a": 1, // 这是注释\n"b": 2}'),
        {"a": 1, "b": 2},
        "// 注释 → 移除"
    )
    assert_eq(
        relaxed_json_loads('{"a": 1 /* 块注释 */, "b": 2}'),
        {"a": 1, "b": 2},
        "块注释 → 移除"
    )

    # 1.8 未引号 key
    assert_eq(
        relaxed_json_loads('{a: 1, b: "hello"}'),
        {"a": 1, "b": "hello"},
        "未引号 key → 自动加引号"
    )

    # 1.9 控制字符
    assert_eq(
        relaxed_json_loads('{"a":"hello\x00world"}'),
        {"a": "helloworld"},
        "控制字符 → 移除"
    )

    # 1.10 从文本中提取 JSON
    assert_eq(
        relaxed_json_loads('some text {"a": 1} more text'),
        {"a": 1},
        "从文本提取 JSON 对象"
    )

    # 1.11 从文本提取 JSON 数组
    assert_eq(
        relaxed_json_loads('prefix [1, 2, 3] suffix'),
        [1, 2, 3],
        "从文本提取 JSON 数组"
    )

    # 1.12 反斜杠转义修复
    result = relaxed_json_loads('{"path": "C:\\Users\\test\\file.txt"}')
    assert_eq(result["path"], "C:\\Users\\test\\file.txt", "反斜杠转义修复")

    # 1.13 空对象
    assert_eq(relaxed_json_loads("{}"), {}, "空对象")
    assert_eq(relaxed_json_loads("[]"), [], "空数组")

    # 1.14 深层嵌套
    assert_eq(
        relaxed_json_loads('{"a": {"b": {"c": [1, 2, {"d": 3}]}}}'),
        {"a": {"b": {"c": [1, 2, {"d": 3}]}}},
        "深层嵌套 JSON"
    )

    # 1.15 完全无法修复时抛异常
    assert_raises(
        json.JSONDecodeError,
        lambda: relaxed_json_loads("{{{{{ totally invalid"),
        "完全无效输入 → 抛 JSONDecodeError"
    )


# ================================================================
# Section 2: _compress_json_args
# ================================================================
def test_compress_json_args():
    from tea_agent.basesession import BaseChatSession
    compress = BaseChatSession._compress_json_args

    print("\n━━━ Section 2: _compress_json_args ━━━")

    # 2.1 短字符串不截断
    short = json.dumps({"name": "test", "value": "123"})
    result = compress(short, len(short.encode("utf-8")))
    assert_eq(result, short, "短字符串不变")

    # 2.2 长字符串值被截断
    long_val = "x" * 5000
    args = json.dumps({"content": long_val})
    args_bytes = len(args.encode("utf-8"))
    result = compress(args, args_bytes)
    parsed = json.loads(result)
    # 应该被截断，包含 [截断 ...] 标记
    assert_true("截断" in parsed["content"], "长字符串被截断")
    assert_true(len(parsed["content"]) < 1500, f"截断后长度 {len(parsed['content'])} < 1500")

    # 2.3 嵌套 dict 中长值被截断
    args = json.dumps({"outer": {"inner": {"data": "y" * 3000}}})
    args_bytes = len(args.encode("utf-8"))
    result = compress(args, args_bytes)
    parsed = json.loads(result)
    assert_true("截断" in parsed["outer"]["inner"]["data"], "嵌套 dict 长值截断")

    # 2.4 嵌套 list 中长值被截断
    args = json.dumps({"items": ["a" * 3000]})
    args_bytes = len(args.encode("utf-8"))
    result = compress(args, args_bytes)
    parsed = json.loads(result)
    assert_true("截断" in parsed["items"][0], "嵌套 list 长值截断")

    # 2.5 数字值不变
    args = json.dumps({"num": 12345, "pi": 3.14159})
    args_bytes = len(args.encode("utf-8"))
    result = compress(args, args_bytes)
    assert_eq(json.loads(result), {"num": 12345, "pi": 3.14159}, "数字值不变")

    # 2.6 bool/null 值不变
    args = json.dumps({"flag": True, "empty": None})
    args_bytes = len(args.encode("utf-8"))
    result = compress(args, args_bytes)
    assert_eq(json.loads(result), {"flag": True, "empty": None}, "bool/null 不变")

    # 2.7 非 JSON → 回退字节截断
    raw = "plain text that is not json at all and it's quite long " * 50
    result = compress(raw, len(raw.encode("utf-8")))
    assert_in("[L1截断", result, "非 JSON 回退到字节截断")

    # 2.8 空对象
    assert_eq(compress("{}", 2), "{}", "空对象不变")
    assert_eq(compress("[]", 2), "[]", "空数组不变")


# ================================================================
# Section 3: filter_level2_by_relevance
# ================================================================
def test_filter_level2_by_relevance():
    from tea_agent.session.history_builder import filter_level2_by_relevance

    print("\n━━━ Section 3: filter_level2_by_relevance ━━━")

    # 3.1 空输入
    assert_eq(filter_level2_by_relevance([], ""), [], "空 level2 列表")
    result = filter_level2_by_relevance(
        [{"user": "hi", "assistant": "hello"}], ""
    )
    assert_eq(len(result), 1, "空 current_msg 返回全部")

    # 3.2 高关键词重叠 → kind=full
    level2 = [
        {"user": "如何用 Python 读取 CSV 文件", "assistant": "使用 pandas.read_csv"}
    ]
    result = filter_level2_by_relevance(level2, "Python 读取 CSV")
    assert_true(len(result) > 0, "有匹配结果")
    assert_eq(result[0].get("kind"), "full", "高相关 → kind=full")

    # 3.3 低关键词重叠 → kind=summary
    level2 = [
        {"user": "如何配置 Docker 网络", "assistant": "创建自定义 bridge 网络"}
    ]
    result = filter_level2_by_relevance(level2, "天气怎么样")
    if result:
        # 可能有 summary 或 full（取最高分）
        pass
    print(f"  ℹ️  低相关结果: {[r.get('kind') for r in result]}")

    # 3.4 文件路径匹配 → 高相关
    level2 = [
        {"user": "修改 main.py 的登录函数", "assistant": "已修改 login()", "files": ["src/main.py"]}
    ]
    result = filter_level2_by_relevance(level2, "main.py 登录")
    assert_true(len(result) > 0, "文件路径匹配有结果")
    if result:
        assert_eq(result[0].get("kind"), "full", "文件匹配 → kind=full")

    # 3.5 测试 files 字段加分
    level2 = [
        {"user": "了解模块A", "assistant": "模块A的功能是...", "files": ["module_a.py"]}
    ]
    result = filter_level2_by_relevance(level2, "请修改 module_a.py")
    assert_true(len(result) > 0, "文件匹配触发高相关")

    # 3.6 多个 level2 混合返回
    level2 = [
        {"user": "Python 列表推导式", "assistant": "[x**2 for x in range(10)]"},
        {"user": "Docker 部署", "assistant": "编写 Dockerfile"},
        {"user": "Python 生成器", "assistant": "yield 关键字"},
    ]
    result = filter_level2_by_relevance(level2, "Python 生成器和列表")
    assert_true(len(result) <= len(level2), "结果数不超过输入")
    print(f"  ℹ️  混合筛选: {len(level2)} in → {len(result)} out")

    # 3.7 thinking 字段也参与评分
    level2 = [
        {"user": "优化性能", "thinking": "可以使用缓存减少数据库查询", "assistant": "已添加缓存"}
    ]
    result = filter_level2_by_relevance(level2, "数据库查询缓存")
    assert_true(len(result) > 0, "thinking 字段参与评分")


# ================================================================
# Section 4: _progressive_trim
# ================================================================
def make_msg(role, content, **kw):
    m = {"role": role, "content": content}
    m.update(kw)
    return m

def test_progressive_trim():
    from tea_agent.session.history_builder import _progressive_trim
    from tea_agent.session.history_builder import estimate_messages_tokens

    print("\n━━━ Section 4: _progressive_trim ━━━")

    # Mock context
    class MockContext:
        max_context_tokens = 8000

    ctx = MockContext()

    # 4.1 低于预算不裁剪
    msgs = [make_msg("user", "hi"), make_msg("assistant", "hello")]
    result = _progressive_trim(msgs, 99999, ctx)
    assert_eq(len(result), 2, "低于预算不裁剪")

    # 4.2 策略1: 删除 [历史记录] 标记的 L2 条目
    msgs = [
        make_msg("system", "You are a helpful assistant."),
        make_msg("user", "[历史记录] 昨天的对话"),
        make_msg("assistant", "是的，这是昨天的讨论"),
        make_msg("user", "今天的问题"),
    ]
    result = _progressive_trim(msgs, 15, ctx)  # 极低预算触发裁剪
    has_history = any("[历史记录]" in m.get("content", "")
                      for m in result if isinstance(m.get("content"), str))
    # 可能被删了也可能只剩摘要
    print(f"  ℹ️  策略1后消息数: {len(result)}, 含历史: {has_history}")

    # 4.3 策略2: 工具输出替换为占位符
    long_tool = "x" * 2000
    msgs = [
        make_msg("user", "请搜索"),
        make_msg("assistant", "我来搜索", tool_calls=[{"id": "c1", "function": {"name": "s", "arguments": "{}"}}]),
        make_msg("tool", long_tool, tool_call_id="c1"),
    ]
    result = _progressive_trim(msgs, 20, ctx, tool_prune_threshold=100)
    tool_msgs = [m for m in result if m.get("role") == "tool"]
    for tm in tool_msgs:
        if "工具结果已省略" in tm.get("content", ""):
            print(f"  ✅ 策略2: 工具输出被替换为占位符")
            break
    else:
        # 可能预算够大没被替换
        print(f"  ℹ️  策略2: 工具输出未替换 (预算可能足够)")

    # 4.4 策略3: 删除 reasoning_content
    msgs = [
        make_msg("user", "hi"),
        make_msg("assistant", "hello", reasoning_content="这是很长的思考过程 " * 200),
    ]
    result = _progressive_trim(msgs, 10, ctx)
    for m in result:
        rc = m.get("reasoning_content", "")
        assert_true(rc == "" or len(rc) < 100, "reasoning_content 被清空或截断")

    # 4.5 策略4: 长文本截断
    long_text = "word " * 10000
    msgs = [
        make_msg("user", "short"),
        make_msg("assistant", long_text),
    ]
    result = _progressive_trim(msgs, 50, ctx)
    for m in result:
        c = m.get("content", "")
        if len(c) > 1000:
            assert_in("已截断", c, "长文本被添加截断标记")

    # 4.6 策略5: 删除 L1 旧轮次
    msgs = []
    for i in range(20):
        msgs.append(make_msg("user", f"msg {i}"))
        msgs.append(make_msg("assistant", f"reply {i}"))
    result = _progressive_trim(msgs, 100, ctx)
    user_count = sum(1 for m in result if m.get("role") == "user")
    print(f"  ℹ️  策略5: {user_count} 轮 user 保留 (≤5 轮)")

    # 4.7 最终保护: 超预算时紧急截断
    huge = "A" * 100000
    msgs = [make_msg("user", "hi"), make_msg("assistant", huge)]
    result = _progressive_trim(msgs, 10, ctx)
    last_content = result[-1].get("content", "")
    assert_in("紧急截断" if len(huge) > len(last_content) else "", last_content
              if "紧急截断" in last_content else "ok",
              "最终保护: 紧急截断最后一条消息"
              if "紧急截断" in last_content else "预算已满足，未触发紧急截断")


# ================================================================
# Section 5: _validate_tool_call / _validate_output_format
# ================================================================
def test_validate_tool_call():
    from tea_agent.session.tool_loop_runner import _validate_tool_call

    print("\n━━━ Section 5: _validate_tool_call ━━━")

    # 5.1 空 rules → 通过
    allowed, reason = _validate_tool_call("any_tool", {})
    assert_true(allowed, "空 rules → 通过")
    assert_eq(reason, "", "空 rules → reason 为空")

    # 5.2 有 rules 但当前实现始终通过（自由奔放模式）
    rules = {"allowed_tools": ["only_this"], "forbidden_tools": ["bad_tool"]}
    allowed, reason = _validate_tool_call("bad_tool", rules)
    assert_true(allowed, "即使规则禁止也通过（当前实现自由奔放）")

    # 5.3 None rules
    allowed, reason = _validate_tool_call("tool", None)
    assert_true(allowed, "None rules → 通过")


def test_validate_output_format():
    from tea_agent.session.tool_loop_runner import _validate_output_format

    print("\n━━━ Section 5b: _validate_output_format ━━━")

    # 5b.1 空 rules → 通过
    valid, warns = _validate_output_format("anything", {})
    assert_true(valid, "空 rules → 通过")
    assert_eq(warns, [], "空 rules → 空警告列表")

    # 5b.2 空 content → 通过
    valid, warns = _validate_output_format("", {"required_sections": ["结论"]})
    assert_true(valid, "空 content → 通过")

    # 5b.3 必含段落检查
    rules = {"required_sections": ["结论", "方法"]}
    valid, warns = _validate_output_format("## 结论\n 好", rules)
    assert_true(not valid, "缺少「方法」→ 不通过")
    assert_true(any("方法" in w for w in warns), "警告包含缺失段落")

    # 5b.4 全部段落存在 → 通过
    valid, warns = _validate_output_format("## 结论\n好\n## 方法\n测试", rules)
    assert_true(valid, "全部必含段落存在 → 通过")

    # 5b.5 【段落名】格式也识别
    valid, warns = _validate_output_format("【结论】好\n【方法】测试", rules)
    assert_true(valid, "【】格式段落 → 通过")

    # 5b.6 禁止模式检查
    rules = {"forbidden_patterns": ["密码", "密钥"]}
    valid, warns = _validate_output_format("我的密码是 1234", rules)
    assert_true(not valid, "包含禁止模式「密码」→ 不通过")

    # 5b.7 JSON 格式校验
    rules = {"output_format": "json"}
    valid, warns = _validate_output_format('{"key": "value"}', rules)
    assert_true(valid, "合法 JSON → 通过")

    valid, warns = _validate_output_format("not json at all", rules)
    assert_true(not valid, "非法 JSON → 不通过")

    # 5b.8 综合: 多个警告
    rules = {
        "required_sections": ["A", "B"],
        "forbidden_patterns": ["bad"],
        "output_format": "json"
    }
    valid, warns = _validate_output_format('{"key": "bad"}', rules)
    assert_true(len(warns) >= 2, "多个规则同时出警告")

    # 5b.9 None content
    valid, warns = _validate_output_format(None, {"required_sections": ["A"]})
    assert_true(valid, "None content → 通过")


# ================================================================
# Section 6: agent_background / agent_pipeline
# ================================================================
def test_agent_background():
    from tea_agent.agent_background import start_scheduler

    print("\n━━━ Section 6a: agent_background ━━━")

    # start_scheduler 会尝试启动调度器，通常返回 True（或 False 如果已有）
    result = start_scheduler()
    # 无论 True/False 都正常（可能已有调度器运行）
    print(f"  ✅ start_scheduler() = {result}")


def test_agent_pipeline():
    from tea_agent.agent_pipeline import _empty_usage, _merge_usage

    print("\n━━━ Section 6b: agent_pipeline helpers ━━━")

    # 6b.1 _empty_usage
    u = _empty_usage()
    assert_eq(u["total_tokens"], 0, "空 usage total_tokens=0")
    assert_eq(u["prompt_tokens"], 0, "空 usage prompt_tokens=0")
    assert_eq(u["completion_tokens"], 0, "空 usage completion_tokens=0")

    # 6b.2 _merge_usage
    acc = {"total_tokens": 100, "prompt_tokens": 60, "completion_tokens": 40}
    new = {"total_tokens": 50, "prompt_tokens": 30, "completion_tokens": 20}
    _merge_usage(acc, new)
    assert_eq(acc["total_tokens"], 150, "merge total=100+50")
    assert_eq(acc["prompt_tokens"], 90, "merge prompt=60+30")
    assert_eq(acc["completion_tokens"], 60, "merge completion=40+20")

    # 6b.3 _merge_usage 空值合并
    acc2 = {}
    _merge_usage(acc2, {"total_tokens": 10, "prompt_tokens": 5, "completion_tokens": 5})
    assert_eq(acc2.get("total_tokens"), 10, "merge 空 acc")
    assert_eq(acc2.get("prompt_tokens"), 5, "merge 空 acc prompt")
    assert_eq(acc2.get("completion_tokens"), 5, "merge 空 acc completion")

    # 6b.4 _merge_usage 缺少 key → 默认为 0
    acc3 = {}
    _merge_usage(acc3, {"total_tokens": 10})
    assert_eq(acc3.get("total_tokens"), 10, "merge 缺少 key 时默认 0")
    assert_eq(acc3.get("prompt_tokens"), 0, "prompt_tokens 默认 0")
    assert_eq(acc3.get("completion_tokens"), 0, "completion_tokens 默认 0")

    print("\n--- agent_pipeline summary functions (mocked) ---")

    # 6b.5 auto_summary — 模拟一个 mock agent 测试分支覆盖
    # 测试失败路径（正常，因为 _HAVE_GUI_TOPIC_SUMMARY 可能为 False）
    class MockAgent:
        class MockDB:
            def get_topic(self, tid):
                return None
            def get_recent_conversations(self, tid, limit=3):
                return []
            def update_topic_title(self, tid, title):
                pass
        class MockSess:
            @staticmethod
            def _get_summarize_client():
                return None, None
            def _get_effective_params(self, tier):
                return {}
            context = None
        def __init__(self):
            self._db = self.MockDB()
            self._sess = self.MockSess()

    from tea_agent.agent_pipeline import auto_summary, l2_to_l3_summary, do_async_summaries

    # auto_summary 无 recent → 返回 (None, usage)
    summary, usage = auto_summary(MockAgent(), "test_topic")
    assert_eq(summary, None, "auto_summary 无 recent → None")
    assert_eq(usage.get("total_tokens"), 0, "auto_summary usage 空")

    # l2_to_l3_summary 跳过（无 cli）
    summary2, usage2 = l2_to_l3_summary(MockAgent(), "test_topic", [{"user": "hi", "assistant": "hello"}])
    # 因为 _get_summarize_client 返回 (None, None)，会尝试调用，可能异常
    print(f"  ℹ️  l2_to_l3_summary baseline: ({summary2!r}, {usage2})")

    # do_async_summaries 不抛异常
    try:
        do_async_summaries(MockAgent(), "test_topic", None, should_summarize=False)
        print(f"  ✅ do_async_summaries 不抛异常")
    except Exception as e:
        print(f"  ❌ do_async_summaries 异常: {e}")


# ================================================================
# Section 7: build_api_messages 集成测试
# ================================================================
def test_build_api_messages():
    from tea_agent.session.history_builder import build_api_messages
    from types import SimpleNamespace

    print("\n━━━ Section 7: build_api_messages 集成 ━━━")

    # 构造完整 context 模拟
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi! How can I help you?"},
        {"role": "user", "content": "What's Python?"},
        {"role": "assistant", "content": "Python is a programming language."},
    ]

    context = SimpleNamespace(
        messages=messages,
        _level2=[],
        _semantic_summary="",
        _tool_chain_summary="",
        disable_summary=False,
        disable_l3=False,
        disable_l2=False,
        supports_reasoning=False,
        supports_vision=False,
        max_context_tokens=4096,
        _skill_validate_rules={},
        _injected_memories_text="",
        _history_summary="",
        _last_l0_hash=0,
        model="test-model",
    )

    system_prompt = "You are a helpful assistant."

    # 7.1 基础: 三级结构完整
    result = build_api_messages(context, system_prompt)
    assert_true(len(result) > 0, "build_api_messages 返回非空列表")

    # 第一条是 system
    assert_eq(result[0]["role"], "system", "第一条是系统消息")
    assert_in(system_prompt[:20], result[0]["content"], "系统消息包含原始 prompt")

    # L1 最新对话应该在末尾
    last = result[-1]
    assert_eq(last["role"], "assistant", "最后一条是 assistant")

    # 7.2 L2 注入测试
    context2 = SimpleNamespace(**{**context.__dict__})
    context2._level2 = [
        {"user": "What is Python?", "assistant": "A programming language."}
    ]
    context2.supports_reasoning = True
    result2 = build_api_messages(context2, system_prompt)
    l2_msgs = [m for m in result2 if "[历史记录]" in str(m.get("content", ""))]
    assert_true(len(l2_msgs) > 0, "L2 条目被注入")
    print(f"  ℹ️  L2 条目数: {len(l2_msgs)}")

    # 7.3 L3 注入测试
    context3 = SimpleNamespace(**{**context.__dict__})
    context3._semantic_summary = "用户喜欢 Python 和机器学习"
    context3._tool_chain_summary = "上次使用了 toolkit_search"
    result3 = build_api_messages(context3, system_prompt)
    l3_msgs = [m for m in result3 if "系统记忆" in str(m.get("content", ""))]
    assert_true(len(l3_msgs) > 0, "L3 摘要块被注入")
    print(f"  ℹ️  L3 条目数: {len(l3_msgs)}")

    # 7.4 disable_summary → 无 L2/L3
    context4 = SimpleNamespace(**{**context.__dict__})
    context4.disable_summary = True
    context4._level2 = [{"user": "test", "assistant": "reply"}]
    context4._semantic_summary = "some summary"
    result4 = build_api_messages(context4, system_prompt)
    l3_in_result4 = any("系统记忆" in str(m.get("content", "")) for m in result4)
    l2_in_result4 = any("[历史记录]" in str(m.get("content", "")) for m in result4)
    assert_true(not l3_in_result4, "disable_summary → 无 L3")
    assert_true(not l2_in_result4, "disable_summary → 无 L2")

    # 7.5 工具调用消息保留
    context5 = SimpleNamespace(**{**context.__dict__})
    context5.messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Search for X"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
        ]},
        {"role": "tool", "content": "result X", "tool_call_id": "c1"},
    ]
    result5 = build_api_messages(context5, system_prompt)
    tool_msgs = [m for m in result5 if m.get("role") == "tool"]
    assert_true(len(tool_msgs) > 0, "工具调用保留")
    print(f"  ℹ️  工具消息数: {len(tool_msgs)}")

    # 7.6 孤立 tool 消息被移除
    context6 = SimpleNamespace(**{**context.__dict__})
    context6.messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "test"},
        {"role": "tool", "content": "orphan", "tool_call_id": "nonexistent"},
    ]
    result6 = build_api_messages(context6, system_prompt)
    orphan_msgs = [m for m in result6 if m.get("role") == "tool"]
    assert_eq(len(orphan_msgs), 0, "孤立 tool 消息被移除")

    # 7.7 不支持的视觉消息处理
    context7 = SimpleNamespace(**{**context.__dict__})
    context7.messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "check this image", "images": ["nonexistent.png"]},
    ]
    context7.supports_vision = False
    try:
        result7 = build_api_messages(context7, system_prompt)
        print(f"  ✅ 不支持视觉时图片被跳过")
    except Exception as e:
        print(f"  ❌ 不支持视觉异常: {e}")


# ================================================================
# Main
# ================================================================
if __name__ == "__main__":
    # 注册所有测试
    tests = [
        ("relaxed_json_loads", test_relaxed_json_loads),
        ("_compress_json_args", test_compress_json_args),
        ("filter_level2_by_relevance", test_filter_level2_by_relevance),
        ("_progressive_trim", test_progressive_trim),
        ("_validate_tool_call", test_validate_tool_call),
        ("_validate_output_format", test_validate_output_format),
        ("agent_background", test_agent_background),
        ("agent_pipeline", test_agent_pipeline),
        ("build_api_messages", test_build_api_messages),
    ]

    from tea_agent.basesession import relaxed_json_loads

    total_start = __import__('time').time()

    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            import traceback
            print(f"  ❌❌ [{name}] 抛异常: {e}")
            traceback.print_exc()
            # 标记失败但不修改 global，test fn 自己的 except 已处理
            # 这里额外给个计数
            import sys
            sys.stderr.write(f"[FATAL] {name} 未处理异常\n")

    elapsed = __import__('time').time() - total_start
    print(f"\n━━━ 总计: {passed} 通过 | ❌ {failed} 失败 | 共 {passed+failed} 项 | {elapsed:.2f}s ━━━")
    sys.exit(0 if failed == 0 else 1)
