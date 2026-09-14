"""出站 API 请求的 HTTP 层：请求头注入 + 容错的 httpx 客户端构建。

**OpenCode Go / Zen**（``https://opencode.ai/zen/go/v1``）要求客户端：

1. 用**自有** User-Agent 标识自己（如 ``my-coding-agent/1.0``），
   而不是 SDK / HTTP 库的通用名；
2. 每个会话(conversation)发送**稳定的** ``x-opencode-session``，
   便于网关做路由与 prompt 缓存命中。

缺少 session 头时网关直接返回 400，请求根本不会被执行::

    {"type":"error","error":{"type":"MissingSessionID",
     "message":"Error from provider (Console Go): Request is missing
                x-opencode-session and cannot be routed efficiently."}}

除了上述自动注入，本模块还支持在 ``config.yaml`` 里为**自建网关/反代**声明附加
请求头（按 host 匹配，避免把网关密钥泄露给其它 provider）::

    api_headers:
      "*":                     # 匹配所有端点
        X-Trace-Source: tea_agent
      gateway.example.com:     # 精确 host
        X-Gateway-Token: ${MY_GATEWAY_TOKEN}   # 支持 ${ENV_VAR} 引用
      "*.internal.example":    # 子域通配
        X-Route: internal
    opencode_session_header: true   # 是否给 opencode 端点注入 x-opencode-session

注入方式：

- :func:`request_event_hooks` —— 挂在 ``httpx.Client`` 上，
  **每次请求发送时**才解析 session id，适合一个会话对象服务多个
  topic/对话的场景（如 OnlineToolSession）；
- :func:`default_headers_for` —— 构造期固定的
  ``OpenAI(default_headers=...)``，适合会话与对话一一对应的场景
  （如 LiteSession 子 Agent、一次性视觉客户端）。
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("api_headers")

# 网关要求的会话标识头（见 https://opencode.ai/docs/go/#where-can-i-use-it）
OPENCODE_SESSION_HEADER = "x-opencode-session"

# 端点识别：仅 host 命中该后缀时才注入 opencode 专用头
_OPENCODE_HOST_SUFFIX = "opencode.ai"

# 合法 HTTP 头名（RFC 7230 token）；不合法的一律丢弃，防止头注入
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+$")

# 配置值里的 ${ENV_VAR} 引用（避免把网关密钥硬编码进配置）
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# 缓存自有 User-Agent，避免每次请求都读版本号
_USER_AGENT: str | None = None


def _package_version() -> str:
    """读取包版本号（与 ``tea_agent.__version__`` 同源，但不导入包以避免循环依赖）。"""
    pyproject = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml")
    try:
        if os.path.isfile(pyproject):
            with open(pyproject, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("version"):
                        value = line.split("=", 1)[-1].strip().strip('"').strip("'")
                        if value:
                            return value
    except Exception as e:  # pragma: no cover - 仅防御性兜底
        logger.debug("api_headers: 读取 pyproject 版本失败: %s", e)
    try:
        from importlib.metadata import version as _md_version

        return _md_version("tea_agent")
    except Exception:
        return "0.0.0"


def user_agent() -> str:
    """返回 tea_agent 自有 User-Agent，如 ``tea-agent/0.16.6``。"""
    global _USER_AGENT
    if _USER_AGENT is None:
        _USER_AGENT = f"tea-agent/{_package_version()}"
    return _USER_AGENT


def is_opencode_endpoint(api_url: str | None) -> bool:
    """判断 base_url 是否指向 OpenCode 网关（Go / Zen）。

    用 host 匹配而非子串匹配，避免 ``https://opencode.ai.evil.com`` 之类的
    伪装域名拿到会话头。
    """
    if not api_url:
        return False
    try:
        host = (urlparse(str(api_url).strip()).hostname or "").lower()
    except Exception:
        return False
    return host == _OPENCODE_HOST_SUFFIX or host.endswith("." + _OPENCODE_HOST_SUFFIX)


def new_session_id() -> str:
    """生成一个新的会话标识（用于没有 topic id 的场景，如子 Agent）。"""
    return uuid.uuid4().hex


def sanitize_headers(raw: Any) -> dict[str, str]:
    """校验并规范化一组请求头。

    - 头名必须符合 RFC 7230 token，否则丢弃（防头注入）；
    - 值中不允许 ``\\r`` / ``\\n``（防响应/请求拆分）；
    - 值支持 ``${ENV_VAR}`` 引用环境变量；变量缺失时该头被丢弃（避免发出空密钥）。

    Args:
        raw: ``{name: value}`` 形式的映射（可含非字符串值）

    Returns:
        规范化后的 ``{name: value}``；输入非法时返回空字典
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not _HEADER_NAME_RE.match(name):
            logger.warning("api_headers: 忽略非法请求头名 %r", name)
            continue
        text = str(value)
        if "${" in text:
            missing = [ref for ref in _ENV_REF_RE.findall(text) if os.environ.get(ref) is None]
            if missing:
                logger.warning("api_headers: 请求头 %s 引用的环境变量不存在: %s", name, ", ".join(missing))
                continue
            text = _ENV_REF_RE.sub(lambda m: os.environ.get(m.group(1), ""), text)
        text = text.strip()
        if "\r" in text or "\n" in text:
            logger.warning("api_headers: 忽略含换行的请求头 %s", name)
            continue
        if text:
            out[name] = text
    return out


def _host_match_score(pattern: str, host: str) -> int:
    """返回 host 匹配模式的 specificity（0=不匹配，越大越具体）。"""
    key = pattern.strip().lower()
    if not key or not host:
        return 0
    if key == "*":
        return 1
    if key.startswith("*."):
        suffix = key[1:]  # ".example.com"
        return 3 if host.endswith(suffix) else 0
    if key == host:
        return 4
    if host.endswith("." + key):
        return 2
    return 0


