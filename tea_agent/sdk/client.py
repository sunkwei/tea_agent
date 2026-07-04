"""
Tea Agent Python SDK — Synchronous API wrapper using urllib.
"""
import json
from urllib.request import Request, urlopen, HTTPError

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
        url = f"http://{self.base_url}{path}"
        data_bytes = json.dumps(data).encode() if data else None
        req = Request(method, url, headers=self.headers, data=data_bytes)
        try:
            with urlopen(req, timeout=self.timeout) as r:
                return r.getcode(), json.loads(r.read().decode())
        except HTTPError as e:
            return e.code, json.loads(e.read().decode())
        except Exception as e:
            return 500, {"error": str(e)}

    def chat(self, message, stream=False,
              model="default", topic_id=""):
        payload = {"messages": [{"role": "user", "content": message}],
                  "stream": stream, "model": model}
        if topic_id:
            payload["topic_id"] = topic_id
        code, data = self._request("POST", "/v1/chat/completions", payload)
        if code == 200:
            return data["choices"][0]["message"]["content"]
        return data.get("error", str(data))

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

    def create_session(self, title="SDK م导"):
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
