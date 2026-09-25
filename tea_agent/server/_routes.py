"""路由表构建（由 server.py 抽出，逐字搬运）。

同目录抽取：保证 Path(__file__).parent / "static" 的解析结果与原先一致。
"""

from pathlib import Path


def _build_routes() -> list:
    """Build the complete route list with fresh handler references.

    Uses local imports so that each call captures the latest
    version of route_handlers — essential for hot-reload.
    """
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles

    from tea_agent.server import route_handlers as rh

    static_dir = str(Path(__file__).parent / "static")

    return [
        # 就绪探测端点。handle_health 早已存在、也列入了鉴权 skip_paths 与
        # OpenAPI 声明，但此处从未注册 → 实际访问恒为 404（实测确认）。
        # 重启的就绪探测（_wait_ready）依赖它，缺失会导致新进程被误判失败。
        Route("/health", rh.handle_health),
        Route("/", rh.handle_web_root),
        Route("/api/chat", rh.handle_web_chat, methods=["POST"]),
        Route("/api/chat/steering", rh.handle_web_chat_steering, methods=["POST"]),
        Route("/api/chat/continue", rh.handle_chat_continue, methods=["POST"]),
        Route("/api/chat/question", rh.handle_chat_question, methods=["POST"]),
        Route("/api/chat/abort", rh.handle_chat_abort, methods=["POST"]),
        Route("/api/queue/{topic_id:str}", rh.handle_web_queue_list),
        Route("/api/queue/{topic_id:str}", rh.handle_web_queue_add, methods=["POST"]),
        Route("/api/queue/{topic_id:str}/{item_id:str}", rh.handle_web_queue_remove, methods=["DELETE"]),
        Route("/api/screenshot/region", rh.handle_screenshot_region, methods=["POST"]),
        Route("/api/screenshot/full", rh.handle_screenshot_full),
        Route("/api/screenshot/interactive", rh.handle_screenshot_interactive, methods=["POST"]),
        Route("/api/new_topic", rh.handle_web_new_topic, methods=["POST"]),
        Route("/api/topic/{topic_id:str}/fork", rh.handle_web_fork_topic, methods=["POST"]),
        Route("/api/sessions", rh.handle_web_sessions),
        Route("/api/topic/{topic_id:str}", rh.handle_web_topic_info, methods=["GET", "PUT", "DELETE"]),
        Route("/api/topic/{topic_id:str}/status", rh.handle_web_topic_status),
        Route("/api/topic/{topic_id:str}/stream-buffer", rh.handle_web_topic_stream_buffer),
        Route("/api/topic/{topic_id:str}/conversations", rh.handle_web_topic_conversations),
        Route("/api/image/{image_id:str}", rh.handle_web_image),
        Route("/api/topic/{topic_id:str}/trajectory", rh.handle_web_topic_trajectory),
        Route("/api/topic/{topic_id:str}/todos", rh.handle_web_topic_todos),
        Route("/api/topic/{topic_id:str}/todos/{idx:int}", rh.handle_web_topic_todo_update, methods=["PUT"]),
        Route("/api/topic/{topic_id:str}/plans", rh.handle_web_topic_plans),
        Route("/api/tools", rh.handle_web_tools),
        Route("/api/interruptions", rh.handle_web_interruptions),
        Route("/api/config", rh.handle_web_config),
        Route("/api/config", rh.handle_web_update_config, methods=["PUT"]),
        Route("/api/configs", rh.handle_web_list_configs),
        Route("/api/config/create", rh.handle_web_create_config, methods=["POST"]),
        Route("/api/model", rh.handle_web_model_info),
        Route("/api/model", rh.handle_web_model_switch, methods=["POST"]),
        Route("/api/model/config", rh.handle_web_model_config, methods=["POST"]),
        Route("/api/model/test", rh.handle_model_test, methods=["POST"]),
        Route("/api/providers", rh.handle_providers_list),
        Route("/api/providers", rh.handle_provider_create, methods=["POST"]),
        Route("/api/providers/{name:str}", rh.handle_provider_update, methods=["PUT"]),
        Route("/api/providers/{name:str}", rh.handle_provider_delete, methods=["DELETE"]),
        Route("/api/providers/{name:str}/models", rh.handle_provider_models),
        Route("/api/providers/{name:str}/apply", rh.handle_provider_apply, methods=["POST"]),
        # ── 统一模型配置面板（~/.tea_agent/model_config.json 单一事实源）──
        Route("/api/model-config", rh.handle_model_config_get),
        Route("/api/model-config/model", rh.handle_model_config_model_put, methods=["PUT"]),
        Route("/api/model-config/model", rh.handle_model_config_model_add, methods=["POST"]),
        Route("/api/model-config/model", rh.handle_model_config_model_del, methods=["DELETE"]),
        Route("/api/model-config/sync", rh.handle_model_config_sync, methods=["POST"]),
        Route("/api/model-config/switch", rh.handle_model_config_switch, methods=["POST"]),
        Route("/api/model-options", rh.handle_model_options),
        Route("/api/model-select", rh.handle_model_select, methods=["POST"]),
        Route("/api/config/upload", rh.handle_web_upload_config, methods=["POST"]),
        # ── Provider Store（~/.tea_agent/provider.yaml 独立供应商/模型目录）──
        Route("/api/provider-store", rh.handle_provider_store_list),
        Route("/api/provider-store", rh.handle_provider_store_upsert, methods=["POST"]),
        Route("/api/provider-store/{name:str}", rh.handle_provider_store_get),
        Route("/api/provider-store/{name:str}", rh.handle_provider_store_delete, methods=["DELETE"]),
        Route("/api/provider-store/{name:str}/model", rh.handle_provider_store_model_put, methods=["PUT"]),
        Route("/api/provider-store/{name:str}/model", rh.handle_provider_store_model_delete, methods=["DELETE"]),
        Route("/api/provider-store/{name:str}/models", rh.handle_provider_store_query_models),
        Route("/api/provider-store/{name:str}/models/sync", rh.handle_provider_store_sync_models, methods=["POST"]),
        Route("/api/provider-store/{name:str}/apply", rh.handle_provider_store_apply, methods=["POST"]),
        Route("/api/modules", rh.handle_list_modules),
        Route("/api/modules/{name:str}", rh.handle_get_module),
        Route("/api/modules/{name:str}/reload", rh.handle_reload_module, methods=["POST"]),
        Route("/api/modules/reload", rh.handle_reload_all_modules, methods=["POST"]),
        Route("/api/modules/watcher/start", rh.handle_start_watcher, methods=["POST"]),
        Route("/api/modules/watcher/stop", rh.handle_stop_watcher, methods=["POST"]),
        Route("/api/modules/reload-routes", rh.handle_reload_routes, methods=["POST"]),
        Route("/api/restart", rh.handle_restart, methods=["POST"]),
        Route("/api/files", rh.handle_file_tree),
        Route("/api/file", rh.handle_file_read),
        Route("/v1/models", rh.handle_list_models),
        Route("/v1/tools", rh.handle_list_tools),
        Route("/v1/tools/{name:str}/run", rh.handle_run_tool, methods=["POST"]),
        Route("/v1/sessions", rh.handle_list_sessions),
        Route("/v1/sessions", rh.handle_create_session, methods=["POST"]),
        Route("/v1/sessions/{topic_id:str}", rh.handle_get_session),
        Route("/v1/sessions/{topic_id:str}", rh.handle_delete_session, methods=["DELETE"]),
        Route("/v1/sessions/{topic_id:str}/messages", rh.handle_get_session_messages),
        Route("/v1/config", rh.handle_get_config),
        Route("/v1/config/switch", rh.handle_switch_config, methods=["POST"]),
        Route("/v1/memory", rh.handle_list_memory),
        Route("/v1/memory", rh.handle_create_memory, methods=["POST"]),
        Route("/v1/memory/{mem_id:str}", rh.handle_delete_memory, methods=["DELETE"]),
        Route("/v1/tasks", rh.handle_list_tasks),
        Route("/v1/tasks", rh.handle_create_task, methods=["POST"]),
        Route("/v1/tasks/{task_id:str}", rh.handle_delete_task, methods=["DELETE"]),
        Route("/v1/search", rh.handle_search),
        Route("/v1/export/pdf/{topic_id:str}", rh.handle_export_pdf),
        Route("/v1/export/md/{topic_id:str}", rh.handle_export_md),
        Route("/v1/download/{filename:str}", rh.handle_file_download),
        Route("/v1/preview/{filename:str}", rh.handle_file_preview),
        Route("/v1/upload", rh.handle_upload, methods=["POST"]),
        Route("/api/dags", rh.handle_list_dags),
        Route("/dag/{viz_id:str}", rh.handle_dag_viz),
        Route("/dag/{viz_id:str}/events", rh.handle_dag_sse),
        Route("/dag/{viz_id:str}/status", rh.handle_dag_status),
        Route("/dag/{viz_id:str}/image", rh.handle_dag_image),
        Route("/docs", rh.handle_docs),
        Route("/openapi.json", rh.handle_openapi),
        Mount("/static", app=StaticFiles(directory=static_dir), name="static"),
    ]
