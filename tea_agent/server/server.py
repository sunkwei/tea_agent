"""
Tea Agent HTTP API Server (minimal) — REST API + Web UI.

All business logic is delegated to hot-reloadable modules.
The server is just Starlette + routes — thin, clean, hot-reloadable.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("api_server")

try:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route, WebSocketRoute
    from starlette.staticfiles import StaticFiles
except ImportError:
    raise ImportError("pip install starlette uvicorn")

from tea_agent.server.module import get_registry
from tea_agent.server.modules import load_all


def _capture_and_encode(action, region=None):
    """Screenshot + base64 encode (shared by screenshot_region/full)."""
    import base64
    import tempfile
    try:
        from tea_agent.toolkit.toolkit_screenshot import toolkit_screenshot
        tmp = os.path.join(tempfile.gettempdir(), f"screenshot_{action}.png")
        r = toolkit_screenshot(action=action, region=region, output=tmp) if region else toolkit_screenshot(action=action, output=tmp)
        if not r.get("success"):
            return {"ok": False, "error": r.get("error", "failed")}
        p = r.get("path", "")
        if not p or not os.path.isfile(p):
            if os.path.isfile(tmp):
                p = tmp
            else:
                return {"ok": False, "error": "no screenshot file"}
        with open(p, "rb") as f:
            d = f.read()
        if len(d) < 100:
            return {"ok": False, "error": f"screenshot too small: {len(d)}b"}
        return {"ok": True,
                "image_base64": f"data:image/png;base64,{base64.b64encode(d).decode()}",
                "path": p, "size": len(d)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

__version__ = "0.14.0"

_server_instance = None
_uvicorn_server = None
_restart_args: list[str] = []


def restart_server() -> dict:
    """Graceful restart: spawn new process, then signal current to stop."""
    global _uvicorn_server
    if _uvicorn_server is None:
        return {"ok": False, "error": "Server not running"}
    import subprocess
    import sys
    try:
        subprocess.Popen([sys.executable, *(_restart_args or ["-m", "tea_agent.server"])],
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    _uvicorn_server.should_exit = True
    return {"ok": True, "message": "Restart initiated"}


class MinimalServer:
    """Minimal HTTP API Server — delegates all business to modules."""

    def __init__(self, api_key="", config_path=""):
        self._api_key = (api_key or os.environ.get("TEA_API_KEY", "")).strip()
        self._config_path = config_path or ""
        self._registry = get_registry()
        self._loaded = False
        self._app = None  # Starlette app reference, set by create_app()

    def load_modules(self):
        if self._loaded:
            return {}
        results = load_all(self._registry)
        self._loaded = True
        agent_mod = self._registry.get_loaded("agent")
        if agent_mod and self._config_path:
            agent_mod.set_config_path(self._config_path)
        if agent_mod:
            agent_mod._server_version = __version__
        return results

    def get_registry(self):
        return self._registry

    def health(self):
        statuses = self._registry.status()
        all_ok = all(s.get("loaded", False) for s in statuses)
        return {"status": "ok" if all_ok else "degraded",
                "version": __version__, "modules": statuses}

    def list_modules(self):
        return self._registry.status()

    def get_module(self, name):
        cls = self._registry.get(name)
        return cls.health() if cls else None

    def reload_module(self, name):
        mod = self._registry.get(name)
        if mod is None:
            return {"ok": False, "error": f"Module '{name}' not found"}
        success = self._registry.reload_module(name)
        return {"ok": success, "module": name, "health": mod.health()}

    def reload_all_modules(self):
        results = self._registry.reload_all()
        return {"ok": all(results.values()), "results": results}

    def start_watcher(self, interval=2.0):
        self._registry.start_watcher(interval=interval, server=self)
        return {"ok": True, "interval": interval}

    def stop_watcher(self):
        self._registry.stop_watcher()
        return {"ok": True}

    def get_config_path(self):
        return self._config_path

    # ── Delegation methods (compat: route_handlers calls get_server().xxx()) ──

    def list_tasks(self):
        """Delegate to StorageModule."""
        from .modules.storage_module import StorageModule
        return StorageModule.list_tasks()

    def create_task(self, name, command, schedule):
        from .modules.storage_module import StorageModule
        return StorageModule.create_task(name, command, schedule)

    def delete_task(self, task_id):
        from .modules.storage_module import StorageModule
        return StorageModule.delete_task(task_id)

    def get_config_info(self):
        from .modules.agent_module import AgentModule
        return AgentModule.get_config_info()

    def update_config(self, updates):
        from .modules.agent_module import AgentModule
        return AgentModule.update_config(updates)

    def switch_config(self, config_path):
        from .modules.agent_module import AgentModule
        return AgentModule.switch_config(config_path)

    def list_config_files(self, check_valid=False):
        from .modules.agent_module import AgentModule
        return AgentModule.list_config_files(check_valid)

    def create_config_file(self, **kwargs):
        from .modules.agent_module import AgentModule
        return AgentModule.create_config_file(**kwargs)

    def _get_storage(self):
        from .modules.storage_module import StorageModule
        return StorageModule.get_storage()

    def get_agent(self):
        from .modules.agent_module import AgentModule
        return AgentModule.get_agent()

    def switch_model(self, *args, **kwargs):
        from .modules.agent_module import AgentModule
        return AgentModule.switch_model(*args, **kwargs)

    def list_sessions(self, limit=20):
        from .modules.storage_module import StorageModule
        return StorageModule.list_topics(limit)

    def create_topic_session(self, title="API"):
        from .modules.storage_module import StorageModule
        return StorageModule.create_topic(title)

    def get_session(self, topic_id):
        from .modules.storage_module import StorageModule
        return StorageModule.get_topic(topic_id)

    def delete_session(self, topic_id):
        from .modules.storage_module import StorageModule
        return StorageModule.delete_topic(topic_id)

    def rename_topic(self, topic_id, new_title):
        from .modules.storage_module import StorageModule
        return StorageModule.rename_topic(topic_id, new_title)

    def get_topic_info(self, topic_id):
        from .modules.storage_module import StorageModule
        return StorageModule.get_topic_info(topic_id)

    def get_topic_conversations(self, topic_id, limit=0):
        from .modules.storage_module import StorageModule
        return StorageModule.get_topic_conversations(topic_id, limit)

    def get_session_messages(self, topic_id, limit=50):
        from .modules.storage_module import StorageModule
        return StorageModule.get_session_messages(topic_id, limit)

    def list_memories(self, limit=50):
        from .modules.storage_module import StorageModule
        return StorageModule.list_memories(limit)

    def create_memory(self, content, category="general", priority=2):
        from .modules.storage_module import StorageModule
        return StorageModule.create_memory(content, category, priority)

    def delete_memory(self, mem_id):
        from .modules.storage_module import StorageModule
        return StorageModule.delete_memory(mem_id)

    def search(self, query, limit=20):
        from .modules.storage_module import StorageModule
        return StorageModule.search(query, limit)

    def list_tools(self):
        from .modules.toolkit_module import ToolkitModule
        return ToolkitModule.list_tools()

    def run_tool(self, tool_name, arguments):
        from .modules.toolkit_module import ToolkitModule
        return ToolkitModule.run_tool(tool_name, arguments)

    def create_session(self, config_path=None):
        from .modules.agent_module import AgentModule
        return AgentModule.create_session(config_path)

    def chat_completion(self, *args, **kwargs):
        from .modules.agent_module import AgentModule
        return AgentModule.chat_completion(*args, **kwargs)

    def chat_completion_stream(self, *args, **kwargs):
        from .modules.agent_module import AgentModule
        return AgentModule.chat_completion_stream(*args, **kwargs)

    def screenshot_region(self, x, y, w, h):
        return _capture_and_encode("region", f"{x},{y},{w},{h}")

    def screenshot_full(self):
        return _capture_and_encode("full")

    # ── Route hot-reload ──

    def rebuild_routes(self):
        """Hot-reload all routes without restarting the server.

        Reloads the route_handlers module (fresh handler references),
        clears the Starlette app's existing routes, and re-registers
        all routes. Use after editing route_handlers.py or server.py.
        """
        import importlib
        import sys

        mod_name = "tea_agent.server.route_handlers"
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])

        if not self._app:
            return {"ok": False, "error": "App not initialized"}

        # Clear existing routes (Starlette Router internal list)
        self._app._routes.clear()

        # Re-build and register fresh routes with new handler refs
        routes = _build_routes()
        self._app._routes.extend(routes)

        logger.info(f"Routes hot-reloaded: {len(routes)} routes registered")
        return {"ok": True, "route_count": len(routes)}


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
        Route("/", rh.handle_web_root),
        Route("/api/chat", rh.handle_web_chat, methods=["POST"]),
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
        Route("/api/sessions", rh.handle_web_sessions),
        Route("/api/topic/{topic_id:str}", rh.handle_web_topic_info, methods=["GET", "PUT", "DELETE"]),
        Route("/api/topic/{topic_id:str}/status", rh.handle_web_topic_status),
        Route("/api/topic/{topic_id:str}/stream-buffer", rh.handle_web_topic_stream_buffer),
        Route("/api/topic/{topic_id:str}/conversations", rh.handle_web_topic_conversations),
        Route("/api/topic/{topic_id:str}/todos", rh.handle_web_topic_todos),
        Route("/api/topic/{topic_id:str}/todos/{idx:int}", rh.handle_web_topic_todo_update, methods=["PUT"]),
        Route("/api/topic/{topic_id:str}/plans", rh.handle_web_topic_plans),
        Route("/api/tools", rh.handle_web_tools),
        Route("/api/config", rh.handle_web_config),
        Route("/api/config", rh.handle_web_update_config, methods=["PUT"]),
        Route("/api/configs", rh.handle_web_list_configs),
        Route("/api/config/create", rh.handle_web_create_config, methods=["POST"]),
        Route("/api/model", rh.handle_web_model_info),
        Route("/api/model", rh.handle_web_model_switch, methods=["POST"]),
        Route("/api/model/config", rh.handle_web_model_config, methods=["POST"]),
        Route("/api/config/upload", rh.handle_web_upload_config, methods=["POST"]),
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
        Route("/api/asr/status", rh.handle_asr_status),
        Route("/api/asr/transcribe", rh.handle_asr_transcribe, methods=["POST"]),
        WebSocketRoute("/api/asr/ws", rh.handle_asr_ws),
        Route("/health", rh.handle_health),
        Route("/v1/chat/completions", rh.handle_chat_completions, methods=["POST"]),
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


def create_app(api_key=None, config_path=None):
    """Create the Starlette application (thin — logic in modules)."""
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("api_server").setLevel(logging.INFO)

    global _server_instance
    _server_instance = MinimalServer(api_key=api_key or "",
                                     config_path=config_path or "")
    results = _server_instance.load_modules()
    ok_count = sum(1 for v in results.values() if v)
    logger.info(f"Modules loaded: {ok_count}/{len(results)}")

    routes = _build_routes()

    app = Starlette(debug=False, routes=routes)
    _server_instance._app = app

    # API Key auth
    server_api_key = _server_instance._api_key
    if server_api_key:
        _SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/", "/static"}

        class AuthMiddleware:
            def __init__(self, app, api_key):
                self.app = app
                self.api_key = api_key

            async def __call__(self, scope, receive, send):
                if scope["type"] != "http":
                    await self.app(scope, receive, send)
                    return
                path = scope.get("path", "")
                if path in _SKIP_PATHS or path.startswith("/static"):
                    await self.app(scope, receive, send)
                    return
                headers = dict(scope.get("headers", []))
                a = headers.get(b"authorization", b"").decode()
                x = headers.get(b"x-api-key", b"").decode()
                token = a[7:] if a.startswith("Bearer ") else x
                if token != self.api_key:
                    r = JSONResponse({"error": "Unauthorized"}, status_code=401)
                    await r(scope, receive, send)
                    return
                await self.app(scope, receive, send)

        app.add_middleware(AuthMiddleware, api_key=server_api_key)
        logger.info("API Key auth middleware enabled")

    logger.info(f"API Server initialized | v{__version__}")
    return app


def get_server():
    global _server_instance
    return _server_instance


def run_server(host="127.0.0.1", port=8282,
               api_key=None, config_path=None, open_browser=False):
    try:
        import uvicorn
    except ImportError:
        raise ImportError("pip install starlette uvicorn")

    actual_config = config_path or os.environ.get("TEA_CONFIG", "")
    if not actual_config:
        default_cfg = os.path.join(os.path.expanduser("~"), ".tea_agent", "config.yaml")
        actual_config = default_cfg if os.path.isfile(default_cfg) else "(built-in default)"

    app = create_app(api_key=api_key, config_path=config_path)

    server_url = f"http://{host}:{port}"
    print("=" * 56)
    print(f"  Tea Agent Server v{__version__}")
    print(f"  Listening on:  {server_url}")
    print(f"  API Docs:      {server_url}/docs")
    print(f"  Config file:   {actual_config}")
    print(f"  API Key:       {'ENABLED' if api_key else 'DISABLED'}")
    print("  Hot-Reload:    ENABLED  (/api/modules)")
    print("=" * 56)

    if open_browser:
        import threading as _th
        import time as _time
        import webbrowser as _wb
        _th.Thread(target=lambda: (_time.sleep(1.5), _wb.open(server_url)),
                   daemon=True).start()

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    global _uvicorn_server, _restart_args
    _uvicorn_server = uvicorn.Server(config)
    _restart_args = [m for m in ["-m", "tea_agent.server", "--host", str(host),
                                  "--port", str(port), "--config", config_path or "",
                                  "--api-key", api_key or ""] if m]
    try:
        _uvicorn_server.run()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def main():
    """CLI entry point."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="Tea Agent Server")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8282)
    parser.add_argument("--api-key", type=str, default="")
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()

    config_path = args.config or os.path.join(
        os.path.expanduser("~"), ".tea_agent", "config.yaml")

    if not os.path.isfile(config_path):
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    from tea_agent.config import load_config
    try:
        cfg = load_config(config_path)
        if not cfg.main_model.is_configured:
            print(f"Error: Config file '{config_path}' is invalid!")
            sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to load config: {e}")
        sys.exit(1)

    run_server(host=args.host, port=args.port,
               api_key=args.api_key or None,
               config_path=config_path,
               open_browser=args.browser)


if __name__ == "__main__":
    main()
