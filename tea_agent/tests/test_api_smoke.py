"""公共 API 入口冒烟测试（含阳性/阴性对照）。

设计原则（源自本会话反复踩到的坑：检测器本身极易错）：
1. **阳性对照**：合成的「委托层签名漂移」必须被检出 —— 否则检测器可能空转；
2. **阴性对照**：健康的入口不得被误报 —— 否则指标淹没在假阳性里；
3. **非空转**：必须真的调用了足量入口（checked 数量下限）；
4. 真实仓库当前应为 /**零致命失败**（failures == 0）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ── 对照实验（先证明检测器会报、也不会乱报）──────────────────────

def test_positive_control_catches_signature_drift():
    """阳性对照：委托层签名漂移（本仓库真实缺陷形态）必须被检出。"""
    from tea_agent.evaluation.api_smoke import Entry, smoke

    class _Impl:
        def run(self, topic_id, existing_l3, summarize_client, extra_params=None):
            return "ok"

    class _Hub:
        def __init__(self):
            self._impl = _Impl()

        def run(self, topic_id, level2_items=None):
            # 漂移：按旧签名转发，而实现方需要 4 个参数
            return self._impl.run(topic_id, level2_items, extra_params=None)

    res = smoke([Entry("_Hub.run", _Hub().run)], pool={"topic_id": "t"})
    assert res.checked == 1, "阳性对照未被实际调用"
    assert res.failures, "检测器未能捕获签名漂移（假绿）"
    assert res.failures[0]["exc"] == "TypeError"


def test_positive_control_catches_missing_symbol():
    """阳性对照：引用不存在的符号（ImportError 形态）必须被检出。"""
    from tea_agent.evaluation.api_smoke import Entry, smoke

    def _dangling():
        raise ImportError("cannot import name 'ExperienceSolidifier'")

    res = smoke([Entry("_dangling", _dangling)])
    assert res.failures and res.failures[0]["exc"] == "ImportError"


def test_negative_control_healthy_entry_not_flagged():
    """阴性对照：健康入口不得被误报；合法入参拒绝（ValueError）视为通过。"""
    from tea_agent.evaluation.api_smoke import Entry, smoke

    class _Ok:
        def get(self, topic_id, limit=5):
            return {"topic_id": topic_id, "limit": limit}

        def strict(self, topic_id, count):
            # 最小入参合法非法是业务判断，入口本身是通的
            raise ValueError("count must be > 0")

    res = smoke([Entry("_Ok.get", _Ok().get), Entry("_Ok.strict", _Ok().strict)],
                pool={"topic_id": "t"})
    assert res.checked == 2
    assert res.failures == [], f"误报健康入口: {res.failures}"


def test_annotation_string_form_is_handled():
    """注解为字符串（`from __future__ import annotations`）时仍能正确合成参数。

    若只比较类型对象，字符串注解会全部失配 → 参数退化为 None → 假阳性。
    """
    from tea_agent.evaluation.api_smoke import Entry, smoke

    class _Mod:
        def get(self, topic_id: "str", limit: "int" = 5):
            assert isinstance(topic_id, str), f"应为 str，实得 {type(topic_id)}"
            return topic_id

    res = smoke([Entry("_Mod.get", _Mod().get)], pool={"topic_id": "t"})
    assert res.failures == [], f"字符串注解处理失败: {res.failures}"


# ── 真实仓库断言 ──────────────────────────────────────────────────

def test_public_api_entries_all_resolve():
    """`tea_agent.__all__` 的每个公开名都必须可解析（公开契约）。"""
    from tea_agent.evaluation.api_smoke import discover_public, smoke

    res = smoke(discover_public())
    assert res.checked > 0, "未发现任何公开名（非空转失效）"
    assert res.failures == [], f"公开名不可用: {res.failures}"


def test_repo_api_smoke_has_no_fatal_failures():
    """真实仓库：入口级冒烟不得出现致命失败（非空转 + 零失败）。"""
    from tea_agent.evaluation.api_smoke import run

    out = run(scope="all")
    assert out["checked"] >= 40, (
        f"仅调用 {out['checked']} 个入口，疑似非空转（应覆盖 Storage 公共方法）")
    assert out["failures"] == [], f"入口级致命失败: {out['failures'][:5]}"


def test_unexpected_exceptions_surface_detail_for_review():
    """`unexpected` 中的异常必须带定位信息，便于人工判定是否真缺陷。"""
    from tea_agent.evaluation.api_smoke import run

    out = run(scope="storage")
    for item in out["unexpected"][:3]:
        assert item["label"] and item["exc"], f"缺少定位信息: {item}"


def test_smoke_does_not_touch_real_user_data():
    """冒烟必须使用临时库，不得触碰用户真实数据库。"""
    from tea_agent.evaluation.api_smoke import discover_storage

    db, _entries = discover_storage()
    path = str(getattr(db, "db_path", "") or getattr(db, "_db_path", ""))
    assert "tmp" in path.lower() or "temp" in path.lower(), (
        f"冒烟数据库不在临时目录: {path!r}")


def test_vector_and_bytes_params_get_sized_values():
    """向量 / bytes 类参数必须拿到「有长度」的良性值。

    真实教训：`Storage.store_embedding` 的委托层曾注解 `embedding: bytes`，而实现
    方对其做 `np.array()` / `len()`。若合成器把该参数退化为 None，就会误报
    TypeError —— 那是**合成产物**而非产品缺陷（假阳性）。
    """
    from tea_agent.evaluation.api_smoke import _required_kwargs

    def fn(embedding, blob: bytes, dimension: int = 0):
        assert embedding is not None and len(embedding) >= 1, "embedding 应有长度"
        assert isinstance(blob, bytes), f"bytes 注解未识别: {type(blob)}"
        return True

    kw = _required_kwargs(fn, {})
    assert kw["embedding"] and len(kw["embedding"]) >= 1, f"向量参数合成失败: {kw}"
    assert isinstance(kw["blob"], bytes), f"bytes 参数合成失败: {kw}"
    assert "dimension" not in kw, "有默认值的参数不应被传入（减少副作用）"
