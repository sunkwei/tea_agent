# NOTE: 2026-05-06 09:01:04, self-evolved by tea_agent --- C2: 将 _generate_topic_summary 从 main_db_gui.py 提取到 session_summarizer.py 消除循环依赖
"""
会话摘要模块
负责历史摘要、Topic 摘要、消息压缩等功能

摘要生命周期:
1. 历史摘要 (History Summary) - 将会话早期的旧消息压缩为摘要
2. Topic 摘要 (Topic Summary)  - 为整个会话主题生成简短标题
3. 消息压缩 (Message Compact)  - 截断超长消息，控制 Token 消耗
"""

# NOTE: 2026-05-07 11:29:46, self-evolved by tea_agent --- session_summarizer.py 添加 logging import 和模型调用 DEBUG/WARNING 日志
import re
import logging
from typing import List, Dict, Tuple, Any, Optional, Callable

from tea_agent.session_prompts import (
    HISTORY_SUMMARIZE_SYSTEM,
    HISTORY_SUMMARIZE_USER,
    TOPIC_SUMMARY_SYSTEM,
    TOPIC_SUMMARY_USER_TEMPLATE,
)

logger = logging.getLogger("session.summarizer")

# NOTE: 2026-05-06 gen by claude, 从 main_db_gui.py 提取，消除 agent_core → main_db_gui 循环依赖
# ── Topic 摘要 Prompt（与 GUI 共用）──────────────────

# NOTE: 2026-05-01 08:17:23, self-evolved by tea_agent --- _generate_topic_summary: min_length从2提高到5，提示词强化中文自然表达
# NOTE: 2026-05-01 20:12:32, self-evolved by tea_agent --- 更新 system prompt：强调基于用户输入概括，不基于 AI 回复
# NOTE: 2026-05-04 14:58:14, self-evolved by tea_agent --- Prompt 模板更新：明确使用最近10条用户输入提取标题
_SHARED_TOPIC_SUMMARY_SYSTEM = (
    "你是一个摘要生成器。根据最近10条用户输入，生成不超过20字的自然中文摘要标题。"
    "要求："
    "1. 根据用户的发言概括对话主题，不要基于 AI 的回复来概括。"
    "2. 用日常口语表达，像人聊天时随口说的标题那样。"
    "3. 至少6个字以上，禁止输出残缺句子或单字。"
    "4. 不使用书名号、引号、多余修饰词。"
    "直接输出摘要文本，不要任何额外说明。"
)

# NOTE: 2026-05-01 20:12:10, self-evolved by tea_agent --- 摘要生成只用 user input（去除 AI 回复），基于最近多轮而非最后一轮
_SHARED_TOPIC_SUMMARY_USER_TEMPLATE = (
    "以下是最近10条用户输入：\n\n{user_msgs}\n\n"
    "请根据这些用户输入，生成不超过20字的摘要标题："
)


# NOTE: 2026-05-06 gen by claude, 提取自 main_db_gui.py，agent_core 和 main_db_gui 共用
def generate_topic_summary_shared(client, model: str, conversations: List[Dict]) -> Optional[str]:
    """[DISABLED: 2026-05-20] not imported"""
    pass  # DISABLED

def _get_cheap_params(defaults=None):
    """返回 cheap 模型 {temperature, max_tokens}，失败时使用传入的 defaults 或保守值。"""
    d = defaults or {"temperature": 0.3, "max_tokens": 500}
    try:
        from .config import get_config
        eff = get_config().get_effective_params("cheap", "mixed")
        return {
            "temperature": eff.get("temperature", d["temperature"]),
            "max_tokens": eff.get("max_tokens", d["max_tokens"]),
        }
    except Exception:
        return d


class SessionSummarizerMixin:
    """
    摘要管理 Mixin 类，提供历史摘要、Topic 摘要、消息压缩功能。

    依赖属性 (由使用者提供):
        messages: 消息列表，当前会话的完整对话历史
        keep_turns: 保留最近 N 轮对话 (默认 5)
        max_tool_output: 工具输出最大字符数 (默认 128KB)
        max_assistant_content: 助手回复最大字符数 (默认 128KB)
        tool_log: 可选的日志回调函数
        _get_summarize_client(): 获取摘要客户端的方法

    内部状态:
        _history_summary: 累积的历史摘要文本
    """

