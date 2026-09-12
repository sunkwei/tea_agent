"""公共 API 入口冒烟 —— 检出「入口级」静默失效（运行时实证）。

为什么需要它（本仓库两个真实缺陷都无法被静态检查捕获）：
- `Storage.generate_l2_to_l3_summary` 委托层签名漂移 → 调用即 TypeError，
  被上层 except 吞成 WARNING，L3 语义摘要长期静默失效；
- `tea_agent.__all__` 声明 8 个公开名却只绑定 2 个 → `from tea_agent import
  Storage` 直接 ImportError。
两者都只在**运行期、入口处**暴露：静态扫描看到的是「代码存在」，看不到
「调用得通不通」。

判定原则（避免假阳性与假绿）：
- **计为失败**：TypeError / ImportError / NameError / AttributeError /
  UnboundLocalError —— 这些是「签名对不上」「符号不存在」的特征，即功能已死。
- **视为通过**：ValueError / KeyError / IndexError / NotImplementedError 等
  合法入参拒绝 —— 说明入口本身是通的，只是最小入参不构成有效业务输入。
  若把这类也计为失败，指标会淹没在噪声里而失去信号。
- 其余异常单独归入 `unexpected` 供人工审阅，不直接计入失败（避免合成入参
  造成的误判被当成缺陷）。
- 只填**必填参数**、放过带默认值的参数，最大限度减少副作用。
- 全程使用临时数据库，不触碰用户真实数据。
"""

from __future__ import annotations

import inspect
import logging
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("toolkit")

# 入口级管线错误：出现即意味着功能不可达
FATAL_EXCS = (TypeError, ImportError, NameError, AttributeError, UnboundLocalError)
# 合法入参拒绝：入口是通的，只是合成入参不构成有效业务输入
REJECT_EXCS = (ValueError, KeyError, IndexError, NotImplementedError)

_MISSING = object()


@dataclass
class Entry:
    """一个待冒烟的入口。"""

    label: str
    fn: object
    kind: str = "callable"


@dataclass
class Result:
    """冒烟结果桶。

    checked=实际调用数；failures=入口级致命失败（TypeError/ImportError 等）；
    unexpected=待人工审阅的其它异常；skipped=无法调用（无签名等）。
    """

    checked: int = 0
    failures: list = field(default_factory=list)
    unexpected: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    def as_dict(self) -> dict:
        """转为可序列化字典（供工具层与基准直接使用）。"""
        return {
            "checked": self.checked,
            "failures": self.failures,
            "unexpected": self.unexpected,
            "skipped": self.skipped,
        }


def _ann_name(ann) -> str:
    """归一化注解名。

    `from __future__ import annotations` 会让注解变成**字符串**（'str' 而非 str），
    若只比较类型对象，所有注解都会失配 → 合成参数退化为 None → 假阳性。
    """
    if ann is inspect.Parameter.empty:
        return ""
    if isinstance(ann, str):
        return ann
    return getattr(ann, "__name__", "")


def _value_for(pname: str, ann, pool: dict):
    """为必填参数合成一个「最小良性」值。"""
    if pname in pool:
        return pool[pname]
    low = pname.lower()

    # 顺序重要：list/dict 必须先于 str（'list[str]' 同时含两者）
    a = _ann_name(ann)
    if a:
        if "list" in a or "tuple" in a or "sequence" in a or "iterable" in a:
            return []
        if "dict" in a or "mapping" in a:
            return {}
        if "bool" in a:
            return False
        if "bytes" in a or "bytearray" in a:
            return b"smoke"
        if "int" in a or "float" in a:
            return 1
        if "str" in a or "path" in a.lower():
            return "smoke-id" if low.endswith("_id") else "smoke"

    # 向量/嵌入类参数：实现方普遍对其做 len()/np.array()，传 None 会直接 TypeError
    # —— 那是合成入参的产物而非缺陷，须给一个「有长度」的良性值。
    if "embedding" in low or "vector" in low:
        return [0.0]

    # 无注解 / 注解不可识别时按参数名推断
    if low.endswith("_id") or low == "id":
        return "smoke-id"
    if low in ("limit", "top_k", "count", "num", "size", "max", "n"):
        return 1
    if low.startswith(("is_", "has_", "enable", "allow", "with_")):
        return False
    if "list" in low or "items" in low or "rounds" in low or "files" in low:
        return []
    if "dict" in low or "params" in low or "usage" in low:
        return {}
    if any(k in low for k in ("title", "name", "content", "msg", "text", "query",
                              "prompt", "summary", "path", "cmd", "command", "key")):
        return "smoke"
    return None


def _required_kwargs(fn, pool: dict) -> dict | None:
    """按签名合成必填关键字参数；无法取签名时返回 None。"""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    kwargs = {}
    for pname, p in sig.parameters.items():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if p.default is not inspect.Parameter.empty:
            continue  # 有默认值 → 不传，减少副作用
        kwargs[pname] = _value_for(pname, p.annotation, pool)
    return kwargs


