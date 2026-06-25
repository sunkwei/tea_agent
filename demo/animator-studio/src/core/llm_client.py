"""
LLM 客户端 — 读取 tea_agent 配置，调用 DeepSeek API

用法:
    from src.core.llm_client import llm
    resp = llm.chat([{"role":"user","content":"描述"}])
    print(resp)
"""

import os
import json
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
import httpx


# ── 默认配置路径 ──
_DEFAULT_CONFIG_PATH = Path.home() / ".tea_agent" / "config_ds_flash.yaml"


def _load_config(config_path: Optional[str] = None) -> dict:
    """加载 tea_agent 配置"""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if not path.exists():
        # 回退：尝试查找其他 config
        alt = Path.home() / ".tea_agent"
        if alt.exists():
            for f in alt.glob("config*.yaml"):
                path = f
                break
    if not path.exists():
        raise FileNotFoundError(f"LLM 配置未找到: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def _get_model_config(cfg: dict, key: str = "main_model") -> dict:
    """从配置中提取模型信息"""
    mc = cfg.get(key, cfg.get("main_model", {}))
    if not mc:
        raise ValueError(f"配置中缺少模型定义: {key}")
    return {
        "api_key": mc.get("api_key", ""),
        "api_url": mc.get("api_url", "").rstrip("/"),
        "model_name": mc.get("model_name", "deepseek-chat"),
        "max_tokens": mc.get("max_tokens", 8192),
        "temperature": cfg.get("mode_params", {}).get("creative", {}).get("temperature", 0.7),
        "top_p": cfg.get("mode_params", {}).get("creative", {}).get("top_p", 0.95),
    }


class LLMClient:
    """LLM API 客户端 — 支持同步/流式调用"""

    def __init__(self, config_path: Optional[str] = None,
                 model_key: str = "main_model"):
        cfg = _load_config(config_path)
        mc = _get_model_config(cfg, model_key)

        self.api_key = mc["api_key"]
        self.api_url = mc["api_url"]
        self.model_name = mc["model_name"]
        self.max_tokens = mc["max_tokens"]
        self.temperature = mc["temperature"]
        self.top_p = mc["top_p"]
        self._client = httpx.Client(timeout=120)

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _endpoint(self, path: str = "/chat/completions") -> str:
        return f"{self.api_url}{path}"

    def chat(self, messages: List[Dict[str, str]],
             temperature: Optional[float] = None,
             max_tokens: Optional[int] = None,
             response_format: Optional[dict] = None,
             stream: bool = False) -> str:
        """
        同步对话调用

        参数:
            messages: [{"role":"user","content":"..."}]
            temperature: 温度 (默认使用配置)
            max_tokens: 最大 token 数
            response_format: {"type":"json_object"} 强制 JSON
            stream: 是否流式

        返回:
            模型回复文本
        """
        body = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "top_p": self.top_p,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": stream,
        }
        if response_format:
            body["response_format"] = response_format

        resp = self._client.post(
            self._endpoint(),
            headers=self._headers,
            json=body,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"API 调用失败 [{resp.status_code}]: {resp.text}"
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"API 返回空 choices: {data}")

        content = choices[0].get("message", {}).get("content", "")
        return content

    def chat_stream(self, messages: List[Dict[str, str]],
                    on_chunk: Callable[[str], None],
                    temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None):
        """流式对话调用"""
        body = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "top_p": self.top_p,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": True,
        }

        with self._client.stream(
            "POST", self._endpoint(), headers=self._headers, json=body
        ) as resp:
            if resp.status_code != 200:
                raise RuntimeError(
                    f"API 流式调用失败 [{resp.status_code}]"
                )
            full = ""
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        full += content
                        on_chunk(content)
                except json.JSONDecodeError:
                    continue
            return full

    def close(self):
        self._client.close()


# 全局单例
llm = LLMClient()
