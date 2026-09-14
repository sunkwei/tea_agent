"""
JSON 校验与修复模块

从 onlinesession.py 提取的独立功能：
- sanitize_api_messages: 校验并修复 API 消息中的 tool_calls JSON
- try_fix_truncated_json: 尝试修复被截断的 JSON 字符串
- escape_raw_control_chars: 转义字符串内未转义的裸控制字符（真实换行等）
- quote_bare_values: 为未加引号的裸标量值补引号（{"app": bash}）
"""

import json
import logging
import re

logger = logging.getLogger("session.json_sanitizer")

# 字符串字面量内部允许转义的控制字符（语义等价，故可安全补转义）
_CTRL_ESCAPE_MAP = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}

# 裸标量值 token（不含空白/引号等结构字符；允许前导 '-' 以覆盖 "-lc" 这类命令行选项）
_BARE_VALUE_RE = re.compile(r"-?[A-Za-z_][A-Za-z0-9_.\-/]*")

# JSON 字面量，不能加引号
_JSON_LITERALS = frozenset({"true", "false", "null"})

# 结尾的反斜杠序列（用于识别截断在转义符中间的残缺转义）
_TRAILING_BACKSLASH_RE = re.compile(r"\\+$")

# 闭合引号之后允许出现的结构字符（出现这些说明该引号是字符串的合法结束）
_STRUCTURAL_AFTER_QUOTE = ",}]:"


def escape_unescaped_inner_quotes(s: str) -> str:
    """把 JSON 字符串**内部未转义的双引号**转义为 ``\\"``。

    弱模型（尤其量化小模型）写 shell 脚本时习惯直接用裸 ``"`` 包裹内容
    （``echo "=== start ==="``），而 JSON 要求写成 ``\\"``。这些裸引号会
    让解析器提前结束字符串，后果是：

    - 完整 JSON 被判为不可修复 → 整个 tool_call 被丢弃；
    - 截断 JSON 触发"从尾部删除"兜底 → 命令内容被静默砍掉。

    判定规则：字符串已开启时遇到 ``"``，向后跳过空白看第一个非空字符：

    - 是 ``,`` / ``}`` / ``]`` / ``:`` 或已到结尾 → 是合法闭合引号，保留；
    - 其他（``=``、字母、``\\`` 等）→ 判定为内容里的裸引号，转义并保持字符串开启。

    合法 JSON 中闭合引号后面必然是结构字符，因此本函数对合法 JSON 是恒等变换。

    Args:
        s: 原始 JSON 文本

    Returns:
        内层裸引号已转义的文本；无需修改时原样返回
    """
    if not s or '"' not in s:
        return s

    out: list[str] = []
    i = 0
    n = len(s)
    in_str = False
    while i < n:
        ch = s[i]
        if ch == "\\":
            # 已转义的字符整体透传，避免把 \" 误判为内外层边界
            out.append(s[i : i + 2])
            i += 2
            continue
        if ch != '"':
            out.append(ch)
            i += 1
            continue
        if not in_str:
            in_str = True
            out.append(ch)
            i += 1
            continue
        # 字符串内遇到引号：向后找第一个非空白字符判断是否为结构字符
        j = i + 1
        while j < n and s[j] in " \t\r\n":
            j += 1
        if j >= n or s[j] in _STRUCTURAL_AFTER_QUOTE:
            in_str = False
            out.append(ch)
        else:
            out.append('\\"')  # 内容里的裸引号
        i += 1
    return "".join(out)


def escape_raw_control_chars(s: str) -> str:
    """把 JSON 字符串字面量内部**未转义的裸控制字符**转义为合法转义序列。

    LLM 编写多行 shell 脚本时常直接输出真实换行/制表符（而不是 ``\\n`` 转义），
    这在 JSON 字符串内属于非法控制字符（``json.loads`` 报
    ``Invalid control character``），会让整个 tool_call 参数被判为不可修复而丢弃。

    这些字符出现在字符串内本就不合法，转义后语义完全等价；
    字符串**外部**的换行属于合法空白，必须原样保留（否则会破坏格式化 JSON）。

    Args:
        s: 原始 JSON 文本

    Returns:
        字符串内裸控制字符已转义的文本；无需修改时原样返回
    """
    if not s or not any(c in s for c in "\n\r\t\b\f"):
        return s

    out: list[str] = []
    in_str = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            out.append(ch)
            continue
        if ch == "\\":
            escape = True
            out.append(ch)
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if in_str:
            if ch in _CTRL_ESCAPE_MAP:
                out.append(_CTRL_ESCAPE_MAP[ch])
                continue
            if ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
                continue
        out.append(ch)
    return "".join(out)


