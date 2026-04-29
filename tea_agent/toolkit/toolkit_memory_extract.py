## llm generated tool func, created Wed Apr 29 09:42:40 2026
# version: 1.0.0

# @2026-04-29 gen by deepseek-v4-pro, 内置工具: 提取对话记忆
def toolkit_memory_extract(topic_id: int = -1, max_chars: int = 4000):
    """
    从指定 topic 的未摘要会话中提取对话文本，供 Agent 分析并提取记忆。
    
    Agent 应分析返回的对话文本，识别以下信息并用 toolkit_memory_add 保存：
    - instruction: 用户明确说"记住"的规则/指令 → priority=0
    - preference: 用户偏好/习惯 → priority=1
    - reminder: 有时效提醒 → 带上 expires_at
    - fact: 技术事实/决策 → priority=2
    - general: 其他参考信息 → priority=3
    """
    try:
        from tea_agent.store import get_storage
        storage = get_storage()
        
        # 获取未摘要对话
        unsummarized = storage.get_unsummarized_conversations(topic_id) if topic_id > 0 else []
        
        if not unsummarized:
            return "📭 没有未摘要的对话可提取。可以手动使用 toolkit_memory_add 添加记忆。"
        
        # 构建对话文本
        lines = [f"📄 从 topic #{topic_id} 的 {len(unsummarized)} 条未摘要对话中提取:", ""]
        
        total_chars = 0
        for i, conv in enumerate(unsummarized):
            user = conv.get("user_msg", "")[:300]
            ai = conv.get("ai_msg", "")[:500]
            entry = f"--- 对话 {i+1} ---\n用户: {user}\n助手: {ai}\n"
            if total_chars + len(entry) > max_chars:
                lines.append(f"... 还有 {len(unsummarized) - i} 条对话因长度限制未显示")
                break
            lines.append(entry)
            total_chars += len(entry)
        
        lines.append("")
        lines.append("--- 请分析以上对话，识别值得长期保存的信息 ---")
        lines.append("使用 toolkit_memory_add 逐条添加记忆。")
        lines.append("分类参考: instruction(指令)/preference(偏好)/fact(事实)/reminder(提醒)/general(一般)")
        lines.append("优先级: 0=CRITICAL(必须遵循) 1=HIGH 2=MEDIUM 3=LOW")
        
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 提取记忆文本失败: {e}"

def meta_toolkit_memory_extract() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_extract", "description": "从指定 topic 的未摘要对话中提取待分析文本，供 Agent 识别有价值的信息后通过 toolkit_memory_add 保存为记忆。手动触发记忆提取流程。", "parameters": {"type": "object", "properties": {"topic_id": {"type": "integer", "description": "要提取记忆的 topic ID，-1 表示当前活跃 topic"}, "max_chars": {"type": "integer", "description": "返回对话文本的最大字符数", "default": 4000}}, "required": []}}}


def meta_toolkit_memory_extract() -> dict:
    return {"type": "function", "function": {"name": "toolkit_memory_extract", "description": "从指定 topic 的未摘要对话中提取待分析文本，供 Agent 识别有价值的信息后通过 toolkit_memory_add 保存为记忆。手动触发记忆提取流程。", "parameters": {"type": "object", "properties": {"topic_id": {"type": "integer", "description": "要提取记忆的 topic ID，-1 表示当前活跃 topic"}, "max_chars": {"type": "integer", "description": "返回对话文本的最大字符数", "default": 4000}}, "required": []}}}
