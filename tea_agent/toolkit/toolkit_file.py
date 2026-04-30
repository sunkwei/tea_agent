# @2026-04-29 gen by deepseek-v4-pro, 合并load_file+save_file为一个统一入口
# version: 1.0.0

def toolkit_file(action: str, filename: str, content: str = ""):
    """
    统一文件读写操作。
    - action="read": 读取文件全部内容并返回字符串。需 filename。
    - action="write": 将 content 写入文件。需 filename + content。返回 0 成功，否则错误信息。
    """
    if action == "read":
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return f"Error: File '{filename}' not found."
        except Exception as e:
            return f"Error: {str(e)}"

    elif action == "write":
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            return 0
        except Exception as e:
            return f"Error: {str(e)}"

    else:
        return f"❌ 未知 action: '{action}'，可选: read / write"


def meta_toolkit_file() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_file",
            "description": "统一文件读写。action='read' 读取文件内容；action='write' 将内容写入文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write"],
                        "description": "操作：read=读取, write=写入",
                    },
                    "filename": {
                        "type": "string",
                        "description": "文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "[write] 要写入的内容",
                    },
                },
                "required": ["action", "filename"],
            },
        },
    }
