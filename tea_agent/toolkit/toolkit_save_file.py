# llm generated tool func, created Wed Apr 15 13:28:07 2026

def toolkit_save_file(filename: str, content: str) -> int:
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        return 0
    except Exception as e:
        return f"Error: {str(e)}"


def meta_toolkit_save_file() -> dict:
    return {"type": "function", "function": {"name": "toolkit_save_file", "description": "将内容写入指定文件，返回 0 表示成功，非 0 表示出错信息", "parameters": {"type": "object", "properties": {"filename": {"type": "string", "description": "文件路径"}, "content": {"type": "string", "description": "要写入的文件内容"}}, "required": ["filename", "content"]}}}
