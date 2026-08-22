"""
配置向导 (setup wizard) — 首次运行引导用户完成基础配置。

当 $HOME/.tea_agent/config.yaml 不存在时，各入口（server / cli / gui）可调用
``run_setup_wizard()`` 启动交互式向导，引导用户输入主模型的 api_url /
api_key / model_name 等，生成 config.yaml 后继续启动。

特性：
- 复用 providers.py 的 Provider 注册表（50+ 模型服务商）
- 常用 Provider 快捷选择 + 自定义 URL 兜底
- 可选配置 cheap_model（摘要/记忆）与 vision_model（图片）
- 纯标准库，无第三方依赖

独立运行::

    python -m tea_agent.setup_wizard [--config PATH]
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from tea_agent.config import AgentConfig, save_config
from tea_agent.providers import get_provider

__all__ = [
    "run_setup_wizard",
    "QUICK_PROVIDERS",
    "WizardCancelled",
]

# 向导中展示的常用 Provider（保持精简；完整列表见 providers.PROVIDERS）
QUICK_PROVIDERS = [
    "DeepSeek", "OpenAI", "Gemini", "Anthropic",
    "Moonshot", "Alibaba", "SiliconFlow", "Ollama", "OpenRouter",
]

BANNER = r"""
  ┌───────────────────────────────────────────────┐
  │   🍵 Tea Agent 首次配置向导                    │
  │   只需几步即可完成基础配置，随时可 Ctrl+C 取消  │
  └───────────────────────────────────────────────┘
