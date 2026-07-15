"""会话模块 - 基类，提供聊天会话接口抽象基类。"""

import logging
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable

logger = logging.getLogger("basesession")


def relaxed_json_loads(raw: str):
    """容错 JSON 解析：处理 LLM 常见无效输出（单引号/尾逗号/Python布尔/反斜杠/注释/控制字符/截断）。"""
    import json
    import re

    if not raw or not raw.strip():
        return {}

    s = raw.strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    s = re.sub(r"\bNone\b", "null", s)
    s = re.sub(r"//[^\n]*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    s = re.sub(r"\\([a-zA-Z])", r"\\\\\1", s)

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Step 6: 单引号 → 双引号
    def _fix_single_quotes(text):
        result = []
        i = 0
        in_single = False
        in_double = False
        while i < len(text):
            ch = text[i]
            if ch == "\\":
                result.append(ch)
                if i + 1 < len(text):
                    result.append(text[i + 1])
                    i += 2
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                result.append('"')
            elif ch == '"' and not in_single:
                in_double = not in_double
                result.append(ch)
            else:
                result.append(ch)
            i += 1
        return "".join(result)

    s = _fix_single_quotes(s)

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Step 7: 为未引号包裹的 key 添加引号
    s = re.sub(r"([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', s)

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Step 8: 尝试从文本中提取 JSON 对象
    brace_match = re.search(r"\{.*\}|\[.*\]", s, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    # Step 9: 尝试修复被截断的 JSON
    # 延迟导入避免循环依赖
    try:
        from tea_agent.session.json_sanitizer import try_fix_truncated_json

        fixed = try_fix_truncated_json(s)
        if fixed is not None:
            return json.loads(fixed)
    except Exception:
        pass

    # 全部失败，抛原始异常
    raise json.JSONDecodeError("无法解析 JSON (已尝试多种修复)", raw, 0)


class BaseChatSession(ABC):
    """
    聊天会话抽象基类
    定义公共接口和共享功能
    """

    _KB_THRESHOLD: int = 65536  # toolkit_kb 输出阈值: 64KB
    _DEFAULT_TOOL_THRESHOLD: int = 2048  # 默认工具输出阈值: 2KB
    _TEXT_FILE_THRESHOLD: int = 16384  # 文本/日志文件阈值: 16KB
    _SOURCE_EXTENSIONS = {
        ".py",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rs",
        ".go",
        ".ts",
        ".js",
        ".jsx",
        ".tsx",
        ".vue",
        ".swift",
        ".kt",
        ".scala",
        ".rb",
        ".php",
        ".cs",
        ".sql",
        ".sh",
        ".bash",
        ".ps1",
        ".bat",
        ".cmd",
        ".xml",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".cfg",
        ".ini",
        ".conf",
        ".cmake",
        ".mk",
        ".r",
        ".jl",
        ".lua",
        ".ex",
        ".exs",
        ".erl",
        ".hrl",
        ".elm",
        ".dart",
        ".nim",
        ".zig",
        ".v",
        ".sv",
        ".vhdl",
    }
    _TEXT_EXTENSIONS = {
        ".txt",
        ".log",
        ".md",
        ".rst",
        ".csv",
        ".tsv",
        ".text",
        ".out",
        ".err",
        ".stdout",
        ".stderr",
        ".nohup",
    }

    def __init__(
        self,
        model: str,
        max_history: int = 10,
        system_prompt: str = "你是一个智能助手，可以调用工具函数来帮助用户解决问题。",
    ):
        """
        初始化基类

        Args:
            model: 模型名称
            max_history: 最大历史消息数
            system_prompt: 系统提示词
        """
        self.model = model
        self.max_history = max_history
        self.system_prompt = system_prompt
        self._history_summary = ""

        # 消息列表
        self.messages: list[dict] = []
        self.messages.append({"role": "system", "content": self.system_prompt})

        # 打断标志
        self.interrupted = False

    @abstractmethod
    def chat_stream(
        self, msg: str, callback: Callable[[str], None]
    ) -> tuple[str, bool]:
        """
        流式对话（抽象方法，子类必须实现）

        Args:
            msg: 用户消息
            callback: 流式输出回调函数

        Returns:
            Tuple[str, bool]: (助手完整回复, 是否使用了工具调用)
        """
        pass

    def add_user_message(self, msg):
        """添加用户消息，支持纯文本或含图片的结构化输入"""
        if isinstance(msg, str):
            self.messages.append({"role": "user", "content": msg})
        elif isinstance(msg, dict):
            entry = {"role": "user", "content": msg.get("text", "")}
            images = msg.get("images", [])
            if images:
                entry["images"] = images
            self.messages.append(entry)
        else:
            self.messages.append({"role": "user", "content": str(msg)})

    def add_assistant_message(self, msg: str):
        """添加助手消息"""
        self.messages.append({"role": "assistant", "content": msg})

    def add_tool_result(self, tool_call_id: str, content: str):
        """添加工具执行结果"""
        self.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )

    def get_recent_messages(self) -> list[dict]:
        """获取最近的消息（排除系统消息）"""
        return [m for m in self.messages if m["role"] != "system"]

    @staticmethod
    def _strip_reasoning_content(messages: list[dict]) -> None:
        """
        原地清除消息列表中的 reasoning_content 字段。

        注意：对于包含 tool_calls 的 assistant 消息，必须保留 reasoning_content，
        否则 DeepSeek API 会返回 400 错误。
        """
        for msg in messages:
            # 如果是助手消息且包含工具调用，则保留 reasoning_content
            if msg.get("role") == "assistant":
                continue
            msg.pop("reasoning_content", None)

    @staticmethod
    def _compress_tool_content(content: str, max_chars: int = 2048) -> str:
        """
        L1 工具输出压缩：首尾各 max_chars//2 字节，按换行对齐。

        策略：
        - 短输出（≤max_chars 字节）：原样保留
        - max_chars >= sys.maxsize：不截断，完整返回
        - 长输出：保留首尾各 half 字节，按换行边界对齐避免截断半行

        Args:
            content: 原始工具输出
            max_chars: 阈值字节数，超过则触发首尾截断

        Returns:
            压缩后的输出摘要
        """
        if not content:
            return content

        # 不限长：完整返回
        if max_chars >= sys.maxsize:
            return content

        # 编码为字节以准确计算字节长度（与 API token 计数一致）
        raw = content.encode("utf-8")
        total_bytes = len(raw)

        if total_bytes <= max_chars:
            return content

        half = max_chars // 2

        # 前半部分：从 half 位置向前找最近换行
        head_end = half
        if head_end > 0:
            # 向后找换行
            nl = raw.find(b"\n", head_end)
            if nl != -1 and nl < half + 256:
                head_end = nl
            else:
                # 向前找换行
                nl = raw.rfind(b"\n", 0, head_end)
                if nl != -1 and nl > half - 256:
                    head_end = nl

        head_bytes = raw[:head_end]

        # 后半部分：从尾部 half 位置向后找最近换行
        tail_start = total_bytes - half
        if tail_start > 0:
            nl = raw.rfind(b"\n", tail_start, total_bytes)
            if nl != -1 and nl > tail_start - 256:
                tail_start = nl + 1  # 从换行后开始
            else:
                nl = raw.find(b"\n", tail_start)
                if nl != -1 and nl < tail_start + 256:
                    tail_start = nl + 1

        tail_bytes = raw[tail_start:]

        head_text = head_bytes.decode("utf-8", errors="replace")
        tail_text = tail_bytes.decode("utf-8", errors="replace")
        skipped_bytes = total_bytes - len(head_bytes) - len(tail_bytes)

        return (
            f"[工具输出压缩: {total_bytes}B 原始, 保留 {len(head_bytes) + len(tail_bytes)}B]\n"
            f"{head_text}\n"
            f"... [{skipped_bytes} 字节省略] ...\n"
            f"{tail_text}"
        )

    @staticmethod
    def _compress_json_args(
        args_str: str, args_bytes: int, max_bytes: int = 2048
    ) -> str:
        """
        JSON 感知截断 tool_calls 参数。

        策略：
        1. 尝试 json.loads 解析 → 成功则递归压缩超长 string value
        2. 解析失败 → 回退到字节截断（首尾各1024B，按换行对齐）

        递归压缩规则（对 dict 和 list 中的值）：
        - string > 1024 字节：截为首512B+尾512B，标记 [截断]
        - 其他类型（number/bool/null）：原样保留
        - 嵌套 dict/list：递归处理

        Args:
            args_str: 原始 arguments JSON 字符串
            args_bytes: 原始字节数（用于截断标记）
            max_bytes: 触发压缩的阈值

        Returns:
            压缩后的合法 JSON 字符串
        """
        import json as _json

        # Step 1: 尝试解析
        try:
            obj = _json.loads(args_str)
        except (_json.JSONDecodeError, ValueError):
            # 解析失败 → 回退到字节截断
            half = max_bytes // 2
            raw = args_str.encode("utf-8")
            # 按换行对齐首尾
            head_end = half
            nl = raw.find(b"\n", head_end)
            if nl != -1 and nl < half + 256:
                head_end = nl
            else:
                nl = raw.rfind(b"\n", 0, head_end)
                if nl != -1 and nl > half - 256:
                    head_end = nl
            tail_start = len(raw) - half
            nl = raw.rfind(b"\n", tail_start, len(raw))
            if nl != -1 and nl > tail_start - 256:
                tail_start = nl + 1

            head_text = raw[:head_end].decode("utf-8", errors="replace")
            tail_text = raw[tail_start:].decode("utf-8", errors="replace")
            return head_text + f"\n... [L1截断: {args_bytes}B 参数] ...\n" + tail_text

        # Step 2: 递归压缩超长 string value
        HALF = 512  # 每个 value 的首尾保留字节数

        def _compress_value(val, path=""):
            """递归压缩值，返回 (compressed_val, truncated_count)"""
            if isinstance(val, str):
                vbytes = len(val.encode("utf-8"))
                if vbytes > 1024:
                    raw = val.encode("utf-8")
                    # 按换行对齐
                    head_end = HALF
                    nl = raw.find(b"\n", head_end)
                    if nl != -1 and nl < head_end + 128:
                        head_end = nl
                    tail_start = len(raw) - HALF
                    nl = raw.rfind(b"\n", tail_start, len(raw))
                    if nl != -1 and nl > tail_start - 128:
                        tail_start = nl + 1
                    head_t = raw[:head_end].decode("utf-8", errors="replace")
                    tail_t = raw[tail_start:].decode("utf-8", errors="replace")
                    return (
                        head_t
                        + f"\n... [截断 {vbytes}B→{len(head_t.encode('utf-8')) + len(tail_t.encode('utf-8'))}B] ...\n"
                        + tail_t,
                        1,
                    )
                return (val, 0)
            elif isinstance(val, dict):
                new_d = {}
                total_trunc = 0
                for k, v in val.items():
                    cv, ct = _compress_value(v, f"{path}.{k}" if path else k)
                    new_d[k] = cv
                    total_trunc += ct
                return (new_d, total_trunc)
            elif isinstance(val, list):
                new_l = []
                total_trunc = 0
                for i, v in enumerate(val):
                    cv, ct = _compress_value(v, f"{path}[{i}]")
                    new_l.append(cv)
                    total_trunc += ct
                return (new_l, total_trunc)
            else:
                # number, bool, null
                return (val, 0)

        compressed_obj, truncated = _compress_value(obj)

        if truncated == 0:
            # 没有需要截断的 value，返回原字符串（避免 re-serialize 格式变化）
            return args_str

        result = _json.dumps(compressed_obj, ensure_ascii=False)
        return result

    @staticmethod
    def _guess_tool_threshold(tool_name: str, arguments: str) -> int:
        """
        根据工具名称和参数推断合适的输出截断阈值。

        策略：
        - toolkit_kb → 64KB
        - toolkit_file read 源码文件 → 不截断 (sys.maxsize)
        - toolkit_file read 文本/日志 → 16KB
        - 其他 → 2KB 默认
        """
        import json as _json_gt

        if tool_name == "toolkit_kb":
            return BaseChatSession._KB_THRESHOLD

        # 尝试从参数中提取文件路径/扩展名
        try:
            args = (
                _json_gt.loads(arguments)
                if isinstance(arguments, str)
                else (arguments or {})
            )
        except Exception:
            return BaseChatSession._DEFAULT_TOOL_THRESHOLD

        if not isinstance(args, dict):
            return BaseChatSession._DEFAULT_TOOL_THRESHOLD

        # 查找可能的文件路径参数
        filepath = None
        for key in ("filename", "path", "file", "file_path", "target"):
            val = args.get(key, "")
            if isinstance(val, str) and val:
                filepath = val
                break

        if not filepath:
            return BaseChatSession._DEFAULT_TOOL_THRESHOLD

        # 提取扩展名并匹配
        ext = os.path.splitext(filepath)[1].lower()
        basename = os.path.basename(filepath).lower()

        if ext in BaseChatSession._SOURCE_EXTENSIONS:
            return sys.maxsize  # 源码文件：不截断
        if ext in BaseChatSession._TEXT_EXTENSIONS:
            return BaseChatSession._TEXT_FILE_THRESHOLD  # 文本/日志：16KB
        # 无扩展名的常见文本文件
        if basename in (
            "makefile",
            "dockerfile",
            "license",
            "changelog",
            "readme",
            "authors",
        ):
            return BaseChatSession._TEXT_FILE_THRESHOLD

        return BaseChatSession._DEFAULT_TOOL_THRESHOLD

    @staticmethod
    def _compress_tool_rounds(rounds: list[dict]) -> list[dict]:
        """
        对 rounds 中的工具调用链进行 L1 智能压缩。

        规则：
        - user 消息：完整保留
        - assistant 含 tool_calls（中间步骤）：保留 reasoning_content，
          对每个 tool_call 的 function.arguments 若 >2048 字节则截断
        - tool 消息：调用 _compress_tool_content 压缩输出
        - 最终 assistant 消息（末尾无 tool_calls）：完整保留，不压缩

        参数:
            rounds: 原始 rounds 列表

        返回:
            压缩后的 rounds（非原地修改）
        """
        if not rounds:
            return rounds

        # ── 首遍扫描：收集 tool_call_id → (tool_name, arguments) ──
        tc_map: dict[str, tuple] = {}  # tool_call_id → (tool_name, arguments_str)
        for rd in rounds:
            if rd.get("role") == "assistant" and rd.get("tool_calls"):
                for tc in rd["tool_calls"]:
                    tc_id = tc.get("id", "")
                    func = tc.get("function", {})
                    if tc_id and isinstance(func, dict):
                        tc_map[tc_id] = (
                            func.get("name", ""),
                            func.get("arguments", ""),
                        )

        n = len(rounds)
        result = []

        for i, rd in enumerate(rounds):
            role = rd.get("role", "")
            is_last = i == n - 1

            if role == "user":
                # user 消息完整保留
                result.append(dict(rd))

            elif role == "assistant":
                if rd.get("tool_calls") and not is_last:
                    # 中间 assistant 消息（含工具调用）：JSON感知压缩参数
                    compressed = dict(rd)
                    # 保留 reasoning_content
                    tc_list = compressed.get("tool_calls", [])
                    new_tc = []
                    for tc in tc_list:
                        tc_copy = dict(tc)
                        func = tc_copy.get("function", {})
                        if isinstance(func, dict):
                            args_str = func.get("arguments", "")
                            if isinstance(args_str, str):
                                args_bytes = len(args_str.encode("utf-8"))
                                if args_bytes > 2048:
                                    func["arguments"] = (
                                        BaseChatSession._compress_json_args(
                                            args_str, args_bytes
                                        )
                                    )
                            tc_copy["function"] = func
                        new_tc.append(tc_copy)
                    compressed["tool_calls"] = new_tc
                    result.append(compressed)
                else:
                    # 最终 assistant 消息（末尾，无 tool_calls 或恰好是最后一个）：完整保留
                    result.append(dict(rd))

            elif role == "tool":
                # tool 消息：根据工具名和参数自适应压缩输出
                compressed = dict(rd)
                tc_id = rd.get("tool_call_id", "")
                tool_name, args_str = tc_map.get(tc_id, ("", ""))
                threshold = BaseChatSession._guess_tool_threshold(tool_name, args_str)
                compressed["content"] = BaseChatSession._compress_tool_content(
                    rd.get("content", ""), max_chars=threshold
                )
                result.append(compressed)

            else:
                # system 等其他角色
                result.append(dict(rd))

        return result

    @staticmethod
    def _repair_incomplete_tool_chains(rounds: list[dict]) -> list[dict]:
        """
        修复中断导致的不完整工具调用链。

        规则：
          - 每个带有 tool_calls 的 assistant 消息，其后必须有对应的 tool 消息
            回应每一个 tool_call_id，否则该 assistant 及其后续消息被截断。
          - 孤立的 tool 消息（无对应 assistant tool_calls）也被移除。

        Args:
            rounds: 原始 rounds 列表（可能包含不完整链）

        Returns:
            修复后的 rounds 列表
        """
        if not rounds:
            return rounds

        result: list[dict] = []
        # 追踪尚未匹配的 tool_call_id -> 在 result 中的起始索引
        pending: dict[str, int] = {}
        last_safe_len = 0  # 最后安全点：所有 pending 已清零时的 result 长度

        for _i, rd in enumerate(rounds):
            role = rd.get("role", "")

            if role == "assistant" and rd.get("tool_calls"):
                # 先检查当前是否有未清空的 pending（前一个 assistant 的 tool_calls 未完成）
                # 这种情况：上一个 assistant 的 tool_calls 还没全匹配，又来了新 assistant
                # → 放弃当前批次（上一个 assistant 之后的都是垃圾），回滚到上一个安全点
                if pending:
                    result = result[:last_safe_len]
                    pending.clear()

                # 记录新的 tool_call_ids
                tc_list = rd["tool_calls"]
                tc_ids = (
                    [tc.get("id", "") for tc in tc_list if tc.get("id")]
                    if isinstance(tc_list, list)
                    else []
                )

                if not tc_ids:
                    # 有 tool_calls 字段但没有有效 id，视为纯 assistant 消息
                    result.append(dict(rd))
                    last_safe_len = len(result)
                    continue

                # 添加 assistant 消息
                start_idx = len(result)
                result.append(dict(rd))
                for tid in tc_ids:
                    pending[tid] = start_idx

            elif role == "tool":
                tid = rd.get("tool_call_id", "")
                if tid and tid in pending:
                    # 匹配到一个 tool_call_id
                    result.append(dict(rd))
                    del pending[tid]
                    if not pending:
                        # 所有 tool_call_id 都已匹配 → 安全点
                        last_safe_len = len(result)
                else:
                    # 孤立的 tool 消息：跳过
                    logger.debug(f"_repair: 跳过孤立 tool 消息 tool_call_id={tid}")
                    continue

            elif role == "assistant":
                # 纯 assistant 消息（无 tool_calls）
                if pending:
                    # 前一批 tool_calls 还没清空就来了新的 assistant 消息
                    # → 回滚到上一个安全点，丢弃未完成的工具调用链
                    result = result[:last_safe_len]
                    pending.clear()
                result.append(dict(rd))
                last_safe_len = len(result)

            else:
                # user/system 等其他角色：直接保留
                result.append(dict(rd))

        # 末尾检查：如果还有未清空的 pending，回滚到最后一个安全点
        if pending:
            result = result[:last_safe_len]
            logger.warning(
                f"_repair: 截断不完整工具调用链，移除 {len(pending)} 个未匹配的 tool_call_id: "
                f"{list(pending.keys())}"
            )

        # 最终清理：结果中不应再有 reasoning_content（非 assistant 消息）
        BaseChatSession._strip_reasoning_content(result)

        return result

    def load_history(
        self,
        conversations: list[dict],
        summary: str = "",
        recent_turns: int = 10,
        level2: list = None,
        semantic_summary: str = "",
        tool_chain_summary: str = "",
    ):
        """
        三级历史加载：

        Level 1: 最新一轮压缩对话（user + 工具调用链[参数/输出截断] + assistant(final)完整）
        Level 2: 近期语义相关的 user+assistant 自然语言对
        Level 3: 压缩摘要 — semantic_summary + tool_chain_summary

        Args:
            conversations: 对话记录列表（时间正序）
            summary: 兼容旧字段的摘要
            recent_turns: 兼容旧参数（不再强制使用）
            level2: Level 2 条目列表 [{"user": ..., "assistant": ...}, ...]
            semantic_summary: 语义摘要（长期偏好、任务背景、关键结论）
            tool_chain_summary: 工具链摘要（旧任务工具调用链、关键I/O、结论）
        """
        self.messages = [{"role": "system", "content": self.system_prompt}]

        # ── Level 3 摘要存储 ──
        self._semantic_summary = semantic_summary or summary  # 兼容旧 summary
        self._tool_chain_summary = tool_chain_summary

        # ── Level 2 存储（用于 prompt 构建时直接拼入）──
        self._level2 = level2 or []  # instance attribute; subclasses with context bridge to context._level2

        # ── Level 1: 最新一轮压缩加载 ──
        total = len(conversations)
        if total == 0:
            self._history_summary = ""  # 兼容旧代码
            logger.info("加载历史 0条 (新主题)")
            return

        # 最新一条作为 Level 1（压缩工具链）
        last_conv = conversations[-1]
        raw_user_msg = last_conv["user_msg"]
        user_entry = {"role": "user"}
        if isinstance(raw_user_msg, str) and raw_user_msg.startswith("{"):
            try:
                import json as _json_lh

                parsed = _json_lh.loads(raw_user_msg)
                if isinstance(parsed, dict):
                    user_entry["content"] = parsed.get("text", "")
                    imgs = parsed.get("images", [])
                    if imgs:
                        user_entry["images"] = imgs
                else:
                    user_entry["content"] = raw_user_msg
            except Exception:
                user_entry["content"] = raw_user_msg
        else:
            user_entry["content"] = str(raw_user_msg) if raw_user_msg else ""
        self.messages.append(user_entry)

        rounds = last_conv.get("rounds_json_parsed")
        if rounds and last_conv.get("is_func_calling"):
            repaired = BaseChatSession._repair_incomplete_tool_chains(rounds)
            compressed = BaseChatSession._compress_tool_rounds(repaired)
            for rd in compressed:
                self.messages.append(rd)
        else:
            self.messages.append({"role": "assistant", "content": last_conv["ai_msg"]})

        # ── 旧轮次不再直接加载到 self.messages ──
        # Level 2 + Level 3 由 _build_api_messages 拼接
        self._history_summary = ""  # 旧字段，不再使用
        logger.info(
            f"三级加载: L1=1轮压缩 , L2={len(self._level2)}对 , "
            f"L3_semantic={len(self._semantic_summary)}chars , L3_tool={len(self._tool_chain_summary)}chars"
        )

    def interrupt(self):
        """打断当前生成"""
        self.interrupted = True

    def reset_interrupt(self):
        """重置打断标志"""
        self.interrupted = False

    def _trim_messages(self):
        """[DISABLED: 2026-05-20] no references — trimming now via L3 summary"""
        pass  # DISABLED
