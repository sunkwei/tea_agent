"""统一模型配置中心 — ~/.tea_agent/model_config.json

Tea Agent 的「提供商 → 模型 → 能力参数」单一事实源，供 Web 模型管理面板读写：

  - providers: 内置提供商(providers.PROVIDERS) + 自定义提供商(custom_providers.yaml) 的合并视图
  - 每模型配置: max_context_tokens(最大上下文) / max_output_tokens(最大输出) /
    supports_thinking(思考) / supports_vision(多模态输入) / supports_tools / note
  - roles: main / cheap / vision 三角色当前绑定的 provider/model（一键应用时自动写入）

首次加载自动 bootstrap（内置注册表 ⊕ 自定义 yaml ⊕ 当前 config.yaml 角色），
无配置的模型给出启发式默认值（按模型名 pattern 猜测，见 guess_model_config）；
之后读写均以该 JSON 文件为准。保存为原子写入 + 时间戳 .bak 备份，线程安全。

分层原则：只依赖 tea_agent.config / tea_agent.providers（不 import model_manager，避免循环）；
「查询/应用」行为仍由 model_manager.ProviderService 承担（本模块提供其逐模型配置默认值）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("tea_agent.model_config")

CONFIG_DIR = Path.home() / ".tea_agent"
DEFAULT_CONFIG_FILE = CONFIG_DIR / "model_config.json"

ROLES = ("main", "cheap", "vision")
SCHEMA_VERSION = 1

_INT_FIELDS = {"max_context_tokens": (1024, 200_000_000), "max_output_tokens": (1, 64_000_000)}
_BOOL_FIELDS = {"supports_thinking", "supports_vision", "supports_tools"}
_STR_FIELDS = {"note": 200}
CFG_FIELDS = set(_INT_FIELDS) | set(_BOOL_FIELDS) | set(_STR_FIELDS)

# 常用模型能力速查表（bootstrap 与 heuristic 兜底；单位=token）
_KNOWN_MODELS: dict[str, dict] = {
    # DeepSeek
    "deepseek-chat": {"max_context_tokens": 128_000, "max_output_tokens": 8_192},
    "deepseek-chat-v3-0324": {"max_context_tokens": 128_000, "max_output_tokens": 8_192},
    "deepseek-reasoner": {"max_context_tokens": 128_000, "max_output_tokens": 64_000,
                          "supports_thinking": True},
    "deepseek-v4-flash": {"max_context_tokens": 128_000, "max_output_tokens": 384_000,
                          "supports_thinking": True},
    "deepseek-v4-flash-vision-exp": {"max_context_tokens": 128_000, "max_output_tokens": 384_000,
                                     "supports_thinking": True, "supports_vision": True},
    # OpenAI
    "gpt-4o": {"max_context_tokens": 128_000, "max_output_tokens": 16_384, "supports_vision": True},
    "gpt-4o-mini": {"max_context_tokens": 128_000, "max_output_tokens": 16_384, "supports_vision": True},
    "gpt-4-turbo": {"max_context_tokens": 128_000, "max_output_tokens": 4_096, "supports_vision": True},
    "gpt-4.1": {"max_context_tokens": 1_000_000, "max_output_tokens": 32_768, "supports_vision": True},
    "gpt-4.1-mini": {"max_context_tokens": 1_000_000, "max_output_tokens": 32_768, "supports_vision": True},
    "o3": {"max_context_tokens": 200_000, "max_output_tokens": 100_000, "supports_thinking": True},
    "o4-mini": {"max_context_tokens": 200_000, "max_output_tokens": 100_000, "supports_thinking": True},
    # Anthropic
    "claude-sonnet-4-20250514": {"max_context_tokens": 200_000, "max_output_tokens": 64_000,
                                 "supports_thinking": True, "supports_vision": True},
    "claude-4-opus-20250514": {"max_context_tokens": 200_000, "max_output_tokens": 32_000,
                               "supports_thinking": True, "supports_vision": True},
    "claude-3-5-sonnet-20241022": {"max_context_tokens": 200_000, "max_output_tokens": 8_192,
                                   "supports_vision": True},
    # Google
    "gemini-2.5-pro-exp-03-25": {"max_context_tokens": 1_048_576, "max_output_tokens": 65_536,
                                 "supports_thinking": True, "supports_vision": True},
    "gemini-2.5-flash-preview-04-17": {"max_context_tokens": 1_048_576, "max_output_tokens": 65_536,
                                       "supports_thinking": True, "supports_vision": True},
    "gemini-2.0-flash": {"max_context_tokens": 1_048_576, "max_output_tokens": 8_192,
                         "supports_vision": True},
    "gemini-2.0-flash-lite": {"max_context_tokens": 1_048_576, "max_output_tokens": 8_192,
                              "supports_vision": True},
    # Qwen / Moonshot
    "qwen-max": {"max_context_tokens": 32_768, "max_output_tokens": 8_192},
    "qwen-plus": {"max_context_tokens": 128_000, "max_output_tokens": 8_192},
    "qwen3-235b-a22b": {"max_context_tokens": 128_000, "max_output_tokens": 16_384,
                        "supports_thinking": True},
    "moonshot-v1-8k": {"max_context_tokens": 8_192, "max_output_tokens": 4_096},
    "moonshot-v1-32k": {"max_context_tokens": 32_768, "max_output_tokens": 4_096},
    "moonshot-v1-128k": {"max_context_tokens": 128_000, "max_output_tokens": 4_096},
}

_THINK_RE = re.compile(
    r"(reason|r1|thinking|o1-|o3|o4|qwen3|qwq|kimi-k2|deepseek-v4|v4-pro|v4-flash|gemini-2\.5"
    r"|glm-4\.[56]|seed.*thinking)", re.I)
_VISION_RE = re.compile(
    r"(vision|\bvl\b|omni|gemini|gpt-4o|claude-(3|4)|qwen-vl|glm-4v|internvl|kimi-vision"
    r"|minicpm-v)", re.I)
_CTX_SUFFIX_RE = re.compile(r"[-_](\d+(?:\.\d+)?)(k|m)\b", re.I)

_DEFAULT_CTX = 128_000
_DEFAULT_OUT = 8_192


def _blank_config() -> dict:
    return {
        "max_context_tokens": _DEFAULT_CTX,
        "max_output_tokens": _DEFAULT_OUT,
        "supports_thinking": False,
        "supports_vision": False,
        "supports_tools": True,
        "note": "",
    }


def guess_model_config(model_id: str, provider_caps: dict | None = None) -> dict:
    """按模型名启发式猜测能力配置（速查表 → 名称 pattern → 全局默认）。

    Args:
        model_id: 模型 id，如 deepseek-chat / gemini-2.5-pro
        provider_caps: 提供商级能力 {supports_thinking: bool, supports_vision: bool}，
                       模型名无线索时作为兜底（提供商声明能力一般对其主力模型成立）。
    """
    cfg = _blank_config()
    mid = (model_id or "").strip()
    low = mid.lower()
    known = _KNOWN_MODELS.get(low)
    if known:
        cfg.update(known)
    # 名称后缀上下文标记：moonshot-v1-32k / ernie-4.5-8k / llama-3.1-70b-128k
    m = _CTX_SUFFIX_RE.search(low)
    if m and not known:
        n, unit = float(m.group(1)), m.group(2).lower()
        cfg["max_context_tokens"] = int(n * (1_048_576 if unit == "m" else 1024))
    if _THINK_RE.search(low):
        cfg["supports_thinking"] = True
    if _VISION_RE.search(low):
        cfg["supports_vision"] = True
    if provider_caps:
        if provider_caps.get("supports_thinking") and not _KNOWN_MODELS.get(low):
            cfg["supports_thinking"] = True
        if provider_caps.get("supports_vision") and not _KNOWN_MODELS.get(low):
            cfg["supports_vision"] = True
    return cfg


def clean_model_config(raw: dict, partial: bool = True) -> dict:
    """校验/规范化逐模型配置。partial=True 允许仅提供部分字段。

    Raises:
        ModelConfigError: 未知字段或类型/越界。
    """
    if not isinstance(raw, dict):
        raise ModelConfigError("config must be an object")
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key in ("provider", "model", "source", "updated_at", "created_at"):
            continue
        if key not in CFG_FIELDS:
            raise ModelConfigError(f"unknown config field '{key}', allowed: {sorted(CFG_FIELDS)}")
        if value is None or (isinstance(value, str) and not value.strip() and key in _INT_FIELDS):
            continue
        if key in _INT_FIELDS:
            lo, hi = _INT_FIELDS[key]
            try:
                iv = int(value)
            except (TypeError, ValueError):
                raise ModelConfigError(f"'{key}' must be an integer") from None
            if not lo <= iv <= hi:
                raise ModelConfigError(f"'{key}' out of range [{lo}, {hi}]: {iv}")
            out[key] = iv
        elif key in _BOOL_FIELDS:
            out[key] = bool(value)
        else:  # note
            out[key] = str(value)[:_STR_FIELDS[key]]
    if not partial:
        merged = _blank_config()
        merged.update(out)
        out = merged
    return out


class ModelConfigError(Exception):
    """模型配置中心异常（携带错误码与 HTTP status，风格与 ProviderError 对齐）。"""

    def __init__(self, message: str, code: str = "BAD_REQUEST", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _normalize_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _resolve_path(path: str | Path | None = None) -> Path:
    """解析配置文件路径：显式参数 > 环境变量 TEA_MODEL_CONFIG > ~/.tea_agent/model_config.json。"""
    if path:
        return Path(path)
    env = os.environ.get("TEA_MODEL_CONFIG", "").strip()
    return Path(env) if env else DEFAULT_CONFIG_FILE


class ModelConfigStore:
    """~/.tea_agent/model_config.json 读写服务（providers/models/roles）。"""

    def __init__(self, path: str | Path | None = None):
        self._path = _resolve_path(path)
        self._lock = threading.RLock()
        self._data: dict | None = None
        self._mtime: float = 0.0

    @property
    def file_path(self) -> Path:
        return self._path

    # ── 加载 / 保存 ─────────────────────────────────────────

    def load(self, force: bool = False) -> dict:
        """加载全量配置；文件缺失/损坏时自动 bootstrap。mtime 变化自动重载。"""
        mtime = 0.0
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            pass
        with self._lock:
            if not force and self._data is not None and mtime == self._mtime:
                return self._data
            data: dict | None = None
            if mtime and self._path.exists():
                try:
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and isinstance(raw.get("providers"), dict):
                        data = raw
                except Exception as e:
                    logger.warning("model_config.json corrupt (%s), rebinding bootstrap", e)
            if data is None:
                data = self._bootstrap()
                self._write_unlocked(data)
            elif self._sync_registry(data):
                # 注册表(内置⊕自定义)有新增 provider/model 或自定义被删除 → 增量同步落盘
                self._write_unlocked(data)
            # 所有加载路径都必须回填缓存，否则 save() 读到 _data=None 会写空覆盖文件
            self._data, self._mtime = data, self._stat_mtime()
            return data

    def save(self) -> dict:
        """原子落盘（临时文件 + os.replace，旧文件时间戳 .bak 备份）。"""
        with self._lock:
            if self._data is None:
                self.load()
            data = self._data or {}
            self._write_unlocked(data)
            self._mtime = self._stat_mtime()
            return data

    def _stat_mtime(self) -> float:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return 0.0

    def _write_unlocked(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data.setdefault("version", SCHEMA_VERSION)
        data["updated_at"] = _now()
        if self._path.exists():
            bak = self._path.with_name(
                f"model_config.json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
            try:
                shutil.copy2(self._path, bak)
            except OSError:
                pass
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
        logger.info("model_config saved: %d providers / %s",
                    len(data.get("providers", {})), self._path)

    # ── bootstrap ───────────────────────────────────────────

    def _merged_registry(self) -> dict[str, dict]:
        """内置 PROVIDERS ⊕ custom_providers.yaml（直接读文件，不依赖 model_manager）。"""
        from tea_agent.providers import PROVIDERS

        merged: dict[str, dict] = {}
        for name, info in PROVIDERS.items():
            merged[name] = {**info, "source": "builtin"}
        custom_file = CONFIG_DIR / "custom_providers.yaml"
        if custom_file.exists():
            try:
                import yaml

                raw = yaml.safe_load(custom_file.read_text(encoding="utf-8")) or {}
                providers = raw.get("providers", {}) if isinstance(raw, dict) else {}
                for name, info in providers.items():
                    if isinstance(info, dict):
                        merged[str(name)] = {**info, "source": "custom"}
            except Exception as e:
                logger.warning("custom_providers.yaml read failed: %s", e)
        return merged

    def _bootstrap(self) -> dict:
        """从注册表构建全量配置，并按当前 config.yaml 写入角色绑定。"""
        data: dict = {"version": SCHEMA_VERSION, "roles": {}, "providers": {}}
        for name, info in self._merged_registry().items():
            caps = {k: info.get(k, False) for k in ("supports_thinking", "supports_vision")}
            models: dict[str, dict] = {}
            ids = list(dict.fromkeys([*(info.get("models") or []),
                                      info.get("default_model", "")]))
            for mid in ids:
                if mid:
                    models[mid] = guess_model_config(mid, caps)
            data["providers"][name] = {
                "source": info.get("source", "builtin"),
                "api_url": info.get("api_url", ""),
                "default_model": info.get("default_model", ""),
                "description": info.get("description", ""),
                "supports_thinking": bool(info.get("supports_thinking", False)),
                "supports_vision": bool(info.get("supports_vision", False)),
                "models": models,
            }
        # 角色绑定：读取当前 config.yaml
        try:
            from tea_agent.config import load_config

            cfg = load_config(None)
            for role in ROLES:
                mc = getattr(cfg, f"{role}_model", None)
                model_name = getattr(mc, "model_name", "") or ""
                if not model_name:
                    continue
                api_url = getattr(mc, "api_url", "") or ""
                provider = self._find_provider(data, api_url)
                data["roles"][role] = {"provider": provider, "model": model_name,
                                       "api_url": api_url, "updated_at": _now()}
                if provider and model_name not in data["providers"][provider]["models"]:
                    data["providers"][provider]["models"][model_name] = guess_model_config(
                        model_name, data["providers"][provider])
        except Exception as e:
            logger.warning("bootstrap roles from config.yaml failed: %s", e)
        return data

    @staticmethod
    def _find_provider(data: dict, api_url: str) -> str:
        want = _normalize_url(api_url)
        if not want:
            return ""
        for name, p in data.get("providers", {}).items():
            if _normalize_url(p.get("api_url", "")) == want:
                return name
        return ""

    def _sync_registry(self, data: dict) -> bool:
        """把注册表(内置 PROVIDERS ⊕ custom_providers.yaml)增量并入 data：

        - 缺失的 provider/model → 按启发式补齐（用户已编辑的条目永不覆盖）
        - provider 元信息(api_url/default_model/description/capabilities) → 以注册表为准刷新
        - 已从 custom_providers.yaml 删除的自定义 provider → 清理（连带其角色绑定）

        Returns: True 表示 data 被修改，需要落盘。
        """
        changed = False
        registry = self._merged_registry()
        providers = data.setdefault("providers", {})
        for name, info in registry.items():
            caps = {"supports_thinking": bool(info.get("supports_thinking", False)),
                    "supports_vision": bool(info.get("supports_vision", False))}
            p = providers.get(name)
            if p is None:
                p = {"source": info.get("source", "builtin"), "models": {}}
                providers[name] = p
                changed = True
            for field in ("source", "api_url", "default_model", "description"):
                val = info.get(field, "") or ""
                if field == "source":
                    val = info.get("source", "builtin")
                if p.get(field, "") != val:
                    p[field] = val
                    changed = True
            for cap in ("supports_thinking", "supports_vision"):
                if bool(p.get(cap, False)) != caps[cap]:
                    p[cap] = caps[cap]
                    changed = True
            for mid in [*(info.get("models") or []), info.get("default_model", "")]:
                if mid and mid not in p["models"]:
                    p["models"][mid] = guess_model_config(mid, caps)
                    changed = True
        # 清理已不存在的自定义 provider（内置 provider 不会出现在删除场景）
        for name in list(providers):
            if providers[name].get("source") == "custom" and name not in registry:
                providers.pop(name, None)
                changed = True
                for role, r in list(data.get("roles", {}).items()):
                    if (r or {}).get("provider", "") == name:
                        data["roles"].pop(role, None)
                        changed = True
        return changed

    # ── 查询 ────────────────────────────────────────────────

    @staticmethod
    def _get_provider(data: dict, name: str) -> dict:
        """按名称(不区分大小写)查找 provider，找不到抛 NOT_FOUND。"""
        want = (name or "").strip()
        providers = data.get("providers", {})
        if want in providers:
            return providers[want]
        for k, v in providers.items():
            if k.lower() == want.lower():
                return v
        raise ModelConfigError(f"provider '{name}' not found", "NOT_FOUND", 404)

    @staticmethod
    def _get_model(provider: dict, model: str) -> tuple[str, dict]:
        """按模型 id(不区分大小写)查找，返回 (规范id, config)。"""
        want = (model or "").strip()
        models = provider.get("models", {})
        if want in models:
            return want, models[want]
        for k, v in models.items():
            if k.lower() == want.lower():
                return k, v
        raise ModelConfigError(f"model '{model}' not found", "NOT_FOUND", 404)

    def get_model_config(self, provider: str, model: str) -> dict:
        """单模型有效配置（无存储条目时回退启发式，标记 source）。"""
        data = self.load()
        try:
            p = self._get_provider(data, provider)
            mid, cfg = self._get_model(p, model)
            out = _blank_config()
            out.update({k: v for k, v in cfg.items() if k in CFG_FIELDS})
            out["source"] = "saved"
            return out
        except ModelConfigError:
            out = guess_model_config(model, None)
            out["source"] = "heuristic"
            return out

    def panel(self, config_path: str = "") -> dict:
        """模型管理面板全量视图：providers(含逐模型配置) + roles + active(实时) 。"""
        data = self.load()
        active: dict[str, Any] = {}
        try:
            from tea_agent.config import load_config

            cfg = load_config(config_path or None)
            for role in ROLES:
                mc = getattr(cfg, f"{role}_model", None)
                if mc is None or not getattr(mc, "model_name", ""):
                    active[role] = None
                    continue
                key = getattr(mc, "api_key", "") or ""
                active[role] = {
                    "model": mc.model_name,
                    "api_url": mc.api_url,
                    "api_key_masked": (key[:6] + "****" + key[-4:]) if len(key) > 12 else "",
                    "temperature": mc.temperature,
                    "max_tokens": mc.max_tokens,
                    "top_p": mc.top_p,
                    "max_context_tokens": mc.max_context_tokens,
                    "options": mc.options or {},
                }
        except Exception as e:
            logger.warning("panel active from config failed: %s", e)
        providers = []
        total_models = 0
        for name in sorted(data.get("providers", {}), key=str.lower):
            p = data["providers"][name]
            models = []
            for mid in sorted(p.get("models", {}), key=str.lower):
                cfg = _blank_config()
                cfg.update({k: v for k, v in p["models"][mid].items() if k in CFG_FIELDS})
                models.append({"id": mid, "config": cfg,
                               "is_default": mid == p.get("default_model", "")})
            total_models += len(models)
            providers.append({
                "name": name,
                "source": p.get("source", "builtin"),
                "api_url": p.get("api_url", ""),
                "default_model": p.get("default_model", ""),
                "description": p.get("description", ""),
                "supports_thinking": bool(p.get("supports_thinking", False)),
                "supports_vision": bool(p.get("supports_vision", False)),
                "models": models,
                "model_count": len(models),
            })
        return {
            "ok": True,
            "version": data.get("version", SCHEMA_VERSION),
            "file": str(self._path),
            "updated_at": data.get("updated_at", ""),
            "roles": data.get("roles", {}),
            "active": active,
            "providers": providers,
            "total_providers": len(providers),
            "total_models": total_models,
        }

    def roles(self) -> dict:
        return dict(self.load().get("roles", {}))

    # ── provider 级写操作（供 model_manager CRUD 镜像） ─────

    def ensure_provider(self, name: str, meta: dict) -> dict:
        """新增/更新 provider 元信息并同步其模型列表（保留已存的逐模型配置）。"""
        name = (name or "").strip()
        if not name:
            raise ModelConfigError("provider name required")
        data = self.load()
        p = data["providers"].get(name)
        caps = {k: bool(meta.get(k, False)) for k in ("supports_thinking", "supports_vision")}
        if p is None:
            p = {"source": meta.get("source", "custom"), "api_url": meta.get("api_url", ""),
                 "default_model": meta.get("default_model", ""),
                 "description": meta.get("description", ""), "models": {}}
            data["providers"][name] = p
        p["api_url"] = meta.get("api_url", p.get("api_url", ""))
        p["default_model"] = meta.get("default_model", p.get("default_model", ""))
        p["description"] = meta.get("description", p.get("description", ""))
        p["supports_thinking"] = caps["supports_thinking"]
        p["supports_vision"] = caps["supports_vision"]
        ids = list(dict.fromkeys([*(meta.get("models") or []),
                                  meta.get("default_model", "")]))
        for mid in ids:
            if mid and mid not in p["models"]:
                p["models"][mid] = guess_model_config(mid, caps)
        self.save()
        return p

    def remove_provider(self, name: str) -> bool:
        data = self.load()
        providers = data.get("providers", {})
        target = next((k for k in providers if k.lower() == (name or "").strip().lower()), None)
        if not target:
            return False
        providers.pop(target)
        for role, r in list(data.get("roles", {}).items()):
            if (r or {}).get("provider", "").lower() == target.lower():
                data["roles"].pop(role, None)
        self.save()
        return True

    def upsert_model(self, provider: str, model: str,
                     config: dict | None = None) -> dict:
        """新增模型条目（config 缺省用启发式默认），已存在则合并更新。"""
        model = (model or "").strip()
        if not model:
            raise ModelConfigError("model id required")
        data = self.load()
        try:
            p = self._get_provider(data, provider)
        except ModelConfigError:
            meta = self._merged_registry().get((provider or "").strip())
            if meta is None:
                raise
            p = self.ensure_provider(str(provider).strip(), meta)
        patch = clean_model_config(config or {}, partial=True)
        entry = p["models"].get(model)
        if entry is None:
            entry = guess_model_config(model, p)
            p["models"][model] = entry
        entry.update(patch)
        entry["updated_at"] = _now()
        self.save()
        return {"provider": provider, "model": model, "config": entry}

    def update_model_config(self, provider: str, model: str, patch: dict) -> dict:
        """更新既有模型配置（面板「保存模型配置」入口）。模型不存在时按默认创建。"""
        return self.upsert_model(provider, model, patch)

    def delete_model(self, provider: str, model: str) -> bool:
        data = self.load()
        p = self._get_provider(data, provider)
        models = p.get("models", {})
        target = next((k for k in models if k.lower() == (model or "").strip().lower()), None)
        if target is None:
            return False
        models.pop(target)
        self.save()
        return True

    def sync_live_models(self, provider: str, model_ids: list[str]) -> dict:
        """把实时 /v1/models 查询结果写回配置：新增(启发式默认)，已有条目不动。"""
        data = self.load()
        p = self._get_provider(data, provider)
        added, existing = [], []
        for mid in model_ids or []:
            mid = str(mid or "").strip()
            if not mid:
                continue
            if mid in p["models"] or any(k.lower() == mid.lower() for k in p["models"]):
                existing.append(mid)
                continue
            p["models"][mid] = guess_model_config(mid, p)
            added.append(mid)
        p["live_synced_at"] = _now()
        if added:
            self.save()
        return {"provider": provider, "added": added, "kept": existing,
                "total": len(p["models"])}

    def set_role(self, role: str, provider: str, model: str, api_url: str = "") -> None:
        if role not in ROLES:
            raise ModelConfigError(f"invalid role '{role}', use one of {list(ROLES)}")
        if not (model or "").strip():
            raise ModelConfigError("model required")
        data = self.load()
        data.setdefault("roles", {})[role] = {
            "provider": provider or "", "model": model.strip(),
            "api_url": api_url or "", "updated_at": _now()}
        self.save()


# ── 模块级单例 ──────────────────────────────────────────────

_store: ModelConfigStore | None = None
_store_lock = threading.Lock()


def get_model_config_store(path: str | Path | None = None) -> ModelConfigStore:
    """获取 ModelConfigStore 单例；解析路径变化时自动重建（测试可用 TEA_MODEL_CONFIG 隔离）。"""
    global _store
    target = _resolve_path(path)
    with _store_lock:
        if _store is None or _store.file_path != target:
            _store = ModelConfigStore(target)
        return _store
