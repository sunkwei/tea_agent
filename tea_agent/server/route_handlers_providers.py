"""热重载（模块列表/查询/重载、watcher、路由重载）与服务商管理、模型连通性测试。

由 route_handlers.py 拆分而来（逐字搬运，函数体未改写）。
"""

from starlette.responses import JSONResponse

from tea_agent.model_manager import ProviderError

from ._compat import (
    get_server,
    logger,
)


async def handle_list_modules(request):
    """GET /api/modules -- list all modules with status"""
    return JSONResponse(get_server().list_modules())


async def handle_get_module(request):
    """GET /api/modules/{name} -- get module health"""
    name = request.path_params.get("name", "")
    info = get_server().get_module(name)
    if info is None:
        return JSONResponse({"error": f'Module "{name}" not found'}, status_code=404)
    return JSONResponse(info)


async def handle_reload_module(request):
    """POST /api/modules/{name}/reload -- hot-reload a module"""
    name = request.path_params.get("name", "")
    result = get_server().reload_module(name)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


async def handle_reload_all_modules(request):
    """POST /api/modules/reload -- reload all modules"""
    result = get_server().reload_all_modules()
    return JSONResponse(result)


async def handle_start_watcher(request):
    """POST /api/modules/watcher/start -- start file watcher"""
    body = await request.json() if request.headers.get("content-length") else {}
    interval = float(body.get("interval", 2.0))
    result = get_server().start_watcher(interval)
    return JSONResponse(result)


async def handle_stop_watcher(request):
    """POST /api/modules/watcher/stop -- stop file watcher"""
    result = get_server().stop_watcher()
    return JSONResponse(result)


async def handle_reload_routes(request):
    """POST /api/modules/reload-routes -- hot-reload routes without restart.

    Reloads route_handlers.py and rebuilds all routes on the live
    Starlette app. No server restart needed.
    """
    result = get_server().rebuild_routes()
    return JSONResponse(result)
def _model_service():
    """获取 ProviderService 单例（绑定 server 当前配置路径）。"""
    from tea_agent.model_manager import get_provider_service

    return get_provider_service(get_server().get_config_path())


def _provider_error_response(e) -> JSONResponse:
    """ProviderError → 统一错误 JSON。"""
    return JSONResponse({"ok": False, "error": str(e), "code": e.code}, status_code=e.status)


async def handle_providers_list(request):
    """GET /api/providers — 提供商列表（内置+自定义，含来源/能力/当前使用状态）。"""
    try:
        return JSONResponse(_model_service().list_providers())
    except Exception as e:
        logger.exception("list providers failed")
        return JSONResponse({"ok": False, "error": str(e), "code": "SERVER_ERROR"}, status_code=500)


async def handle_provider_models(request):
    """GET /api/providers/{name}/models — 查询提供商可用模型（缓存优先，实时 fallback）。

    Query params:
        refresh: true=强制实时查询并更新缓存；false/缺省=5 分钟内优先返回缓存
        api_key: 可选，实时查询所需（自定义供应商必填）
    """
    name = request.path_params.get("name", "")
    refresh = request.query_params.get("refresh", "false").lower() in ("1", "true", "yes")
    api_key = request.query_params.get("api_key", "") or ""
    try:
        result = _model_service().query_models(name, api_key=api_key, refresh=refresh)
        return JSONResponse(result)
    except ProviderError as e:
        return _provider_error_response(e)
    except Exception as e:
        logger.exception("query provider models failed: %s", name)
        return JSONResponse({"ok": False, "error": str(e), "code": "QUERY_FAILED"}, status_code=502)


async def handle_provider_create(request):
    """POST /api/providers — 新增自定义供应商（持久化到 custom_providers.yaml）。"""
    body = await request.json()
    try:
        provider = _model_service().add_custom_provider(body)
        return JSONResponse({"ok": True, "provider": provider})
    except ProviderError as e:
        return _provider_error_response(e)
    except Exception as e:
        logger.exception("create custom provider failed")
        return JSONResponse({"ok": False, "error": str(e), "code": "SERVER_ERROR"}, status_code=500)


