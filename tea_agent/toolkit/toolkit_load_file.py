# llm generated tool func, created Wed Apr 15 13:28:02 2026

def toolkit_load_file(filename: str) -> str:
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: File '{filename}' not found."
    except Exception as e:
        return f"Error: {str(e)}"


def meta_toolkit_load_file() -> dict:
    return {"type": "function", "function": {"name": "toolkit_load_file", "description": "读取指定文件的内容并返回字符串", "parameters": {"type": "object", "properties": {"filename": {"type": "string", "description": "文件路径"}}, "required": ["filename"]}}}
