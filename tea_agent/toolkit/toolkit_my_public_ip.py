## llm generated tool func, created Tue May 26 15:45:11 2026
# version: 1.0.0

import requests

def toolkit_my_public_ip() -> str:
    """通过自定义API获取本机公网IP地址
    
    访问 http://120.26.89.217:9994/kvs?name=qd_public_ip 获取IP
    
    Returns:
        str: 公网IP地址字符串，如 "123.456.789.0"
    """
    res = requests.get("http://120.26.89.217:9994/kvs?name=qd_public_ip", timeout=10)
    res.raise_for_status()
    return res.text.strip()


def meta_toolkit_my_public_ip() -> dict:
    return {"type": "function", "function": {"name": "toolkit_my_public_ip", "description": "通过自定义API获取本机公网IP地址。调用 http://120.26.89.217:9994/kvs?name=qd_public_ip", "parameters": {"type": "object", "properties": {}, "required": []}}}
