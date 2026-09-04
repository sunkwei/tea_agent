"""Provider Catalog — ~/.tea_agent/provider.yaml 唯一事实源

Tea Agent 供应商→模型 目录的统一持久化层。将原先分散的
  - providers.py 内置静态注册表
  - ~/.tea_agent/custom_providers.yaml（自定义供应商）
  - ~/.tea_agent/model_config.json（逐模型能力/roles）
  - config*.yaml 内嵌完整模型块
收敛为单一 YAML 文件；config*.yaml 仅以 p_name + m_name 引用本文件条目。

provider.yaml schema (v1):
    version: 1
    providers:
      <p_name>:                       # 供应商名（内置或自定义，唯一）
        api_url: "https://..."        # OpenAI 兼容端点
        api_key: "sk-..."             # API Key（用户级，明文；展示时掩码）
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
from typing import Any

logger = logging.getLogger("tea_agent.provider_store")

try:
    import yaml

    HAS_YAML = True
except ImportError:  # pragma: no cover
    HAS_YAML = False

CONFIG_DIR = Path.home() / ".tea_agent"
DEFAULT_PROVIDER_FILE = CONFIG_DIR / "provider.yaml"
SCHEMA_VERSION = 1

# 模型能力字段（与 model_config.json / ModelConfig.options 对齐）
_INT_FIELDS = {"max_context_tokens", "max_output_tokens"}
_BOOL_FIELDS = {"supports_vision", "supports_reasoning", "supports_tools"}
_STR_FIELDS = {"note", "reasoning_effort"}
MODEL_FIELDS = _INT_FIELDS | _BOOL_FIELDS | _STR_FIELDS
PROVIDER_FIELDS = {"api_url", "api_key", "default_model", "description",
                   "supports_vision", "supports_thinking", "source"}

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
        "note": "",
    }


def guess_model_cfg(model_id: str) -> dict:
    """按模型名给出启发式能力默认（无内置元数据时的兜底）。"""
    cfg = _blank_model_cfg()
    low = (model_id or "").strip().lower()
    if not low:
        return cfg
    try:
        from tea_agent.model_config import guess_model_config as _gmc

        g = _gmc(low) or {}
        cfg["max_context_tokens"] = int(g.get("max_context_tokens") or 0)
        cfg["max_output_tokens"] = int(g.get("max_output_tokens") or 0)
        cfg["supports_vision"] = bool(g.get("supports_vision"))
        cfg["supports_reasoning"] = bool(g.get("supports_thinking"))
        cfg["supports_tools"] = bool(g.get("supports_tools", True))
    except Exception:  # pragma: no cover - 防御性
        pass
    return cfg


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
            except (TypeError, ValueError):
                pass
        elif k in _BOOL_FIELDS:
            cfg[k] = bool(v)
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
    return p


class ProviderStore:
    """~/.tea_agent/provider.yaml 读写服务（供应商 CRUD + 模型目录 + resolve）。"""

    def __init__(self, path: str | Path | None = None):
        self._path = _resolve_path(path)
        self._lock = threading.RLock()
        self._data: dict | None = None
        self._mtime: float = 0.0

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
            except OSError:  # pragma: no cover
                pass
        tmp = self._path.with_suffix(".yaml.tmp")
        tmp.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        os.replace(tmp, self._path)
        logger.info("provider.yaml saved: %d providers", len(data.get("providers", {})))

    # ── bootstrap / 迁移 ─────────────────────────────────────

    def _builtin_registry(self) -> dict[str, dict]:
        """内置静态目录（providers.py PROVIDERS），转换为 provider.yaml 模型字段。"""
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
                for entry in info.get("models") or []:
                    if isinstance(entry, str):
                        p["models"][entry] = guess_model_cfg(entry)
                    elif isinstance(entry, dict) and entry.get("id"):
                        mid = str(entry["id"])
                        cfg = guess_model_cfg(mid)
                        if entry.get("context_window"):
                            cfg["max_context_tokens"] = int(entry["context_window"])
                        if entry.get("max_output_tokens"):
                            cfg["max_output_tokens"] = int(entry["max_output_tokens"])
                        if entry.get("supports_vision") is not None:
                            cfg["supports_vision"] = bool(entry["supports_vision"])
                        if entry.get("supports_thinking") is not None:
                            cfg["supports_reasoning"] = bool(entry["supports_thinking"])
                        if entry.get("description"):
                            cfg["note"] = str(entry["description"])
                        p["models"][mid] = cfg
                if not p["models"] and p["default_model"]:
                    p["models"][p["default_model"]] = guess_model_cfg(p["default_model"])
                out[name] = p
        except Exception as e:  # pragma: no cover - 防御性
            logger.debug("builtin registry import failed: %s", e)
        return out

    def _bootstrap(self) -> dict:
        """首启 bootstrap：内置目录 ⊕ 自定义供应商 ⊕ 既有 config*.yaml 供应商信息。"""
        data: dict[str, dict] = {}
        # 1) 内置静态目录
        for name, p in self._builtin_registry().items():
            data[name] = p
        # 2) 旧 custom_providers.yaml（含 api_key 时一并并入）
        try:
            cp = Path.home() / ".tea_agent" / "custom_providers.yaml"
            if cp.exists():
                raw = yaml.safe_load(cp.read_text(encoding="utf-8")) or {}
                for name, info in (raw.get("providers") or {}).items():
                    if isinstance(info, dict):
                        self._merge_provider(data, name, self._convert_custom(info), source="custom")
        except Exception as e:
            logger.debug("custom_providers.yaml merge skipped: %s", e)
        # 3) 既有 config*.yaml 供应商信息（api_key/api_url/模型）
        self._merge_config_profiles(data)
        # 4) 旧 model_config.json 逐模型能力（覆盖启发式默认）
        try:
            mc = Path.home() / ".tea_agent" / "model_config.json"
            if mc.exists():
                import json

                raw = json.loads(mc.read_text(encoding="utf-8")) or {}
                for name, p in (raw.get("providers") or {}).items():
                    target = self._find_provider(data, name) or self._find_by_url(data, p.get("api_url", ""))
                    if target is None:
                        continue
                    for mid, mcfg in (p.get("models") or {}).items():
                        entry = data[target]["models"].setdefault(mid, guess_model_cfg(mid))
                        for k in MODEL_FIELDS:
                            if k in mcfg and mcfg.get(k) is not None:
                                entry[k] = mcfg[k]
        except Exception as e:
            logger.debug("model_config.json merge skipped: %s", e)
        return {"version": SCHEMA_VERSION, "providers": data}

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

    def _merge_config_profiles(self, data: dict[str, dict]) -> None:
        """搜集 config*.yaml 的 main/cheap/vision 供应商信息并入目录。

        同一 api_url 出现多个不同 api_key 时保留一个（优先 config.yaml 主模型 key），
        模型合并去重；无法按 url 归属内置的（自定义网关）以 profile 名为 p_name 新增。
        """
        base = CONFIG_DIR
        try:
            files = sorted(list(base.glob("config*.yaml")) + list(base.glob("config*.yml")))
        except OSError:
            return
        # 第一遍：统计 url → 优先 key（config.yaml 主模型优先）
        url_key: dict[str, str] = {}
        for f in files:
            try:
                raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            mb = raw.get("main_model")
            if not isinstance(mb, dict):
                continue
            url = str(mb.get("api_url") or "").strip().rstrip("/").lower()
            key = str(mb.get("api_key") or "").strip()
            if not url or not key:
                continue
            if url not in url_key or f.name == "config.yaml":
                url_key[url] = key
        # 第二遍：按文件合并
        for f in files:
            try:
                raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            stem = f.stem
            profile_name = "default" if stem == "config" else (
                stem[len("config_"):] if stem.startswith("config_") else stem
            )
            found = False
            for role in ("main_model", "cheap_model", "vision_model"):
                block = raw.get(role)
                if not isinstance(block, dict):
                    continue
                url = str(block.get("api_url") or "").strip()
                model = str(block.get("model_name") or "").strip()
                key = str(block.get("api_key") or "").strip()
                if not url:
                    continue
                pname = self._find_by_url(data, url) or self._builtin_name_for_url(url)
                if pname is None:
                    pname = profile_name
                p = data.setdefault(pname, {
                    "api_url": url,
                    "api_key": "",
                    "default_model": model,
                    "description": f"profile · {f.name}",
                    "supports_vision": bool(block.get("options", {}).get("supports_vision", False)),
                    "supports_thinking": bool(block.get("options", {}).get("supports_reasoning", False)),
                    "source": "builtin" if pname in self._builtin_registry() else "config",
                    "models": {},
                })
                p["api_url"] = url
                # key：url_key 优先（同 url 多 key 保留一个），文件自己 key 与目录一致才写入
                kept = url_key.get(url.rstrip("/").lower(), "")
                if kept and (not p.get("api_key") or p.get("api_key") == kept):
                    p["api_key"] = kept
                elif not p.get("api_key"):
                    p["api_key"] = key
                if model:
                    self._ensure_model_entry(data, pname, model, block)
                found = True
            if not found:
                # 引用式 config（provider/model 字段）也尝试补全默认模型
                self._ensure_ref_model(data, f)
        return

    def _ensure_ref_model(self, data: dict, f: Path) -> None:
        """引用式 config：main_model: {provider, model} → provider.yaml 目录补齐模型。"""
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        mb = raw.get("main_model")
        if not isinstance(mb, dict):
            return
        pname = str(mb.get("provider") or "").strip()
        model = str(mb.get("model") or mb.get("model_name") or "").strip()
        if not pname or not model:
            return
        p = data.setdefault(pname, {
            "api_url": str(mb.get("api_url") or ""),
            "api_key": str(mb.get("api_key") or ""),
            "default_model": model,
            "description": f"profile · {f.name}",
            "source": "custom", "models": {},
        })
        if model not in p["models"]:
            p["models"][model] = guess_model_cfg(model)

    @staticmethod
    def _ensure_model_entry(data: dict, pname: str, model: str, block: dict) -> None:
        p = data.get(pname) or {}
        m = p.setdefault("models", {}).setdefault(model, guess_model_cfg(model))
        opts = block.get("options") if isinstance(block, dict) else None
        if isinstance(opts, dict):
            if opts.get("supports_vision") is not None:
                m["supports_vision"] = bool(opts["supports_vision"])
            if opts.get("supports_reasoning") is not None:
                m["supports_reasoning"] = bool(opts["supports_reasoning"])
        if block.get("max_tokens"):
            try:
                m["max_output_tokens"] = int(block["max_tokens"])
            except (TypeError, ValueError):
                pass
        if block.get("max_context_tokens"):
            try:
                m["max_context_tokens"] = int(block["max_context_tokens"])
            except (TypeError, ValueError):
                pass
        if block.get("reasoning_effort"):
            m["reasoning_effort"] = str(block["reasoning_effort"])

    @staticmethod
    def _builtin_name_for_url(url: str) -> str | None:
        try:
            from tea_agent.providers import PROVIDERS

            want = (url or "").strip().rstrip("/").lower()
            for name, info in PROVIDERS.items():
                if (info.get("api_url") or "").strip().rstrip("/").lower() == want:
                    return name
        except Exception:
            pass
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
                catalog.append({
                    "id": mid,
                    "max_context_tokens": int(cfg.get("max_context_tokens") or 0),
                    "max_output_tokens": int(cfg.get("max_output_tokens") or 0),
                    "supports_vision": bool(cfg.get("supports_vision", False)),
                    "supports_reasoning": bool(cfg.get("supports_reasoning", False)),
                    "supports_tools": bool(cfg.get("supports_tools", True)),
                    "reasoning_effort": cfg.get("reasoning_effort", "auto"),
                    "note": cfg.get("note", ""),
                })
            out.append({
                "name": name,
                "api_url": p.get("api_url", ""),
                "api_key_masked": _mask_key(p.get("api_key", "")),
                "default_model": p.get("default_model", ""),
                "description": p.get("description", ""),
                "source": p.get("source", "builtin"),
                "supports_vision": bool(p.get("supports_vision", False)),
                "supports_thinking": bool(p.get("supports_thinking", False)),
                "catalog": catalog,
                "model_count": len(catalog),
            })
        return out

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
        # models: 传入即整体替换（调用方负责合并），否则保留
        if isinstance(meta.get("models"), list):
            models_new = {}
            for m in meta["models"]:
                if isinstance(m, str) and m.strip():
                    models_new[m.strip()] = guess_model_cfg(m.strip())
                elif isinstance(m, dict) and m.get("id"):
                    mid = str(m["id"]).strip()
                    if not mid:
                        continue
                    models_new[mid] = _clean_model_entry(m)
            p["models"] = models_new or {p.get("default_model", ""): guess_model_cfg(p.get("default_model", ""))} if p.get("default_model") else {}
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

    def upsert_model(self, provider: str, model: str, config: dict | None = None) -> dict:
        """新增/更新模型条目（config 缺省启发式默认，仅合并白名单字段）。"""
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
            cfg.update({k: v for k, v in _clean_model_entry(config).items() if v not in ("", [], 0, False) or k in ("supports_tools",)})
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


# ── 模块级单例 ──────────────────────────────────────────────

_store: ProviderStore | None = None
_store_lock = threading.Lock()


def get_provider_store(path: str | Path | None = None) -> ProviderStore:
    """ProviderStore 单例；path 变化自动重建（测试可用 TEA_PROVIDER_FILE 隔离）。"""
    global _store
    target = _resolve_path(path)
    with _store_lock:
        if _store is None or _store.file_path != target:
            _store = ProviderStore(target)
        return _store