# NOTE: 2026-05-04 16:43:20, self-evolved by tea_agent --- 修复 SessionSummarizerMixin.__init__ 覆盖 self.messages 为空列表的 bug
    def __init__(self):
        # NOTE: 不设置 self.messages，由 BaseChatSession.__init__ 负责初始化
        # 否则会覆盖基类已填充的 system message

        # 摘要配置
        self.keep_turns: int = 5
        self.max_tool_output: int = 128 * 1024
        self.max_assistant_content: int = 128 * 1024

        # 日志回调
        self.tool_log: Optional[Callable[[str], None]] = None

    # ──────────────────────────────────────────────
    # 历史摘要 (History Summary)
    # ──────────────────────────────────────────────

    def count_user_msg(self) -> int:
        """[DISABLED: 2026-05-20] no callers"""
        pass  # DISABLED

    def _call_summarize_api(self, cli, mdl, messages, temperature=0.1, max_tokens=500):
        """
        调用 LLM 生成摘要，显式禁用 thinking。

        Args:
            cli: OpenAI 客户端实例
            mdl: 模型名称
            messages: API 消息列表
            temperature: 温度参数
            max_tokens: 最大输出 token

        Returns:
            API 响应对象
        """
# NOTE: 2026-05-07 11:30:01, self-evolved by tea_agent --- _call_summarize_api 添加模型请求 DEBUG 日志和失败 WARNING 日志
        try:
            logger.debug(f"summarize API request: model={mdl}, msgs={len(messages)}, temperature={temperature}, max_tokens={max_tokens}")
            return cli.chat.completions.create(
                model=mdl,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except Exception as e:
            err_str = str(e).lower()
            if 'thinking' in err_str or 'extra_body' in err_str:
                # 模型不支持 thinking 参数，回退到不带 extra_body 的调用
                logger.debug(f"summarize API: thinking disabled not supported, retrying without extra_body")
                return cli.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            logger.warning(f"summarize API call failed: model={mdl}, error={e}")
            raise

    def _summarize_old_history(self) -> None:
        """
        持久化摘要逻辑：
            1. 获取当前 topic 下所有未摘要的对话记录 (is_summarized=0)
            2. 如果数量超过 keep_turns，则将多出的部分 (最早的 N 条) 提取出来
            3. 将这些对话内容与现有摘要合并，调用 LLM 生成新摘要
            4. 更新数据库：更新摘要文本，并将这些对话标记为已摘要
            5. 同步内存：更新 self._history_summary 并裁剪 self.messages
        """
        topic_id = getattr(self, "current_topic_id", None)
        storage = getattr(self, "storage", None)
        if not (topic_id and storage):
            return

        # 1. 获取未摘要的对话
        unsummarized = storage.get_unsummarized_conversations(topic_id)
        if len(unsummarized) <= self.keep_turns:
            return

        # 2. 确定需要摘要的范围 (除了最近的 keep_turns 条，其余全部摘要)
        num_to_summarize = len(unsummarized) - self.keep_turns
        convs_to_summarize = unsummarized[:num_to_summarize]
        
        # 3. 提取对话文本
        old_text = self._conversations_to_text(convs_to_summarize)
        if not old_text:
            return

        # 获取旧摘要
        old_summary = storage.get_topic_summary(topic_id) or ""
        
        # 构建 Prompt
        existing = (
            f"已有摘要：{old_summary}\n\n"
            if old_summary
            else ""
        )

        try:
            cli, mdl = self._get_summarize_client()
            # NOTE: 2026-04-29, self-evolved by claude-agent ---
            # 判断是否使用便宜模型，以便正确路由 token 统计
            is_cheap = (
                hasattr(self, '_cheap_client')
                and self._cheap_client is not None
                and cli is self._cheap_client
            )
# NOTE: 2026-05-17 08:57:54, self-evolved by tea_agent --- 摘要调用改用 cheap 模型 config 参数
# NOTE: 2026-05-17 08:59:29, self-evolved by tea_agent --- 简化摘要调用 — 使用 _get_cheap_params helper
            # NOTE: 2026-04-29, self-evolved by claude-agent ---
            # 使用统一入口 _call_summarize_api，显式禁用 thinking 节省 token
            cheap_params = _get_cheap_params({"temperature": 0.1, "max_tokens": 500})
            response = self._call_summarize_api(
                cli, mdl,
                messages=[
                    {"role": "system", "content": HISTORY_SUMMARIZE_SYSTEM},
                    {
                        "role": "user",
                        "content": HISTORY_SUMMARIZE_USER.format(
                            existing=existing, old_text=old_text
                        ),
                    },
                ],
                temperature=cheap_params["temperature"],
                max_tokens=cheap_params["max_tokens"],
            )
            # NOTE: 2026-04-29, self-evolved by claude-agent ---
            # 统计便宜模型 token 用量
            if hasattr(self, '_track_api_usage'):
                self._track_api_usage(response, is_cheap=is_cheap)
                
            content = response.choices[0].message.content
            if isinstance(content, str):
                new_summary = content.strip()
                
                # 4. 更新数据库
                last_conv_id = convs_to_summarize[-1]['id']
                storage.update_topic_summary(topic_id, new_summary, last_summarized_id=last_conv_id)
                for conv in convs_to_summarize:
                    storage.mark_as_summarized(conv['id'])
                
                # 5. 同步内存
                self._history_summary = new_summary
                
                # 裁剪 self.messages，保持与数据库同步
                boundary = self._find_recent_boundary()
                if boundary > 1:
                    self.messages = [self.messages[0]] + self.messages[boundary:]

                if self.tool_log:
                    self.tool_log(f"📝 历史摘要更新：{new_summary}")

# NOTE: 2026-05-07 11:30:07, self-evolved by tea_agent --- _summarize_old_history 异常改为 WARNING 日志
        except Exception as e:
            logger.warning(f"历史摘要生成失败: model={mdl}, error={e}")
            if self.tool_log:
                self.tool_log(f"⚠️ 摘要生成失败: {e}")
        return None

    def _conversations_to_text(self, conversations: List[Dict], max_per_msg: int = 500) -> str:
        """将对话记录列表转为文本，用于摘要生成"""
        lines = []
        for conv in conversations:
            # 用户消息
            u_msg = conv.get("user_msg", "")
            lines.append(f"[USER]: {u_msg[:max_per_msg]}")
            
            # AI 消息（含工具调用链）
            rounds = conv.get("rounds_json_parsed")
            if rounds and conv.get("is_func_calling"):
                for rd in rounds:
                    role = rd.get("role", "")
                    content = rd.get("content", "")
                    if role == "assistant" and rd.get("tool_calls"):
                        tc_names = [tc["function"]["name"] for tc in rd["tool_calls"]]
                        lines.append(f"[ASSISTANT 调用工具]: {', '.join(tc_names)}")
                        if content:
                            lines.append(f"[ASSISTANT]: {content[:max_per_msg]}")
                    elif role == "tool":
                        lines.append(f"[工具结果]: {content[:max_per_msg]}")
                    elif role == "assistant" and content:
                        lines.append(f"[ASSISTANT]: {content[:max_per_msg]}")
            else:
                ai_msg = conv.get("ai_msg", "")
                lines.append(f"[ASSISTANT]: {ai_msg[:max_per_msg]}")
                
        return "\n".join(lines)

    # ──────────────────────────────────────────────
    # Topic 摘要 (Topic Summary)
    # ──────────────────────────────────────────────

    def generate_topic_summary(self, conversations):
        """[DISABLED: 2026-05-20] class method — no callers"""
        pass  # DISABLED

    def _extract_user_messages(self, conversations, max_len=200):
        """[DISABLED: 2026-05-20] only used by dead generate_topic_summary"""
        pass  # DISABLED

    def _clean_topic_summary(self, raw: str) -> Optional[str]:
        """[DISABLED: 2026-05-20] only used by dead generate_topic_summary"""
        pass  # DISABLED

    def _build_api_messages(self) -> List[Dict]:
        """[DISABLED: 2026-05-20] raises Exception — real impl in onlinesession.py"""
        pass  # DISABLED

    def _compact_message(self, msg: Dict) -> Dict:
        """[DISABLED: 2026-05-20] no references"""
        pass  # DISABLED

    # ──────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────

    def _messages_to_text(self, messages, max_per_msg=500):
        """[DISABLED: 2026-05-20] no references"""
        pass  # DISABLED

    def _find_recent_boundary(self) -> int:
        """
        找到最近 keep_turns 轮对话的起始索引。

        从后向前遍历消息列表，统计用户消息数量（排除摘要消息），找到第 keep_turns 个
        用户消息的位置。

        Returns:
            最近 N 轮对话的起始索引 (至少为 1，跳过系统消息)
        """
        user_count = 0

        for i in range(len(self.messages) - 1, 0, -1):
            msg = self.messages[i]
            if msg.get("role") == "user":                
                user_count += 1
                if user_count >= self.keep_turns:
                    return i

        # 不足 keep_turns 轮，保留全部 (跳过系统消息)
        return 1
    
    def _find_last_need_summary_pair(self) -> Tuple[int, int]:
        """[DISABLED: 2026-05-20] no references"""
        pass  # DISABLED

    def reset_summary_state(self) -> None:
        """[DISABLED: 2026-05-20] no callers"""
        pass  # DISABLED


