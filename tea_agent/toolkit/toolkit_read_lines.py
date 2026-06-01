## llm generated tool func, created Wed Apr 22 20:18:03 2026

def toolkit_read_lines(filename: str, start: int, end: int) -> str:
    """读取文件指定行范围的内容"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        result = []
        for i in range(max(0, start - 1), min(len(lines), end)):
            result.append(f"{i + 1}: {lines[i]}")
        
        return ''.join(result)
    except Exception as e:
        return f"Error reading file: {e}"

def meta_toolkit_read_lines() -> dict:
    return {"description": "读取文件指定行范围的内容", "type": "function", "function": {"name": "toolkit_read_lines", "parameters": {"type": "object", "properties": {"filename": {"type": "string", "description": "文件路径"}, "start": {"type": "integer", "description": "起始行号（从1开始）"}, "end": {"type": "integer", "description": "结束行号（包含）"}}, "required": ["filename", "start", "end"]}}}
