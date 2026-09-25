"""Web 配置与模型切换：读取/更新配置、配置列表与创建、模型信息、模型热切换、配置上传、根页面。

由 route_handlers.py 拆分而来（逐字搬运，函数体未改写）。
"""

import contextlib
import os
from pathlib import Path

from starlette.responses import HTMLResponse, JSONResponse, Response

from ._compat import (
    get_server,
    logger,
)


async def handle_web_config(request):
    """GET /api/config"""
    try:
        return JSONResponse(get_server().get_config_info())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


async def handle_web_update_config(request):
    """PUT /api/config — update runtime config fields."""
    body = await request.json()
    if not body:
        return JSONResponse({"ok": False, "errors": ["empty body"]}, status_code=400)
    result = get_server().update_config(body)
    status = 200 if result["ok"] else 400
    return JSONResponse(result, status_code=status)


async def handle_web_list_configs(request):
    """GET /api/configs"""
    server = get_server()
    # ⚠️ 必须先获取 active_config_path，再调用 list_config_files！
    # list_config_files 内部遍历所有 yaml 文件并调用 load_config()，
    # 这会污染全局 _last_config_path，导致后续 get_agent() 获取错误的配置路径。
    active_config_path = ""
    active_config_filename = ""
    try:
        agent = server.get_agent()
        if agent and agent._config_path:
            active_config_path = agent._config_path
            active_config_filename = Path(active_config_path).name
    except Exception:
        pass
    result = server.list_config_files(check_valid=True)
    configs = result["configs"]
    any_valid = result["any_valid"]
    return JSONResponse({
        "configs": configs,
        "count": len(configs),
        "any_valid": any_valid,
        "active_config_path": active_config_path,
        "active_config_filename": active_config_filename,
    })