async def handle_provider_update(request):
    """PUT /api/providers/{name} — 更新自定义供应商（内置拒绝修改）。"""
    name = request.path_params.get("name", "")
    body = await request.json()
    try:
        provider = _model_service().update_custom_provider(name, body)
        return JSONResponse({"ok": True, "provider": provider})
    except ProviderError as e:
        return _provider_error_response(e)
    except Exception as e:
        logger.exception("update custom provider failed: %s", name)
        return JSONResponse({"ok": False, "error": str(e), "code": "SERVER_ERROR"}, status_code=500)


async def handle_provider_delete(request):
    """DELETE /api/providers/{name} — 删除自定义供应商（内置拒绝删除）。"""
    name = request.path_params.get("name", "")
    try:
        return JSONResponse(_model_service().delete_custom_provider(name))
    except ProviderError as e:
        return _provider_error_response(e)
    except Exception as e:
        logger.exception("delete custom provider failed: %s", name)
        return JSONResponse({"ok": False, "error": str(e), "code": "SERVER_ERROR"}, status_code=500)


async def handle_provider_apply(request):
    """POST /api/providers/{name}/apply — 一键应用提供商到模型配置（main/cheap/vision）。

    Body:
        api_key: 可选，留空复用该角色现有 key
        model:   可选，默认提供商 default_model
        role:    main | cheap | vision，默认 main
        temperature / max_tokens / top_p / max_context_tokens / options: 可选覆盖
    """
    name = request.path_params.get("name", "")
    body = await request.json() if request.headers.get("content-length") else {}
    api_key = (body.get("api_key") or "").strip()
    role = (body.get("role") or "main").strip()
    try:
        result = _model_service().apply_provider(
            name,
            api_key=api_key,
            model=(body.get("model") or "").strip(),
            role=role,
            config_path=get_server().get_config_path(),
            temperature=body.get("temperature"),
            max_tokens=body.get("max_tokens"),
            top_p=body.get("top_p"),
            max_context_tokens=body.get("max_context_tokens"),
            options=body.get("options"),
        )
        # 配置已落盘 → 必须失效会话配置缓存，否则 create_session
        # 命中启动时的旧配置，聊天会话仍用老模型（热生效失效的根因）。
        # 无论 role 都要失效（cheap/vision 的新会话同样读取缓存）。
        if result.get("ok"):
            try:
                from .modules.agent_module import AgentModule
                AgentModule.invalidate_config_cache(get_server().get_config_path())
            except Exception as e:
                logger.warning("invalidate config cache failed: %s", e)
        # 会话续用切换：配置已落盘（apply_provider 含逐模型配置注入），
        # 读盘后交给 AgentModule.request_model_switch —— 空闲立即热切（保留当前
        # 主题历史）；对话进行中则挂起，本轮结束后自动应用，绝不中断流式回复。
        if result.get("ok") and role == "main":
            try:
                from tea_agent.config import load_config

                from .modules.agent_module import AgentModule
                mc = load_config(get_server().get_config_path() or None).main_model
                AgentModule.request_model_switch(
                    mc.api_key, mc.api_url, mc.model_name,
                    provider=mc.provider, ref_model=mc.ref_model,
                    temperature=mc.temperature, max_tokens=mc.max_tokens,
                    top_p=mc.top_p, max_context_tokens=mc.max_context_tokens,
                    options=mc.options)
            except Exception as e:
                logger.warning("hot-switch after apply failed (config saved): %s", e)
        return JSONResponse(result)
    except ProviderError as e:
        return _provider_error_response(e)
    except Exception as e:
        logger.exception("apply provider failed: %s", name)
        return JSONResponse({"ok": False, "error": str(e), "code": "SERVER_ERROR"}, status_code=500)


async def handle_model_test(request):
    """POST /api/model/test — 测试连接（最小请求验证端点+key+模型）。

    Body:
        api_url:  必填
        api_key:  必填
        model:    可选
    """
    body = await request.json() if request.headers.get("content-length") else {}
    api_url = (body.get("api_url") or "").strip()
    api_key = (body.get("api_key") or "").strip()
    model = (body.get("model") or "").strip()
    if not api_url or not api_key:
        return JSONResponse(
            {"ok": False, "error": "api_url and api_key required", "code": "BAD_REQUEST"},
            status_code=400,
        )
    try:
        result = _model_service().test_connection(api_url, api_key, model)
        return JSONResponse(result)
    except ProviderError as e:
        return _provider_error_response(e)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "code": "TEST_FAILED"}, status_code=502)
