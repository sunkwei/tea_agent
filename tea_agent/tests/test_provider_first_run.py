"""首启流程回归 — provider.yaml 中心化（config.yaml 不再是启动前提）。

钉住的行为契约：
1. load_config 在 main_model 缺失/全空时，用 provider.yaml 第一个提供商
   （**文档序**，非字母序）的第一个模型（default_model → models 键序首）补位；
2. config.yaml 提供了有效 main_model 时被尊重，不被兜底覆盖；
3. needs_provider_setup：文件缺失（bootstrap 迁移后）或 providers 为空 → True；
4. run_provider_setup_wizard：选提供商 → 选模型 → 输 key 写 provider.yaml，
   可循环多家，所选模型置 models 首位；未写入即取消 → False；
5. agent._load_config：默认路径无 config.yaml 不再 FileNotFoundError（身份三元组
   由 provider.yaml 兜底）；全空才 ValueError；显式路径缺失仍报错；
6. server.main：无 provider.yaml 且非 TTY → 打印指引但继续启动到 run_server
   （不退出）；--config 指向缺失文件 → exit(1) 且不启动。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import tea_agent.config as config_mod
from tea_agent.provider_store import ProviderStore

# ── 隔离辅助 ────────────────────────────────────────────────


def _isolate_config(monkeypatch, yaml_path: str | None = None) -> None:
    """隔离 config 全局状态：路径解析返回 yaml_path（None=无配置文件）。"""
    monkeypatch.setattr(config_mod, "_last_config_path", None)
    monkeypatch.setattr(config_mod, "_active_config_path", None)
    monkeypatch.setattr(config_mod, "_config_cache", None)
    monkeypatch.setattr(config_mod, "resolve_config_path", lambda p=None: yaml_path)


def _use_provider_file(monkeypatch, tmp_path: Path, providers: dict) -> Path:
    """写 provider.yaml 并让单例单例指向它（env 驱动自动重建）。"""
    path = tmp_path / "provider.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "providers": providers},
                       allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEA_PROVIDER_FILE", str(path))
    return path


def _prov(models: list[str], default: str = "", key: str = "sk-t") -> dict:
    """构造 provider.yaml 条目。"""
    return {
        "api_url": "https://api.example.com/v1",
        "api_key": key,
        "default_model": default,
        "models": {m: {} for m in models},
        "source": "builtin",
    }


class _InputSeq:
    """按序供给输入，模拟用户回车/编号/key 输入。"""

    def __init__(self, answers: list[str]):
        self._answers = list(answers)

    def __call__(self, _prompt: str) -> str:
        if not self._answers:
            raise AssertionError("输入序列耗尽：向导索取了未预期的输入")
        return self._answers.pop(0)


# ── 1. load_config 首个提供商首个模型兜底 ──────────────────


def test_load_config_falls_back_to_first_provider_document_order(monkeypatch, tmp_path):
    """兜底取**文档序**第一个提供商（Zeta 在前；字母序 Alpha 在前——必须钉文档序）。"""
    _isolate_config(monkeypatch, yaml_path=None)
    _use_provider_file(monkeypatch, tmp_path, {
        "Zeta": _prov(["zm1", "zm2"], default="zm2", key="sk-zeta"),
        "Alpha": _prov(["am1"], default="am1", key="sk-alpha"),
    })

    cfg = config_mod.load_config()

    m = cfg.main_model
    assert cfg.main_model.is_configured
    assert m.is_reference
    assert m.provider == "Zeta", "必须是文档序第一个（写入序），不是字母序第一个"
    assert m.ref_model == "zm2"
    assert m.model_name == "zm2"
    assert m.api_key == "sk-zeta"
    assert m.api_url == "https://api.example.com/v1"


def test_first_model_rule_falls_back_to_first_model_key(monkeypatch, tmp_path):
    """无 default_model → models 键序第一个。"""
    _isolate_config(monkeypatch, yaml_path=None)
    _use_provider_file(monkeypatch, tmp_path, {
        "P": _prov(["first-model", "second-model"], default=""),
    })

    cfg = config_mod.load_config()

    assert cfg.main_model.is_configured
    assert cfg.main_model.ref_model == "first-model"


def test_config_main_model_respected_not_overridden(monkeypatch, tmp_path):
    """config.yaml 提供了有效 main_model → 尊重原值，兜底不覆盖。"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "main_model": {
                "api_url": "https://from-config/v1",
                "api_key": "sk-from-config",
                "model_name": "config-model",
            },
        }, allow_unicode=True),
        encoding="utf-8",
    )
    _isolate_config(monkeypatch, yaml_path=str(cfg_file))
    _use_provider_file(monkeypatch, tmp_path, {
        "P": _prov(["pm"], default="pm", key="sk-provider"),
    })

    cfg = config_mod.load_config()

    assert cfg.main_model.model_name == "config-model"
    assert cfg.main_model.api_key == "sk-from-config"


