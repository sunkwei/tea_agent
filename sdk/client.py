"""
Tea Agent Python SDK — Synchronous API wrapper using urllib.
"""
import json
import logging
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger("tea_agent.sdk")

# 本机回环地址：走系统代理不仅多余，还会让请求根本到不了本地服务
# （Windows 上 urlopen 默认读取注册表代理设置，把 127.0.0.1 也丢给代理，
# 结果是本地服务未启动时拿到代理返回的 502，而不是「连不上」这一真实原因）。
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})


def _no_proxy_opener():
    """构造忽略一切代理的 opener（用于访问本机服务）。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def assemble_sse(raw_text: str) -> str:
    """把 OpenAI 兼容 SSE 文本（``data: {...}\\n\\n``，末帧 ``data: [DONE]``）拼成完整回复。

    服务端在 ``stream=true`` 时按 ``choices[0].delta.content`` 逐帧下发；本函数只负责
    纯文本拼装，便于单测覆盖（不需要真起服务器）。无法解析的帧直接跳过，保证不抛异常。
    """
    parts: list[str] = []
    for block in (raw_text or "").split("\n\n"):
        for line in block.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                continue
            for choice in obj.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                for key in ("delta", "message"):
                    content = (choice.get(key) or {}).get("content")
                    if isinstance(content, str) and content:
                        parts.append(content)
                        break
    return "".join(parts)


class AgentSDK:
    """Synchronous Tea Agent SDK Client.

    Usage:
        >>> from sdk import AgentSDK
        >>> sdk = AgentSDK("127.0.0.1:8081")
        >>> sdk.chat("Hello")
    """

    def __init__(self, base_url="127.0.0.1:8081",
                 api_key="", timeout=30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {"X-Api-Key": api_key} if api_key else {}

    def _request(self, method, path, data=None):
        """发一次 HTTP 请求。

        ⚠️ ``urllib.request.Request`` 的签名是 ``Request(url, data=None, headers={},
        method=None)`` —— url 必须是第一个位置参数。旧写法
        ``Request(method, url, headers=..., data=...)`` 把 method 塞进了 url 位、
        又把真实 url 塞进了 data 位，再重复传 data 关键字，导致**每个方法**都抛
        ``TypeError: got multiple values for argument 'data'``（SDK 自引入起全废）。
        """
        url = f"http://{self.base_url}{path}"
        # 只有 None 才表示「无 body」；{} / "" 是合法 body，不能被静默丢掉
        data_bytes = json.dumps(data).encode("utf-8") if data is not None else None
        headers = dict(self.headers)
        if data_bytes is not None:
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data_bytes, headers=headers, method=method)
        # 本机地址绕开系统代理：否则未启动服务时拿到的是代理返回的 502，
        # 而非「连不上」这一真实原因；更糟的是请求根本没到过 tea_agent 服务。
        # 必须解析最终 url 而不是 base_url —— 后者形如 "127.0.0.1:8081" 无 scheme，
        # urlparse 提不出 hostname，会让本分支静默失效（代理问题依旧）。
        opener = _no_proxy_opener() if urlparse(url).hostname in _LOCAL_HOSTS else None
        try:
            if opener is not None:
                resp = opener.open(req, timeout=self.timeout)
            else:
                resp = urlopen(req, timeout=self.timeout)
            with resp as r:
                return r.getcode(), self._decode(r.read())
        except HTTPError as e:
            return e.code, self._decode(e.read())
        except URLError as e:
            # 连不上服务是 SDK 最常见的失败，必须可读而非裸 500
            return 500, {"error": f"无法连接 {self.base_url}: {getattr(e, 'reason', e)}"}
        except Exception as e:  # noqa: BLE001 — SDK 边界：不把异常抛给调用方
            logger.debug("SDK 请求失败: %s %s", method, path, exc_info=True)
            return 500, {"error": f"{type(e).__name__}: {e}"}

    @staticmethod
    def _decode(raw: bytes) -> dict:
        """把响应体解析成 dict。服务端可能返回空体（204）或纯文本错误页，
        旧实现让 ``json.loads`` 的异常穿透到 ``except Exception`` 后，HTTP 状态码
        与真实错误一起丢失（401 会被伪装成 500）。

        非 JSON 文本（``stream=true`` 的 SSE 正文）保留在 ``_raw`` 里交给上层拼装，
        否则流式调用会拿到空 dict —— 又是一次静默丢内容。
        """
        if not raw:
            return {}
        text = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}

    def chat(self, message, stream=False,
             model="default", topic_id=""):
        payload = {"messages": [{"role": "user", "content": message}],
                   "stream": stream, "model": model}
        if topic_id:
            payload["topic_id"] = topic_id
        code, data = self._request("POST", "/v1/chat/completions", payload)
        if code != 200:
            return data.get("error", str(data))
        # stream=true 时服务端逐帧下发 SSE；非流式仍是 choices[0].message.content
        return self._extract_content(data)

    @staticmethod
    def _extract_content(data):
        """从聊天响应取正文，兼容非流式 JSON 与流式 SSE 两种形态。"""
        if isinstance(data, str):
            return assemble_sse(data) if "data:" in data else data
        if isinstance(data, dict):
            raw = data.get("_raw")
            if isinstance(raw, str) and raw:
                return assemble_sse(raw)
            if data.get("error"):
                return data["error"]
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message") or choices[0].get("delta") or {}
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, str):
                    return content
            for key in ("content", "response", "ai_msg"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        return str(data)

    def list_tools(self):
        code, data = self._request("GET", "/v1/tools")
        return data.get("data", [])

    def run_tool(self, tool_name, arguments=None):
        arguments = arguments or {}
        code, data = self._request("POST",
            f"/v1/tools/{tool_name}/run",
            {"arguments": arguments})
        return data

    def list_sessions(self, limit=20):
        code, data = self._request("GET", f"/v1/sessions?limit={limit}")
        return data.get("data", [])

    def create_session(self, title="SDK 导入"):
        code, data = self._request("POST", "/v1/sessions",
                    {"title": title})
        return data.get("id", "")

    def get_session(self, topic_id):
        code, data = self._request("GET", f"/v1/sessions/{topic_id}")
        if code == 200: return data
        return None

    def delete_session(self, topic_id):
        code, data = self._request("DELETE", f"/v1/sessions/{topic_id}")
        return data.get("ok", False)

    def get_config(self):
        code, data = self._request("GET", "/v1/config")
        return data

    def health(self):
        code, data = self._request("GET", "/health")
        return data