"""


class WizardCancelled(Exception):
    """用户取消向导（Ctrl+C 或输入 q/quit）。"""


def _ask(prompt: str, default: str = "", required: bool = False,
         input_fn: Callable[[str], str] = input,
         validate: Callable[[str], str | None] | None = None) -> str:
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
        except (EOFError, KeyboardInterrupt):
            raise WizardCancelled()
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


def _collect_answers(input_fn: Callable[[str], str]) -> dict:
    """交互式收集用户输入，返回答案字典。"""
    print("第 1 步：选择主模型服务商\n")

    options = QUICK_PROVIDERS + ["custom"]
    for i, name in enumerate(options, 1):
        if name == "custom":
            print(f"  {i:>2}. ✍️  自定义（手动输入 URL / 模型名）")
        else:
            p = get_provider(name)
            print(f"  {i:>2}. {name:<12} {p['description']}")
    print()

    # 选择服务商（编号）
    while True:
        raw = _ask(f"请选择 [1-{len(options)}]", default="1", input_fn=input_fn)
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                break
        except ValueError:
            pass
        print("  ⚠ 请输入有效的选项编号")
    provider_name = options[idx - 1]

    if provider_name == "custom":
        api_url = _ask(
            "模型 API URL",
            required=True,
            input_fn=input_fn,
            validate=lambda u: (
                None if u.startswith(("http://", "https://"))
                else "URL 需以 http:// 或 https:// 开头"
            ),
        )
        model_name = _ask("模型名称", required=True, input_fn=input_fn)
        supports_vision = False
        default_api_url = ""
    else:
        provider = get_provider(provider_name)
        api_url = provider["api_url"]
        model_name = _ask("模型名称", default=provider["default_model"],
                          input_fn=input_fn)
        supports_vision = provider.get("supports_vision", False)
        default_api_url = api_url

    api_key = _ask("API Key", required=True, input_fn=input_fn)

    # ── 便宜模型（可选，用于摘要/记忆等轻量任务） ──
    print("\n第 2 步：便宜模型（可选，用于摘要/记忆等轻量任务，省 token）")
    use_cheap = _ask("是否单独配置便宜模型？[y/N]", default="n", input_fn=input_fn)
    cheap: dict = {}
    if use_cheap.lower() in ("y", "yes", "是"):
        cp_name = _ask("便宜模型服务商（回车=与主模型相同）",
                       default="" if provider_name == "custom" else provider_name,
                       input_fn=input_fn)
        cp = get_provider(cp_name) if cp_name else (
            None if provider_name == "custom" else get_provider(provider_name)
        )
        if cp:
            cheap = {
                "api_url": cp["api_url"],
                "model_name": _ask("便宜模型名称", default=cp["default_model"],
                                   input_fn=input_fn),
            }
        else:
            cheap = {
                "api_url": _ask("便宜模型 API URL", required=True, input_fn=input_fn),
                "model_name": _ask("便宜模型名称", required=True, input_fn=input_fn),
            }
        cheap["api_key"] = _ask("便宜模型 API Key（回车复用主模型 Key）",
                                default=api_key, input_fn=input_fn)
        cheap["temperature"] = 0.3

    # ── 视觉模型（可选） ──
    print("\n第 3 步：视觉模型（可选，会话含图片时自动使用）")
    use_vision = _ask("是否配置视觉模型？[y/N]", default="n", input_fn=input_fn)
    vision: dict = {}
    if use_vision.lower() in ("y", "yes", "是"):
        vp_name = _ask("视觉模型服务商（回车=与主模型相同）",
                       default="" if provider_name == "custom" else provider_name,
                       input_fn=input_fn)
        vp = get_provider(vp_name) if vp_name else (
            None if provider_name == "custom" else get_provider(provider_name)
        )
        if vp:
            vision = {
                "api_url": vp["api_url"],
                "model_name": _ask("视觉模型名称", default=vp["default_model"],
                                   input_fn=input_fn),
            }
        else:
            vision = {
                "api_url": _ask("视觉模型 API URL", required=True, input_fn=input_fn),
                "model_name": _ask("视觉模型名称", required=True, input_fn=input_fn),
            }
        vision["api_key"] = _ask("视觉模型 API Key（回车复用主模型 Key）",
                                 default=api_key, input_fn=input_fn)

    return {
        "provider_name": provider_name,
        "api_url": api_url,
        "api_key": api_key,
        "model_name": model_name,
        "supports_vision": supports_vision,
        "cheap": cheap,
        "vision": vision,
    }


def _build_config(answers: dict) -> AgentConfig:
    """根据向导答案构建 AgentConfig 实例。"""
    cfg = AgentConfig()
    cfg.main_model.api_url = answers["api_url"]
    cfg.main_model.api_key = answers["api_key"]
    cfg.main_model.model_name = answers["model_name"]
    cfg.main_model.options["supports_vision"] = (
        "true" if answers.get("supports_vision") else "false"
    )
    cfg.main_model.options["supports_reasoning"] = "false"

    cheap = answers.get("cheap") or {}
    if cheap.get("api_url") and cheap.get("model_name"):
        cfg.cheap_model.api_url = cheap["api_url"]
        cfg.cheap_model.model_name = cheap["model_name"]
        cfg.cheap_model.api_key = cheap.get("api_key") or answers["api_key"]
        cfg.cheap_model.temperature = float(cheap.get("temperature", 0.3))

    vision = answers.get("vision") or {}
    if vision.get("api_url") and vision.get("model_name"):
        cfg.vision_model.api_url = vision["api_url"]
        cfg.vision_model.model_name = vision["model_name"]
        cfg.vision_model.api_key = vision.get("api_key") or answers["api_key"]
        cfg.vision_model.options["supports_vision"] = "true"

    return cfg


def run_setup_wizard(config_path: str | None = None,
                     input_fn: Callable[[str], str] | None = None) -> str | None:
    """运行首次配置向导。

    Args:
        config_path: 目标配置文件路径，默认 ~/.tea_agent/config.yaml
        input_fn: 输入函数（测试注入用）；None 时使用内置 input()

    Returns:
        成功保存的配置文件路径；用户取消返回 None
    """
    if input_fn is None:
        input_fn = input

    target = config_path or str(Path.home() / ".tea_agent" / "config.yaml")
    print(BANNER)

    try:
        answers = _collect_answers(input_fn)
    except WizardCancelled:
        print("\n✋ 向导已取消，未生成配置文件。")
        return None

    cfg = _build_config(answers)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    saved = save_config(cfg, target)

    print("\n✅ 配置已保存！")
    print(f"   配置文件: {saved}")
    print(f"   主模型:   {cfg.main_model.model_name} @ {cfg.main_model.api_url}")
    if cfg.cheap_model.is_configured:
        print(f"   便宜模型: {cfg.cheap_model.model_name}")
    if cfg.vision_model.is_configured:
        print(f"   视觉模型: {cfg.vision_model.model_name}")
    print("\n💡 提示：可随时编辑该文件修改配置，或删除后重新运行向导。")
    return saved


def main() -> None:
    """独立运行入口: python -m tea_agent.setup_wizard [--config PATH]"""
    import argparse

    parser = argparse.ArgumentParser(description="Tea Agent 配置向导")
    parser.add_argument("--config", type=str, default=None,
                        help="目标配置文件路径（默认 ~/.tea_agent/config.yaml）")
    args = parser.parse_args()
    saved = run_setup_wizard(args.config)
    sys.exit(0 if saved else 1)


if __name__ == "__main__":
    main()
