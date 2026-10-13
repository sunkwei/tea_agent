"""渠道适配器共用的 `/model` 命令实现。

数据源与 Web「模型」面板一致：`provider.yaml`
（读 `GET /api/model-config`，切 `POST /api/model-config/switch`）。
微信 / Telegram 两个适配器共用本模块，避免文案与语义分叉。

角色（`--role`）对应 provider.yaml 的 roles 键：
  main   主力模型（对话本身，默认）
  cheap  轻量模型（子任务 / 后台线程等 lite 调用）
  vision 视觉模型（图片理解调用）

⚠️ 切换为**全局**生效（Web / 渠道 / API 共用同一份配置）。
"""

from collections.abc import Callable

ApiGet = Callable[..., "dict | None"]
ApiPost = Callable[..., "dict | None"]

_ROLE_LABEL = {"main": "主力", "cheap": "轻量", "vision": "视觉"}
VALID_ROLES = tuple(_ROLE_LABEL)

# 非 main 角色服务端不走「会话续接热切」（role==main 才 request_model_switch），
# 落盘后由下一次 create_session 自然读取 → 生效时机文案须与之匹配，勿写成「已立即生效」。
_ROLE_EFFECT_TIP = {
    "cheap": "💾 已保存 — 子任务/后台（lite）调用下次即使用该模型",
    "vision": "💾 已保存 — 图片理解调用下次即使用该模型",
}

_SWITCH_MODE_TIP = {
    "applied": "✅ 已立即生效（当前话题无缝续接）",
    "pending_next_turn": "⏳ 正在回复中，本轮结束后自动生效",
    "next_message": "💾 已保存，下一条消息生效",
    "config_only": "💾 配置已保存",
}


def _model_ids(p: dict) -> list[str]:
    return [m.get("id", "") for m in (p.get("models") or []) if m.get("id")]


def split_role(tokens: list[str]) -> tuple[list[str], str, str]:
    """从参数串里剥离角色标志，返回 (剩余 token, 角色, 错误信息)。

    支持 `--role cheap` / `-r cheap`，以及简写 `--cheap` / `--main` / `--vision`。
    标志可出现在任意位置（`/model mimo pro --role cheap`）。
    错误信息非空时调用方应直接回传，不再执行切换。
    """
    rest: list[str] = []
    role = "main"
    i = 0
    while i < len(tokens):
        t = tokens[i]
        low = t.lower()
        if low in ("--role", "-r"):
            if i + 1 >= len(tokens):
                return rest, role, f"❌ `{t}` 后面需要角色名：{' | '.join(VALID_ROLES)}"
            role = tokens[i + 1].strip().lower()
            i += 2
            continue
        if low.startswith("--") and low[2:] in _ROLE_LABEL:
            role = low[2:]
            i += 1
            continue
        rest.append(t)
        i += 1

    if role not in _ROLE_LABEL:
        return rest, role, f"❌ 未知角色 `{role}`\n可用：{' | '.join(VALID_ROLES)}"
    return rest, role, ""


def _role_marks(active: dict) -> dict:
    """provider 名 → 该提供商承担的角色标记（同名可多角色，按 main>cheap>vision 排）。"""
    marks: dict = {}
    for role in VALID_ROLES:
        name = (active.get(role) or {}).get("provider", "")
        if name:
            marks.setdefault(name, []).append(role)
    return marks


def build_model_reply(args: str, api_get: ApiGet, api_post: ApiPost, api_base: str = "") -> str:
    """组装 `/model` 命令的回复文本。

    Args:
        args: 命令后的参数串。空=查看当前；`list`/`ls`=列出提供商与模型；
            `<提供商>`=切到该提供商默认模型；`<提供商> <模型>`=指定切换；
            `--role main|cheap|vision`（默认 main）指定切换哪个角色的模型。
        api_get: 适配器侧 GET 封装，签名 `(path, timeout=...) -> dict | None`。
        api_post: 适配器侧 POST 封装，签名 `(path, json_data, timeout=...) -> dict | None`。
        api_base: 仅用于失败提示中展示当前 API 地址。

    Returns:
        str: 可直接发送的回复文本（Markdown 标记由渠道自行渲染）。
    """
    tokens, role, err = split_role(args.split())
    if err:
        return f"{err}\n\n示例：`/model mimo pro --role cheap`"

    panel = api_get("/api/model-config", timeout=15)
    if not panel:
        return f"❌ 读取模型配置失败\n请确认 tea_agent server 正在运行。\n当前 API: {api_base}"

    providers = panel.get("providers") or []
    active = panel.get("active") or {}
    label = _ROLE_LABEL[role]
    marks = _role_marks(active)

    def _mark(name: str) -> str:
        got = marks.get(name) or []
        return "".join({"main": " ✅", "cheap": " ⚡", "vision": " 👁"}[r] for r in got)

    if not tokens:
        lines = ["🎛 *当前模型*"]
        for r in VALID_ROLES:
            cur = active.get(r) or {}
            if cur or r == "main":
                lines.append(f"• {_ROLE_LABEL[r]}: `{cur.get('provider', '-')}` / `{cur.get('model', '-')}`")
        lines += [
            "",
            "*用法*",
            "`/model list` — 列出提供商与模型",
            "`/model <提供商> <模型>` — 切换主力模型",
            "`/model <提供商>` — 切到该提供商默认模型",
            f"`/model <提供商> <模型> --role cheap` — 切换轻量模型（{' | '.join(VALID_ROLES)}）",
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
            out.append(f"*{name}*{_mark(name)}")
            ids = _model_ids(p)
            out.append("  " + (", ".join(ids) if ids else "（无模型）"))
            if p.get("default_model"):
                out.append(f"  默认: {p['default_model']}")
        out += ["", "`✅`主力 `⚡`轻量 `👁`视觉", "切换：`/model <提供商> <模型> [--role cheap]`"]
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
                + f"\n\n切换：`/model {name} <模型>"
                + ("" if role == "main" else f" --role {role}")
                + "`"
            )

    res = api_post(
        "/api/model-config/switch",
        {"provider": name, "model": model, "role": role},
        timeout=40,
    )
    if not res:
        return (
            f"❌ 切换失败（服务端未返回成功）\n"
            f"请求: {name} / {model}（{label}）\n"
            "请确认模型已登记在 provider.yaml，或查看服务端日志。"
        )
    if not res.get("ok"):
        return f"❌ 切换失败: {res.get('error') or res}"

    mode = (res.get("switch") or {}).get("mode", "")
    tip = _ROLE_EFFECT_TIP.get(role) or _SWITCH_MODE_TIP.get(mode, "✅ 已切换")
    return f"🎛 模型切换\n• {label}: `{name}` / `{model}`\n{tip}"
