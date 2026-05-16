"""
会话模块 - 基类
提供统一的聊天会话接口抽象基类
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Callable, Tuple
import logging

logger = logging.getLogger("basesession")

class BaseChatSession(ABC):
    """
    聊天会话抽象基类
    定义公共接口和共享功能
    """

    def __init__(
        self,
        model: str,
        max_history: int = 10,
        system_prompt: str = "你是一个智能助手，可以调用工具函数来帮助用户解决问题。"
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
        self.messages: List[Dict] = []
        self.messages.append({"role": "system", "content": self.system_prompt})

        # 打断标志
        self.interrupted = False

    @abstractmethod
    def chat_stream(self, msg: str, callback: Callable[[str], None]) -> Tuple[str, bool]:
        """
        流式对话（抽象方法，子类必须实现）

        Args:
            msg: 用户消息
            callback: 流式输出回调函数

        Returns:
            Tuple[str, bool]: (助手完整回复, 是否使用了工具调用)
        """
        pass

    # NOTE: 2026-05-15 gen by tea_agent, 支持图片附件：msg 可为 str 或 {"text": str, "images": [str]}
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
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })

    def get_recent_messages(self) -> List[Dict]:
        """获取最近的消息（排除系统消息）"""
        return [m for m in self.messages if m["role"] != "system"]

    # NOTE: 2026-05-03 06:37:41, self-evolved by tea_agent --- basesession.py: 添加 _repair_incomplete_tool_chains 修复中断导致的残缺工具调用链
# NOTE: 2026-04-28, self-evolved by claude-agent ---
    # 从加载的历史消息中清除 reasoning_content。
    # reasoning_content 是 DeepSeek thinking 模式下的会话内状态，
    # 只在一个 API 会话内有效。从数据库加载的历史消息中的
    # reasoning_content 属于之前的 API 会话，传回新会话将导致
    # DeepSeek API 返回 400 错误：
    # "The reasoning_content in the thinking mode must be passed back to the API."
    @staticmethod
    def _strip_reasoning_content(messages: List[Dict]) -> None:
        """
        原地清除消息列表中的 reasoning_content 字段。
        
        注意：对于包含 tool_calls 的 assistant 消息，必须保留 reasoning_content，
        否则 DeepSeek API 会返回 400 错误。
        """
        for msg in messages:
            # 如果是助手消息且包含工具调用，则保留 reasoning_content
            # if msg.get("role") == "assistant" and msg.get("tool_calls"):
            if msg.get("role") == "assistant":
                continue
            msg.pop("reasoning_content", None)

    # NOTE: 2026-05-20 gen by tea_agent, L1压缩：首尾各1024字节按换行对齐，替代首尾3行策略
    @staticmethod
    def _compress_tool_content(content: str, max_chars: int = 2048) -> str:
        """
        L1 工具输出压缩：首尾各 1024 字节，按换行对齐。

        策略：
        - 短输出（≤max_chars 字节）：原样保留
        - 长输出：保留首 1024 字节 + 尾 1024 字节，按换行边界对齐避免截断半行

        Args:
            content: 原始工具输出
            max_chars: 阈值字节数，超过则触发首尾截断

        Returns:
            压缩后的输出摘要
        """
        if not content:
            return content

        # 编码为字节以准确计算字节长度（与 API token 计数一致）
        raw = content.encode("utf-8")
        total_bytes = len(raw)

        if total_bytes <= max_chars:
            return content

        half = max_chars // 2  # 各保留 1024 字节

        # 前半部分：从 half 位置向前找最近换行
        head_end = half
        if head_end > 0:
            # 向后找换行
            nl = raw.find(b'\n', head_end)
            if nl != -1 and nl < half + 256:
                head_end = nl
            else:
                # 向前找换行
                nl = raw.rfind(b'\n', 0, head_end)
                if nl != -1 and nl > half - 256:
                    head_end = nl

        head_bytes = raw[:head_end]

        # 后半部分：从尾部 half 位置向后找最近换行
        tail_start = total_bytes - half
        if tail_start > 0:
            nl = raw.rfind(b'\n', tail_start, total_bytes)
            if nl != -1 and nl > tail_start - 256:
                tail_start = nl + 1  # 从换行后开始
            else:
                nl = raw.find(b'\n', tail_start)
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

    # NOTE: 2026-05-20 gen by tea_agent, L1压缩：对 assistant tool_calls 参数截断 + 保留最终 assistant 消息完整
    @staticmethod
    def _compress_tool_rounds(rounds: List[Dict]) -> List[Dict]:
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

        n = len(rounds)
        result = []

        for i, rd in enumerate(rounds):
            role = rd.get("role", "")
            is_last = (i == n - 1)

            if role == "user":
                # user 消息完整保留
                result.append(dict(rd))

            elif role == "assistant":
                if rd.get("tool_calls") and not is_last:
                    # 中间 assistant 消息（含工具调用）：压缩参数
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
                                        args_str[:1024] +
                                        f"\n... [L1截断: {args_bytes}B 参数, 保留首1024B] ...\n" +
                                        args_str[-1024:]
                                    )
                            tc_copy["function"] = func
                        new_tc.append(tc_copy)
                    compressed["tool_calls"] = new_tc
                    result.append(compressed)
                else:
                    # 最终 assistant 消息（末尾，无 tool_calls 或恰好是最后一个）：完整保留
                    result.append(dict(rd))

            elif role == "tool":
                # tool 消息：压缩输出
                compressed = dict(rd)
                compressed["content"] = BaseChatSession._compress_tool_content(
                    rd.get("content", "")
                )
                result.append(compressed)

            else:
                # system 等其他角色
                result.append(dict(rd))

        return result

# NOTE: 2026-05-04 14:53:44, self-evolved by tea_agent --- 补回 _repair_incomplete_tool_chains 缺失的 @staticmethod 和 def 行，修复死代码导致的 400 错误
    @staticmethod
    def _repair_incomplete_tool_chains(rounds: List[Dict]) -> List[Dict]:
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

        result: List[Dict] = []
        # 追踪尚未匹配的 tool_call_id -> 在 result 中的起始索引
        pending: Dict[str, int] = {}
        last_safe_len = 0  # 最后安全点：所有 pending 已清零时的 result 长度

        for i, rd in enumerate(rounds):
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
                if isinstance(tc_list, list):
                    tc_ids = [tc.get("id", "") for tc in tc_list if tc.get("id")]
                else:
                    tc_ids = []

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

# NOTE: 2026-04-30 10:02:24, self-evolved by tea_agent --- load_history支持recent_turns参数，旧轮次仅user+ai，最近N轮含完整工具链
    def load_history(self, conversations: List[Dict], summary: str = "", recent_turns: int = 10,
                     level2: list = None, semantic_summary: str = "", tool_chain_summary: str = ""):
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
        self._level2 = level2 or []

        # ── Level 1: 最新一轮压缩加载 ──
        total = len(conversations)
        if total == 0:
            self._history_summary = ""  # 兼容旧代码
            logger.info("加载历史 0条 (新主题)")
            return

        # 最新一条作为 Level 1（压缩工具链）
        last_conv = conversations[-1]
        # NOTE: 2026-05-18 gen by tea_agent, 修复 JSON 格式 user_msg（含图片）的解析
        raw_user_msg = last_conv["user_msg"]
        user_entry = {"role": "user"}
        if isinstance(raw_user_msg, str) and raw_user_msg.startswith('{'):
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
            # NOTE: 2026-05-20 gen by tea_agent, L1压缩：工具参数>2048B截断，工具输出首尾各1024B
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
        """裁剪消息，保持最近N条"""
        if len(self.messages) <= self.max_history * 2 + 1:
            return

        system_msg = self.messages[0]
        recent = self.messages[-(self.max_history * 2):]
        self.messages = [system_msg] + recent
