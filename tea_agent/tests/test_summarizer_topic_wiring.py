"""摘要组件的 topic 定位 + numpy 依赖声明回归测试。

## 背景（真实缺陷）

``SummarizerComponent.summarize_old_history`` 曾写成::

    topic_id = getattr(self.ctx, "current_topic_id", None)

但 ``SessionContext`` 上**没有** ``current_topic_id`` 这个字段（该属性只在
session/agent 上）→ 恒为 ``None`` → 函数每次都在 guard 处静默早退，
**L3 历史摘要完全失效**（实测：连 ``get_unsummarized_conversations`` 都不会被调用）。

与 ``session/components/tool.py`` 的 ``_log_tool_event`` 是同一类缺陷
（Component 只持有 ctx，却按 session 的属性名取值）。

## 为什么用「是否越过 guard」而不是「摘要是否生成」做断言

摘要生成依赖 LLM，测试里必须 stub；一旦 stub 出问题（或异常被 except 吞掉），
"摘要没生成"与"guard 早退"就分不清 —— 那正是本缺陷长期潜伏的原因。
因此断言钉在**更早、更确定**的一环：``get_unsummarized_conversations`` 是否被调用。
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tea_agent.session.components.summarizer import SummarizerComponent  # noqa: E402
from tea_agent.session.context import SessionContext  # noqa: E402
from tea_agent.store import Storage  # noqa: E402


@pytest.fixture()
def storage(tmp_path):
    st = Storage(str(tmp_path / "chat_history.db"))
    yield st
    try:
        st.close()
    except Exception:
        pass


def _seed_conversations(storage, topic_id: str, n: int = 4) -> None:
    """造 n 轮未摘要对话（超过 keep_turns 才会触发摘要）。"""
    for i in range(n):
        cid = storage.save_msg(topic_id, f"用户{i}", "", False)
        storage.update_msg_rounds(cid, f"AI{i}", False)


class _ApiStub:
    """仅用于让调用链继续前进；真正的断言在 guard 处。"""

    def call_summarize_api(self, *a, **k):
        raise RuntimeError("reached summarize api")


def _spy_unsummarized(storage, calls: list):
    """包装 get_unsummarized_conversations，记录被调用的 topic。"""
    orig = storage.get_unsummarized_conversations
    storage.get_unsummarized_conversations = lambda t: (calls.append(t), orig(t))[1]


# ─────────── 契约：SessionContext 的字段名 ───────────

def test_session_context_has_no_current_topic_id():
    """SessionContext 不存在 current_topic_id —— 组件读它必然得到 None。

    本用例把这个「陷阱字段」钉住：若将来有人真的给 ctx 加上
    current_topic_id，本用例会红，提醒同步检查各组件是否已统一到 topic_id。
    """
    ctx = SessionContext()
    assert not hasattr(ctx, "current_topic_id"), (
        "SessionContext 不应有 current_topic_id（组件应统一读 topic_id）"
    )
    assert hasattr(ctx, "topic_id"), "SessionContext 必须有 topic_id"


# ─────────── 行为：guard 必须被越过 ───────────

def test_summarizer_proceeds_when_ctx_topic_id_set(storage):
    """设了 ctx.topic_id → 摘要流程必须真的启动（越过 guard）。

    缺陷版本（读 ctx.current_topic_id）下本用例失败：调用次数为 0。
    """
    tid = storage.create_topic("摘要测试")
    _seed_conversations(storage, tid, n=4)

    ctx = SessionContext(storage=storage, keep_turns=1)
    ctx.topic_id = tid
    comp = SummarizerComponent(ctx)

    calls: list = []
    _spy_unsummarized(storage, calls)

    comp.summarize_old_history(_ApiStub(), lambda: (_ for _ in ()).throw(RuntimeError("no client")))

    assert calls == [tid], (
        f"guard 未越过 —— 摘要组件读错了主题字段（实际调用: {calls}）"
    )


def test_summarizer_skips_when_no_topic(storage):
    """无 topic_id 时仍应静默早退（别把防护修成「无脑摘要」）。"""
    ctx = SessionContext(storage=storage, keep_turns=1)  # topic_id 为空
    comp = SummarizerComponent(ctx)

    calls: list = []
    _spy_unsummarized(storage, calls)

    comp.summarize_old_history(_ApiStub(), lambda: (None, "m"))

    assert calls == [], "无主题时不应触碰存储"


def test_summarizer_skips_when_disabled(storage):
    """disable_summary / disable_l3 生效时不应进入摘要流程。"""
    tid = storage.create_topic("T")
    _seed_conversations(storage, tid, n=4)

    ctx = SessionContext(storage=storage, keep_turns=1, disable_summary=True)
    ctx.topic_id = tid
    comp = SummarizerComponent(ctx)

    calls: list = []
    _spy_unsummarized(storage, calls)

    comp.summarize_old_history(_ApiStub(), lambda: (None, "m"))

    assert calls == [], "禁用摘要时不应进入流程"


# ─────────── numpy 依赖声明 ───────────

def _pyproject() -> dict:
    import tomllib

    root = pathlib.Path(__file__).resolve().parents[2]
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def test_numpy_not_a_core_dependency():
    """numpy 不应是核心依赖 —— 核心包零使用，声明它会误导用户装无用重依赖。"""
    deps = _pyproject()["project"]["dependencies"]
    assert not any("numpy" in d for d in deps), (
        f"numpy 不应出现在核心依赖（核心包零使用）: {deps}"
    )


def test_numpy_declared_in_demo_extra():
    """numpy 必须仍被 demo extra 声明 —— 否则 demo 脚本跑不起来。"""
    extras = _pyproject()["project"]["optional-dependencies"]
    assert any("numpy" in d for d in extras.get("demo", [])), (
        "demo/ 下的脚本需要 numpy，应保留在 [demo] extra"
    )


def test_core_package_has_no_numpy_import():
    """核心包（非 demo）不得 import numpy —— 这是「可安全移除依赖」的不变式。

    只要核心包出现一处顶层 numpy import，移除依赖就会让用户 ImportError。
    本用例是该不变式的守卫：将来有人往核心包塞 numpy，此处立刻变红。
    """
    pkg = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for f in sorted(pkg.rglob("*.py")):
        s = f.as_posix()
        if "/demo/" in s or "__pycache__" in s:
            continue
        for i, line in enumerate(
            f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            if line.strip().startswith(("import numpy", "from numpy")):
                offenders.append(f"{s}:{i}")
    assert not offenders, f"核心包出现 numpy import（移除依赖会 ImportError）: {offenders}"
