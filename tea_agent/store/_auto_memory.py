# version: 1.0.0

"""
自动记忆提取模块 (AutoMemoryExtractor)

在对话结束时自动分析并提取值得长期保存的记忆：
1. 获取对话摘要
2. LLM分析：哪些信息值得长期保存
3. 自动分类：instruction/preference/fact
4. 去重检查：避免重复记忆
5. 自动入库
"""

import logging
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("Storage.AutoMemory")

# 记忆提取提示词
EXTRACTION_PROMPT = """分析以下对话，提取值得长期保存的信息。

对话内容:
{conversation}

请以JSON数组格式返回，每个记忆包含:
- content: 记忆内容（简洁明了，50-200字）
- category: 分类（instruction/preference/fact/reminder/general）
- importance: 重要度（1-5）
- tags: 标签（逗号分隔）

分类说明:
- instruction: 用户明确的指令或要求
- preference: 用户的偏好或习惯
- fact: 技术事实或知识点
- reminder: 需要记住的提醒
- general: 一般信息

只提取真正值得长期保存的信息，避免提取临时性或低价值内容。

返回格式: [{{"content": "...", "category": "...", "importance": 3, "tags": "..."}}]
如果没有值得保存的信息，返回空数组 []"""


class AutoMemoryExtractor:
    """自动记忆提取器"""
    
    def __init__(self, storage):
        """初始化
        
        Args:
            storage: Storage 实例
        """
        self.storage = storage
    
    def extract_from_topic(self, topic_id: str, force: bool = False) -> Dict:
        """从主题对话中自动提取记忆
        
        Args:
            topic_id: 主题ID
            force: 是否强制提取（忽略去重）
            
        Returns:
            提取结果统计
        """
        try:
            # 1. 获取未提取的对话
            conversations = self._get_unextracted_conversations(topic_id)
            if not conversations:
                return {"status": "no_new_conversations", "extracted": 0}
            
            # 2. 合并对话内容
            conversation_text = self._merge_conversations(conversations)
            
            # 3. 调用LLM提取记忆
            extracted_memories = self._extract_with_llm(conversation_text)
            
            # 4. 去重并入库
            saved_count = 0
            skipped_count = 0
            
            for memory in extracted_memories:
                # 去重检查
                if not force and self._is_duplicate(memory["content"]):
                    skipped_count += 1
                    continue
                
                # 保存记忆
                self.storage.add_memory(
                    content=memory["content"],
                    category=memory.get("category", "general"),
                    importance=memory.get("importance", 3),
                    tags=memory.get("tags", ""),
                    source_topic_id=topic_id
                )
                saved_count += 1
            
            # 5. 标记对话为已提取
            self._mark_conversations_extracted(conversations)
            
            logger.info(f"从topic {topic_id} 提取记忆: 保存{saved_count}条, 跳过{skipped_count}条")
            
            return {
                "status": "success",
                "extracted": saved_count,
                "skipped": skipped_count,
                "total_conversations": len(conversations)
            }
            
        except Exception as e:
            logger.error(f"自动提取记忆失败: {e}")
            return {"status": "error", "error": str(e)}
    
    def _get_unextracted_conversations(self, topic_id: str) -> List[Dict]:
        """获取未提取的对话"""
        c = self.storage.conn.cursor()
        c.execute("""
            SELECT id, user_msg, ai_msg, stamp 
            FROM conversations 
            WHERE topic_id = ? AND is_summarized = 0
            ORDER BY stamp ASC
        """, (topic_id,))
        
        rows = c.fetchall()
        c.close()
        
        return [dict(r) for r in rows]
    
    def _merge_conversations(self, conversations: List[Dict]) -> str:
        """合并对话为文本"""
        parts = []
        for conv in conversations[:10]:  # 限制最多10轮
            user_msg = conv.get("user_msg", "")[:500]
            ai_msg = conv.get("ai_msg", "")[:1000]
            parts.append(f"用户: {user_msg}\n助手: {ai_msg}")
        
        return "\n\n".join(parts)
    
    def _extract_with_llm(self, conversation_text: str) -> List[Dict]:
        """调用LLM提取记忆
        
        注意：此方法需要外部LLM支持
        实际实现中应该调用 agent 的 LLM 能力
        """
        # 这里返回模拟结果，实际应该调用LLM
        # 在实际集成时，需要通过 agent 的 LLM 接口调用
        
        # 简单的关键词提取作为备选方案
        memories = []
        
        # 提取可能的指令
        if any(kw in conversation_text for kw in ["请", "帮我", "记住", "不要", "必须"]):
            memories.append({
                "content": "用户表达了某些偏好或指令",
                "category": "instruction",
                "importance": 3,
                "tags": "auto_extracted"
            })
        
        return memories
    
    def _is_duplicate(self, content: str, threshold: float = 0.7) -> bool:
        """检查是否与现有记忆重复
        
        使用简单的文本相似度检查
        """
        try:
            existing_memories = self.storage.get_active_memories(limit=100)
            
            for mem in existing_memories:
                similarity = self._calculate_similarity(content, mem["content"])
                if similarity > threshold:
                    return True
            
            return False
            
        except Exception:
            return False
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度（简单的Jaccard系数）"""
        # 转换为字符集
        set1 = set(text1)
        set2 = set(text2)
        
        # Jaccard系数
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        if union == 0:
            return 0.0
        
        return intersection / union
    
    def _mark_conversations_extracted(self, conversations: List[Dict]):
        """标记对话为已提取"""
        c = self.storage.conn.cursor()
        for conv in conversations:
            c.execute(
                "UPDATE conversations SET is_summarized = 1 WHERE id = ?",
                (conv["id"],)
            )
        self.storage.conn.commit()
        c.close()
    
    def get_extraction_stats(self, topic_id: Optional[str] = None) -> Dict:
        """获取提取统计"""
        c = self.storage.conn.cursor()
        
        # 总记忆数
        c.execute("SELECT COUNT(*) as total FROM memories WHERE is_active = 1")
        total_memories = c.fetchone()["total"]
        
        # 按来源统计
        if topic_id:
            c.execute(
                "SELECT COUNT(*) as cnt FROM memories WHERE source_topic_id = ?",
                (topic_id,)
            )
            from_topic = c.fetchone()["cnt"]
        else:
            from_topic = None
        
        # 按分类统计
        c.execute(
            "SELECT category, COUNT(*) as cnt FROM memories WHERE is_active = 1 GROUP BY category"
        )
        by_category = {r["category"]: r["cnt"] for r in c.fetchall()}
        
        c.close()
        
        return {
            "total_memories": total_memories,
            "from_topic": from_topic,
            "by_category": by_category
        }