async def handle_web_create_config(request):
    """POST /api/config/create"""
    body = await request.json()
    filename = (body.get("filename") or "").strip()
    main_model_name = (body.get("main_model_name") or "").strip()
    main_api_url = (body.get("main_api_url") or "").strip()
    main_api_key = (body.get("main_api_key") or "").strip()
    cheap_model_name = (body.get("cheap_model_name") or "").strip()
    cheap_api_url = (body.get("cheap_api_url") or "").strip()
    cheap_api_key = (body.get("cheap_api_key") or "").strip()

    errors = []
    if not filename:
        errors.append("filename required")
    if not main_model_name:
        errors.append("main_model_name required")
    if not main_api_url:
        errors.append("main_api_url required")
    if not main_api_key:
        errors.append("main_api_key required")
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    server = get_server()
    try:
        fpath = server.create_config_file(
            filename=filename,
            main_model_name=main_model_name,
            main_api_url=main_api_url,
            main_api_key=main_api_key,
            cheap_model_name=cheap_model_name,
            cheap_api_url=cheap_api_url,
            cheap_api_key=cheap_api_key,
        )
        server.switch_config(fpath)
        return JSONResponse({"ok": True, "config_path": fpath, "filename": filename})
    except Exception as e:
        logger.exception("create_config_file failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_web_model_info(request):
    """GET /api/model"""
    try:
        return JSONResponse(get_server().get_config_info())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


def _writeback_provider_yaml(server, wb: dict, agent) -> None:
    """把 POST /api/model 提交的模型参数写回 provider.yaml 对应条目。

    provider.yaml 是模型属性（窗口/输出上限/能力标记/采样默认）唯一事实源；
    配置对话框只提交参数（url/key/模型名只读），故此处仅回写 wb 中非 None
    （=本次显式提交）的字段。provider 解析：config 的 provider 引用 →
    空则按 api_url 反查 provider.yaml。任何失败静默降级（fail-open），
    不阻断热切主流程。
    """
    try:
        from tea_agent.provider_store import get_provider_store
        ps = get_provider_store()
        if agent is not None:
            mc, cm = agent._cfg.main_model, agent._cfg.cheap_model
        else:
            from tea_agent.config import load_config
            c = load_config(server.get_config_path() or None)
            mc, cm = c.main_model, c.cheap_model

        def _pname(m) -> str:
            p = (getattr(m, "provider", "") or "").strip()
            if p:
                return p
            want = (m.api_url or "").strip().rstrip("/").lower()
            if not want:
                return ""
            for pi in ps.list_providers():
                if (pi.get("api_url") or "").strip().rstrip("/").lower() == want:
                    return str(pi.get("name") or "")
            return ""

        def _entry(prefix: str, opts_key: str) -> dict:
            e: dict = {}
            for src, dst in (("max_context_tokens", "max_context_tokens"),
                             ("max_tokens", "max_output_tokens"),
                             ("temperature", "temperature"),
                             ("top_p", "top_p")):
                v = wb.get(prefix + src)
                if v is None:
                    continue
                e[dst] = float(v) if dst in ("temperature", "top_p") else int(v)
            opts = wb.get(opts_key)
            if isinstance(opts, dict):
                if "supports_vision" in opts:
                    e["supports_vision"] = bool(opts["supports_vision"])
                if "supports_reasoning" in opts:
                    e["supports_reasoning"] = bool(opts["supports_reasoning"])
                if opts.get("reasoning_effort"):
                    e["reasoning_effort"] = opts["reasoning_effort"]  # str 或 list，_clean 兼容
            return e

        for m, prefix, opts_key in ((mc, "", "options"), (cm, "cheap_", "cheap_options")):
            entry = _entry(prefix, opts_key)
            if not entry:
                continue
            pname = _pname(m)
            mkey = ((getattr(m, "ref_model", "") or "") or m.model_name or "").strip()
            if not pname or not mkey:
                continue  # 传统内嵌且 url 反查不到 provider → 跳过（不猜）
            ps.upsert_model(pname, mkey, entry)
            logger.debug("provider.yaml writeback: %s/%s <- %s", pname, mkey, sorted(entry))
    except Exception as e:
        logger.debug("provider.yaml writeback skipped: %s", e)


async def handle_web_model_switch(request):
    """POST /api/model - hot-switch model at runtime."""
    body = await request.json()
    server = get_server()
    agent = getattr(server, "_agent", None) or server.get_agent()
    # 缺省兑底当前配置：配置对话框语义 =「只改参数，url/key/模型名只读」——
    # 不传这些字段时保持原值（长驻 Agent 内存优先，无则读盘）。
    if agent is not None:
        _mcfg, _ccfg = agent._cfg.main_model, agent._cfg.cheap_model
    else:
        from tea_agent.config import load_config as _load_cfg0
        _cfg0 = _load_cfg0(server.get_config_path() or None)
        _mcfg, _ccfg = _cfg0.main_model, _cfg0.cheap_model

    api_key = (body.get("api_key") or _mcfg.api_key or "").strip()
    api_url = (body.get("api_url") or _mcfg.api_url or "").strip()
    model_name = (body.get("model_name") or _mcfg.model_name or "").strip()
    # cheap 兑底后：只要当前 cheap 已配置，cheap_* 参数即可生效
    # （switch_model 仅在 cheap url+name 均非空时应用 cheap 更新）
    cheap_api_key = (body.get("cheap_api_key") or _ccfg.api_key or "").strip()
    cheap_api_url = (body.get("cheap_api_url") or _ccfg.api_url or "").strip()
    cheap_model_name = (body.get("cheap_model_name") or _ccfg.model_name or "").strip()

    def _float_or_none(key):
        v = body.get(key)
        return float(v) if v is not None and str(v).strip() else None
    def _int_or_none(key):
        v = body.get(key)
        return int(v) if v is not None and str(v).strip() else None

    temperature = _float_or_none("temperature")
    max_tokens = _int_or_none("max_tokens")
    top_p = _float_or_none("top_p")
    max_context_tokens = _int_or_none("max_context_tokens")
    options = body.get("options")

    cheap_temperature = _float_or_none("cheap_temperature")
    cheap_max_tokens = _int_or_none("cheap_max_tokens")
    cheap_top_p = _float_or_none("cheap_top_p")
    cheap_max_context_tokens = _int_or_none("cheap_max_context_tokens")
    cheap_options = body.get("cheap_options")

    errors = []
    if not api_key:
        errors.append("api_key required")
    if not api_url:
        errors.append("api_url required")
    if not model_name:
        errors.append("model_name required")
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    try:
        server.switch_model(
            api_key, api_url, model_name,
            cheap_api_key=cheap_api_key, cheap_api_url=cheap_api_url,
            cheap_model_name=cheap_model_name,
            temperature=temperature, max_tokens=max_tokens,
            top_p=top_p, max_context_tokens=max_context_tokens,
            options=options,
            cheap_temperature=cheap_temperature, cheap_max_tokens=cheap_max_tokens,
            cheap_top_p=cheap_top_p, cheap_max_context_tokens=cheap_max_context_tokens,
            cheap_options=cheap_options,
        )
        # 落盘 + 失效配置缓存：switch_model 只改长驻 Agent 内存，
        # Web 聊天走 create_session → config_cache，若不落盘+失效，
        # 新会话仍读磁盘旧配置（热切换对 Web 聊天无效的根因）。
        try:
            from tea_agent.config import save_config

            from .modules.agent_module import AgentModule

            if agent is not None:
                save_config(agent._cfg, server.get_config_path())
            AgentModule.invalidate_config_cache(server.get_config_path())
        except Exception as e:
            logger.warning("persist/invalidate after model switch failed: %s", e)
        # 参数写回 provider.yaml（模型属性唯一事实源）：仅回写本次显式提交的
        # 字段（_num 规范化后的 None=未传），失败静默降级不阻断热切主流程。
        _writeback_provider_yaml(server, {
            "temperature": temperature, "max_tokens": max_tokens,
            "top_p": top_p, "max_context_tokens": max_context_tokens,
            "options": options,
            "cheap_temperature": cheap_temperature, "cheap_max_tokens": cheap_max_tokens,
            "cheap_top_p": cheap_top_p, "cheap_max_context_tokens": cheap_max_context_tokens,
            "cheap_options": cheap_options,
        }, agent)
        masked_key = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 12 else "***"
        result = {"ok": True, "model": model_name, "api_url": api_url,
                  "api_key_masked": masked_key}
        if cheap_model_name:
            cheap_masked = (cheap_api_key[:6] + "..." + cheap_api_key[-4:]) if len(cheap_api_key) > 12 else "***"
            result["cheap_model"] = {
                "model": cheap_model_name, "api_url": cheap_api_url,
                "api_key_masked": cheap_masked}
        return JSONResponse(result)
    except Exception as e:
        logger.exception("model_switch failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_web_model_config(request):
    """POST /api/model/config - switch config from file."""
    body = await request.json()
    config_path = (body.get("config_path") or "").strip()
    if not config_path:
        return JSONResponse({"error": "config_path required"}, status_code=400)
    server = get_server()
    result = server.switch_config(config_path)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


async def handle_web_upload_config(request):
    """POST /api/config/upload - upload a .yaml config file."""
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"ok": False, "error": "请选择文件"}, status_code=400)

    filename = file.filename or ""
    if not filename.endswith((".yaml", ".yml")):
        return JSONResponse({"ok": False, "error": "仅支持 .yaml / .yml 文件"}, status_code=400)

    content = await file.read()
    if not content or not content.strip():
        return JSONResponse({"ok": False, "error": "文件内容为空"}, status_code=400)

    server = get_server()
    configs_dir = server._get_configs_dir()
    configs_dir.mkdir(parents=True, exist_ok=True)
    dest_path = configs_dir / filename

    if dest_path.exists():
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_stem = dest_path.stem
        dest_path = configs_dir / f"{name_stem}_{stamp}.yaml"

    try:
        if isinstance(content, bytes):
            dest_path.write_bytes(content)
        else:
            dest_path.write_text(content, encoding="utf-8")
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"保存文件失败: {e}"}, status_code=500)

    from tea_agent.config import load_config
    try:
        cfg = load_config(str(dest_path))
    except Exception as e:
        with contextlib.suppress(Exception):
            dest_path.unlink()
        return JSONResponse({"ok": False, "error": f"配置解析失败: {e}"}, status_code=400)

    main_m = cfg.main_model
    if not main_m.is_configured:
        with contextlib.suppress(Exception):
            dest_path.unlink()
        return JSONResponse({
            "ok": False,
            "error": "配置无效：必须包含 main_model 的 api_url、api_key 和 model_name",
        }, status_code=400)

    try:
        switch_result = server.switch_config(str(dest_path))
        if not switch_result.get("ok"):
            logger.warning(f"Auto-switch config after upload failed: {switch_result.get('error', '')}")
    except Exception as e:
                    logger.warning(f"Auto-switch config after upload exception: {e}")

    config_link = configs_dir / "config.yaml"
    try:
        if config_link.exists() or config_link.is_symlink():
            if config_link.is_symlink():
                config_link.unlink()
            else:
                from datetime import datetime
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = configs_dir / f"config_{stamp}.yaml"
                import shutil
                shutil.move(str(config_link), str(backup_path))
                logger.info(f"Existing config.yaml backed up to {backup_path}")
        try:
            if os.name == "nt":
                try:
                    os.symlink(str(dest_path), str(config_link))
                    logger.info(f"Symlink created: {config_link} → {dest_path}")
                except (OSError, PermissionError):
                    import shutil
                    shutil.copy2(str(dest_path), str(config_link))
                    logger.info(f"Symlink failed, copied file to {config_link}")
            else:
                os.symlink(str(dest_path), str(config_link))
                logger.info(f"Symlink created: {config_link} → {dest_path}")
        except Exception as e:
            logger.warning(f"Create config.yaml symlink failed: {e}")
    except Exception as e:
        logger.warning(f"Config.yaml symlink handling error: {e}")

    return JSONResponse({
        "ok": True,
        "filename": dest_path.name,
        "path": str(dest_path),
        "is_valid": True,
    })


async def handle_web_root(request):
    """GET / - serve Web UI index.html."""
    index_path = Path(__file__).parent / "static" / "index.html"
    if index_path.exists():
        content = index_path.read_bytes()
        return Response(
            content=content,
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return HTMLResponse("<h1>Tea Agent Server</h1><p>Web UI not found. Visit <a href='/docs'>/docs</a> for API.</p>")
