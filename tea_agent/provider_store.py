"""Provider Catalog — ~/.tea_agent/provider.yaml 唯一事实源

Tea Agent 供应商→模型 目录的统一持久化层。所有供应商、逐模型能力与
角色绑定（main/cheap）**只存本文件**，不再有 model_config.json 等第二份存储；
config*.yaml 也不再是提供商来源（仅作运行期角色引用的可选载体）。

provider.yaml schema (v1):
    version: 1
    providers:
      <p_name>:                       # 供应商名（内置或自定义，唯一）
        api_url: "https://..."        # OpenAI 兼容端点
        api_keys: ["sk-..."]       # API Keys 列表（首个=主 key；多 key 时保留全部，加载仅用首个）
        api_key: "sk-..."             # 兼容字段 = api_keys[0]（主 key）
        default_model: "..."          # 默认模型 id（须存在于 models）
        description: "..."            # 一句话说明
        supports_vision: false        # 供应商级能力兜底
        supports_thinking: true
        source: builtin|custom|config # 来源标记（迁移/展示用）
        models:                       # 模型目录（逐模型参数覆盖供应商级）
          <m_name>:
            max_context_tokens: 0     # 最大上下文（0=未知）
            max_output_tokens: 0      # 最大单次输出
            supports_vision: false
            supports_reasoning: false
            supports_tools: true
            reasoning_effort: auto    # 字符串或可接受值域列表
            note: ""

分层原则：
  - 本模块只负责 provider.yaml 读写 + 合并解析（resolve），不依赖 server/model_manager；
  - resolve 将「供应商+模型」解析为可直接写回 config.ModelConfig 的扁平元数据；
  - 内置静态目录（providers.PROVIDERS）仅作 bootstrap 数据源与缺失条目兜底。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path

logger = logging.getLogger("tea_agent.provider_store")

try:
    import yaml

    HAS_YAML = True
except ImportError:  # pragma: no cover
    HAS_YAML = False

CONFIG_DIR = Path.home() / ".tea_agent"
DEFAULT_PROVIDER_FILE = CONFIG_DIR / "provider.yaml"
SCHEMA_VERSION = 1

# 模型能力字段（与 config.ModelConfig.options 对齐）
_INT_FIELDS = {"max_context_tokens", "max_output_tokens"}
_BOOL_FIELDS = {"supports_vision", "supports_reasoning", "supports_tools"}
# 采样默认值：配置对话框可改并写回（0.0 是有效值，不可当"空"过滤）
_FLOAT_FIELDS = {"temperature", "top_p"}
_STR_FIELDS = {"note", "reasoning_effort"}
MODEL_FIELDS = _INT_FIELDS | _BOOL_FIELDS | _FLOAT_FIELDS | _STR_FIELDS
PROVIDER_FIELDS = {"api_url", "api_key", "api_keys", "default_model", "description", "supports_vision", "supports_thinking", "source"}

NAME_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,64}$")


class ProviderStoreError(Exception):
    """provider.yaml 操作异常。"""

    def __init__(self, message: str, code: str = "BAD_REQUEST", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _mask_key(api_key: str) -> str:
    """掩码 api_key：sk-abc123456789xyz → sk-abc****xyz。"""
    if not api_key:
        return ""
    if len(api_key) <= 12:
        return api_key[:2] + "****"
    return api_key[:6] + "****" + api_key[-4:]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _resolve_path(path: str | Path | None = None) -> Path:
    """解析 provider.yaml 路径：显式参数 > 环境变量 TEA_PROVIDER_FILE > ~/.tea_agent/provider.yaml。"""
    if path:
        return Path(path)
    env = os.environ.get("TEA_PROVIDER_FILE", "").strip()
    return Path(env) if env else DEFAULT_PROVIDER_FILE


# ── 启发式模型能力默认（复用 model_config.guess_model_config 的速查思路，避免循环 import） ──


def _blank_model_cfg() -> dict:
    return {
        "max_context_tokens": 0,
        "max_output_tokens": 0,
        "supports_vision": False,
        "supports_reasoning": False,
        "supports_tools": True,
        "reasoning_effort": "auto",
        "temperature": 0.7,
        "top_p": 0.9,
        "note": "",
    }


def guess_model_cfg(model_id: str) -> dict:
    """返回中性模型配置（2026-09-06 起不再按名猜测任何属性）。

    模型属性唯一来源 = provider.yaml 的 models.<m_name> 条目；未收录 →
    全 0=未知，由调用方提示用户在 provider.yaml 显式补配。model_id 入参
    仅为兼容签名，不参与任何推断。
    """
    return _blank_model_cfg()


def _clean_model_entry(raw: dict) -> dict:
    """校验/规范化单模型条目（丢弃未知字段，类型收敛）。"""
    cfg = _blank_model_cfg()
    if not isinstance(raw, dict):
        return cfg
    for k in MODEL_FIELDS:
        if k not in raw:
            continue
        v = raw[k]
        if k in _INT_FIELDS:
            try:
                cfg[k] = max(0, int(v))
            except (TypeError, ValueError) as e:
                logger.debug("provider_store.py._clean_model_entry: (TypeError, ValueError) 已忽略: %s", e)
        elif k in _BOOL_FIELDS:
            cfg[k] = bool(v)
        elif k in _FLOAT_FIELDS:
            try:
                fv = float(v)
            except (TypeError, ValueError) as e:
                logger.debug("provider_store.py._clean_model_entry float 忽略 %s=%r: %s", k, v, e)
            else:
                lo, hi = (0.0, 2.0) if k == "temperature" else (0.0, 1.0)
                cfg[k] = min(max(fv, lo), hi)
        elif k == "reasoning_effort":
            if isinstance(v, list):
                cfg[k] = [str(x) for x in v if str(x).strip()]
            else:
                cfg[k] = str(v) if v else "auto"
        else:
            cfg[k] = str(v)[:200] if v else ""
    return cfg


def _clean_provider(raw: dict) -> dict:
    """规范化供应商级字段（仅保留 MODEL_FIELDS 外的白名单）。"""
    p = {}
    for k in ("api_url", "api_key", "default_model", "description", "source"):
        if k in raw and raw.get(k):
            p[k] = str(raw[k]).strip()
    for k in ("supports_vision", "supports_thinking"):
        if k in raw:
            p[k] = bool(raw[k])
    # api_keys：多 key 支持（首个=主 key，保留顺序去重去空）
    keys: list[str] = []
    if isinstance(raw.get("api_keys"), list):
        for k in raw["api_keys"]:
            kk = str(k or "").strip()
            if kk and kk not in keys:
                keys.append(kk)
    single = str(raw.get("api_key") or "").strip()
    if single and single not in keys:
        keys.insert(0, single)
    if keys:
        p["api_keys"] = keys
        p["api_key"] = keys[0]
    return p


class ProviderStore:
    """~/.tea_agent/provider.yaml 读写服务（供应商 CRUD + 模型目录 + resolve）。"""

    def __init__(self, path: str | Path | None = None, agent_dir: str | Path | None = None):
        self._path = _resolve_path(path)
        # 遗留迁移源所在目录（~/.tea_agent）；测试可注入 tmp 隔离
        self.agent_dir = Path(agent_dir) if agent_dir else None
        self._lock = threading.RLock()
        self._data: dict | None = None
        self._mtime: float = 0.0

    def _cfg_dir(self) -> Path:
        return self.agent_dir if self.agent_dir is not None else CONFIG_DIR

    # ── 基础读写 ─────────────────────────────────────────────

    @property
    def file_path(self) -> Path:
        return self._path

    def _stat_mtime(self) -> float:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return 0.0

    def load(self, force: bool = False) -> dict:
        """加载全量；文件缺失/损坏时自动 bootstrap（内置目录 ⊕ config 迁移）。mtime 自动重载。"""
        if not HAS_YAML:
            return {"version": SCHEMA_VERSION, "providers": {}}
        mtime = self._stat_mtime()
        with self._lock:
            if not force and self._data is not None and mtime == self._mtime:
                return self._data
            data: dict | None = None
            if mtime and self._path.exists():
                try:
                    raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
                    if isinstance(raw, dict) and isinstance(raw.get("providers"), dict):
                        data = raw
                    else:
                        logger.warning("provider.yaml 结构异常，重建 bootstrap")
                except Exception as e:
                    logger.warning("provider.yaml 解析失败(%s)，重建 bootstrap", e)
            if data is None:
                data = self._bootstrap()
                self._write_unlocked(data)
            self._normalize_keys(data)
            self._data, self._mtime = data, self._stat_mtime()
            return data

    def save(self) -> dict:
        """原子落盘（临时文件 + os.replace + 时间戳 .bak）。"""
        with self._lock:
            if self._data is None:
                self.load()
            data = self._data or {}
            self._write_unlocked(data)
            self._mtime = self._stat_mtime()
            return data

    def _write_unlocked(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data.setdefault("version", SCHEMA_VERSION)
        data["updated_at"] = _now()
        if self._path.exists():
            bak = self._path.with_name(f"provider.yaml.bak.{time.strftime('%Y%m%d_%H%M%S')}")
            try:
                shutil.copy2(self._path, bak)
            except OSError as e:  # pragma: no cover
                logger.debug("provider_store.py._write_unlocked: OSError 已忽略: %s", e)
        tmp = self._path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.replace(tmp, self._path)
        logger.info("provider.yaml saved: %d providers", len(data.get("providers", {})))

    # ── bootstrap / 迁移 ─────────────────────────────────────

    @staticmethod
    def _normalize_keys(data: dict) -> None:
        """归一化 api_key/api_keys：api_keys 首位恒等于 api_key；去空去重保序。"""
        providers = data.get("providers")
        if not isinstance(providers, dict):
            return
        for pv in providers.values():
            if not isinstance(pv, dict):
                continue
            keys: list[str] = []
            raw = pv.get("api_keys")
            if isinstance(raw, list):
                for k in raw:
                    kk = str(k or "").strip()
                    if kk and kk not in keys:
                        keys.append(kk)
            single = str(pv.get("api_key") or "").strip()
            if single and single not in keys:
                keys.insert(0, single)
            if keys:
                pv["api_keys"] = keys
                pv["api_key"] = keys[0]
            elif "api_keys" in pv:
                pv.pop("api_keys")

    def _builtin_registry(self) -> dict[str, dict]:
        """内置静态目录（providers.py PROVIDERS），转换为 provider.yaml 模型字段。

        2026-09-06 起 PROVIDERS 仅含纯 id 模型清单（不内置任何属性）；
        模型属性一律由 provider.yaml 显式配置，未收录 → 0=未知。
        """
        out: dict[str, dict] = {}
        try:
            from tea_agent.providers import PROVIDERS

            for name, info in PROVIDERS.items():
                p = {
                    "api_url": info.get("api_url", ""),
                    "api_key": "",
                    "default_model": info.get("default_model", ""),
                    "description": info.get("description", ""),
                    "supports_vision": bool(info.get("supports_vision", False)),
                    "supports_thinking": bool(info.get("supports_thinking", False)),
                    "source": "builtin",
                    "models": {},
                }
                # models 均为纯 id 字符串（providers.py 不再含富条目）
                for entry in info.get("models") or []:
                    if isinstance(entry, str):
                        p["models"][entry] = guess_model_cfg(entry)
                if not p["models"] and p["default_model"]:
                    p["models"][p["default_model"]] = guess_model_cfg(p["default_model"])
                out[name] = p
        except Exception as e:  # pragma: no cover - 防御性
            logger.debug("builtin registry import failed: %s", e)
        return out

    def _bootstrap(self) -> dict:
        """首启 bootstrap：仅保留真实配置过的供应商，不预置无 key 内置目录。

        数据源（仅在 provider.yaml 缺失时一次性迁移）：custom_providers.yaml。
        内置静态目录仅作命名匹配与能力速查，绝不整体写入 provider.yaml。
        """
        data: dict[str, dict] = {}
        # 1) 旧 custom_providers.yaml（含 api_key 时一并并入）
        try:
            cp = self._cfg_dir() / "custom_providers.yaml"
            if cp.exists():
                raw = yaml.safe_load(cp.read_text(encoding="utf-8")) or {}
                for name, info in (raw.get("providers") or {}).items():
                    if isinstance(info, dict):
                        self._merge_provider(data, name, self._convert_custom(info), source="custom")
        except Exception as e:
            logger.debug("custom_providers.yaml merge skipped: %s", e)
        # config*.yaml 扫描与 model_config.json 合并均已停用：
        # provider.yaml 是所有供应商/模型/角色信息的唯一事实源。
        return {"version": SCHEMA_VERSION, "providers": data, "roles": {}}

    @staticmethod
    def _convert_custom(info: dict) -> dict:
        """custom_providers.yaml 条目 → provider 字段。"""
        p = {
            "api_url": str(info.get("api_url") or ""),
            "api_key": str(info.get("api_key") or ""),
            "default_model": str(info.get("default_model") or ""),
            "description": str(info.get("description") or ""),
            "supports_vision": bool(info.get("supports_vision", False)),
            "supports_thinking": bool(info.get("supports_thinking", False)),
            "models": {},
        }
        for m in info.get("models") or []:
            if isinstance(m, str):
                p["models"][m] = guess_model_cfg(m)
            elif isinstance(m, dict) and m.get("id"):
                mid = str(m["id"])
                cfg = guess_model_cfg(mid)
                if m.get("context_window"):
                    cfg["max_context_tokens"] = int(m["context_window"])
                if m.get("max_output_tokens"):
                    cfg["max_output_tokens"] = int(m["max_output_tokens"])
                if m.get("supports_vision") is not None:
                    cfg["supports_vision"] = bool(m["supports_vision"])
                if m.get("supports_thinking") is not None:
                    cfg["supports_reasoning"] = bool(m["supports_thinking"])
                if m.get("description"):
                    cfg["note"] = str(m["description"])
                p["models"][mid] = cfg
        if not p["models"] and p["default_model"]:
            p["models"][p["default_model"]] = guess_model_cfg(p["default_model"])
        return p

    @staticmethod
    @staticmethod
    def _builtin_name_for_url(url: str) -> str | None:
        try:
            from tea_agent.providers import PROVIDERS

            want = (url or "").strip().rstrip("/").lower()
            for name, info in PROVIDERS.items():
                if (info.get("api_url") or "").strip().rstrip("/").lower() == want:
                    return name
        except Exception as e:
            logger.debug("provider_store.py._builtin_name_for_url: Exception 已忽略: %s", e)
        return None

    def _find_by_url(self, data: dict[str, dict], url: str) -> str | None:
        want = (url or "").strip().rstrip("/").lower()
        if not want:
            return None
        for name, p in data.items():
            if (p.get("api_url") or "").strip().rstrip("/").lower() == want:
                return name
        return None

    def _find_provider(self, data: dict[str, dict], name: str) -> str | None:
        want = (name or "").strip().lower()
        for k in data:
            if k.lower() == want:
                return k
        return None

    def _merge_provider(self, data: dict[str, dict], name: str, p: dict, source: str) -> None:
        existing = self._find_provider(data, name)
        if existing:
            target = data[existing]
            for k in ("api_url", "api_key", "default_model", "description"):
                if p.get(k) and not target.get(k):
                    target[k] = p[k]
            for k in ("supports_vision", "supports_thinking"):
                if p.get(k):
                    target[k] = bool(p[k])
            for mid, cfg in p.get("models", {}).items():
                if mid not in target.setdefault("models", {}):
                    target["models"][mid] = cfg
            return
        p["source"] = source
        data[name] = p

    # ── 查询 / resolve ───────────────────────────────────────

    def providers(self) -> dict[str, dict]:
        """全部供应商原始数据（含 api_key，仅供内部/迁移使用）。"""
        return dict(self.load().get("providers", {}))

    def list_providers(self) -> list[dict]:
        """对外列表：掩码 api_key，模型收敛为 catalog（逐模型能力）。"""
        data = self.load().get("providers", {})
        out = []
        for name in sorted(data, key=str.lower):
            p = data[name]
            models = p.get("models") or {}
            catalog = []
            for mid in sorted(models, key=str.lower):
                cfg = models[mid]
                catalog.append(
                    {
                        "id": mid,
                        "max_context_tokens": int(cfg.get("max_context_tokens") or 0),
                        "max_output_tokens": int(cfg.get("max_output_tokens") or 0),
                        "supports_vision": bool(cfg.get("supports_vision", False)),
                        "supports_reasoning": bool(cfg.get("supports_reasoning", False)),
                        "supports_tools": bool(cfg.get("supports_tools", True)),
                        "reasoning_effort": cfg.get("reasoning_effort", "auto"),
                        "note": cfg.get("note", ""),
                    }
                )
            keys = list(p.get("api_keys") or [])
            if not keys and p.get("api_key"):
                keys = [str(p["api_key"])]
            out.append(
                {
                    "name": name,
                    "api_url": p.get("api_url", ""),
                    "api_key_masked": _mask_key(keys[0] if keys else p.get("api_key", "")),
                    "api_keys_masked": [_mask_key(k) for k in keys if k],
                    "key_count": len(keys),
                    "default_model": p.get("default_model", ""),
                    "description": p.get("description", ""),
                    "source": p.get("source", "builtin"),
                    "supports_vision": bool(p.get("supports_vision", False)),
                    "supports_thinking": bool(p.get("supports_thinking", False)),
                    "catalog": catalog,
                    "model_count": len(catalog),
                }
            )
        return out

    def provider_name_for_url(self, api_url: str) -> str:
        """按 api_url 反查供应商名（供内嵌式配置回写 roles 时补齐绑定）。

        Returns:
            命中的供应商名；未命中返回空串
        """
        return self._find_by_url(self.load().get("providers", {}), api_url or "") or ""

    def get_provider(self, name: str) -> dict | None:
        """按名取供应商原始数据（含真实 api_key，仅内部使用）。"""
        data = self.load().get("providers", {})
        key = self._find_provider(data, name)
        if key is None:
            return None
        return {"name": key, **data[key]}

    def get_model(self, provider: str, model: str) -> dict | None:
        """取某供应商下模型的「有效」能力（模型级 ⊕ 供应商级兜底）。"""
        p = self.get_provider(provider)
        if p is None:
            return None
        models = p.get("models") or {}
        key = next((k for k in models if k.lower() == (model or "").strip().lower()), None)
        cfg = models.get(key or model) or {}
        return {
            "id": key or model,
            "max_context_tokens": int(cfg.get("max_context_tokens") or 0),
            "max_output_tokens": int(cfg.get("max_output_tokens") or 0),
            "supports_vision": bool(cfg.get("supports_vision", p.get("supports_vision", False))),
            "supports_reasoning": bool(cfg.get("supports_reasoning", p.get("supports_thinking", False))),
            "supports_tools": bool(cfg.get("supports_tools", True)),
            "reasoning_effort": cfg.get("reasoning_effort", "auto"),
            "note": cfg.get("note", ""),
        }

    def resolve(self, provider: str, model: str) -> dict | None:
        """把 p_name + m_name 解析为 config.ModelConfig 可直接套用的扁平元数据。

        Returns: {provider, model, api_url, api_key, max_context_tokens,
                  max_output_tokens, supports_vision, supports_reasoning,
                  reasoning_effort, options:{...}}；provider/model 不存在返回 None。
        """
        p = self.get_provider(provider)
        if p is None:
            return None
        api_url = p.get("api_url", "")
        api_key = p.get("api_key", "")
        models = p.get("models") or {}
        key = next((k for k in models if k.lower() == (model or "").strip().lower()), None)
        if key is None and model:
            key = model
        cfg = models.get(key) or {}
        eff = {
            "provider": p["name"],
            "model": key or model,
            "api_url": api_url,
            "api_key": api_key,
            "max_context_tokens": int(cfg.get("max_context_tokens") or 0),
            "max_output_tokens": int(cfg.get("max_output_tokens") or 0),
            "supports_vision": bool(cfg.get("supports_vision", p.get("supports_vision", False))),
            "supports_reasoning": bool(cfg.get("supports_reasoning", p.get("supports_thinking", False))),
            "reasoning_effort": cfg.get("reasoning_effort", "auto"),
        }
        eff["options"] = {
            "supports_vision": eff["supports_vision"],
            "supports_reasoning": eff["supports_reasoning"],
        }
        return eff

    # ── 写操作 ───────────────────────────────────────────────

    def upsert_provider(self, name: str, meta: dict) -> dict:
        """新增/更新供应商（保留既有模型目录；meta 中 models 可选新增）。"""
        name = (name or "").strip()
        if not NAME_RE.match(name):
            raise ProviderStoreError(f"invalid provider name '{name}'", "BAD_REQUEST", 400)
        data = self.load()
        providers = data.setdefault("providers", {})
        key = self._find_provider(providers, name) or name
        p = providers.get(key)
        if p is None:
            p = {"source": "custom", "models": {}}
            providers[key] = p
        p.update(_clean_provider(meta))
        # models: 传入 id 列表时**合并**（既有富条目优先保留，仅缺失项补启发式默认）；
        # 传入 dict 条目时按条目覆盖。纯 id 列表整体替换会抹掉 provider.yaml 里
        # 已配置的逐模型能力/窗口（ensure_provider 传的正是 get_provider 的 id 列表）。
        if isinstance(meta.get("models"), list):
            existing = p.get("models") if isinstance(p.get("models"), dict) else {}
            models_new: dict = {}
            for m in meta["models"]:
                if isinstance(m, str) and m.strip():
                    mid = m.strip()
                    models_new[mid] = existing.get(mid) or guess_model_cfg(mid)
                elif isinstance(m, dict) and m.get("id"):
                    mid = str(m["id"]).strip()
                    if mid:
                        models_new[mid] = _clean_model_entry(m)
            p["models"] = models_new
        if p.get("default_model") and p["default_model"] not in p.setdefault("models", {}):
            p["models"][p["default_model"]] = guess_model_cfg(p["default_model"])
        self.save()
        return {"name": key, **p}

    def remove_provider(self, name: str) -> bool:
        data = self.load()
        providers = data.get("providers", {})
        key = self._find_provider(providers, name)
        if key is None:
            return False
        providers.pop(key)
        self.save()
        return True

    def upsert_model(self, provider: str, model: str, config: dict | None = None, strict: bool = False) -> dict:
        """新增/更新模型条目（config 缺省启发式默认，仅合并白名单字段）。

        strict=True 时拒绝含未知字段的 config（面板 PUT 用），避免用户以为
        写进去了、实则被静默丢弃 —— 旧实现直接抛错，此处保留该契约。
        """
        if strict and config:
            unknown = set(config) - MODEL_FIELDS
            if unknown:
                raise ProviderStoreError(f"unknown config field(s): {sorted(unknown)}", "BAD_REQUEST", 400)
        model = (model or "").strip()
        provider = (provider or "").strip()
        if not provider or not model:
            raise ProviderStoreError("provider and model required", "BAD_REQUEST", 400)
        data = self.load()
        providers = data.setdefault("providers", {})
        key = self._find_provider(providers, provider)
        if key is None:
            p = {"api_url": "", "api_key": "", "source": "custom", "models": {}}
            providers[provider] = p
            key = provider
        p = providers[key]
        cfg = p.setdefault("models", {}).setdefault(model, guess_model_cfg(model))
        if config:
            cleaned = _clean_model_entry(config)
            # 只回写调用方显式提供的键（blank 默认不得覆盖既有值）；
            # float(0.0)/bool(False) 是有效采样/能力值，必须可写入
            # （旧过滤 `v not in ("", [], 0, False)` 会把 0.0/False 当空值丢弃）。
            for k in config:
                if k not in cleaned:
                    continue
                v = cleaned[k]
                if k in _FLOAT_FIELDS or k in _BOOL_FIELDS or v not in ("", [], 0, False):
                    cfg[k] = v
        if not p.get("default_model"):
            p["default_model"] = model
        self.save()
        return {"provider": key, "model": model, "config": cfg}

    def delete_model(self, provider: str, model: str) -> bool:
        data = self.load()
        providers = data.get("providers", {})
        pkey = self._find_provider(providers, provider)
        if pkey is None:
            return False
        models = providers[pkey].get("models", {})
        mkey = next((k for k in models if k.lower() == (model or "").strip().lower()), None)
        if mkey is None:
            return False
        models.pop(mkey)
        self.save()
        return True

    def sync_models(self, provider: str, model_ids: list[str]) -> dict:
        """实时 /v1/models 查询结果写回：新增启发式默认，已有条目不动。"""
        data = self.load()
        providers = data.setdefault("providers", {})
        pkey = self._find_provider(providers, provider)
        if pkey is None:
            raise ProviderStoreError(f"provider '{provider}' not found", "NOT_FOUND", 404)
        p = providers[pkey]
        models = p.setdefault("models", {})
        added, kept = [], []
        for mid in model_ids or []:
            mid = str(mid or "").strip()
            if not mid:
                continue
            if mid in models or any(k.lower() == mid.lower() for k in models):
                kept.append(mid)
                continue
            models[mid] = guess_model_cfg(mid)
            added.append(mid)
        p["live_synced_at"] = _now()
        if added:
            self.save()
        return {"provider": pkey, "added": added, "kept": kept, "total": len(models)}

    # ── 在线模型查询 / 端点推断 ──────────────────────────────

    @staticmethod
    def _models_endpoint(api_url: str) -> str:
        """根据 api_url 推断 OpenAI 兼容 /v1/models 端点。"""
        url = (api_url or "").strip().rstrip("/")
        if not url:
            return ""
        if url.endswith("/v1") or url.endswith("/v1beta/openai"):
            return url + "/models"
        return url + "/v1/models"

    @staticmethod
    def _chat_endpoint(api_url: str) -> str:
        """根据 api_url 推断 OpenAI 兼容 /chat/completions 端点。"""
        url = (api_url or "").strip().rstrip("/")
        if not url:
            return ""
        if url.endswith("/v1") or url.endswith("/v1beta/openai"):
            return url + "/chat/completions"
        return url + "/v1/chat/completions"

    def query_live_models(self, provider: str, api_key: str = "", refresh: bool = False, timeout: int = 15) -> dict:
        """实时查询某供应商的 /v1/models 在线模型列表；失败/无 key 时静态 fallback。

        Args:
            provider: 供应商名（p_name）
            api_key: 可选覆盖；留空使用 provider.yaml 中已存的 key
            refresh: True=强制实时查询并更新缓存；False=5 分钟内优先返回缓存
            timeout: 请求超时秒数

        Returns:
            {"ok": True, "provider", "endpoint", "source": live|static|cache,
             "models": [...], "total": N} 或 {"ok": False, "error"}
        """
        p = self.get_provider(provider)
        if p is None:
            return {"ok": False, "error": f"provider '{provider}' not found", "code": "NOT_FOUND"}
        # 静态目录 fallback 视图（含逐模型能力，来自 models dict）
        models_map = p.get("models") or {}
        static_models = []
        for mid in sorted(models_map, key=str.lower):
            cfg = models_map[mid]
            static_models.append(
                {
                    "id": mid,
                    "max_context_tokens": int(cfg.get("max_context_tokens") or 0),
                    "max_output_tokens": int(cfg.get("max_output_tokens") or 0),
                    "supports_vision": bool(cfg.get("supports_vision", False)),
                    "supports_reasoning": bool(cfg.get("supports_reasoning", False)),
                    "note": cfg.get("note", ""),
                }
            )
        base = {
            "provider": p["name"],
            "models": static_models,
            "total": len(static_models),
            "endpoint": self._models_endpoint(p.get("api_url") or ""),
        }
        key = api_key or (p.get("api_key") or "")
        api_url = p.get("api_url") or ""
        if not key or not api_url:
            base.update({"source": "static", "needs_key": not key})
            return {"ok": True, **base}

        cache_key = f"{p['name']}:{key}"
        now = time.time()
        cache = getattr(self, "_live_cache", None)
        if cache is None:
            cache = {}
            self._live_cache = cache
        if not refresh:
            hit = cache.get(cache_key)
            if hit and now - hit[0] < 300.0:
                res = dict(hit[1])
                res["source"] = "cache"
                return {"ok": True, **res}
        endpoint = self._models_endpoint(api_url)
        import json
        import urllib.request as _req

        req = _req.Request(
            endpoint,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with _req.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # 网络失败 → 静态 fallback（UI 永远有数据）
            base.update({"source": "static", "error_hint": str(e)})
            return {"ok": True, **base}
        live_models = []
        for item in (data.get("data") or []) if isinstance(data, dict) else []:
            if isinstance(item, dict) and item.get("id"):
                live_models.append({"id": item["id"], "owned_by": item.get("owned_by", "")})
        if not live_models and isinstance(data, dict) and data.get("error"):
            base.update({"source": "static", "error_hint": str(data["error"])})
            return {"ok": True, **base}
        result = {"provider": p["name"], "endpoint": endpoint, "source": "live", "models": live_models, "total": len(live_models)}
        cache[cache_key] = (now, result)
        return {"ok": True, **result}

    def test_connection(self, provider: str, model: str = "", api_key: str = "", timeout: int = 15) -> dict:
        """最小 chat/completions 请求验证「端点 + key + 模型」三重有效。

        Args:
            provider: 供应商名（p_name）
            model: 目标模型 id；留空用 default_model
            api_key: 可选覆盖；留空使用 provider.yaml 已存 key
            timeout: 请求超时秒数

        Returns:
            {"ok": True, "latency_ms", "model_reported"} 或 {"ok": False, "error"}
        """
        p = self.get_provider(provider)
        if p is None:
            return {"ok": False, "error": f"provider '{provider}' not found"}
        key = api_key or (p.get("api_key") or "")
        api_url = p.get("api_url") or ""
        model = model or (p.get("default_model") or "")
        if not key:
            return {"ok": False, "error": f"provider '{provider}' 未配置 api_key"}
        endpoint = self._chat_endpoint(api_url)
        if not endpoint:
            return {"ok": False, "error": f"invalid api_url: {api_url!r}"}
        import json
        import time as _time
        import urllib.error as _err
        import urllib.request as _req

        payload = {"model": model or "default", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1, "stream": False}
        req = _req.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        t0 = _time.time()
        try:
            with _req.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
        except _err.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
            return {"ok": False, "error": f"HTTP {e.code}: {e.reason}" + (f" — {body}" if body else "")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        latency_ms = round((_time.time() - t0) * 1000, 1)
        if isinstance(data, dict) and data.get("error"):
            return {"ok": False, "error": str(data["error"])}
        reported = str(data.get("model", "")) if isinstance(data, dict) else ""
        return {"ok": True, "latency_ms": latency_ms, "model_reported": reported}

    # ── 清理：剔除未配置的内置占位 ───────────────────────────

    def prune_unconfigured(self, keep_models: bool = True) -> dict:
        """删除「无 api_key 且非 config/custom 来源」的内置占位条目。

        用户诉求：provider.yaml 只保留真实配置过的供应商（手动填入过 key 的），
        不要把 providers.py 静态目录里没有 key 的候选全部占位。

        Args:
            keep_models: 是否同时清理仅存在于被删供应商下的孤儿模型（默认 True）

        Returns:
            {"removed": [name...]}
        """
        data = self.load()
        providers = data.get("providers", {})
        removed = []
        for name in list(providers):
            p = providers[name]
            src = p.get("source", "builtin")
            has_key = bool((p.get("api_key") or "").strip())
            if src == "builtin" and not has_key:
                removed.append(name)
                providers.pop(name, None)
        if removed:
            self.save()
            logger.info("pruned unconfigured builtin placeholders: %s", removed)
        return {"removed": removed}

    # ── 运行时参数（settings 段）— 取代已删除的 config.yaml ────

    def get_settings(self) -> dict:
        """运行时参数（agent 行为调参）。原 config.yaml 的顶层标量字段。

        config.yaml 已删除：运行时参数与 roles 一并存 provider.yaml，
        使「一个用户级配置文件」成为唯一事实源。
        """
        return dict(self.load().get("settings") or {})

    def update_settings(self, patch: dict) -> dict:
        """合并写入运行时参数（只覆盖 patch 中出现的键）。"""
        patch = {k: v for k, v in dict(patch or {}).items() if k != "paths"}
        if not patch:
            return self.get_settings()
        data = self.load()
        cur = data.get("settings")
        if not isinstance(cur, dict):
            cur = {}
            data["settings"] = cur
        cur.update(patch)
        self.save()
        return dict(cur)

    # ── 角色绑定（main/cheap）— provider.yaml roles 段 ────────

    def roles(self) -> dict:
        """当前角色绑定 {role: {provider, model, api_url}}。"""
        return dict(self.load().get("roles", {}))

    def set_role(self, role: str, provider: str, model: str, api_url: str = "") -> None:
        """写入角色绑定（落 provider.yaml 的 roles 段）。"""
        if role not in ("main", "cheap"):
            raise ProviderStoreError(f"invalid role '{role}', use main|cheap", "BAD_REQUEST", 400)
        if not (model or "").strip():
            raise ProviderStoreError("model required", "BAD_REQUEST", 400)
        data = self.load()
        data.setdefault("roles", {})[role] = {"provider": provider or "", "model": model.strip(), "api_url": api_url or "", "updated_at": _now()}
        self.save()

    # ── 兼容 ModelConfigStore 的调用面（无独立文件） ──────────

    def ensure_provider(self, name: str, meta: dict) -> dict:
        """新增/更新供应商元信息（保留已存模型条目）。"""
        return self.upsert_provider(name, meta)

    def get_model_config(self, provider: str, model: str) -> dict:
        """逐模型有效配置（含 source 标记，供面板显示）。"""
        m = self.get_model(provider, model)
        if m is None:
            return {**_blank_model_cfg(), "source": "heuristic"}
        return {**m, "source": "saved"}

    def update_model_config(self, provider: str, model: str, patch: dict) -> dict:
        """更新既有模型配置（面板「保存模型配置」入口）。

        面板沿用历史字段名 ``supports_thinking``；provider.yaml 模型条目里同名
        概念叫 ``supports_reasoning``，在此归一，接受两种写法。
        未知字段直接拒绝（strict），避免"看似保存成功、实则被丢弃"。
        """
        patch = dict(patch or {})
        if "supports_thinking" in patch and "supports_reasoning" not in patch:
            patch = {"supports_reasoning": patch.pop("supports_thinking"), **patch}
        return self.upsert_model(provider, model, patch, strict=True)

    def sync_live_models(self, provider: str, model_ids: list[str]) -> dict:
        """在线模型列表写回（仅新增，不动既有条目）。"""
        return self.sync_models(provider, model_ids)

    def panel(self, config_path: str = "") -> dict:
        """模型管理面板全量视图：providers（含逐模型配置）+ roles + active。

        models 行沿用历史契约（``{"id", "config": {...}, "is_default"}``），
        供 Web 面板与既有调用方无改动消费；「当前使用中」由 active 段表达。
        config 内 ``supports_thinking`` 映射自 provider.yaml 的
        ``supports_reasoning``（同一能力的两处命名，面板沿用旧名）。
        """
        roles = self.roles()
        data = self.load().get("providers", {})
        providers = []
        total = 0
        for p in self.list_providers():
            p = dict(p)
            default_model = p.get("default_model", "")
            raw_models = (data.get(p["name"]) or {}).get("models") or {}
            rows = []
            for entry in p.get("catalog", []):
                mid = entry["id"]
                rows.append(
                    {
                        "id": mid,
                        "is_default": mid == default_model,
                        "config": {
                            "max_context_tokens": entry.get("max_context_tokens", 0),
                            "max_output_tokens": entry.get("max_output_tokens", 0),
                            "supports_thinking": entry.get("supports_reasoning", False),
                            "supports_vision": entry.get("supports_vision", False),
                            "supports_tools": entry.get("supports_tools", True),
                            "note": entry.get("note", ""),
                            "source": "saved" if mid in raw_models else "heuristic",
                        },
                    }
                )
            total += len(rows)
            p["models"] = rows
            p["model_count"] = len(rows)
            providers.append(p)
        return {
            "ok": True,
            "version": SCHEMA_VERSION,
            "file": str(self.file_path),
            "updated_at": self.load().get("updated_at", ""),
            "roles": roles,
            # active.<role> 必须是 dict（面板/前端按 {provider, model, api_url} 读）
            "active": {r: dict(v) if isinstance(v, dict) else {"model": v} for r, v in roles.items()},
            "providers": providers,
            "total_providers": len(providers),
            "total_models": total,
        }


# ── 模块级单例 ──────────────────────────────────────────────

_store: ProviderStore | None = None
_store_lock = threading.Lock()


def get_provider_store(path: str | Path | None = None, agent_dir: str | Path | None = None) -> ProviderStore:
    """ProviderStore 单例；path/agent_dir 变化自动重建（测试可用 TEA_PROVIDER_FILE + tmp 目录隔离）。"""
    global _store
    target = _resolve_path(path)
    adir = Path(agent_dir) if agent_dir else None
    with _store_lock:
        if _store is None or _store.file_path != target or _store.agent_dir != adir:
            _store = ProviderStore(target, agent_dir=adir)
        return _store