def smoke(entries: list, pool: dict | None = None) -> Result:
    """对入口列表做最小调用，返回结构化结果（不依赖真实业务数据）。"""
    pool = dict(pool or {})
    res = Result()
    for e in entries:
        if not callable(e.fn):
            res.skipped.append({"label": e.label, "why": "not callable"})
            continue
        if e.kind == "resolve":
            # 只验可解析性：类（如 Agent）与重构造入口的实例化需要真实配置/凭据，
            # 盲构造既非「入口级管线」验证，也会引入假阳性。公开契约的价值在
            # 「拿得到」，而这一层已由发现阶段（getattr）判定。
            res.checked += 1
            continue
        kwargs = _required_kwargs(e.fn, pool)
        if kwargs is None:
            res.skipped.append({"label": e.label, "why": "no signature"})
            continue
        res.checked += 1
        try:
            e.fn(**kwargs)
        except REJECT_EXCS as ex:
            # 合法拒绝：入口通了，只是最小入参不是有效业务输入
            logger.debug("api_smoke: %s 拒绝最小入参 %s", e.label, type(ex).__name__)
        except FATAL_EXCS as ex:
            res.failures.append({"label": e.label, "exc": type(ex).__name__,
                                 "msg": str(ex)[:200]})
        except Exception as ex:  # noqa: BLE001 — 归入待审阅，不直接判失败
            res.unexpected.append({"label": e.label, "exc": type(ex).__name__,
                                   "msg": str(ex)[:200]})
    return res


# ── 入口发现 ────────────────────────────────────────────────────────

def discover_public() -> list:
    """包公开名（`tea_agent.__all__`）—— 解析本身即验证公开契约。"""
    out = []
    try:
        import tea_agent  # noqa: PLC0415 — 函数内导入，避免新增导入期边
    except (ImportError, SyntaxError, OSError) as ex:
        # 只兜导包常见失败形态；其它异常应外透（那是真 bug，不该被降级成一条记录）
        return [Entry("tea_agent(包导入)", _raise(ex), "public")]
    for name in list(getattr(tea_agent, "__all__", [])):
        obj = getattr(tea_agent, name, _MISSING)
        if obj is _MISSING:
            # 解析失败：构造一个「调用即抛 ImportError」的入口，使公开契约破损
            # 走与其它失败相同的报告通道（kind=call 保证它会被实际调用）
            out.append(Entry(f"tea_agent.{name}", _raise(ImportError(
                f"__all__ 声明但运行时不可用: {name}")), "call"))
        else:
            out.append(Entry(f"tea_agent.{name}", obj, "resolve"))
    return out


def _raise(ex):
    """构造一个「调用即抛既定异常」的入口，用于把解析失败纳入同一报告。"""
    def _fn(*_a, **_k):
        raise ex
    return _fn


def discover_storage() -> tuple:
    """Storage 公共方法（委托枢纽，历史上漂移缺陷所在）。返回 (db, entries)。"""
    from tea_agent.store import Storage  # noqa: PLC0415

    db = Storage(str(Path(tempfile.mkdtemp()) / "api_smoke.db"))
    entries = []
    for name in sorted(dir(Storage)):
        if name.startswith("_"):
            continue
        raw = getattr(Storage, name, None)
        if isinstance(raw, property) or not callable(raw):
            continue
        fn = getattr(db, name, None)
        if callable(fn):
            entries.append(Entry(f"Storage.{name}", fn, "method"))
    return db, entries


def _seed_pool(db) -> dict:
    """建立最小可用上下文（建一个主题），使带 `*_id` 的入口拿到真实 ID。"""
    pool: dict = {}
    try:
        tid = db.create_topic("api-smoke")
        if isinstance(tid, str) and tid:
            pool["topic_id"] = tid
    except (sqlite3.Error, OSError, ValueError, KeyError) as ex:
        # 建种子话题失败不影响主体冒烟：带 *_id 的入口退化为合成 ID
        logger.debug("api_smoke: 建种子主题失败: %s", ex)
    return pool


def run(scope: str = "all", with_entries: bool = False) -> dict:
    """执行冒烟。scope: public / storage / all。"""
    entries: list = []
    pool: dict = {}
    if scope in ("public", "all"):
        entries += discover_public()
    if scope in ("storage", "all"):
        try:
            db, st_entries = discover_storage()
            pool = _seed_pool(db)
            entries += st_entries
        except (ImportError, sqlite3.Error, OSError, ValueError) as ex:
            # Storage 不可用（缺依赖/库文件异常）→ 降级为仅公开名冒烟
            logger.warning("api_smoke: Storage 入口发现失败: %s", ex)
    res = smoke(entries, pool)
    out = res.as_dict()
    out["scope"] = scope
    out["discovered"] = len(entries)
    if with_entries:
        out["entries"] = [e.label for e in entries]
    return out
