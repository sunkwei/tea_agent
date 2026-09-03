"""
模型管理服务 — 提供商合并 / 模型查询 / 自定义供应商 CRUD / 配置应用。

默认提供商源（面板）：扫描 ~/.tea_agent/config_*.yaml 派生的真实 profile
（model_config.scan_config_profiles）⊕ 用户自定义供应商（custom_providers.yaml），
内置 PROVIDERS（providers.py 静态注册表）仅作能力匹配参考与空环境兑底。
本服务为 Web/API 层提供统一支撑：

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
from tea_agent.providers import PROVIDERS, model_entries, model_ids

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
        # 模型查询结果 TTL 缓存: {provider:api_key -> (timestamp, result)}
        self._models_cache: dict[str, tuple[float, dict]] = {}
        self._models_cache_ttl: float = 300.0  # 5 分钟

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

    def _catalog(self, info: dict) -> list[dict]:
        """从 Provider 信息抽取富模型目录（id + 元数据），供 UI 两步选择。

        兼容旧形态：内置 Provider 的 models 是富条目对象；自定义/简写字符串
        也会被统一归一化为 {id, ...}。能力标记缺省继承 Provider 级默认。

        Args:
            info: Provider 原始信息（含 models）

        Returns:
            [{id, context_window, max_output_tokens, supports_vision,
              supports_thinking, description}, ...]
        """
        out = []
        for entry in model_entries(info):
            mid = entry["id"]
            merged = {
                "id": mid,
                "context_window": entry.get("context_window", 0) or 0,
                "max_output_tokens": entry.get("max_output_tokens", 0) or 0,
                "supports_vision": bool(
                    entry.get("supports_vision", info.get("supports_vision", False))
                ),
                "supports_thinking": bool(
                    entry.get("supports_thinking", info.get("supports_thinking", False))
                ),
                "description": entry.get("description", "") or "",
            }
            out.append(merged)
        return out

    def list_providers(self) -> dict:
        """提供商列表（内置+自定义），标注来源与当前使用状态。

        每个提供商含：
          - models: 模型 id 列表（兼容旧前端）
          - catalog: 富模型目录 [{id, context_window, max_output_tokens, ...}]
            —— 切换模型时 UI 只需 provider + model 两步，窗口/输出上限自动填充。
        """
        cfg = self._load_cfg()
        main_url = _normalize_url(getattr(cfg.main_model, "api_url", ""))
        active = {
            "main": getattr(cfg.main_model, "model_name", "") or None,
            "cheap": getattr(cfg.cheap_model, "model_name", "") or None,
            "vision": getattr(cfg.vision_model, "model_name", "") or None,
        }
        providers = []
        for name, info in sorted(self._merged().items()):
            ids = model_ids(info)
            catalog = self._catalog(info)
            providers.append(
                {
                    "name": name,
                    "source": info.get("source", "builtin"),
                    "api_url": info.get("api_url", ""),
                    "default_model": info.get("default_model", ""),
                    "models": ids,
                    "catalog": catalog,
                    "supports_thinking": any(m.get("supports_thinking") for m in catalog),
                    "supports_vision": any(m.get("supports_vision") for m in catalog),
                    "description": info.get("description", ""),
                    "is_configured": bool(
                        main_url and main_url == _normalize_url(info.get("api_url", ""))
                    ),
                }
            )
        return {"providers": providers, "total": len(providers), "active": active}

    def get_provider(self, name: str) -> dict | None:
        """合并后按名称查找（不区分大小写）；注册表未命中时回退 config profile。

        profile 提供商（source="config"）由 ~/.tea_agent/config_*.yaml 派生：
        api_url/models/model_meta/config_path 均来自真实配置文件；密钥不外传。
        """
        name_lower = (name or "").strip().lower()
        for pname, info in self._merged().items():
            if pname.lower() == name_lower:
                return {"name": pname, **info, "source": info.get("source", "builtin")}
        try:
            from tea_agent.model_config import scan_config_profiles

            for pname, info in scan_config_profiles().items():
                if pname.lower() == name_lower:
                    return {"name": pname, **info, "source": "config"}
        except Exception as e:  # pragma: no cover - 防御性
            logger.debug("profile provider lookup skipped: %s", e)
        return None

    # ── 统一模型配置中心（~/.tea_agent/model_config.json） ────

    @staticmethod
    def _profile_secret(config_path: str, model: str = "") -> str:
        """从 profile 配置文件回读 api_key（仅内存使用，绝不写进 model_config.json）。

        指定 model 时优先取 model_name 匹配的角色块；否则回退 main_model 的 key。
        """
        if not config_path:
            return ""
        try:
            import yaml
            from pathlib import Path as _Path

            raw = yaml.safe_load(_Path(config_path).read_text(encoding="utf-8")) or {}
            if model:
                for role in ROLES:
                    block = raw.get(f"{role}_model")
                    if isinstance(block, dict) and str(block.get("model_name") or "") == model:
                        return str(block.get("api_key") or "")
            main = raw.get("main_model")
            return str(main.get("api_key") or "") if isinstance(main, dict) else ""
        except Exception as e:
            logger.debug("profile secret read failed: %s", e)
            return ""

    @staticmethod
    def _store():
        """ModelConfigStore 单例；失败返回 None（best-effort 增强，不阻塞主流程）。"""
        try:
            from tea_agent.model_config import get_model_config_store

            return get_model_config_store()
        except Exception as e:  # pragma: no cover - 防御性
            logger.debug("model config store unavailable: %s", e)
            return None

    def _annotate_models(self, provider_name: str, models: list[dict]) -> None:
        """给模型查询结果附加统一配置的逐模型能力（最大上下文/最大输出/思考/视觉）。"""
        store = self._store()
        if store is None:
            return
        try:
            for m in models:
                mid = m.get("id") if isinstance(m, dict) else None
                if mid:
                    m["config"] = store.get_model_config(provider_name, str(mid))
        except Exception as e:
            logger.debug("annotate model configs skipped: %s", e)

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

    def _normalize_models_input(self, value: list) -> list:
        """规范化自定义供应商的 models 输入。

        接受两种元素形态：
          - 简写字符串: "gpt-4o"                 → {"id": "gpt-4o"}
          - 富条目: {"id": "...", "context_window": 200000,
                     "max_output_tokens": 32768, ...}
        富条目的窗口/输出上限与内置目录同构，切换时可自动填充。

        Args:
            value: 原始 models 列表

        Returns:
            规范化后的富条目列表
        """
        if not isinstance(value, list):
            raise ProviderError("'models' must be a list", "BAD_REQUEST", 400)
        out = []
        for item in value:
            if isinstance(item, str):
                item = item.strip()
                if item:
                    out.append({"id": item})
                continue
            if isinstance(item, dict) and item.get("id"):
                entry = {"id": str(item["id"]).strip()}
                for key in ("context_window", "max_output_tokens"):
                    val = item.get(key)
                    if isinstance(val, (int, float)) and int(val) > 0:
                        entry[key] = int(val)
                for flag in ("supports_vision", "supports_thinking"):
                    if isinstance(item.get(flag), bool):
                        entry[flag] = item[flag]
                if item.get("description"):
                    entry["description"] = str(item["description"]).strip()
                out.append(entry)
                continue
            raise ProviderError(
                "model entries must be strings or dicts with 'id'", "BAD_REQUEST", 400
            )
        return out

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
                if key == "models":
                    clean[key] = self._normalize_models_input(value)
                    continue
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
        catalog = self._catalog(info)
        return {
            "name": name,
            "source": info.get("source", "custom"),
            "api_url": info.get("api_url", ""),
            "default_model": info.get("default_model", ""),
            "models": model_ids(info),
            "catalog": catalog,
            "supports_thinking": any(m.get("supports_thinking") for m in catalog),
            "supports_vision": any(m.get("supports_vision") for m in catalog),
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
        if (store := self._store()) is not None:
            try:
                store.ensure_provider(name, {**entry, "source": "custom"})
            except Exception as e:
                logger.debug("mirror provider to model_config failed: %s", e)
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
        if (store := self._store()) is not None:
            try:
                store.ensure_provider(target, {**merged, "source": "custom"})
            except Exception as e:
                logger.debug("mirror provider update failed: %s", e)
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
        if (store := self._store()) is not None:
            try:
                store.remove_provider(target)
            except Exception as e:
                logger.debug("mirror provider delete failed: %s", e)
        logger.info("custom provider deleted: %s", target)
        return {"ok": True, "deleted": target}

    # ── 模型查询 ──────────────────────────────────────────────

    def query_models(self, name: str, api_key: str = "", refresh: bool = False) -> dict:
        """查询某提供商的可用模型。

        实时调用 {api_url}/v1/models（需 api_key）；失败或未提供 key 时
        自动 fallback 到目录 models 列表，响应标注 source: live/static。

        每个模型条目尽量携带目录元数据（context_window / max_output_tokens /
        supports_vision / supports_thinking），供 UI 两步切换展示能力。

        Args:
            name: 提供商名称（内置或自定义）
            api_key: API Key（自定义供应商通常必需）
            refresh: True=强制实时查询并更新缓存；
                     False=5 分钟内优先返回缓存，过期自动实时。

        响应字段: provider / source(live|static|cache) / models / total /
                  endpoint / needs_key / error_hint / cached_at
        """
        provider = self.get_provider(name)
        if provider is None:
            raise ProviderNotFoundError(name)
        api_url = provider.get("api_url", "")
        static_models = provider.get("models") or []
        # profile 提供商：未显式传 key 时用配置文件真实 key 查在线列表（不落盘）
        if provider.get("source") == "config" and not api_key:
            api_key = self._profile_secret(provider.get("config_path", ""), "")
        result = {
            "provider": provider["name"],
            "source": "static",
            "models": static_models,
            "total": len(static_models),
            "endpoint": _models_endpoint(api_url),
            "needs_key": False,
        }
        self._annotate_models(provider["name"], result["models"])
        if not api_url or not api_key:
            if provider.get("source") == "custom" and not api_key:
                result["needs_key"] = True
                result["error_hint"] = "custom provider needs api_key to query live models"
            return result

        cache_key = f"{provider['name']}:{api_key}"
        now = time.time()
        if not refresh:
            cached = self._models_cache.get(cache_key)
            if cached and now - cached[0] < self._models_cache_ttl:
                hit = dict(cached[1])
                hit["source"] = "cache"
                hit["cached_at"] = cached[0]
                self._annotate_models(provider["name"], hit.get("models") or [])
                return hit

        live = self._query_live(api_url, api_key)
        if live.get("ok"):
            result["source"] = "live"
            result["models"] = self._merge_catalog_meta(live["models"], catalog_by_id)
            result["total"] = live["total"]
            result["endpoint"] = live["endpoint"]
            result.pop("error_hint", None)
            self._annotate_models(provider["name"], result["models"])
            self._models_cache[cache_key] = (now, result)
        else:
            result["error_hint"] = live.get("error", "live query failed, showing static list")
        return result

    @staticmethod
    def _merge_catalog_meta(live_models: list[dict], catalog_by_id: dict) -> list[dict]:
        """实时列表 + 目录元数据合并：id 命中目录时补齐窗口/输出/能力。"""
        out = []
        for item in live_models:
            mid = item.get("id")
            meta = catalog_by_id.get(mid) if mid else None
            if meta:
                merged = {**meta}
                merged.setdefault("owned_by", item.get("owned_by", ""))
                out.append(merged)
            else:
                out.append(item)
        return out

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
        """按「供应商 → 模型」两步应用模型配置（main/cheap/vision），落盘 config.yaml。

        - api_key 留空时复用该角色现有 key
        - model 留空时使用提供商 default_model
        - 模型能力/窗口/输出上限自动取自目录（model catalog）：
            选择 deepseek-chat → max_context_tokens=131072、max_tokens=8192 自动写入；
            显式传入的 max_tokens / max_context_tokens 优先级更高。
        """
        provider = self.get_provider(name)
        if provider is None:
            raise ProviderNotFoundError(name)
        if role not in ROLES:
            raise ProviderError(f"invalid role '{role}', use one of {list(ROLES)}", "BAD_REQUEST", 400)
        model = (model or "").strip() or provider.get("default_model", "")
        if not model:
            raise ProviderError("model required (no default_model on provider)", "BAD_REQUEST", 400)

        # profile 提供商：逐模型解析 api_url（同一 profile 内不同角色可能不同网关）
        api_url = provider.get("api_url", "")
        if provider.get("source") == "config":
            mmeta = (provider.get("model_meta") or {}).get(model) or {}
            api_url = mmeta.get("api_url") or api_url

        cfg_path = config_path or self._config_path or None
        cfg = load_config(cfg_path)
        target = {"main": cfg.main_model, "cheap": cfg.cheap_model, "vision": cfg.vision_model}[role]
        if not api_key and provider.get("source") == "config":
            # 优先级：显式传参 > profile 文件对应角色块 key > 该角色现有 key
            api_key = self._profile_secret(provider.get("config_path", ""), model)
        if not api_key:
            api_key = getattr(target, "api_key", "") or ""
        # ── 统一模型配置中心：逐模型配置作默认值（显式传参优先；面板是唯一事实源）──
        store = self._store()
        mcfg: dict = {}
        if store is not None:
            try:
                store.ensure_provider(provider["name"], {**provider})
                mcfg = store.get_model_config(provider["name"], model)
            except Exception as e:
                logger.debug("model_config lookup skipped: %s", e)
        if max_tokens is None and int(mcfg.get("max_output_tokens") or 0) > 0:
            max_tokens = int(mcfg["max_output_tokens"])
        if max_context_tokens is None and int(mcfg.get("max_context_tokens") or 0) > 0:
            max_context_tokens = int(mcfg["max_context_tokens"])
        target.api_key = api_key
        target.api_url = api_url
        target.model_name = model
        if temperature is not None:
            target.temperature = float(temperature)
        if top_p is not None:
            target.top_p = float(top_p)
        # 目录自动填充：显式传入 > 模型目录默认
        eff_max_tokens = (
            int(max_tokens)
            if max_tokens is not None
            else (int(meta["max_output_tokens"]) if meta.get("max_output_tokens") else target.max_tokens)
        )
        eff_max_context = (
            int(max_context_tokens)
            if max_context_tokens is not None
            else (int(meta["context_window"]) if meta.get("context_window") else target.max_context_tokens)
        )
        target.max_tokens = eff_max_tokens
        target.max_context_tokens = eff_max_context
        merged_options = dict(getattr(target, "options", None) or {})
        if options:
            merged_options.update(options)
        # 能力标记：提供商级 ⊕ 逐模型级取并集（模型专属能力也能在提供商未声明时生效）
        merged_options["supports_vision"] = bool(
            provider.get("supports_vision", False) or mcfg.get("supports_vision"))
        merged_options["supports_reasoning"] = bool(
            provider.get("supports_thinking", False) or mcfg.get("supports_thinking"))
        target.options = merged_options

        save_config(cfg, cfg_path)
        # 角色绑定回写统一配置中心（面板展示“当前使用”的单一事实源）
        if store is not None:
            try:
                store.set_role(role, provider["name"], model, api_url=target.api_url)
            except Exception as e:
                logger.debug("role binding to model_config skipped: %s", e)
        logger.info("applied provider %s → %s/%s (config=%s)", name, role, model, cfg_path or "default")
        return {
            "ok": True,
            "role": role,
            "provider": provider["name"],
            "model": model,
            "api_url": target.api_url,
            "max_tokens": eff_max_tokens,
            "max_context_tokens": eff_max_context,
            "supports_vision": supports_vision,
            "supports_reasoning": supports_reasoning,
            "options": merged_options,
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
