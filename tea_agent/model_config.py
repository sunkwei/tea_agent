"""兼容层：ModelConfigStore → ProviderStore（provider.yaml 唯一事实源）。

历史：本模块曾把「供应商 / 逐模型能力 / 角色绑定」持久化到
``~/.tea_agent/model_config.json``，与 provider.yaml、custom_providers.yaml、
config*.yaml 形成四份互相覆盖的事实源（谁后写谁生效，极难排查）。

现统一收敛到 ``~/.tea_agent/provider.yaml``：本模块**不再读写任何 JSON 文件**，
只把历史 API 名称转发给 :mod:`tea_agent.provider_store`，供既有调用方平滑过渡。
新代码请直接使用 ``tea_agent.provider_store.get_provider_store()``。

停用能力（调用方需注意）：
  - ``scan_config_profiles()`` — config*.yaml 不再是提供商来源，恒返回空
  - ``roles`` 绑定 — 存放于 provider.yaml 的 ``roles`` 段
"""

from __future__ import annotations

import logging

import tea_agent.provider_store as ps

logger = logging.getLogger("tea_agent.model_config")

ROLES = ("main", "cheap")


class ModelConfigError(Exception):
    """模型配置异常（兼容保留；实现见 provider_store.ProviderStoreError）。"""

    def __init__(self, message: str, code: str = "BAD_REQUEST", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


# 配置目录常量（历史名保留：测试用 monkeypatch 重定向它以隔离 tmp 目录）
CONFIG_DIR = ps.CONFIG_DIR


# 单例转发：调用方拿到的即 ProviderStore 实例（无第二个存储）
def get_model_config_store(path=None, agent_dir=None):
    """返回 ProviderStore 单例（历史名保留；不再有 model_config.json）。"""
    from tea_agent.provider_store import get_provider_store

    return get_provider_store(path, agent_dir)


def scan_config_profiles(agent_dir=None) -> dict[str, dict]:
    """已停用：config*.yaml 不再派生提供商（provider.yaml 唯一事实源）。"""
    return {}


def guess_model_config(model_id: str, provider_caps: dict | None = None) -> dict:
    """模型能力默认值（委托 provider_store.guess_model_cfg）。

    provider_caps 仅在供应商级显式声明能力时用于补足，不做模型名启发。
    """
    from tea_agent.provider_store import guess_model_cfg

    cfg = dict(guess_model_cfg(model_id))
    caps = provider_caps or {}
    if caps.get("supports_thinking"):
        cfg["supports_reasoning"] = True
    if caps.get("supports_vision"):
        cfg["supports_vision"] = True
    return cfg


def clean_model_config(raw: dict, partial: bool = True) -> dict:
    """校验/规范化逐模型配置（委托 provider_store 的清洗规则）。

    Raises:
        ModelConfigError: 入参非 dict，或含未知字段。
    """
    from tea_agent.provider_store import MODEL_FIELDS, _blank_model_cfg, _clean_model_entry

    if not isinstance(raw, dict):
        raise ModelConfigError("config must be an object")
    unknown = [k for k in raw if k not in MODEL_FIELDS]
    if unknown:
        raise ModelConfigError(f"unknown config field(s) {unknown}, allowed: {sorted(MODEL_FIELDS)}")
    out = _clean_model_entry(raw)
    if not partial:
        merged = _blank_model_cfg()
        merged.update(out)
        out = merged
    return out
