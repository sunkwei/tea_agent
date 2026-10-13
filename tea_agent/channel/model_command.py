"""渠道适配器共用的 `/model` 命令实现。

数据源与 Web「模型」面板一致：`provider.yaml`
（读 `GET /api/model-config`，切 `POST /api/model-config/switch`）。
微信 / Telegram 两个适配器共用本模块，避免文案与语义分叉。

⚠️ 切换为**全局**生效（Web / 渠道 / API 共用同一份配置）。
"""

from collections.abc import Callable

ApiGet = Callable[..., "dict | None"]
ApiPost = Callable[..., "dict | None"]

_SWITCH_MODE_TIP = {
    "applied": "✅ 已立即生效（当前话题无缝续接）",
    "pending_next_turn": "⏳ 正在回复中，本轮结束后自动生效",
    "next_message": "💾 已保存，下一条消息生效",
    "config_only": "💾 配置已保存",
}


def _model_ids(p: dict) -> list:
    return [m.get("id", "") for m in (p.get("models") or []) if m.get("id")]


def build_model_reply(args: str, api_get: ApiGet, api_post: ApiPost, api_base: str = "") -> str:
    """组装 `/model` 命令的回复文本。

    Args:
        args: 命令后的参数串。空=查看当前；`list`/`ls`=列出提供商与模型；
            `<提供商>`=切到该提供商默认模型；`<提供商> <模型>`=指定切换。
        api_get: 适配器侧 GET 封装，签名 `(path, timeout=...) -> dict | None`。
        api_post: 适配器侧 POST 封装，签名 `(path, json_data, timeout=...) -> dict | None`。
        api_base: 仅用于失败提示中展示当前 API 地址。

    Returns:
        str: 可直接发送的回复文本（Markdown 标记由渠道自行渲染）。
    """
    panel = api_get("/api/model-config", timeout=15)
    if not panel:
        return f"❌ 读取模型配置失败\n请确认 tea_agent server 正在运行。\n当前 API: {api_base}"

    providers = panel.get("providers") or []
    active = panel.get("active") or {}
    main = active.get("main") or {}
    cur_p, cur_m = main.get("provider", ""), main.get("model", "")

    tokens = args.split()
    if not tokens:
        cheap = active.get("cheap") or {}
        lines = ["🎛 *当前模型*", f"• 主力: `{cur_p}` / `{cur_m}`"]
        if cheap:
            lines.append(f"• 轻量: `{cheap.get('provider', '')}` / `{cheap.get('model', '')}`")
        lines += [
            "",
            "*用法*",
            "`/model list` — 列出提供商与模型",
            "`/model <提供商> <模型>` — 切换主力模型",
            "`/model <提供商>` — 切到该提供商默认模型",
            "",
            "⚠️ 切换为全局生效（含 Web 界面）",
        ]
        return "\n".join(lines)

    if tokens[0].lower() in ("list", "ls"):
        if not providers:
            return "❌ provider.yaml 中暂无提供商\n请先在 Web 界面「模型」面板添加。"
        out = [f"📚 *提供商*（{len(providers)}）"]
        for p in providers:
            name = p.get("name", "?") or "?"
            out.append("")
            out.append(f"*{name}*" + (" ✅" if name == cur_p else ""))
            ids = _model_ids(p)
            out.append("  " + (", ".join(ids) if ids else "（无模型）"))
            if p.get("default_model"):
                out.append(f"  默认: {p['default_model']}")
        out += ["", "切换：`/model <提供商> <模型>`"]
        return "\n".join(out)

    provider = tokens[0]
    model = tokens[1] if len(tokens) > 1 else ""
    hit = next((p for p in providers if (p.get("name") or "").lower() == provider.lower()), None)
    if hit is None:
        return f"❌ 未找到提供商 `{provider}`\n\n`/model list` 查看可用列表"

    name = hit.get("name") or provider
    if not model:
        model = hit.get("default_model") or ""
        if not model:
            ids = _model_ids(hit)
            return (
                f"ℹ️ `{name}` 未设默认模型，可选：\n  "
                + (", ".join(ids) if ids else "（无模型）")
                + f"\n\n切换：`/model {name} <模型>`"
            )

    res = api_post(
        "/api/model-config/switch",
        {"provider": name, "model": model, "role": "main"},
        timeout=40,
    )
    if not res:
        return (
            f"❌ 切换失败（服务端未返回成功）\n"
            f"请求: {name} / {model}\n"
            "请确认模型已登记在 provider.yaml，或查看服务端日志。"
        )
    if not res.get("ok"):
        return f"❌ 切换失败: {res.get('error') or res}"

    mode = (res.get("switch") or {}).get("mode", "")
    tip = _SWITCH_MODE_TIP.get(mode, "✅ 已切换")
    return f"🎛 模型切换\n• 主力: `{name}` / `{model}`\n{tip}"