def quote_bare_values(s: str) -> str:
    """为**未加引号的裸标量值**补上双引号：``{"app": bash}`` → ``{"app": "bash"}``。

    小模型/量化模型常把字符串值写成裸 token（值两侧引号一起丢失），
    严格 ``json.loads`` 与常规容错步骤都无法修复，最终导致整个 tool_call 被丢弃。

    仅修复同时满足以下条件的形态，避免把内容改错：

    1. 位于结构位置（``:`` / ``,`` / ``[`` 之后，允许空白）；
    2. 是单个简单 token（``-?[A-Za-z_][A-Za-z0-9_.\\-/]*``，不含空格等结构字符）；
    3. 其后紧跟分隔符（``,`` / ``}`` / ``]``）或文本结尾（截断场景；
       若紧跟 ``:`` 则视为裸 key，交给上游的裸 key 修复步骤处理）；
    4. 不是 ``true`` / ``false`` / ``null``。

    只在字符串字面量**之外**生效（内部逐字符透传），因此形如
    ``{"cmd": "sed -n '1,5p' x: y, z"}`` 的字符串内容不会被误改。

    Args:
        s: 原始 JSON 文本

    Returns:
        裸标量值已补引号的文本；无匹配时原样返回
    """
    if not s:
        return s

    out: list[str] = []
    i = 0
    n = len(s)
    in_str = False
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "\\":
                out.append(s[i : i + 2])
                i += 2
                continue
            if ch == '"':
                in_str = False
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch in ":,[":
            out.append(ch)
            i += 1
            j = i
            while j < n and s[j] in " \t\r\n":
                j += 1
            m = _BARE_VALUE_RE.match(s, j) if j < n and (s[j].isalpha() or s[j] in "_-") else None
            if m:
                k = m.end()
                t = k
                while t < n and s[t] in " \t\r\n":
                    t += 1
                token = m.group(0)
                ends_value = t >= n or s[t] in ",}]"
                is_key = t < n and s[t] == ":"
                if ends_value and not is_key and token not in _JSON_LITERALS:
                    out.append(s[i:j])
                    out.append('"' + token + '"')
                    i = k
                    continue
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def try_fix_truncated_json(s: str) -> str | None:
    """尝试修复被截断的 JSON 字符串。

    通过分析括号栈和字符串状态，补全缺失的闭合符号。
    进入分析前先转义字符串内的裸控制字符（真实换行等），否则即使补全括号
    也无法通过 ``json.loads``，还会退化成"从尾部删除"从而静默丢掉参数内容。

    Args:
        s: 可能被截断的 JSON 字符串

    Returns:
        修复后的合法 JSON 字符串，无法修复则返回 None
    """
    if not s or not s.strip():
        return None

    close_map = {'{': '}', '[': ']'}

    def _try_fix_with_stack(text, stack, in_str):
        """尝试用给定的栈状态修复 JSON"""
        if in_str:
            # 截断落在转义符中间时，结尾残留的单个 '\' 会转义掉补全的引号，
            # 必须先丢弃这个残缺转义符（奇数为残缺，偶数是完整的 '\\'）
            m = _TRAILING_BACKSLASH_RE.search(text)
            if m and len(m.group(0)) % 2 == 1:
                text = text[:-1]
        suffix = ''.join(close_map[c] for c in reversed(stack))
        if in_str:
            suffix = '"' + suffix
        fixed = text + suffix
        try:
            json.loads(fixed)
            return fixed
        except json.JSONDecodeError:
            return None

    def _repair(text: str) -> str | None:
        """对给定文本执行「补全括号 → 从尾部删除」两级修复"""
        # 第一次尝试：直接补全
        stack = []
        in_str = False
        escape = False
        for ch in text:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in '{[':
                stack.append(ch)
            elif ch in '}]' and stack and ((ch == '}' and stack[-1] == '{') or (ch == ']' and stack[-1] == '[')):
                stack.pop()

        if not stack:
            candidate = text + '"' if in_str else text
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                return None

        result = _try_fix_with_stack(text, stack, in_str)
        if result:
            return result

        # 第二次尝试：从末尾往前删除不完整的部分
        # 找到最后一个逗号或冒号的位置
        for i in range(len(text) - 1, -1, -1):
            ch = text[i]
            if ch in ',:':
                truncated = text[:i].rstrip(',').rstrip(':')
                if not truncated:
                    continue

                # 重新分析截断后的字符串
                t_stack = []
                t_in_str = False
                t_escape = False
                for c in truncated:
                    if t_escape:
                        t_escape = False
                        continue
                    if c == '\\':
                        t_escape = True
                        continue
                    if c == '"' and not t_escape:
                        t_in_str = not t_in_str
                        continue
                    if t_in_str:
                        continue
                    if c in '{[':
                        t_stack.append(c)
                    elif c in '}]' and t_stack and ((c == '}' and t_stack[-1] == '{') or (c == ']' and t_stack[-1] == '[')):
                        t_stack.pop()

                result = _try_fix_with_stack(truncated, t_stack, t_in_str)
                if result:
                    return result

        return None

    # 裸控制字符（真实换行）先转义，否则补全括号也无法通过 json.loads
    s = escape_raw_control_chars(s.strip())

    # 内容里有未转义的裸引号（echo "x"）时，原始文本的字符串状态从该引号起就是错的，
    # 直接修复会走进"从尾部删除"兜底、把命令内容静默砍掉。此时优先按转义后的解读修复。
    escaped = escape_unescaped_inner_quotes(s)
    if escaped != s:
        fixed = _repair(escaped)
        if fixed is not None:
            return fixed

    return _repair(s)


