"""
配置向导 (setup wizard) — 首次运行引导用户完成基础配置。

**首启主路径（推荐）**：``run_provider_setup_wizard()`` —— 当 `~/.tea_agent/provider.yaml`
缺失或没有任何提供商时，各入口（server / ACP / 渠道）引导用户「选服务商 → 选模型 → 填 Key」，
结果写入 provider.yaml（密钥与模型能力、运行时参数的唯一事实源），
缺失时由 `load_config` 兜底 provider.yaml 首个提供商的第一个模型。

身份三元组、逐模型能力与运行时参数全部落在
``provider.yaml``（``roles`` / ``settings`` 段）。``run_setup_wizard()`` 保留为
兼容别名，直接委托 ``run_provider_setup_wizard()``。

特性：
- 复用 providers.py 的 Provider 注册表（50+ 模型服务商）
- 常用 Provider 快捷选择 + 自定义 URL 兜底
- provider 引导可循环配置多家服务商；可选配置 cheap_model 角色
- 纯标准库，无第三方依赖

独立运行::

    python -m tea_agent.setup_wizard --provider   # 写 provider.yaml（推荐）
    python -m tea_agent.setup_wizard              # 同上（兼容入口）
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from tea_agent.providers import get_provider

__all__ = [
    "run_setup_wizard",  # 兼容别名 → run_provider_setup_wizard
    "run_provider_setup_wizard",
    "needs_provider_setup",
    "QUICK_PROVIDERS",
    "WizardCancelled",
]

# 向导中展示的常用 Provider（保持精简；完整列表见 providers.PROVIDERS）
QUICK_PROVIDERS = [
    "DeepSeek",
    "OpenAI",
    "Gemini",
    "Anthropic",
    "Moonshot",
    "Alibaba",
    "SiliconFlow",
    "Ollama",
    "OpenRouter",
]

BANNER = r"""
  ┌───────────────────────────────────────────────┐
  │   🍵 Tea Agent 首次配置向导                    │
  │   只需几步即可完成基础配置，随时可 Ctrl+C 取消  │
  └───────────────────────────────────────────────┘
"""

PROVIDER_BANNER = r"""
  ┌───────────────────────────────────────────────┐
  │   🍵 Tea Agent 首启提供商配置（provider.yaml） │
  │   选服务商 → 选模型 → 输入 API Key（可多家）   │
  │   随时可 Ctrl+C 取消                          │
  └───────────────────────────────────────────────┘
