import logging

logger = logging.getLogger("toolkit")

def _export_one_topic(storage, topic, role, dump_dir):
    """导出单个 topic 为 markdown 文件。返回导出的文件路径或 None。"""
    import os
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
    lines.append("**Token 统计:**")
    stats_items = [
        f"- 总消耗: {token_stats.get('total_tokens', 0):,}",
        f"- Prompt: {token_stats.get('total_prompt_tokens', 0):,}",
        f"- Completion: {token_stats.get('total_completion_tokens', 0):,}",
        f"- 便宜模型: {token_stats.get('total_cheap_tokens', 0):,}",
        f"- 嵌入模型: {token_stats.get('total_embedding_tokens', 0):,}",
        f"- 对话轮次: {token_stats.get('conversation_count', 0)}",
        f"- 导出模式: {'仅用户输入' if role == 'user' else '用户+AI终答' if role == 'final_msg' else '完整内容'}",
    ]
    lines.extend(stats_items)
    lines.append("")
    lines.append("---\n")
    lines.append("## 对话记录\n")

    for conv in conversations:
        stamp = conv.get("stamp", "")
        lines.append(f"### [{stamp}]\n")

        if role == "user":
            lines.append(f"**用户:** {conv.get('user_msg', '')}\n")
        elif role == "final_msg":
            # 跳过工具调用链，只输出用户和AI终答
            lines.append(f"**用户:** {conv.get('user_msg', '')}\n")
            lines.append(f"**AI:** {conv.get('ai_msg', '')}\n")
        else:
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
                        lines.append(f"- 📋 工具结果: {content}")
                lines.append("")
        lines.append("---\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return filepath


def toolkit_dump_topic(role: str = "all", topic_id: str = None) -> dict:
    """
    将会话内容从数据库导出到 dump_{date} 子目录。
    每个 topic 对应一个 markdown 文件。

    Args:
        role: 导出范围。"user" 仅导出用户输入，"final_msg" 用户+AI终答（跳过工具链），"all" 完整内容。
        topic_id: 指定 topic_id 则只导出该主题，否则导出全部。
    """
    logger.info(f"toolkit_dump_topic called: role={role!r}, topic_id={topic_id!r}")

    import os
    from datetime import datetime
    from pathlib import Path

    try:
        from tea_agent.config import get_config
        db_path = Path(get_config().paths.db_path_abs)
    except Exception:
        db_path = Path.home() / ".tea_agent" / "chat_history.db"
    if not os.path.exists(db_path):
        return {"status": "error", "message": f"数据库文件不存在: {db_path}"}

    from tea_agent.store import Storage
    storage = Storage(str(db_path))

    date_str = datetime.now().strftime("%Y%m%d")
    dump_dir = os.path.join(str(db_path.parent), f"dump_{date_str}")
    os.makedirs(dump_dir, exist_ok=True)

    if topic_id:
        # 单主题导出
        topic = storage.get_topic(topic_id)
        if not topic:
            return {"status": "error", "message": f"未找到 topic: {topic_id}", "path": dump_dir}
        filepath = _export_one_topic(storage, topic, role, dump_dir)
        return {
            "status": "success",
            "message": f"成功导出 topic: {topic.get('title', topic_id)}",
            "path": filepath,
            "topic_id": topic_id,
        }

    # 全部导出
    topics = storage.list_topics()
    if not topics:
        return {"status": "info", "message": "没有找到任何 topic", "path": dump_dir}

    exported_count = 0
    for topic in topics:
        _export_one_topic(storage, topic, role, dump_dir)
        exported_count += 1

    return {
        "status": "success",
        "message": f"成功导出 {exported_count} 个 topic",
        "path": dump_dir,
    }


def meta_toolkit_dump_topic() -> dict:
    """Meta toolkit dump topic."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_dump_topic",
            "description": "将会话内容从数据库导出到 dump_{date} 子目录，每个 topic 对应一个 markdown 文件。支持导出全部或指定 topic。",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["user", "final_msg", "all"],
                        "description": "导出范围：user=仅用户输入, final_msg=用户+AI终答(跳过工具链), all=完整内容",
                    },
                    "topic_id": {
                        "type": "string",
                        "description": "指定 topic_id 只导出该主题，不填则导出全部",
                    },
                },
                "required": [],
            },
        },
    }

if __name__ == "__main__":
    import json
    import os
    import sys
    # 将项目根目录添加到 sys.path 以支持直接运行
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root_dir not in sys.path:
        sys.path.append(root_dir)

    print("开始导出所有 Topic...")
    res = toolkit_dump_topic("user")
    print(json.dumps(res, indent=2, ensure_ascii=False))