def sanitize_api_messages(messages: list[dict]) -> list[dict]:
    """校验并修复 API 消息中的 tool_calls JSON。

    扫描所有 assistant 消息的 tool_calls，对非法 JSON 参数尝试修复，
    无法修复的则移除该 tool_call。

    Args:
        messages: API 消息列表

    Returns:
        修复后的消息列表
    """
    sanitized = []
    removed_count = 0
    for msg in messages:
        if msg.get("role") != "assistant":
            sanitized.append(msg)
            continue

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            sanitized.append(msg)
            continue

        valid_calls = []
        for tc in tool_calls:
            func = tc.get("function", {})
            raw_args = func.get("arguments", "")

            if isinstance(raw_args, dict):
                valid_calls.append(tc)
                continue

            if not raw_args or not raw_args.strip():
                valid_calls.append(tc)
                continue

            try:
                json.loads(raw_args)
                valid_calls.append(tc)
                continue
            except json.JSONDecodeError:
                pass

            fixed = try_fix_truncated_json(raw_args)
            if fixed is None:
                # 截断补全失败 → 再走容错解析（裸值/裸 key/单引号/真实换行），
                # 成功后重新序列化为标准 JSON。与 normalize_tool_args 保持同一套修复能力，
                # 避免历史中已入库的脏参数被直接丢弃。
                try:
                    from tea_agent.basesession import relaxed_json_loads

                    parsed = relaxed_json_loads(raw_args)
                    if isinstance(parsed, (dict, list)):
                        fixed = json.dumps(parsed, ensure_ascii=False)
                except Exception as e:
                    logger.debug("sanitize_api_messages: relaxed_json_loads 失败: %s", e)
            if fixed is not None:
                tc_copy = dict(tc)
                tc_copy["function"] = dict(func)
                tc_copy["function"]["arguments"] = fixed
                valid_calls.append(tc_copy)
                # 修复成功是防御性兜底（预期内行为），无需 WARNING 刷屏
                logger.debug(f"sanitize_api_messages: 修复截断JSON → {fixed[:80]}...")
            else:
                removed_count += 1
                logger.debug(
                    f"sanitize_api_messages: 移除非法tool_call → "
                    f"func={func.get('name','?')}, args前80={raw_args[:80]}"
                )

        if valid_calls:
            msg_copy = dict(msg)
            msg_copy["tool_calls"] = valid_calls
            sanitized.append(msg_copy)
        else:
            sanitized.append({
                "role": "assistant",
                "content": msg.get("content", "") or "[工具调用参数损坏，已移除]"
            })

    if removed_count > 0:
        logger.debug(f"sanitize_api_messages: 共移除 {removed_count} 个非法 tool_call")
    return sanitized


def normalize_tool_args(func_name: str, raw: str) -> str | None:
    """源头规范化 tool_call arguments：合法 JSON 原样返回；截断/非法 JSON 尝试修复。

    修复优先级：严格 json.loads（逐字节保留）→ try_fix_truncated_json（补全闭合括号）
    → relaxed_json_loads（容错解析后重新序列化）。全部失败返回 None（调用方丢弃）。

    目标：LLM 流式累计的截断参数在入库前修复为完整 JSON，避免污染
    context.messages → 每轮 build_api_messages 重复 sanitize 修复（WARNING 刷屏）。

    Args:
        func_name: 工具名（仅用于日志）
        raw: 原始 arguments 字符串

    Returns:
        规范化后的 JSON 字符串；无法修复返回 None
    """
    if not isinstance(raw, str) or not raw.strip():
        return raw

    s = raw.strip()
    try:
        json.loads(s)
        return raw  # 已是合法 JSON，原样返回（逐字节一致，前缀缓存友好）
    except json.JSONDecodeError:
        pass

    # 截断 JSON：先尝试补全闭合括号
    try:
        fixed = try_fix_truncated_json(s)
        if fixed is not None:
            return fixed
    except Exception:
        pass

    # 容错解析（单引号 / 尾逗号 / Python 布尔等），成功后规范化为标准 JSON
    try:
        from tea_agent.basesession import relaxed_json_loads

        parsed = relaxed_json_loads(s)
        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed, ensure_ascii=False)
    except Exception:
        pass

    logger.warning(
        f"tool call failed: {func_name} 参数 JSON 无法修复，已丢弃: {raw[:100]}"
    )
    return None
