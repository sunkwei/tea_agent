"""
智能 Compaction — 智能压缩历史对话。

设计灵感:
  learn-claude-code 的 Context Compaction

功能:
  - 保留最近 N 轮完整对话
  - 旧对话压缩为摘要
  - 关键代码块完整保留
  - 工具输出智能截断

用法:
    from tea_agent.compaction import Compactor
    
    compactor = Compactor(max_tokens=32000)
    compressed = compactor.compact(messages)
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import re

import logging

logger = logging.getLogger(__name__)


@dataclass
class CompactionConfig:
    """压缩配置"""
    max_tokens: int = 32000           # 最大 token 数
    keep_recent_rounds: int = 5       # 保留最近 N 轮完整对话
    summarize_old: bool = True        # 是否压缩旧对话
    keep_code_blocks: bool = True     # 是否保留完整代码块
    truncate_tool_output: int = 500   # 工具输出截断长度
    preserve_keywords: List[str] = None  # 保留关键词相关内容
    
    def __post_init__(self):
        if self.preserve_keywords is None:
            self.preserve_keywords = []


@dataclass
class CompactResult:
    """压缩结果"""
    messages: List[Dict]              # 压缩后的消息
    original_count: int               # 原始消息数
    compressed_count: int             # 压缩后消息数
    tokens_saved: int                 # 节省的 token 数
    summary: str                      # 压缩摘要
    
    @property
    def compression_ratio(self) -> float:
        """压缩率"""
        if self.original_count == 0:
            return 0.0
        return 1.0 - (self.compressed_count / self.original_count)


class Compactor:
    """智能压缩器"""
    
    # 需要保留的关键词
    DEFAULT_PRESERVE_KEYWORDS = [
        "重要", "关键", "必须", "注意", "警告",
        "important", "critical", "must", "note", "warning",
        "TODO", "FIXME", "BUG", "HACK",
    ]
    
    def __init__(self, config: Optional[CompactionConfig] = None):
        """
        Args:
            config: 压缩配置
        """
        self.config = config or CompactionConfig()
        
        # 合并默认保留关键词
        if self.config.preserve_keywords is None:
            self.config.preserve_keywords = []
        self.config.preserve_keywords.extend(self.DEFAULT_PRESERVE_KEYWORDS)
    
    def compact(self, messages: List[Dict]) -> CompactResult:
        """
        压缩消息列表。
        
        Args:
            messages: 原始消息列表
            
        Returns:
            压缩结果
        """
        original_count = len(messages)
        
        if original_count == 0:
            return CompactResult(
                messages=[],
                original_count=0,
                compressed_count=0,
                tokens_saved=0,
                summary="无消息"
            )
        
        # 1. 分离系统消息和对话消息
        system_messages = [m for m in messages if m.get("role") == "system"]
        conversation = [m for m in messages if m.get("role") != "system"]
        
        if len(conversation) <= self.config.keep_recent_rounds * 2:
            # 对话轮次较少，无需压缩
            return CompactResult(
                messages=messages,
                original_count=original_count,
                compressed_count=original_count,
                tokens_saved=0,
                summary="对话较短，无需压缩"
            )
        
        # 2. 分离近期和历史对话
        recent_count = self.config.keep_recent_rounds * 2  # user + assistant
        recent = conversation[-recent_count:]
        history = conversation[:-recent_count]
        
        # 3. 压缩历史对话
        if self.config.summarize_old and history:
            compressed_history = self._compress_history(history)
        else:
            compressed_history = []
        
        # 4. 重新组装消息
        compacted = system_messages + compressed_history + recent
        
        # 5. 截断工具输出
        compacted = self._truncate_tool_outputs(compacted)
        
        # 6. 计算统计
        compressed_count = len(compacted)
        tokens_saved = self._estimate_tokens(messages) - self._estimate_tokens(compacted)
        
        summary = f"压缩 {original_count} → {compressed_count} 条消息, 节省 ~{tokens_saved} tokens"
        logger.info(f"📦 {summary}")
        
        return CompactResult(
            messages=compacted,
            original_count=original_count,
            compressed_count=compressed_count,
            tokens_saved=max(0, tokens_saved),
            summary=summary,
        )
    
    def _compress_history(self, history: List[Dict]) -> List[Dict]:
        """压缩历史对话"""
        compressed = []
        
        # 按轮次分组 (user + assistant)
        rounds = self._group_rounds(history)
        
        for i, (user_msg, assistant_msg) in enumerate(rounds):
            # 提取关键信息
            summary = self._summarize_round(user_msg, assistant_msg, i + 1)
            
            if summary:
                compressed.append({
                    "role": "system",
                    "content": f"[历史记录] 第 {i+1} 轮: {summary}"
                })
        
        return compressed
    
    def _group_rounds(self, messages: List[Dict]) -> List[Tuple[Optional[Dict], Optional[Dict]]]:
        """将消息按轮次分组"""
        rounds = []
        current_user = None
        
        for msg in messages:
            role = msg.get("role")
            
            if role == "user":
                if current_user is not None:
                    # 保存上一轮（无 assistant）
                    rounds.append((current_user, None))
                current_user = msg
            elif role == "assistant":
                rounds.append((current_user, msg))
                current_user = None
        
        # 保存最后一轮（无 assistant）
        if current_user is not None:
            rounds.append((current_user, None))
        
        return rounds
    
    def _summarize_round(
        self,
        user_msg: Optional[Dict],
        assistant_msg: Optional[Dict],
        round_num: int,
    ) -> str:
        """压缩单轮对话"""
        parts = []
        
        # 用户消息
        if user_msg:
            content = user_msg.get("content", "")
            # 提取关键部分
            key_part = self._extract_key_part(content)
            if key_part:
                parts.append(f"问: {key_part}")
        
        # AI 回复
        if assistant_msg:
            content = assistant_msg.get("content", "")
            # 检查是否有重要关键词
            if self._contains_preserve_keywords(content):
                # 包含重要关键词，保留更多内容
                key_part = self._extract_key_part(content, max_len=200)
            else:
                key_part = self._extract_key_part(content, max_len=100)
            
            if key_part:
                parts.append(f"答: {key_part}")
            
            # 检查工具调用
            tool_calls = assistant_msg.get("tool_calls", [])
            if tool_calls:
                tools_used = [tc.get("function", {}).get("name", "") for tc in tool_calls]
                tools_str = ", ".join(set(tools_used))
                parts.append(f"工具: {tools_str}")
        
        return " | ".join(parts) if parts else ""
    
    def _extract_key_part(self, content: str, max_len: int = 100) -> str:
        """提取关键部分"""
        if not content:
            return ""
        
        # 移除代码块
        content_no_code = re.sub(r'```[\s\S]*?```', '[代码块]', content)
        content_no_code = re.sub(r'`[^`]+`', '[代码]', content_no_code)
        
        # 取第一段
        lines = content_no_code.strip().split('\n')
        first_line = lines[0].strip() if lines else ""
        
        if len(first_line) > max_len:
            return first_line[:max_len] + "..."
        
        return first_line
    
    def _contains_preserve_keywords(self, content: str) -> bool:
        """检查是否包含需要保留的关键词"""
        content_lower = content.lower()
        for keyword in self.config.preserve_keywords:
            if keyword.lower() in content_lower:
                return True
        return False
    
    def _truncate_tool_outputs(self, messages: List[Dict]) -> List[Dict]:
        """截断工具输出"""
        if self.config.truncate_tool_output <= 0:
            return messages
        
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if len(content) > self.config.truncate_tool_output:
                    msg = {**msg, "content": content[:self.config.truncate_tool_output] + "...[截断]"}
            result.append(msg)
        
        return result
    
    def _estimate_tokens(self, messages: List[Dict]) -> int:
        """估算 token 数"""
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            total_chars += len(content)
        
        # 粗略估算: 1 token ≈ 4 字符 (中文) 或 4 字符 (英文)
        return total_chars // 4


class AdaptiveCompactor:
    """自适应压缩器 — 根据 token 预算动态调整"""
    
    def __init__(self, max_tokens: int = 32000):
        self.max_tokens = max_tokens
        self.compactor = Compactor(CompactionConfig(max_tokens=max_tokens))
    
    def compact_to_budget(self, messages: List[Dict], budget: int) -> CompactResult:
        """
        压缩到指定 token 预算。
        
        Args:
            messages: 原始消息
            budget: 目标 token 预算
            
        Returns:
            压缩结果
        """
        # 估算当前 token
        current_tokens = self.compactor._estimate_tokens(messages)
        
        if current_tokens <= budget:
            return CompactResult(
                messages=messages,
                original_count=len(messages),
                compressed_count=len(messages),
                tokens_saved=0,
                summary=f"当前 {current_tokens} tokens, 未超预算 {budget}"
            )
        
        # 需要压缩
        # 动态调整保留轮数
        needed_saving = current_tokens - budget
        saving_ratio = needed_saving / current_tokens
        
        if saving_ratio > 0.5:
            # 需要大幅压缩
            keep_rounds = 2
        elif saving_ratio > 0.3:
            keep_rounds = 3
        elif saving_ratio > 0.1:
            keep_rounds = 4
        else:
            keep_rounds = 5
        
        # 创建配置
        config = CompactionConfig(
            max_tokens=budget,
            keep_recent_rounds=keep_rounds,
        )
        
        compactor = Compactor(config)
        return compactor.compact(messages)
