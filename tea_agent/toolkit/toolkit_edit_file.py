## llm generated tool func, created Wed Apr 22 20:29:53 2026

def toolkit_edit_file(filename: str, old_text: str, new_text: str, description: str = "") -> str:
    """编辑文件，替换指定的文本片段"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if old_text not in content:
            return f"Error: old_text not found in file"
        
        new_content = content.replace(old_text, new_text)
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return f"Success: {description}"
    except Exception as e:
        return f"Error: {e}"

def meta_toolkit_edit_file() -> dict:
    return {"description": "编辑文件，替换指定的文本片段", "type": "function", "function": {"name": "toolkit_edit_file", "parameters": {"type": "object", "properties": {"filename": {"type": "string", "description": "文件路径"}, "old_text": {"type": "string", "description": "要替换的旧文本"}, "new_text": {"type": "string", "description": "替换后的新文本"}, "description": {"type": "string", "description": "修改说明"}}, "required": ["filename", "old_text", "new_text"]}}}