def resolve_extra_headers(api_url: str | None, table: Any = None) -> dict[str, str]:
    """按 base_url 的 host 解析配置里的附加请求头。

    匹配优先级（后者覆盖前者）：``*`` < 裸域名后缀 < ``*.`` 通配 < 精确 host。

    Args:
        api_url: 目标 base_url
        table: 覆盖用的头表；默认读 ``AgentConfig.api_headers``（便于单测注入）

    Returns:
        合并后的 ``{name: value}``；无匹配返回空字典
    """
    if table is None:
        try:
            from tea_agent.config import get_config

            table = getattr(get_config(), "api_headers", None)
        except Exception as e:
            logger.debug("api_headers: 读取配置附加头失败: %s", e)
            return {}
    if not isinstance(table, dict) or not table:
        return {}

    try:
        host = (urlparse(str(api_url or "").strip()).hostname or "").lower()
    except Exception:
        host = ""

    matched: list[tuple[int, str]] = []
    for pattern in table:
        score = _host_match_score(str(pattern), host)
        if score:
            matched.append((score, str(pattern)))
    matched.sort(key=lambda item: item[0])

    merged: dict[str, str] = {}
    for _, pattern in matched:
        merged.update(sanitize_headers(table.get(pattern)))
    return merged


def opencode_session_header_enabled() -> bool:
    """配置开关：是否给 opencode 端点注入 ``x-opencode-session``（默认开）。"""
    try:
        from tea_agent.config import get_config

        return bool(getattr(get_config(), "opencode_session_header", True))
    except Exception:
        return True


def _build_hook(
    session_id: str | None,
    session_id_provider: Callable[[], str | None] | None,
    extra_headers: dict[str, str] | None,
) -> Callable[[Any], None]:
    """构造 httpx request 事件钩子（发送前改写请求头）。"""

    def _hook(request: Any) -> None:
        try:
            url = str(request.url)
            # 1) 配置声明的附加头（按请求实际 host 解析，支持同一客户端换端点）
            for name, value in (extra_headers if extra_headers is not None else resolve_extra_headers(url)).items():
                request.headers[name] = value
            # 2) opencode 专用头：稳定 session id + 自有 UA
            if is_opencode_endpoint(url):
                if opencode_session_header_enabled():
                    sid = session_id_provider() if session_id_provider is not None else session_id
                    if sid:
                        request.headers[OPENCODE_SESSION_HEADER] = str(sid)
                request.headers["User-Agent"] = user_agent()
        except Exception as e:  # pragma: no cover - 头注入失败不应阻断请求
            logger.debug("api_headers: 注入请求头失败: %s", e)

    return _hook


def request_event_hooks(
    api_url: str | None,
    session_id: str | None = None,
    session_id_provider: Callable[[], str | None] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, list[Callable[[Any], None]]]:
    """返回可传给 ``httpx.Client(event_hooks=...)`` 的钩子字典。

    每次请求发送前解析 session id，因此同一个客户端可以服务多个对话：
    ``session_id_provider`` 返回当前对话的稳定 id（如 topic id），
    切换对话后下一个请求自动使用新的 id。

    Args:
        api_url: 该客户端对应的 base_url
        session_id: 固定 session id（与 provider 二选一）
        session_id_provider: 请求时动态获取 session id 的回调（优先）
        extra_headers: 显式附加头（None=请求时读配置解析）

    Returns:
        需要注入任何头时返回 ``{"request": [hook]}``，否则返回空字典
    """
    hooks_needed = is_opencode_endpoint(api_url)
    configured = resolve_extra_headers(api_url) if extra_headers is None else extra_headers
    if not hooks_needed and not configured:
        return {}
    return {"request": [_build_hook(session_id, session_id_provider, extra_headers)]}


def default_headers_for(
    api_url: str | None,
    session_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """返回可传给 ``OpenAI(default_headers=...)`` 的请求头。

    适用于构造期即可确定会话标识的客户端（子 Agent、一次性视觉客户端）。
    未命中任何规则时返回空字典（调用方应避免传空 dict 以保持原调用形态）。
    """
    headers: dict[str, str] = {}
    if extra_headers is not None:
        headers.update(sanitize_headers(extra_headers))
    else:
        headers.update(resolve_extra_headers(api_url))
    if is_opencode_endpoint(api_url):
        if opencode_session_header_enabled():
            headers[OPENCODE_SESSION_HEADER] = str(session_id or new_session_id())
        headers["User-Agent"] = user_agent()
    return headers


def build_http_client(timeout: Any, event_hooks: Any = None, **kwargs: Any):
    """构建出站 httpx 客户端，对**畸形代理环境变量**做降级容错。

    背景：``httpx.Client(proxy=None)`` 仍会读取环境代理配置，
    若 ``NO_PROXY``/``no_proxy`` 含 ``[::1]`` 这类 httpx 解析不了的条目
    （Docker/国内开发环境很常见），构造会直接抛
    ``InvalidURL: Invalid port: ':1]'``，导致**会话根本无法建立**
    （不是慢，是起不来）。这里先按原样构造；失败则回退为
    ``trust_env=False``（忽略环境代理与 netrc），保证会话可用。
    """
    import httpx

    base: dict[str, Any] = {"timeout": timeout, "proxy": None, **kwargs}
    if event_hooks:
        base["event_hooks"] = event_hooks
    try:
        return httpx.Client(**base)
    except Exception as e:
        logger.warning(
            "httpx 客户端初始化失败（疑似代理环境变量畸形，如 NO_PROXY 含 [::1]），回退为忽略环境代理: %s",
            e,
        )
        return httpx.Client(**{**base, "trust_env": False})
