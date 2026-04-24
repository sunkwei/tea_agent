def toolkit_dump_topic(role: str = "all") -> dict:
    """
    将当前所有会话内容从数据库导出到 dump_{date} 子目录。
    每个 topic 对应一个 markdown 文件。

    Args:
        role: 导出范围。"user" 仅导出用户输入，"all" 导出所有内容（含 AI 回复和工具调用链）。
    """
    import os
    import json
    from datetime import datetime
    from pathlib import Path

    base_dir = os.getcwd()
    # db_path = os.path.join(base_dir, "chat_history.db")
    db_path = Path.home() / ".tea_agent" / "chat_history.db"
    if not os.path.exists(db_path):
        return {"status": "error", "message": f"数据库文件不存在: {db_path}"}

    from tea_agent.store import Storage
    storage = Storage(str(db_path))

    date_str = datetime.now().strftime("%Y%m%d")
    dump_dir = os.path.join(base_dir, f"dump_{date_str}")
    os.makedirs(dump_dir, exist_ok=True)

    topics = storage.list_topics()
    if not topics:
        return {"status": "info", "message": "没有找到任何 topic", "path": dump_dir}

    exported_count = 0
    for topic in topics:
        topic_id = topic.get("topic_id")
        title = topic.get("title", f"topic_{topic_id}")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
        filename = f"{topic_id}_{safe_title}.md"
        filepath = os.path.join(dump_dir, filename)

        conversations = storage.get_conversations(topic_id)
        token_stats = storage.get_topic_tokens(topic_id)

        lines = []
        lines.append(f"# {title}\n")
        lines.append(f"**创建时间:** {topic.get('create_stamp', 'N/A')}")
        lines.append(f"**最后更新:** {topic.get('last_update_stamp', 'N/A')}")
        lines.append("")
        lines.append(f"**Token 统计:**")
        lines.append(f"- 总消耗: {token_stats.get('total_tokens', 0):,}")
        lines.append(f"- Prompt Tokens: {token_stats.get('total_prompt_tokens', 0):,}")
        lines.append(f"- Completion Tokens: {token_stats.get('total_completion_tokens', 0):,}")
        lines.append(f"- 对话轮次: {token_stats.get('conversation_count', 0)}")
        lines.append(f"- 导出模式: {'仅用户输入' if role == 'user' else '完整内容'}")
        lines.append("")
        lines.append("---\n")
        lines.append("## 对话记录\n")

        for conv in conversations:
            stamp = conv.get("stamp", "")
            lines.append(f"### [{stamp}]\n")

            if role == "user":
                # 仅导出用户输入
                lines.append(f"**用户:** {conv.get('user_msg', '')}\n")
            else:
                # 导出完整内容
                lines.append(f"**用户:** {conv.get('user_msg', '')}\n")
                lines.append(f"**AI:** {conv.get('ai_msg', '')}\n")

                rounds = conv.get("rounds_json_parsed")
                if rounds and conv.get("is_func_calling"):
                    lines.append("**工具调用链:**\n")
                    for rd in rounds:
                        role_rd = rd.get("role", "")
                        if role_rd == "assistant":
                            content = rd.get("content", "")
                            tc = rd.get("tool_calls")
                            if tc:
                                for t in tc:
                                    fn = t.get("function", {})
                                    lines.append(f"- 🔧 调用工具: `{fn.get('name', '')}`")
                                    args = fn.get("arguments", "")
                                    if args:
                                        lines.append(f"  - 参数: {args}")
                            if content:
                                lines.append(f"- 回复: {content}")
                        elif role_rd == "tool":
                            content = rd.get("content", "")
                            lines.append(f"- 📋 工具结果: {content[:200]}..." if len(content) > 200 else f"- 📋 工具结果: {content}")
                    lines.append("")
            lines.append("---\n")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        exported_count += 1

    return {
        "status": "success",
        "message": f"成功导出 {exported_count} 个 topic",
        "path": dump_dir
    }

def meta_toolkit_dump_topic() -> dict:
    return {"type": "function", "function": {"name": "toolkit_dump_topic", "description": "将当前所有会话内容从数据库导出到 dump_{date} 子目录，每个 topic 对应一个 markdown 文件。", "parameters": {"type": "object", "properties": {"role": {"type": "string", "enum": ["user", "all"], "description": "导出范围：user 仅导出用户输入，all 导出完整内容"}}, "required": []}}}

if __name__ == "__main__":
    import sys, os, json
    # 将项目根目录添加到 sys.path 以支持直接运行
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root_dir not in sys.path:
        sys.path.append(root_dir)
        
    print("开始导出所有 Topic...")
    res = toolkit_dump_topic("user")
    print(json.dumps(res, indent=2, ensure_ascii=False))