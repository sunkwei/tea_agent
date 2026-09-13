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

from tea_agent import __version__
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

_server_instance = None
_uvicorn_server = None
_restart_args: list[str] = []
_restart_requested = False


def _build_restart_args(host: str, port: int, config_path: str | None = None,
                        api_key: str | None = None) -> list[str]:
    """构建重启子进程的参数列表（成对构建，避免空值留下悬空 flag）。

    回归背景（实测）：旧实现用
    ``[m for m in [... "--config", config_path or "", "--api-key", api_key or ""] if m]``
    过滤空串 —— flag 被保留而值被丢弃，config/api_key 为空时产生
    ``--config --api-key``，新进程 argparse 直接报错退出，重启静默失效。
    """
    args = ["-m", "tea_agent.server", "--host", str(host), "--port", str(port)]
    if config_path:
        args += ["--config", str(config_path)]
    if api_key:
        args += ["--api-key", str(api_key)]
    return args


def _port_free(host: str, port: int) -> bool:
    """端口是否已释放（能 bind 即视为空闲）。"""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host or "127.0.0.1", int(port)))
        except OSError:
            return False
    return True


def _wait_port_free(host: str, port: int, timeout: float = 10.0) -> bool:
    """等待端口释放，超时返回 False。"""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_free(host, port):
            return True
        time.sleep(0.1)
    return _port_free(host, port)


def _wait_ready(host: str, port: int, timeout: float = 20.0) -> bool:
    """轮询 /health 直到新进程返回 2xx，判定就绪。"""
    import time
    import urllib.error
    import urllib.request

    url = f"http://{host or '127.0.0.1'}:{port}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 300:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.25)
    return False