"""


class WizardCancelled(Exception):  # noqa: N818
    """用户取消向导（Ctrl+C 或输入 q/quit）。"""


def _ask(
    prompt: str,
    default: str = "",
    required: bool = False,
    input_fn: Callable[[str], str] = input,
    validate: Callable[[str], str | None] | None = None,
) -> str:
    """带默认值 / 必填校验的提问，返回去空白后的用户输入。

    Args:
        prompt: 提示文本
        default: 默认值（用户回车时采用；空串表示无默认值）
        required: 是否必填（空输入会循环追问）
        input_fn: 输入函数（测试可注入）
        validate: 校验函数，返回错误信息字符串；通过则返回 None

    Returns:
        用户输入或默认值

    Raises:
        WizardCancelled: 用户 Ctrl+C / EOF 时
    """
    while True:
        suffix = f" [{default}]" if default else ""
        try:
            raw = input_fn(f"{prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise WizardCancelled() from exc
        if raw.lower() in ("q", "quit", "exit"):
            raise WizardCancelled()
        if not raw and default:
            return default
        if not raw and required:
            print("  ⚠ 此项必填，请重新输入（输入 q 可退出向导）")
            continue
        if validate:
            err = validate(raw)
            if err:
                print(f"  ⚠ {err}")
                continue
        return raw


def needs_provider_setup(store=None) -> bool:
    """是否需要首启提供商引导：provider.yaml 缺失（bootstrap 迁移后）providers 仍为空。

    判定语义：
      - 文件不存在 → store.load() 触发 bootstrap（仅迁移 custom_providers.yaml；
        无迁移源则创建空文件）
      - 迁移后 providers 非空 → 老用户已有真实配置 → 不需要引导，直接启动
      - providers 为空（全新安装 / 被清空）→ 需要引导

    Args:
        store: ProviderStore 注入（测试用）；None 时用全局单例

    Returns:
        True=需要引导；provider 基础设施异常时 False（不阻塞启动）
    """
    try:
        from tea_agent.provider_store import get_provider_store

        data = (store or get_provider_store()).load()
        return not (data.get("providers") or {})
    except Exception:
        return False


def _pick_model(provider_name: str, input_fn: Callable[[str], str]) -> str:
    """选择模型：内置目录编号列表（default_model 默认）；无目录时手输 id。"""
    from tea_agent.providers import model_ids

    p = get_provider(provider_name)
    ids = model_ids(p)
    if not ids:
        return _ask("模型名称", required=True, input_fn=input_fn)

    print("\n  可用模型：")
    default_id = str(p.get("default_model") or "")
    default_idx = 1
    for i, mid in enumerate(ids, 1):
        if mid == default_id:
            default_idx = i
        mark = " (默认)" if mid == default_id else ""
        print(f"  {i:>2}. {mid}{mark}")
    while True:
        raw = _ask(
            f"请选择模型 [1-{len(ids)}，或直接输入模型 id]",
            default=str(default_idx),
            input_fn=input_fn,
        )
        if raw.isdigit() and 1 <= int(raw) <= len(ids):
            return ids[int(raw) - 1]
        if raw and not raw.isdigit():
            return raw  # 直接输入目录外的模型 id
        print("  ⚠ 请输入有效的选项编号")


def run_provider_setup_wizard(input_fn: Callable[[str], str] | None = None, store=None) -> bool:
    """首启提供商引导：选供应商 → 选模型 → 输入 api_key，可循环添加多个。

    结果写入 provider.yaml（身份三元组唯一事实源 = provider.yaml）。
    首个完成的条目即启动默认主模型：文档序第一个提供商，default_model = 所选模型，
    且所选模型置于 models 首位（两条「第一个」口径都指向本次选择）。

    Args:
        input_fn: 输入函数（测试注入用）；None 用内置 input()
        store: ProviderStore 注入（测试用）；None 用全局单例

    Returns:
        True=至少完成一个提供商；False=未写入任何条目即取消
    """
    if input_fn is None:
        input_fn = input
    from tea_agent.provider_store import get_provider_store
    from tea_agent.providers import model_ids

    st = store or get_provider_store()
    print(PROVIDER_BANNER)
    written = 0
    try:
        while True:
            # ── 1. 选择供应商 ──
            print("\n第 1 步：选择服务商\n")
            options = QUICK_PROVIDERS + ["custom"]
            for i, name in enumerate(options, 1):
                if name == "custom":
                    print(f"  {i:>2}. ✍️  自定义（手动输入 URL / 模型名）")
                else:
                    info = get_provider(name)
                    print(f"  {i:>2}. {name:<12} {info.get('description', '')}")
            print()
            while True:
                raw = _ask(f"请选择 [1-{len(options)}]", default="1", input_fn=input_fn)
                try:
                    idx = int(raw)
                    if 1 <= idx <= len(options):
                        break
                except ValueError:
                    pass
                print("  ⚠ 请输入有效的选项编号")
            name = options[idx - 1]

            # ── 2. 模型与端点 ──
            if name == "custom":
                api_url = _ask(
                    "模型 API URL",
                    required=True,
                    input_fn=input_fn,
                    validate=lambda u: None if u.startswith(("http://", "https://")) else "URL 需以 http:// 或 https:// 开头",
                )
                model = _ask("模型名称", required=True, input_fn=input_fn)
                description, source, models = "custom", "custom", [model]
            else:
                info = get_provider(name)
                api_url = str(info.get("api_url") or "")
                model = _pick_model(name, input_fn)
                description = str(info.get("description") or "")
                source = "builtin"
                # 所选模型置首 →「第一个提供商的第一个模型」= 本次所选
                ids = model_ids(info)
                models = [model] + [m for m in ids if m != model]

            # ── 3. API Key ──
            api_key = _ask("API Key", required=True, input_fn=input_fn)

            st.upsert_provider(
                name,
                {
                    "api_url": api_url,
                    "api_key": api_key,
                    "default_model": model,
                    "description": description,
                    "source": source,
                    "models": models,
                },
            )
            written += 1
            print(f"  ✓ 已写入 provider.yaml: {name} / {model}")

            more = _ask("\n继续添加下一个提供商？[y/N]", default="n", input_fn=input_fn)
            if more.lower() not in ("y", "yes", "是"):
                break
    except WizardCancelled:
        pass

    if not written:
        print("\n✋ 向导已取消，未写入任何提供商。")
        return False
    print(f"\n✅ 已配置 {written} 个提供商 → {st.file_path}")
    print("   启动将默认使用第一个提供商的第一个模型。")
    return True


def run_setup_wizard(input_fn: Callable[[str], str] | None = None) -> str | None:
    """兼容别名：委托 ``run_provider_setup_wizard()``（写 provider.yaml）。

    Args:
        input_fn: 输入函数（测试注入用）

    Returns:
        成功时返回 provider.yaml 路径；用户取消返回 None
    """
    from tea_agent.provider_store import get_provider_store

    if not run_provider_setup_wizard(input_fn=input_fn):
        return None
    return str(get_provider_store().file_path)


def main() -> None:
    """独立运行入口: python -m tea_agent.setup_wizard [--provider]"""
    import argparse

    parser = argparse.ArgumentParser(description="Tea Agent 配置向导")
    parser.add_argument("--provider", action="store_true", help="提供商引导（写 provider.yaml，唯一事实源）")
    parser.parse_args()
    saved = run_setup_wizard()
    sys.exit(0 if saved else 1)


if __name__ == "__main__":
    main()
