"""
模型管理服务 — 提供商合并 / 模型查询 / 自定义供应商 CRUD / 配置应用。

将内置 PROVIDERS（providers.py 静态注册表）与用户自定义供应商
（~/.tea_agent/custom_providers.yaml）合并，为 Web/API 层提供统一支撑：

  - list_providers():   内置+自定义提供商列表（含来源、能力、是否当前使用）
  - query_models():     实时 /v1/models + 静态 fallback（双层保证 UI 永远有数据）
  - add/update/delete_custom_provider(): 自定义供应商 CRUD（用户级持久化，升级不丢）
  - apply_provider():   一键应用提供商到模型配置（main/cheap/vision）
  - test_connection():  最小请求验证「端点 + key + 模型」三重有效性

分层原则：providers.py 保持纯静态注册表（职责单一）；本服务承担动态逻辑，
可被 CLI / 内部工具 / HTTP API 三方复用。不依赖 server 模块，无循环导入。

持久化：自定义供应商存于 ~/.tea_agent/custom_providers.yaml（用户级），
不写回源码、不污染 config.yaml；api_key 属于各配置文件的模型配置，
不在此文件中重复存放。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error as urllib_err
import urllib.request as urllib_req
from pathlib import Path
from typing import Any

from tea_agent.config import load_config, save_config
from tea_agent.providers import PROVIDERS

logger = logging.getLogger("tea_agent.model_manager")

# 供应商名称合法性：字母/数字/下划线/连字符，2~32 字符
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")

ROLES = ("main", "cheap", "vision")

_CUSTOM_DIR = Path.home() / ".tea_agent"
_CUSTOM_FILE = _CUSTOM_DIR / "custom_providers.yaml"


class ProviderError(Exception):
    """提供商服务异常，携带错误码与 HTTP 状态。"""

    def __init__(self, message: str, code: str = "BAD_REQUEST", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class DuplicateProviderError(ProviderError):
    """供应商名称冲突（与内置或其他自定义重名）。"""

    def __init__(self, name: str):
        super().__init__(f"provider '{name}' already exists", "DUPLICATE_NAME", 409)


class ProviderNotFoundError(ProviderError):
    """供应商不存在。"""

    def __init__(self, name: str):
        super().__init__(f"provider '{name}' not found", "NOT_FOUND", 404)


class BuiltinProviderError(ProviderError):
    """内置供应商不可修改/删除。"""

    def __init__(self, name: str):
        super().__init__(
            f"provider '{name}' is builtin and cannot be modified", "BUILTIN", 403
        )


def _normalize_url(url: str) -> str:
    """URL 归一化（去空白、去尾部斜杠、小写），用于等价比较。"""
    return (url or "").strip().rstrip("/").lower()


def _models_endpoint(api_url: str) -> str:
    """根据 api_url 推断 OpenAI 兼容 /v1/models 端点。

    各提供商 api_url 形态不一：
      - https://api.openai.com/v1          → 已含 /v1，直接 + /models
      - https://api.deepseek.com           → 无 /v1，补 /v1/models
      - https://generativelanguage.googleapis.com/v1beta/openai → 特殊路径
    """
    url = (api_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/v1") or url.endswith("/v1beta/openai"):
        return url + "/models"
    return url + "/v1/models"


def _chat_endpoint(api_url: str) -> str:
    """推断 OpenAI 兼容 /chat/completions 端点。"""
    url = (api_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/v1") or url.endswith("/v1beta/openai"):
        return url + "/chat/completions"
    return url + "/v1/chat/completions"


def _mask_key(api_key: str) -> str:
    """掩码 api_key：sk-abc123456789xyz → sk-abc****xyz。"""
    if not api_key:
        return ""
    if len(api_key) <= 12:
        return api_key[:2] + "****"
    return api_key[:6] + "****" + api_key[-4:]


class ProviderService:
    """模型管理服务（合并注册表 + 动态查询 + 自定义 CRUD + 配置应用）。"""

    def __init__(self, config_path: str = ""):
        self._config_path = config_path or ""
        self._custom_cache: dict[str, dict] | None = None
        self._custom_mtime: float = 0.0
        self._lock = threading.Lock()

    # ── 自定义供应商持久化 ──────────────────────────────────────

    @property
    def custom_file(self) -> Path:
        return _CUSTOM_FILE

    def _load_custom(self, force: bool = False) -> dict[str, dict]:
        """读取自定义供应商（mtime 缓存，避免每次请求读盘）。"""
        fpath = self.custom_file
        mtime = 0.0
        try:
            mtime = fpath.stat().st_mtime
        except OSError:
            pass
        with self._lock:
            if self._custom_cache is not None and not force and mtime == self._custom_mtime:
                return self._custom_cache
        data: dict[str, dict] = {}
        if fpath.exists():
            try:
                import yaml

                raw = yaml.safe_load(fpath.read_text(encoding="utf-8")) or {}
                providers = raw.get("providers", {}) if isinstance(raw, dict) else {}
                if isinstance(providers, dict):
                    data = {str(k): v for k, v in providers.items() if isinstance(v, dict)}
            except Exception as e:  # pragma: no cover - 防御性
                logger.warning("custom_providers.yaml load failed: %s", e)
        with self._lock:
            self._custom_cache = data
            self._custom_mtime = mtime
        return data

    def _save_custom(self, providers: dict[str, dict]) -> None:
        """持久化自定义供应商（写前备份，不覆盖历史）。"""
        fpath = self.custom_file
        fpath.parent.mkdir(parents=True, exist_ok=True)
        if fpath.exists():
            bak = fpath.with_name(f"custom_providers.yaml.bak.{time.strftime('%Y%m%d_%H%M%S')}")
            try:
                import shutil

                shutil.copy2(fpath, bak)
            except OSError:  # pragma: no cover
                pass
        import yaml

        payload = {"version": 1, "providers": providers}
        fpath.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        with self._lock:
            self._custom_cache = providers
            try:
                self._custom_mtime = fpath.stat().st_mtime
            except OSError:  # pragma: no cover
                self._custom_mtime = time.time()
        logger.info("custom providers saved: %d total", len(providers))

    # ── 合并注册表 ─────────────────────────────────────────────

    def _merged(self) -> dict[str, dict]:
        """内置 PROVIDERS ⊕ 自定义供应商，统一加 source 标记。"""
        merged: dict[str, dict] = {}
        for name, info in PROVIDERS.items():
            merged[name] = {**info, "name": name, "source": "builtin"}
        for name, info in self._load_custom().items():
            merged[name] = {**info, "name": name, "source": "custom"}
        return merged

    def _load_cfg(self):
        """加载配置（失败时返回默认空配置，避免服务不可用）。"""
        try:
            return load_config(self._config_path or None)
        except Exception:
            from tea_agent.config import AgentConfig

            return AgentConfig()

    def list_providers(self) -> dict:
        """提供商列表（内置+自定义），标注来源与当前使用状态。"""
        cfg = self._load_cfg()
        main_url = _normalize_url(getattr(cfg.main_model, "api_url", ""))
        active = {
            "main": getattr(cfg.main_model, "model_name", "") or None,
            "cheap": getattr(cfg.cheap_model, "model_name", "") or None,
            "vision": getattr(cfg.vision_model, "model_name", "") or None,
        }
        providers = []
        for name, info in sorted(self._merged().items()):
            providers.append(
                {
                    "name": name,
                    "source": info.get("source", "builtin"),
                    "api_url": info.get("api_url", ""),
                    "default_model": info.get("default_model", ""),
                    "models": info.get("models") or [],
                    "supports_thinking": bool(info.get("supports_thinking", False)),
                    "supports_vision": bool(info.get("supports_vision", False)),
                    "description": info.get("description", ""),
                    "is_configured": bool(
                        main_url and main_url == _normalize_url(info.get("api_url", ""))
                    ),
                }
            )
        return {"providers": providers, "total": len(providers), "active": active}

    def get_provider(self, name: str) -> dict | None:
        """合并后按名称查找（不区分大小写）。"""
        name_lower = (name or "").strip().lower()
        for pname, info in self._merged().items():
            if pname.lower() == name_lower:
                return {"name": pname, **info, "source": info.get("source", "builtin")}
        return None

    # ── 自定义供应商 CRUD ──────────────────────────────────────

    def _validate_name(self, name: str) -> str:
        name = (name or "").strip()
        if not NAME_RE.match(name):
            raise ProviderError(
                f"invalid provider name '{name}': 2-32 chars of [A-Za-z0-9_-]",
                "BAD_REQUEST",
                400,
            )
        return name

    def _validate_payload(self, data: dict, partial: bool = False) -> dict:
        """校验并规范化供应商字段。partial=True 时仅校验提供的字段。"""
        allowed = {
            "api_url": (str, True),
            "default_model": (str, True),
            "models": (list, False),
            "supports_thinking": (bool, False),
            "supports_vision": (bool, False),
            "description": (str, False),
        }
        clean: dict[str, Any] = {}
        for key, (typ, required) in allowed.items():
            if key not in data:
                if required and not partial:
                    raise ProviderError(f"'{key}' is required", "BAD_REQUEST", 400)
                continue
            value = data[key]
            if typ is list:
                if not isinstance(value, list) or not all(isinstance(m, str) for m in value):
                    raise ProviderError(f"'{key}' must be a list of strings", "BAD_REQUEST", 400)
                clean[key] = [m.strip() for m in value if m.strip()]
                continue
            if typ is bool:
                clean[key] = bool(value)
                continue
            if not isinstance(value, str) or not value.strip():
                raise ProviderError(f"'{key}' must be a non-empty string", "BAD_REQUEST", 400)
            clean[key] = value.strip()
        # api_url 必须为 http(s):// 形式
        api_url = clean.get("api_url")
        if api_url and not api_url.startswith(("http://", "https://")):
            raise ProviderError("'api_url' must start with http:// or https://", "BAD_REQUEST", 400)
        return clean

    def _provider_out(self, name: str, info: dict) -> dict:
        """规范化输出单个供应商（供 API 返回）。"""
        return {
            "name": name,
            "source": info.get("source", "custom"),
            "api_url": info.get("api_url", ""),
            "default_model": info.get("default_model", ""),
            "models": info.get("models") or [],
            "supports_thinking": bool(info.get("supports_thinking", False)),
            "supports_vision": bool(info.get("supports_vision", False)),
            "description": info.get("description", ""),
            "created_at": info.get("created_at", ""),
            "updated_at": info.get("updated_at", ""),
        }

    def add_custom_provider(self, data: dict) -> dict:
        """新增自定义供应商（重名抛 DuplicateProviderError）。"""
        name = self._validate_name(data.get("name", ""))
        if self.get_provider(name) is not None:
            raise DuplicateProviderError(name)
        clean = self._validate_payload(data)
        custom = self._load_custom()
        entry = {
            **clean,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        custom[name] = entry
        self._save_custom(custom)
        logger.info("custom provider added: %s (%s)", name, entry.get("api_url", ""))
        return self._provider_out(name, {**entry, "source": "custom"})

    def update_custom_provider(self, name: str, data: dict) -> dict:
        """更新自定义供应商（仅更新提供的字段；内置供应商拒绝修改）。"""
        name_lower = (name or "").strip().lower()
        custom = self._load_custom()
        target = None
        for cname in custom:
            if cname.lower() == name_lower:
                target = cname
                break
        if target is None:
            # 检查是否为内置（内置不可修改）
            if self.get_provider(name) is not None:
                raise BuiltinProviderError(name)
            raise ProviderNotFoundError(name)
        clean = self._validate_payload(data, partial=True)
        merged = {**custom[target], **clean}
        if "models" in clean and not clean["models"]:
            merged.pop("models", None)
        merged["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        custom[target] = merged
        self._save_custom(custom)
        logger.info("custom provider updated: %s", target)
        return self._provider_out(target, {**merged, "source": "custom"})

    def delete_custom_provider(self, name: str) -> dict:
        """删除自定义供应商（内置供应商拒绝删除）。"""
        name_lower = (name or "").strip().lower()
        custom = self._load_custom()
        target = None
        for cname in custom:
            if cname.lower() == name_lower:
                target = cname
                break
        if target is None:
            if self.get_provider(name) is not None:
                raise BuiltinProviderError(name)
            raise ProviderNotFoundError(name)
        del custom[target]
        self._save_custom(custom)
        logger.info("custom provider deleted: %s", target)
        return {"ok": True, "deleted": target}

    # ── 模型查询 ──────────────────────────────────────────────

    def query_models(self, name: str, api_key: str = "", refresh: bool = True) -> dict:
        """查询某提供商的可用模型。

        实时调用 {api_url}/v1/models（需 api_key）；失败或未提供 key 时
        自动 fallback 到静态 models 列表，响应标注 source: live/static。
        """
        provider = self.get_provider(name)
        if provider is None:
            raise ProviderNotFoundError(name)
        api_url = provider.get("api_url", "")
        static_models = provider.get("models") or []
        result = {
            "provider": provider["name"],
            "source": "static",
            "models": [{"id": m, "owned_by": provider["name"]} for m in static_models],
            "total": len(static_models),
            "endpoint": _models_endpoint(api_url),
            "needs_key": False,
        }
        if not api_url or not api_key:
            if provider.get("source") == "custom" and not api_key:
                result["needs_key"] = True
                result["error_hint"] = "custom provider needs api_key to query live models"
            return result
        if not refresh:
            return result
        live = self._query_live(api_url, api_key)
        if live.get("ok"):
            result["source"] = "live"
            result["models"] = live["models"]
            result["total"] = live["total"]
            result["endpoint"] = live["endpoint"]
            result.pop("error_hint", None)
        else:
            result["error_hint"] = live.get("error", "live query failed, showing static list")
        return result

    def _query_live(self, api_url: str, api_key: str) -> dict:
        """实时查询 OpenAI 兼容 /v1/models 端点。"""
        endpoint = _models_endpoint(api_url)
        if not endpoint:
            return {"ok": False, "error": "invalid api_url"}
        req = urllib_req.Request(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib_req.urlopen(req, timeout=15) as resp:  # noqa: S310 - 用户配置端点
                data = json.loads(resp.read().decode("utf-8"))
        except urllib_err.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
            return {
                "ok": False,
                "error": f"HTTP {e.code}: {e.reason}" + (f" — {body}" if body else ""),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
        models = []
        for item in data.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                entry: dict[str, Any] = {"id": item["id"]}
                if item.get("owned_by"):
                    entry["owned_by"] = item["owned_by"]
                models.append(entry)
        return {"ok": True, "models": models, "total": len(models), "endpoint": endpoint}

    # ── 配置应用 ──────────────────────────────────────────────

    def apply_provider(
        self,
        name: str,
        api_key: str = "",
        model: str = "",
        role: str = "main",
        config_path: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        max_context_tokens: int | None = None,
        options: dict | None = None,
    ) -> dict:
        """一键应用提供商到模型配置（main/cheap/vision），落盘到 config.yaml。

        - api_key 留空时复用该角色现有 key
        - model 留空时使用提供商 default_model
        - 提供商能力（supports_vision/supports_reasoning）自动合并进 options
        """
        provider = self.get_provider(name)
        if provider is None:
            raise ProviderNotFoundError(name)
        if role not in ROLES:
            raise ProviderError(f"invalid role '{role}', use one of {list(ROLES)}", "BAD_REQUEST", 400)
        model = (model or "").strip() or provider.get("default_model", "")
        if not model:
            raise ProviderError("model required (no default_model on provider)", "BAD_REQUEST", 400)

        cfg_path = config_path or self._config_path or None
        cfg = load_config(cfg_path)
        target = {"main": cfg.main_model, "cheap": cfg.cheap_model, "vision": cfg.vision_model}[role]
        if not api_key:
            api_key = getattr(target, "api_key", "") or ""
        target.api_key = api_key
        target.api_url = provider.get("api_url", "")
        target.model_name = model
        if temperature is not None:
            target.temperature = float(temperature)
        if max_tokens is not None:
            target.max_tokens = int(max_tokens)
        if top_p is not None:
            target.top_p = float(top_p)
        if max_context_tokens is not None:
            target.max_context_tokens = int(max_context_tokens)
        merged_options = dict(getattr(target, "options", None) or {})
        if options:
            merged_options.update(options)
        merged_options["supports_vision"] = bool(provider.get("supports_vision", False))
        merged_options["supports_reasoning"] = bool(provider.get("supports_thinking", False))
        target.options = merged_options

        save_config(cfg, cfg_path)
        logger.info("applied provider %s → %s/%s (config=%s)", name, role, model, cfg_path or "default")
        return {
            "ok": True,
            "role": role,
            "provider": provider["name"],
            "model": model,
            "api_url": target.api_url,
            "config_path": str(Path(cfg_path).resolve()) if cfg_path else "",
        }

    def _existing_key(self, role: str, config_path: str = "") -> str:
        """读取某角色现有的 api_key（掩码前）。"""
        cfg_path = config_path or self._config_path or None
        cfg = load_config(cfg_path)
        target = {"main": cfg.main_model, "cheap": cfg.cheap_model, "vision": cfg.vision_model}[role]
        return getattr(target, "api_key", "") or ""

    # ── 连接测试 ──────────────────────────────────────────────

    def test_connection(self, api_url: str, api_key: str, model: str = "") -> dict:
        """最小 chat/completions 请求，验证端点+key+模型三重有效性。"""
        if not api_url or not api_key:
            raise ProviderError("api_url and api_key required", "BAD_REQUEST", 400)
        endpoint = _chat_endpoint(api_url)
        if not endpoint:
            raise ProviderError("invalid api_url", "BAD_REQUEST", 400)
        payload = {
            "model": model or "default",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }
        req = urllib_req.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        t0 = time.time()
        try:
            with urllib_req.urlopen(req, timeout=20) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
        except urllib_err.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
            return {
                "ok": False,
                "error": f"HTTP {e.code}: {e.reason}" + (f" — {body}" if body else ""),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
        latency_ms = round((time.time() - t0) * 1000, 1)
        if isinstance(data, dict):
            if data.get("error"):
                return {"ok": False, "error": str(data["error"])}
            model_reported = str(data.get("model", ""))
        else:
            model_reported = ""
        return {"ok": True, "latency_ms": latency_ms, "model_reported": model_reported}


# ── 模块级单例（供 handler/CLI 复用） ─────────────────────────

_service: ProviderService | None = None
_service_lock = threading.Lock()


def _default_cfg():
    """返回默认（空）AgentConfig，供测试与异常兜底。"""
    from tea_agent.config import AgentConfig

    return AgentConfig()


def get_provider_service(config_path: str = "") -> ProviderService:
    """获取 ProviderService 单例；config_path 变化时自动更新。"""
    global _service
    with _service_lock:
        if _service is None:
            _service = ProviderService(config_path)
        elif config_path and _service._config_path != config_path:
            _service._config_path = config_path
        return _service
