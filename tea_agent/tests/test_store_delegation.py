"""Storage 纯委托层签名一致性（结构性不变量 + 运行时实证）。

背景（真实缺陷，由终端报错发现）：
    agent.pipeline: L2→L3 摘要失败: Storage.generate_l2_to_l3_summary()
    got an unexpected keyword argument 'extra_params'

`Storage.generate_l2_to_l3_summary` 是**纯委托层**（body 仅一条
`return self._summaries.<同名方法>(...)`），但长期停留在旧签名（只收 3 参：
topic_id / level2_items / cheap_model），而真实实现
`SummaryStore.generate_l2_to_l3_summary` 需要 6 参。调用方按 6 参调用 →
每次触发必然 TypeError → 被上层 `except` 吞成 WARNING → **L3 语义摘要长期
静默失效**（每约 30 轮触发一次，从未成功）。

两条测试分别覆盖：
1. 运行时实证：按调用方真实入参调用，必须正常返回（回归该缺陷本身）。
2. 结构性不变量：scan 全部 store 纯委托层，调用点实参须被真实实现接受
   （防止同类漂移再次发生）。
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "tea_agent" / "store"


# ── 1. 运行时实证 ────────────────────────────────────────────────

def test_l2_to_l3_summary_accepts_caller_arguments(tmp_path):
    """按 agent_pipeline 的真实入参调用委托层，必须正常返回而非 TypeError。

    overflow_items 为空 → 实现直接返回 (existing_l3, 空 usage)，
    无需真实 LLM 客户端即可完成端到端委托路径验证。
    """
    from tea_agent.store import Storage

    db = Storage(str(tmp_path / "deleg.db"))
    try:
        result = db.generate_l2_to_l3_summary(
            "topic-x",
            [],                      # overflow_items 为空 → 不触发 LLM
            "已有摘要",               # existing_l3
            None,                    # summarize_client（空溢出时不使用）
            "cheap-model",           # summarize_model
            extra_params={"temperature": 0.3},
        )
    finally:
        try:
            db.conn.close()
        except Exception:
            pass

    assert isinstance(result, tuple) and len(result) == 2, f"返回值形态异常: {result!r}"
    assert result[0] == "已有摘要", f"空溢出时应原样返回既有 L3 摘要: {result[0]!r}"
    assert isinstance(result[1], dict), f"usage 应为 dict: {result[1]!r}"


def test_l2_to_l3_summary_signature_matches_implementation():
    """委托层与实现方的参数名须逐一对齐（防止再次漂移）。"""
    from tea_agent.store._core import Storage
    from tea_agent.store._summaries import SummaryStore

    w = list(inspect.signature(Storage.generate_l2_to_l3_summary).parameters)[1:]
    i = list(inspect.signature(SummaryStore.generate_l2_to_l3_summary).parameters)[1:]
    assert w == i, f"委托层参数 {w} != 实现方参数 {i}"


# ── 2. 结构性不变量：调用点感知的委托层检查 ──────────────────────

def _delegation_call(fn):
    """body 仅一条 `return self.<attr>.<name>(...)` 时返回 (name, call)。"""
    try:
        src = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None  # 含未缩进多行字符串 → dedent 失效；由阳性对照保证非空转
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = [b for b in node.body if not isinstance(b, ast.Expr)]
            if len(body) != 1 or not isinstance(body[0], ast.Return):
                return None
            call = body[0].value
            if not isinstance(call, ast.Call):
                return None
            f = call.func
            if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute)
                    and isinstance(f.value.value, ast.Name)
                    and f.value.value.id == "self"):
                return f.attr, call
            return None
    return None


def _call_problems(call, impl_sig) -> list:
    """调用点实参 vs 实现方签名 → 仅报确实不兼容者（名字差异/位置传参不算）。"""
    params = list(impl_sig.parameters.values())[1:]  # 去掉 self（由 self.<attr> 绑定）
    by_name = {p.name: p for p in params}
    has_kwargs = any(p.kind == p.VAR_KEYWORD for p in params)
    has_varargs = any(p.kind == p.VAR_POSITIONAL for p in params)
    pos_params = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    problems, provided = [], set()

    for kw in call.keywords:
        if kw.arg is None:          # **expr 解包：无法静态判定，保守跳过
            continue
        provided.add(kw.arg)
        p = by_name.get(kw.arg)
        if p is None:
            if not has_kwargs:
                problems.append(f"关键字实参 {kw.arg!r} 实现方不接受")
        elif p.kind == p.POSITIONAL_ONLY:
            problems.append(f"关键字实参 {kw.arg!r} 为实现方的仅位置参数")

    if not any(isinstance(a, ast.Starred) for a in call.args):
        if len(call.args) > len(pos_params) and not has_varargs:
            problems.append(f"位置实参 {len(call.args)} 个 > 实现方上限 {len(pos_params)}")

    for idx, p in enumerate(pos_params):
        if p.name in provided or idx < len(call.args):
            continue
        if p.default is inspect.Parameter.empty:
            problems.append(f"实现方必填参数 {p.name!r} 未被提供")
    return problems


def test_store_pure_delegations_are_call_site_compatible():
    """store 包内所有纯委托层的调用点实参，须被真实实现接受。

    纯委托层（`return self._x.same_name(...)`）是「无逻辑的转发」，
    其参数必须与实现一一对应；一旦实现演进而委托层未同步，调用方就会
    在运行期 TypeError —— 且常被上层 except 吞掉，形成静默失效。
    """
    from tea_agent.store._core import Storage

    # 阳性对照：检测器必须能识别已知委托（防探针空转假绿）
    probe = _delegation_call(Storage.generate_l2_to_l3_summary)
    assert probe and probe[0] == "generate_l2_to_l3_summary", f"检测器失效: {probe!r}"

    mods = [importlib.import_module(f"tea_agent.store.{p.stem}")
            for p in sorted(STORE.glob("*.py")) if p.name != "__init__.py"]

    impls: dict = {}
    for m in mods:
        for _cn, cls in inspect.getmembers(m, inspect.isclass):
            if not cls.__module__.startswith("tea_agent.store"):
                continue
            for name, fn in vars(cls).items():
                if isinstance(fn, (staticmethod, classmethod)):
                    fn = fn.__func__
                if inspect.isfunction(fn):
                    try:
                        impls.setdefault(name, {})[cls.__name__] = inspect.signature(fn)
                    except (TypeError, ValueError):
                        pass

    drifts = []
    for m in mods:
        for _cn, cls in inspect.getmembers(m, inspect.isclass):
            if not cls.__module__.startswith("tea_agent.store"):
                continue
            for name, fn in vars(cls).items():
                if not inspect.isfunction(fn):
                    continue
                got = _delegation_call(fn)
                if not got or got[0] != name:
                    continue
                _tgt, call = got
                cands = {c: s for c, s in impls.get(name, {}).items()
                         if c != cls.__name__}
                if len(cands) != 1:
                    continue  # 无法唯一确定实现方 → 跳过
                impl_cls, impl_sig = next(iter(cands.items()))
                problems = _call_problems(call, impl_sig)
                if problems:
                    drifts.append({"wrapper": f"{cls.__name__}.{name}",
                                   "impl": f"{impl_cls}.{name}",
                                   "problems": problems})
    assert drifts == [], f"委托层与实现不兼容 {len(drifts)} 处: " \
                         f"{json.dumps(drifts, ensure_ascii=False)}"