def test_empty_main_block_falls_back(monkeypatch, tmp_path):
    """config.yaml 的 main_model 块存在但身份字段全空串 → 视为未配置，兜底接管。"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "main_model": {"api_url": "", "api_key": "", "model_name": ""},
            "keep_turns": 7,
        }, allow_unicode=True),
        encoding="utf-8",
    )
    _isolate_config(monkeypatch, yaml_path=str(cfg_file))
    _use_provider_file(monkeypatch, tmp_path, {
        "P": _prov(["pm"], default="pm", key="sk-provider"),
    })

    cfg = config_mod.load_config()

    assert cfg.main_model.is_configured
    assert cfg.main_model.model_name == "pm"
    assert cfg.keep_turns == 7, "非身份配置段仍从 config.yaml 读取"


def test_provider_empty_main_not_configured(monkeypatch, tmp_path):
    """provider.yaml 无提供商 → 兜底无源，main_model 保持未配置。"""
    _isolate_config(monkeypatch, yaml_path=None)
    _use_provider_file(monkeypatch, tmp_path, {})

    cfg = config_mod.load_config()

    assert not cfg.main_model.is_configured


def test_paths_resolved_without_config_file(monkeypatch, tmp_path):
    """无 config.yaml 时 paths 必须仍被解析（否则 data_dir_abs 为空串）。"""
    _isolate_config(monkeypatch, yaml_path=None)
    _use_provider_file(monkeypatch, tmp_path, {"P": _prov(["pm"], default="pm")})

    cfg = config_mod.load_config()

    assert cfg.paths.data_dir_abs, "paths 未 resolve：data_dir_abs 为空"
    assert cfg.paths.data_dir_abs.endswith(".tea_agent")


# ── 2. needs_provider_setup 判定 ───────────────────────────


def test_needs_setup_true_when_file_missing_and_no_migration_source(tmp_path):
    """文件缺失 + 无任何 config*.yaml 迁移源 → bootstrap 空 providers → 需要引导。"""
    store = ProviderStore(tmp_path / "provider.yaml", agent_dir=tmp_path / "empty")
    (tmp_path / "empty").mkdir()

    assert ProviderStore is not None  # 类可用
    from tea_agent.setup_wizard import needs_provider_setup

    assert needs_provider_setup(store=store) is True


def test_needs_setup_false_when_providers_exist(monkeypatch, tmp_path):
    """已有 providers → 直接启动，不引导。"""
    _use_provider_file(monkeypatch, tmp_path, {"P": _prov(["pm"], default="pm")})
    from tea_agent.setup_wizard import needs_provider_setup

    assert needs_provider_setup() is False


def test_needs_setup_true_when_providers_empty(tmp_path):
    """文件存在但 providers 为空（被清空）→ 需要引导。"""
    path = tmp_path / "provider.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "providers": {}}), encoding="utf-8")
    store = ProviderStore(path, agent_dir=tmp_path)
    from tea_agent.setup_wizard import needs_provider_setup

    assert needs_provider_setup(store=store) is True


# ── 3. run_provider_setup_wizard 交互写入 ──────────────────


def test_wizard_single_provider_selected_model_first(tmp_path):
    """选非首个模型：default_model 与 models 首键都必须是所选（置首语义）。"""
    from tea_agent.setup_wizard import needs_provider_setup, run_provider_setup_wizard

    store = ProviderStore(tmp_path / "provider.yaml", agent_dir=tmp_path)
    # 1=DeepSeek → 模型编号 2（deepseek-reasoner）→ key → 不再添加
    ok = run_provider_setup_wizard(
        input_fn=_InputSeq(["1", "2", "sk-wiz-abc123", "n"]),
        store=store,
    )

    assert ok is True
    p = store.get_provider("DeepSeek")
    assert p is not None
    assert p["default_model"] == "deepseek-reasoner"
    assert p["api_key"] == "sk-wiz-abc123"
    assert next(iter(p["models"])) == "deepseek-reasoner", "所选模型必须置 models 首位"
    assert needs_provider_setup(store=store) is False, "引导完成后不再触发引导"


def test_wizard_multi_provider_document_order(tmp_path):
    """多家循环：先写入者成为文档序第一个 = 启动默认主模型的取用对象。"""
    from tea_agent.setup_wizard import run_provider_setup_wizard
    from tea_agent.config import _first_provider_ref

    path = tmp_path / "provider.yaml"
    monkey_iso = None  # noqa: F841 — 单测内直接用 store/env 对齐
    store = ProviderStore(path, agent_dir=tmp_path)
    import os

    old = os.environ.get("TEA_PROVIDER_FILE")
    os.environ["TEA_PROVIDER_FILE"] = str(path)
    try:
        ok = run_provider_setup_wizard(
            # DeepSeek 默认模型 → key → 继续 → OpenAI 默认模型 → key → 结束
            input_fn=_InputSeq(["1", "", "sk-a1", "y", "2", "", "sk-b2", "n"]),
            store=store,
        )
        assert ok is True
        provs = store.providers()
        assert set(provs) == {"DeepSeek", "OpenAI"}

        ref = _first_provider_ref()
        assert ref is not None
        assert ref["provider"] == "DeepSeek", "文档序第一 = 先写入的那家"
        assert ref["model"] == "deepseek-chat"
    finally:
        if old is None:
            os.environ.pop("TEA_PROVIDER_FILE", None)
        else:
            os.environ["TEA_PROVIDER_FILE"] = old


def test_wizard_cancel_writes_nothing(tmp_path):
    """第一问就 q → 取消，不写入任何提供商，返回 False。"""
    from tea_agent.setup_wizard import run_provider_setup_wizard

    store = ProviderStore(tmp_path / "provider.yaml", agent_dir=tmp_path)

    ok = run_provider_setup_wizard(input_fn=_InputSeq(["q"]), store=store)

    assert ok is False
    assert store.providers() == {}


# ── 4. agent._load_config 放宽 ─────────────────────────────


def _bare_agent():
    """跳过重构造，仅取实例调 _load_config。"""
    from tea_agent.agent import Agent

    agent = Agent.__new__(Agent)
    agent._config_fname = None
    return agent


def test_agent_load_config_no_config_file(monkeypatch, tmp_path):
    """默认路径无 config.yaml → 不再 FileNotFoundError，provider.yaml 兜底成功。"""
    import tea_agent.agent as agent_mod

    _isolate_config(monkeypatch, yaml_path=None)
    monkeypatch.setattr(agent_mod, "resolve_config_path", lambda p=None: None)
    _use_provider_file(monkeypatch, tmp_path, {
        "P": _prov(["pm1"], default="pm1", key="sk-agent"),
    })

    agent = _bare_agent()
    cfg = agent._load_config(None)

    assert cfg.main_model.is_configured
    assert cfg.main_model.model_name == "pm1"


def test_agent_load_config_all_empty_raises_value_error(monkeypatch, tmp_path):
    """config 与 provider 全空 → 仍 ValueError，文案指向向导/配置页。"""
    import tea_agent.agent as agent_mod

    _isolate_config(monkeypatch, yaml_path=None)
    monkeypatch.setattr(agent_mod, "resolve_config_path", lambda p=None: None)
    _use_provider_file(monkeypatch, tmp_path, {})

    agent = _bare_agent()
    with pytest.raises(ValueError, match="setup_wizard"):
        agent._load_config(None)


def test_agent_load_config_explicit_missing_file_still_raises():
    """显式指定的配置文件不存在 → 仍 FileNotFoundError（意图落空必须报错）。"""
    agent = _bare_agent()

    with pytest.raises(FileNotFoundError):
        agent._load_config("/nonexistent/config.yaml")


# ── 5. server.main 启动判定 ────────────────────────────────


def _fake_cfg(configured: bool = True):
    return SimpleNamespace(main_model=SimpleNamespace(is_configured=configured))


def _run_server_main(monkeypatch, argv_extra: list[str], *, needs: bool):
    """跑 server.main：patch 掉 run_server / 判定 / load_config，返回 (run_calls, exited)。"""
    import tea_agent.server.server as server_mod
    import tea_agent.setup_wizard as wizard_mod

    calls: list[dict] = []

    def _fake_run_server(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(server_mod, "run_server", _fake_run_server)
    monkeypatch.setattr(wizard_mod, "needs_provider_setup",
                        lambda store=None: needs)
    monkeypatch.setattr(config_mod, "load_config",
                        lambda p=None, **kw: _fake_cfg(configured=True))
    monkeypatch.setattr(sys, "argv", ["tea_agent", *argv_extra])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # isatty()=False

    exited = None
    server_mod.main()
    return calls, exited


def test_server_main_existing_provider_starts_directly(monkeypatch):
    """provider.yaml 已有配置 → 直接启动到 run_server，不进向导。"""
    calls, _ = _run_server_main(monkeypatch, [], needs=False)

    assert len(calls) == 1


def test_server_main_missing_provider_nontty_starts_with_warning(monkeypatch):
    """核心契约：无 provider.yaml 且非 TTY → 打印指引，但仍启动（不退出）。"""
    calls, _ = _run_server_main(monkeypatch, [], needs=True)

    assert len(calls) == 1, "非交互环境不得因缺 provider.yaml 而拒绝启动"


def test_server_main_explicit_missing_config_exits(monkeypatch):
    """--config 指向不存在文件 → exit(1)，不启动 run_server。"""
    with pytest.raises(SystemExit) as exc:
        _run_server_main(monkeypatch, ["--config", "/no/such/config.yaml"], needs=False)

    assert exc.value.code == 1
