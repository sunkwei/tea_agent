"""测试助手：写入隔离的 provider.yaml（唯一事实源）。

provider.yaml 是身份三元组 + 运行时参数的唯一事实源，测试需要构造它的最小形态。
本模块名不以 ``test_`` 开头，pytest 不会收集。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def write_provider_yaml(
    path: str | Path,
    *,
    provider: str = "testprov",
    model_name: str = "test-model",
    api_url: str = "https://api.test.com/v1",
    api_key: str = "sk-test",
    db_path: str = ":memory:",
    toolkit_dir: str = "./tools",
    kb_dir: str = "./kb",
    cheap: bool = False,
    settings: dict[str, Any] | None = None,
    models: dict[str, dict] | None = None,
) -> Path:
    """写一份最小可用的 provider.yaml。

    Args:
        path: 目标文件路径
        provider: 供应商名
        model_name: main 角色绑定的模型 id
        api_url: 供应商端点
        api_key: 供应商密钥
        db_path: settings.paths.db_path
        toolkit_dir: settings.paths.toolkit_dir
        kb_dir: settings.paths.kb_dir
        cheap: 是否同时绑定 cheap 角色（复用 main 的模型）
        settings: 追加/覆盖 settings 段字段
        models: 追加/覆盖供应商 models 条目

    Returns:
        写入的路径
    """
    import yaml

    entry = {
        "max_context_tokens": 131072,
        "max_output_tokens": 8192,
        "supports_vision": False,
        "supports_reasoning": False,
        "supports_tools": True,
    }
    model_entries = {model_name: dict(entry)}
    if models:
        for mid, cfg in models.items():
            model_entries[mid] = {**entry, **(cfg or {})}

    st: dict[str, Any] = {
        "paths": {
            "toolkit_dir": toolkit_dir,
            "kb_dir": kb_dir,
            "db_path": db_path,
        },
        "max_history": 10,
        "max_iterations": 50,
        "keep_turns": 5,
        "max_tool_output": 131072,
        "max_assistant_content": 131072,
        "memory_extraction_threshold": 2,
    }
    if settings:
        st.update(settings)

    roles: dict[str, dict] = {"main": {"provider": provider, "model": model_name}}
    if cheap:
        roles["cheap"] = {"provider": provider, "model": model_name}

    data = {
        "version": 1,
        "providers": {
            provider: {
                "api_url": api_url,
                "api_key": api_key,
                "default_model": model_name,
                "models": model_entries,
            }
        },
        "roles": roles,
        "settings": st,
    }

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p
