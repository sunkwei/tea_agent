"""模型配置与选择：配置增删改同步切换、选项与角色选择、Provider store CRUD 与模型同步。

由 route_handlers.py 拆分而来（逐字搬运，函数体未改写）。
"""

from starlette.responses import JSONResponse

from tea_agent.model_manager import ProviderError

from ._compat import (
    get_server,
    logger,
)
from .route_handlers_providers import _model_service, _provider_error_response


def _model_store():
    """ModelConfigStore 单例（统一模型配置中心）。"""
    from tea_agent.model_config import get_model_config_store
    return get_model_config_store()


def _mc_error_response(e) -> JSONResponse:
    """ModelConfigError → 统一错误 JSON（无 code/status 属性时当 400）。"""
    code = getattr(e, "code", "BAD_REQUEST")
    status = getattr(e, "status", 400)
    return JSONResponse({"ok": False, "error": str(e), "code": code}, status_code=status)


async def handle_model_config_get(request):
    """GET /api/model-config — 面板全量视图：providers→models→逐模型配置 + roles + active + pending_switch。"""
    server = get_server()
    try:
        from .modules.agent_module import AgentModule
        data = _model_store().panel(config_path=server.get_config_path() or "")
        data["pending_switch"] = AgentModule.get_pending_switch()
        # 标注「当前使用中」：提供商 api_url 与 main_model 一致 → is_configured（面板高亮）
        main = (data.get("active") or {}).get("main") or {}
        main_url = (main.get("api_url") or "").strip().rstrip("/").lower()
        for p in data.get("providers", []):
            p_url = (p.get("api_url") or "").strip().rstrip("/").lower()
            p["is_configured"] = bool(main_url) and p_url == main_url
        return JSONResponse(data)
    except Exception as e:
        logger.exception("model config panel failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_model_config_model_put(request):
    """PUT /api/model-config/model — 更新逐模型配置。

    Body: {provider, model, config: {max_context_tokens, max_output_tokens,
           supports_thinking, supports_vision, supports_tools, note}}
    """
    body = await request.json()
    try:
        entry = _model_store().update_model_config(
            body.get("provider", ""), body.get("model", ""), body.get("config") or {})
        return JSONResponse({"ok": True, **entry})
    except Exception as e:
        return _mc_error_response(e)


async def handle_model_config_model_add(request):
    """POST /api/model-config/model — 新增模型 {provider, model, config?}；config 缺省用启发式默认值。"""
    body = await request.json()
    try:
        cfg = body.get("config") or None
        entry = _model_store().upsert_model(
            body.get("provider", ""), body.get("model", ""), cfg)
        return JSONResponse({"ok": True, **entry})
    except Exception as e:
        return _mc_error_response(e)


async def handle_model_config_model_del(request):
    """DELETE /api/model-config/model?provider=X&model=Y — 删除模型配置条目（模型 id 可含 /，故用 query）。"""
    provider = request.query_params.get("provider", "")
    model = request.query_params.get("model", "")
    try:
        if not _model_store().delete_model(provider, model):
            return JSONResponse({"ok": False, "error": f"model '{model}' not found",
                                 "code": "NOT_FOUND"}, status_code=404)
        return JSONResponse({"ok": True, "deleted": {"provider": provider, "model": model}})
    except Exception as e:
        return _mc_error_response(e)


async def handle_model_config_sync(request):
    """POST /api/model-config/sync — 在线模型列表写回 model_config.json。

    Body: {provider, api_key?, refresh?} — 新模型按启发式默认入库，已有条目（用户编辑）不覆盖。
    """
    body = await request.json() if request.headers.get("content-length") else {}
    try:
        res = _model_service().query_models(
            body.get("provider", ""),
            api_key=(body.get("api_key") or "").strip(),
            refresh=bool(body.get("refresh", True)))
    except ProviderError as e:
        return _provider_error_response(e)
    try:
        ids = [m.get("id") for m in res.get("models", [])
               if isinstance(m, dict) and m.get("id")]
        synced = _model_store().sync_live_models(res["provider"], ids)
        return JSONResponse({"ok": True, "query_source": res.get("source"), **synced})
    except Exception as e:
        return _mc_error_response(e)


async def handle_model_config_switch(request):
    """POST /api/model-config/switch — 切换模型并继续当前会话（面板核心切换 API）。

    Body: {provider, model, role=main|cheap|vision, api_key?, continue_session=true,
           temperature?, max_tokens?, top_p?, max_context_tokens?, options?}
    流程：
      1. apply_provider → 逐模型配置自动注入（最大输出/最大上下文/思考/视觉），
         落盘 config.yaml + roles 回写 model_config.json；
      2. role=main 且 continue_session → AgentModule.request_model_switch：
         空闲立即热切（主题历史保留）；对话进行中→挂起，本轮结束自动应用；
         无长驻 Agent→下一条消息自然生效。
    """
    body = await request.json() if request.headers.get("content-length") else {}
    server = get_server()
    role = (body.get("role") or "main").strip()
    continue_session = bool(body.get("continue_session", True))

    def _num(key, cast):
        v = body.get(key)
        if v is None or str(v).strip() == "":
            return None
        try:
            return cast(v)
        except (TypeError, ValueError):
            return None

    try:
        result = _model_service().apply_provider(
            body.get("provider", ""),
            api_key=(body.get("api_key") or "").strip(),
            model=(body.get("model") or "").strip(),
            role=role,
            config_path=server.get_config_path(),
            temperature=_num("temperature", float),
            max_tokens=_num("max_tokens", int),
            top_p=_num("top_p", float),
            max_context_tokens=_num("max_context_tokens", int),
            options=body.get("options"),
        )
    except ProviderError as e:
        return _provider_error_response(e)
    except Exception as e:
        logger.exception("model-config switch apply failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    switch = {"mode": "config_only"}
    if result.get("ok"):
        # 落盘成功 → 无论角色/是否续用会话都必须失效 config_cache：
        # create_session 读 config_cache，不失效则 cheap/vision 切换、
        # 或 continue_session=false 的 main 切换，下一轮仍读旧配置。
        try:
            from .modules.agent_module import AgentModule
            AgentModule.invalidate_config_cache(server.get_config_path())
        except Exception as e:
            logger.warning("invalidate config cache failed: %s", e)
        if role == "main" and continue_session:
            try:
                from tea_agent.config import load_config
                mc = load_config(server.get_config_path() or None).main_model
                switch = AgentModule.request_model_switch(
                    mc.api_key, mc.api_url, mc.model_name,
                    temperature=mc.temperature, max_tokens=mc.max_tokens,
                    top_p=mc.top_p, max_context_tokens=mc.max_context_tokens,
                    options=mc.options)
            except Exception as e:
                logger.warning("session-continue switch failed (config saved): %s", e)
                switch = {"mode": "error", "error": str(e)}
    result["switch"] = switch
    return JSONResponse(result)
def _provider_option_list() -> list[dict]:
    """从 provider.yaml 派生 provider/model 组合列表（下拉框数据源）。

    value = "provider::model"（:: 分隔；provider 名不含 :）；
    label = "provider / model"。去重后按 (provider, model) 排序。
    """
    from tea_agent.provider_store import get_provider_store

    seen: set[str] = set()
    opts: list[dict] = []
    try:
        providers = get_provider_store().list_providers()
    except Exception as e:
        logger.warning("provider option list failed: %s", e)
        return opts
    for p in providers:
        pname = (p.get("name") or "").strip()
        if not pname:
            continue
        models = [m.get("id") for m in (p.get("catalog") or []) if m.get("id")]
        if not models and p.get("default_model"):
            models = [p["default_model"]]
        for mid in models:
            mid = (mid or "").strip()
            if not mid:
                continue
            value = f"{pname}::{mid}"
            if value in seen:
                continue
            seen.add(value)
            opts.append({"value": value, "provider": pname, "model": mid,
                         "label": f"{pname} / {mid}"})
    opts.sort(key=lambda o: (o["provider"].lower(), o["model"].lower()))
    return opts


def _role_selection(mc) -> dict:
    """把 ModelConfig 解析为下拉选中值 {value, provider, model, label}。

    优先引用式 provider+ref_model；无 provider 时按 api_url 回查
    provider.yaml 名字（传统内嵌配置也能被选中），再兜底用 url。
    """
    provider = str(getattr(mc, "provider", "") or "").strip()
    model = str(getattr(mc, "ref_model", "") or "") or str(getattr(mc, "model_name", "") or "").strip()
    if not provider and mc.api_url:
        from tea_agent.provider_store import get_provider_store

        norm = (mc.api_url or "").strip().rstrip("/").lower()
        for p in get_provider_store().list_providers():
            if (p.get("api_url") or "").strip().rstrip("/").lower() == norm:
                provider = (p.get("name") or "").strip()
                break
    if not provider and mc.api_url:
        provider = mc.api_url
    if provider and model:
        value = f"{provider}::{model}"
        label = f"{provider} / {model}"
    else:
        value, label = "", (model or "")
    return {"value": value, "provider": provider, "model": model, "label": label}


def _ensure_selected_option(options: list[dict], sel: dict) -> None:
    """当前选中值不在选项列表时补入（provider.yaml 尚未收录该组合）。"""
    if not sel.get("value"):
        return
    if any(o.get("value") == sel["value"] for o in options):
        return
    options.append({"value": sel["value"], "provider": sel.get("provider", ""),
                    "model": sel.get("model", ""),
                    "label": sel.get("label") or sel["value"]})


async def handle_model_options(request):
    """GET /api/model-options — 主/便宜模型下拉框数据源。

    返回 provider.yaml 全部 provider+model 组合 + 当前 active config 的
    main/cheap 各自选中值。前端据此填充主模型/便宜模型两个 <select>。
    """
    server = get_server()
    try:
        from tea_agent.config import load_config

        options = _provider_option_list()
        cfg = load_config(server.get_config_path() or None)
        main_sel = _role_selection(cfg.main_model)
        cheap_sel = _role_selection(cfg.cheap_model)
        _ensure_selected_option(options, main_sel)
        _ensure_selected_option(options, cheap_sel)
        return JSONResponse({
            "ok": True,
            "options": options,
            "main": main_sel,
            "cheap": cheap_sel,
            "active_config_path": server.get_config_path() or "",
        })
    except Exception as e:
        logger.exception("model-options failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_model_select(request):
    """POST /api/model-select — 选择主/便宜/视觉模型（provider+model 引用式）。

    Body: {role: "main"|"cheap"|"vision", provider, model}
    流程：
      1. resolve provider.yaml → api_key/api_url/max_context/max_output/能力；
      2. 写回 active config 对应角色块（引用式，save_config 只落 provider+model 不内嵌密钥）；
      3. 缓存失效；role==main 时热切换（对话中挂起、空闲立即生效）；
      4. roles 回写 model_config.json（面板"使用中"单一事实源）。
    """
    body = await request.json() if request.headers.get("content-length") else {}
    role = (body.get("role") or "main").strip()
    if role not in ("main", "cheap", "vision"):
        return JSONResponse({"ok": False, "error": f"invalid role '{role}'",
                             "code": "BAD_REQUEST"}, status_code=400)
    provider = (body.get("provider") or "").strip()
    model = (body.get("model") or "").strip()
    if not model:
        return JSONResponse({"ok": False, "error": "model required",
                             "code": "BAD_REQUEST"}, status_code=400)
    server = get_server()
    try:
        from tea_agent.config import load_config, save_config
        from tea_agent.provider_store import get_provider_store

        from .modules.agent_module import AgentModule

        store = get_provider_store()
        resolved = store.resolve(provider, model)
        if resolved is None:
            return JSONResponse({"ok": False, "error": f"provider '{provider}' not found",
                                 "code": "NOT_FOUND"}, status_code=404)
        cfg_path = server.get_config_path() or ""
        cfg = load_config(cfg_path)
        target = {"main": cfg.main_model, "cheap": cfg.cheap_model,
                  "vision": cfg.vision_model}[role]
        target.provider = resolved["provider"]
        target.ref_model = resolved["model"]
        target.api_key = resolved.get("api_key", "")
        target.api_url = resolved.get("api_url", "")
        target.model_name = resolved.get("model", model)
        target.max_context_tokens = int(resolved.get("max_context_tokens") or target.max_context_tokens)
        if int(resolved.get("max_output_tokens") or 0) > 0:
            target.max_tokens = int(resolved["max_output_tokens"])
        opts = dict(target.options or {})
        opts["supports_vision"] = bool(resolved.get("supports_vision", False))
        opts["supports_reasoning"] = bool(resolved.get("supports_reasoning", False))
        if resolved.get("reasoning_effort"):
            opts["reasoning_effort"] = resolved["reasoning_effort"]
        target.options = opts
        save_config(cfg, cfg_path)

        AgentModule.invalidate_config_cache(cfg_path)
        switch = {"mode": "config_only"}
        if role == "main":
            try:
                mc = load_config(cfg_path or None).main_model
                switch = AgentModule.request_model_switch(
                    mc.api_key, mc.api_url, mc.model_name,
                    temperature=mc.temperature, max_tokens=mc.max_tokens,
                    top_p=mc.top_p, max_context_tokens=mc.max_context_tokens,
                    options=mc.options)
            except Exception as e:
                logger.warning("model-select hot-switch failed (config saved): %s", e)
                switch = {"mode": "error", "error": str(e)}

        try:
            _model_store().set_role(role, resolved["provider"], resolved["model"],
                                    api_url=resolved.get("api_url", ""))
        except Exception as e:
            logger.debug("model-select role binding skipped: %s", e)

        return JSONResponse({"ok": True, "role": role,
                             "provider": resolved["provider"], "model": resolved["model"],
                             "config_path": cfg_path, "switch": switch})
    except Exception as e:
        logger.exception("model-select failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
def _provider_store():
    """ProviderStore 单例（provider.yaml 唯一事实源）。"""
    from tea_agent.provider_store import get_provider_store
    return get_provider_store()


def _pstore_error_response(e) -> JSONResponse:
    """ProviderStoreError → 统一错误 JSON。"""
    code = getattr(e, "code", "BAD_REQUEST")
    status = getattr(e, "status", 400)
    return JSONResponse({"ok": False, "error": str(e), "code": code}, status_code=status)


async def handle_provider_store_list(request):
    """GET /api/provider-store — 供应商目录列表（api_key 掩码，含逐模型能力 catalog）。"""
    try:
        store = _provider_store()
        providers = store.list_providers()
        total_models = sum(len(p.get("catalog") or []) for p in providers)
        return JSONResponse({"ok": True, "providers": providers,
                             "total": len(providers), "total_models": total_models,
                             "file": str(store.file_path)})
    except Exception as e:
        logger.exception("provider-store list failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_provider_store_get(request):
    """GET /api/provider-store/{name} — 单个供应商详情（含逐模型能力目录）。"""
    name = request.path_params.get("name", "")
    try:
        store = _provider_store()
        p = store.get_provider(name)
        if p is None:
            return JSONResponse({"ok": False, "error": f"provider '{name}' not found",
                                 "code": "NOT_FOUND"}, status_code=404)
        models = p.get("models") or {}
        catalog = []
        for mid in sorted(models, key=str.lower):
            cfg = models[mid]
            catalog.append({
                "id": mid,
                "max_context_tokens": int(cfg.get("max_context_tokens") or 0),
                "max_output_tokens": int(cfg.get("max_output_tokens") or 0),
                "supports_vision": bool(cfg.get("supports_vision", False)),
                "supports_reasoning": bool(cfg.get("supports_reasoning", False)),
                "reasoning_effort": cfg.get("reasoning_effort", ""),
                "note": cfg.get("note", ""),
            })
        api_key = p.get("api_key", "") or ""
        from tea_agent.model_manager import _mask_key
        masked = _mask_key(api_key)
        return JSONResponse({"ok": True, "provider": {
            "name": p.get("name") or name,
            "api_url": p.get("api_url", ""),
            "api_key_masked": masked,
            "has_key": bool(api_key),
            "default_model": p.get("default_model", ""),
            "description": p.get("description", ""),
            "supports_vision": bool(p.get("supports_vision", False)),
            "supports_reasoning": bool(p.get("supports_reasoning", False)),
            "source": p.get("source", "custom"),
            "catalog": catalog,
            "model_count": len(catalog),
        }})
    except Exception as e:
        logger.exception("provider-store get failed: %s", name)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


async def handle_provider_store_upsert(request):
    """POST /api/provider-store — 新增/更新供应商（body 全量字段，models 可传字符串列表或富条目）。"""
    body = await request.json() if request.headers.get("content-length") else {}
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "name required"}, status_code=400)
    meta = {k: body[k] for k in (
        "api_url", "api_key", "default_model", "description",
        "supports_vision", "supports_reasoning", "source", "models") if k in body}
    try:
        store = _provider_store()
        p = store.upsert_provider(name, meta)
        return JSONResponse({"ok": True, "provider": p.get("name") or name})
    except Exception as e:
        return _pstore_error_response(e)


async def handle_provider_store_delete(request):
    """DELETE /api/provider-store/{name} — 删除供应商（含其模型目录）。"""
    name = request.path_params.get("name", "")
    try:
        ok = _provider_store().remove_provider(name)
        if not ok:
            return JSONResponse({"ok": False, "error": f"provider '{name}' not found",
                                 "code": "NOT_FOUND"}, status_code=404)
        return JSONResponse({"ok": True, "deleted": name})
    except Exception as e:
        return _pstore_error_response(e)


async def handle_provider_store_model_put(request):
    """PUT /api/provider-store/{name}/model — 新增/更新某供应商的模型条目。

    Body: {model, config: {max_context_tokens, max_output_tokens, supports_vision,
          supports_reasoning, reasoning_effort, note}}（config 缺省用启发式默认）。
    """
    name = request.path_params.get("name", "")
    body = await request.json() if request.headers.get("content-length") else {}
    model = (body.get("model") or "").strip()
    if not model:
        return JSONResponse({"ok": False, "error": "model required"}, status_code=400)
    try:
        store = _provider_store()
        entry = store.upsert_model(name, model, body.get("config") or None)
        return JSONResponse({"ok": True, "provider": name, "model": model, "config": entry})
    except Exception as e:
        return _pstore_error_response(e)


async def handle_provider_store_model_delete(request):
    """DELETE /api/provider-store/{name}/model?model=xxx — 删除某模型条目。"""
    name = request.path_params.get("name", "")
    model = request.query_params.get("model", "")
    try:
        ok = _provider_store().delete_model(name, model)
        if not ok:
            return JSONResponse({"ok": False, "error": f"model '{model}' not found",
                                 "code": "NOT_FOUND"}, status_code=404)
        return JSONResponse({"ok": True, "deleted": {"provider": name, "model": model}})
    except Exception as e:
        return _pstore_error_response(e)


async def handle_provider_store_query_models(request):
    """GET /api/provider-store/{name}/models — 实时查询该供应商可用模型。

    Query: refresh=true 强制在线查询；api_key 可选覆盖。返回 live/static 双层结果。
    """
    name = request.path_params.get("name", "")
    refresh = request.query_params.get("refresh", "false").lower() in ("1", "true", "yes")
    api_key = request.query_params.get("api_key", "") or ""
    try:
        store = _provider_store()
        result = store.query_live_models(name, api_key=api_key, refresh=refresh)
        return JSONResponse({"ok": True, **result})
    except Exception as e:
        if getattr(e, "code", "") == "NOT_FOUND":
            return JSONResponse({"ok": False, "error": str(e), "code": "NOT_FOUND"}, status_code=404)
        logger.exception("provider-store query models failed: %s", name)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


async def handle_provider_store_sync_models(request):
    """POST /api/provider-store/{name}/models/sync — 在线模型列表写回 provider.yaml。

    Body: {api_key?, refresh?} — 新模型按启发式默认入库，已有条目（用户编辑）不覆盖。
    """
    name = request.path_params.get("name", "")
    body = await request.json() if request.headers.get("content-length") else {}
    api_key = (body.get("api_key") or "").strip()
    try:
        store = _provider_store()
        live = store.query_live_models(name, api_key=api_key, refresh=True)
        ids = [m.get("id") for m in live.get("models", []) if isinstance(m, dict) and m.get("id")]
        synced = store.sync_models(name, ids)
        return JSONResponse({"ok": True, "query_source": live.get("source"), **synced})
    except Exception as e:
        return _pstore_error_response(e)


async def handle_provider_store_apply(request):
    """POST /api/provider-store/{name}/apply — 把 p_name+m_name 应用到当前 config。

    Body: {model, role=main|cheap|vision} — 写 configxxx.yaml 为引用式组合（不内嵌密钥），
    供独立界面「设为主/便宜模型」使用。provider.yaml 是能力/密钥唯一事实源。
    """
    name = request.path_params.get("name", "")
    body = await request.json() if request.headers.get("content-length") else {}
    model = (body.get("model") or "").strip()
    role = (body.get("role") or "main").strip()
    if role not in ("main", "cheap", "vision"):
        return JSONResponse({"ok": False, "error": f"invalid role '{role}'",
                             "code": "BAD_REQUEST"}, status_code=400)
    if not model:
        return JSONResponse({"ok": False, "error": "model required"}, status_code=400)
    try:
        from tea_agent.config import load_config, save_config
        store = _provider_store()
        resolved = store.resolve(name, model)
        if resolved is None:
            return JSONResponse({"ok": False, "error": f"provider '{name}' not found",
                                 "code": "NOT_FOUND"}, status_code=404)
        server = get_server()
        cfg_path = server.get_config_path() or ""
        cfg = load_config(cfg_path)
        target = {"main": cfg.main_model, "cheap": cfg.cheap_model,
                  "vision": cfg.vision_model}[role]
        # 记录引用来源 → save_config 以引用式写回（provider + model），密钥不落 config
        target.provider = resolved["provider"]
        target.ref_model = resolved["model"]
        target.api_key = resolved.get("api_key", "")
        target.api_url = resolved.get("api_url", "")
        target.model_name = resolved.get("model", model)
        target.max_context_tokens = int(resolved.get("max_context_tokens") or target.max_context_tokens)
        target.max_tokens = int(resolved.get("max_output_tokens") or target.max_tokens)
        opts = dict(target.options or {})
        opts["supports_vision"] = bool(resolved.get("supports_vision", False))
        opts["supports_reasoning"] = bool(resolved.get("supports_reasoning", False))
        if resolved.get("reasoning_effort"):
            opts["reasoning_effort"] = resolved["reasoning_effort"]
        target.options = opts
        saved = save_config(cfg, cfg_path)
        # 配置已落盘 → 必须失效 config_cache，否则下一轮 create_session
        # 命中旧缓存，切换在同一进程内永不生效（与其他 apply 入口对齐）
        try:
            from .modules.agent_module import AgentModule
            AgentModule.invalidate_config_cache(cfg_path)
        except Exception as e:
            logger.warning("invalidate config cache after provider-store apply failed: %s", e)
        return JSONResponse({"ok": True, "role": role, "provider": name, "model": model,
                             "config_path": saved})
    except Exception as e:
        logger.exception("provider-store apply failed: %s", name)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