def _spawn_successor(host: str, port: int, attempts: int = 3,
                     wait_ready: float = 20.0) -> bool:
    """端口释放后拉起新进程并探测就绪；未就绪则终止子进程重试。"""
    import subprocess
    import sys

    args = list(_restart_args) or ["-m", "tea_agent.server"]
    for attempt in range(1, attempts + 1):
        if not _wait_port_free(host, port, timeout=10.0):
            logger.error("restart: 端口 %s:%s 未释放（第 %d 次尝试）", host, port, attempt)
            continue
        try:
            proc = subprocess.Popen(
                [sys.executable, *args],
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except OSError as e:
            logger.error("restart: 拉起新进程失败（第 %d 次）：%s", attempt, e)
            continue
        if _wait_ready(host, port, timeout=wait_ready):
            logger.info("restart: 新进程就绪 pid=%s（第 %d 次尝试）", proc.pid, attempt)
            return True
        logger.error("restart: 新进程未就绪 pid=%s，终止并重试", proc.pid)
        try:
            proc.terminate()
        except OSError:
            pass
    logger.error("restart: 连续 %d 次拉起失败，服务可能未恢复", attempts)
    return False


def _inflight_turns() -> int:
    """当前在途回合数（活跃会话 + 后台会话）。"""
    try:
        from tea_agent.server.modules import state
    except ImportError:
        return 0
    with state.active_sessions_lock:
        count = len(state.active_sessions)
    with state.background_sessions_lock:
        count += len(state.background_sessions)
    return count


def _drain_then_exit(wait_seconds: float) -> None:
    """等待在途回合结束（有界）后置 should_exit，避免中途切断 SSE 流。"""
    import time

    if _uvicorn_server is None:
        return
    deadline = time.monotonic() + max(0.0, wait_seconds)
    drained = _inflight_turns() == 0
    while not drained and time.monotonic() < deadline:
        time.sleep(0.2)
        drained = _inflight_turns() == 0
    if not drained:
        logger.warning("restart: 等待在途回合超时（%ss），强制退出", wait_seconds)
    _uvicorn_server.should_exit = True


def restart_server(graceful: bool = True, wait_seconds: float = 120.0) -> dict:
    """请求重启当前进程：旧进程先退出释放端口，再由 run_server 收尾拉起新进程。

    旧实现的缺陷（实测）：先 Popen 新进程、后置 should_exit —— 新进程在旧进程仍
    占用端口时 bind 失败即退出；重启参数又用 [m for m in [...] if m] 构造，config/
    api_key 为空时留下悬空 flag，新进程 argparse 直接报错。两者叠加使重启静默失效。

    本实现：graceful 时先等待在途回合结束（上限 wait_seconds）再退出，端口经
    _wait_port_free 确认释放后才拉起新进程，并做 /health 就绪探测与失败重试。

    Args:
        graceful: True=等在途回合结束再退出；False=立即退出。
        wait_seconds: graceful 模式下等待在途回合的上限秒数。

    Returns:
        {"ok": True, ...} 或 {"ok": False, "error": ...}（同时仅允许一个重启在途）。
    """
    global _restart_requested
    if _uvicorn_server is None:
        return {"ok": False, "error": "Server not running"}
    if _restart_requested:
        return {"ok": False, "error": "Restart already in progress"}
    _restart_requested = True

    if graceful:
        import threading

        # 排空期间新回合改为排队，避免「刚启动的回合」被 should_exit 切断
        try:
            from tea_agent.server.modules.state import set_draining

            set_draining(True)
        except ImportError:
            logger.warning("restart: 无法置位 draining 标志（state 模块缺失）")

        in_flight = _inflight_turns()
        threading.Thread(target=_drain_then_exit, args=(wait_seconds,),
                         daemon=True, name="tea-restart-drain").start()
        return {"ok": True, "message": "Restart initiated (graceful)",
                "mode": "graceful", "draining": True,
                "wait_seconds": wait_seconds, "inflight_turns": in_flight}

    _uvicorn_server.should_exit = True
    return {"ok": True, "message": "Restart initiated (immediate)",
            "mode": "immediate", "draining": False}


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

    def get_model_service(self):
        """ProviderService 单例（模型管理：提供商/模型查询/自定义供应商）。"""
        from tea_agent.model_manager import get_provider_service
        return get_provider_service(self.get_config_path())

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

    def get_topic_trajectory(self, topic_id, limit=0):
        from .modules.storage_module import StorageModule
        return StorageModule.get_topic_trajectory(topic_id, limit)

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
        Route("/api/sessions", rh.handle_web_sessions),
        Route("/api/topic/{topic_id:str}", rh.handle_web_topic_info, methods=["GET", "PUT", "DELETE"]),
        Route("/api/topic/{topic_id:str}/status", rh.handle_web_topic_status),
        Route("/api/topic/{topic_id:str}/stream-buffer", rh.handle_web_topic_stream_buffer),
        Route("/api/topic/{topic_id:str}/conversations", rh.handle_web_topic_conversations),
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
        Route("/v1/upload", rh.handle_upload, methods=["POST"]),
        Route("/api/dags", rh.handle_list_dags),
        Route("/dag/{viz_id:str}", rh.handle_dag_viz),
        Route("/dag/{viz_id:str}/events", rh.handle_dag_sse),
        Route("/dag/{viz_id:str}/status", rh.handle_dag_status),
        Route("/dag/{viz_id:str}/image", rh.handle_dag_image),
        # ── Pi Features（会话树/消息队列/手动压缩） ──
        Route("/api/pi/tree/{topic_id:str}", rh.handle_pi_tree),
        Route("/api/pi/tree/{topic_id:str}/branch", rh.handle_pi_tree_branch, methods=["POST"]),
        Route("/api/pi/tree/{topic_id:str}/switch", rh.handle_pi_tree_switch, methods=["POST"]),
        Route("/api/pi/tree/{topic_id:str}/summary", rh.handle_pi_tree_summary),
        Route("/api/pi/tree/{topic_id:str}/append", rh.handle_pi_tree_append, methods=["POST"]),
        Route("/api/pi/queue/{topic_id:str}", rh.handle_pi_queue_push, methods=["POST"]),
        Route("/api/pi/queue/{topic_id:str}", rh.handle_pi_queue_status),
        Route("/api/pi/queue/{topic_id:str}", rh.handle_pi_queue_clear, methods=["DELETE"]),
        Route("/api/pi/compact/{topic_id:str}", rh.handle_pi_compact, methods=["POST"]),
        Route("/api/pi/stats", rh.handle_pi_stats),
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

    # ── 终端静音：控制台只保留 WARNING+，INFO 类杂音（模块加载/httpx/embedding/
    #    memory/session 等）不再输出；文件日志（~/.tea_agent/tea_agent.log）不受影响。
    #    实现要点：
    #    1) 必须先 setup_logging() 确保 console handler 已创建——Agent 初始化
    #       （load_modules 内）才创建 handler，届时再加 filter 就太晚了；
    #    2) Filter 必须加在 handler 上——子 logger 传播的记录只经过 handler 的
    #       filter，root logger 的 filter 仅过滤 root 自身 emit 的记录，对传播无效；
    #    3) 排除 TimedRotatingFileHandler（继承自 StreamHandler），避免误伤文件日志。
    try:
        from tea_agent.logging_setup import setup_logging
        setup_logging(debug=False)
    except Exception:
        pass
    _root = logging.getLogger()
    if not getattr(_root, "_tea_server_quiet", False):
        class _ServerQuietFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                return record.levelno >= logging.WARNING

        for _h in list(_root.handlers):
            if isinstance(_h, logging.StreamHandler) \
               and not isinstance(_h, logging.handlers.TimedRotatingFileHandler):
                _h.addFilter(_ServerQuietFilter())
        _root._tea_server_quiet = True
    logging.getLogger("api_server").setLevel(logging.INFO)

    global _server_instance
    _server_instance = MinimalServer(api_key=api_key or "",
                                     config_path=config_path or "")
    results = _server_instance.load_modules()
    ok_count = sum(1 for v in results.values() if v)
    logger.info(f"Modules loaded: {ok_count}/{len(results)}")

    # 预热 jieba 分词器（首次调用会直接 print 到 stdout/stderr 污染控制台）
    try:
        import contextlib
        import io as _io

        with contextlib.redirect_stdout(_io.StringIO()), contextlib.redirect_stderr(_io.StringIO()):
            import jieba

            jieba.initialize()
    except Exception:
        pass

    routes = _build_routes()

    app = Starlette(debug=False, routes=routes)
    _server_instance._app = app

    # API Key auth
    server_api_key = _server_instance._api_key
    if server_api_key:
        skip_paths = {"/health", "/docs", "/openapi.json", "/", "/static"}

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
    # banner 是 server 唯一终端输出；flush=True 确保非 TTY（管道/重定向）下立即可见
    print("=" * 56, flush=True)
    print(f"  Tea Agent Server v{__version__}", flush=True)
    print(f"  Listening on:  {server_url}", flush=True)
    print(f"  API Docs:      {server_url}/docs", flush=True)
    print(f"  Config file:   {actual_config}", flush=True)
    print(f"  API Key:       {'ENABLED' if api_key else 'DISABLED'}", flush=True)
    print("  Hot-Reload:    ENABLED  (/api/modules)", flush=True)
    print("=" * 56, flush=True)

    if open_browser:
        import threading as _th
        import time as _time
        import webbrowser as _wb
        _th.Thread(target=lambda: (_time.sleep(1.5), _wb.open(server_url)),
                   daemon=True).start()

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    global _uvicorn_server, _restart_args
    _uvicorn_server = uvicorn.Server(config)
    _restart_args = _build_restart_args(host, port, config_path, api_key)

    # 启动恢复：上次崩溃/重启时仍在途的回合 → 重建缓冲区供前端续读；
    # 已排队但未开始的消息 → 重新入队，避免重启丢消息
    try:
        from tea_agent.server.modules import state as _state
        from tea_agent.server.turn_snapshot import rebuild_buffers

        _resumed = rebuild_buffers(state_module=_state)
        if _resumed:
            logger.warning("restart recovery: %d in-flight turn(s) restored: %s",
                           len(_resumed), ", ".join(_resumed))
        _requeued = _state.restore_queues()
        if _requeued:
            logger.info("restart recovery: %d queued message(s) restored", _requeued)
    except ImportError:
        logger.warning("restart recovery skipped (modules unavailable)")
    try:
        _uvicorn_server.run()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        # 端口随 uvicorn 退出而释放，此处再拉起新进程（顺序反了会 bind 失败）
        if _restart_requested:
            _spawn_successor(host, port)


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
        if args.config:
            # 用户显式指定路径但不存在 → 报错，不启动向导
            print(f"Error: Config file not found: {config_path}")
            sys.exit(1)
        # 首次运行：启动交互式配置向导引导输入主模型 url/key 等
        from tea_agent.setup_wizard import run_setup_wizard
        print("\n检测到首次运行：未找到配置文件，启动配置向导...\n")
        created = run_setup_wizard(config_path)
        if not created:
            print("\n配置向导已取消，Server 退出。")
            sys.exit(1)
        config_path = created

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
