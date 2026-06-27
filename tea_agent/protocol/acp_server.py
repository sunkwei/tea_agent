"""ACP Protocol Server"""
import asyncio, json, logging, os, threading, time, uuid
from typing import Optional, List, Dict, Any
logger = logging.getLogger("acp_server")
try:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route
except ImportError:
    raise ImportError("pip install starlette uvicorn")
from tea_agent.agent import Agent
__version__ = "0.1.0"
class ACPProtocolServer:
    def __init__(self, config_path=None, api_key=""):
        self._agent = None
        self._config_path = config_path
        self._api_key = api_key or os.environ.get("TEA_API_KEY", "")
        self._lock = threading.Lock()
        self._agent_id = "tea-agent"
        self._start_time = time.time()
    def get_agent(self):
        if self._agent is None:
            self._agent = Agent(mode="lightweight", config_path=self._config_path)
        return self._agent
    def discover_agents(self):
        return {"object": "list", "data": [{"id": self._agent_id, "name": "Tea Agent", "description": "Self-evolving AI coding agent", "capabilities": {"streaming": True, "tool_execution": True}}]}
    def get_agent_info(self):
        try:
            agent = self.get_agent()
            tools = []
            for name, meta in agent.toolkit.meta_map.items():
                fn = meta.get("function", {})
                tools.append({"name": fn.get("name", name), "description": fn.get("description", ""), "input_schema": fn.get("parameters", {})})
            return {"id": self._agent_id, "name": "Tea Agent", "tools": tools, "capabilities": {"streaming": True, "tool_execution": True}}
        except Exception as e:
            return {"id": self._agent_id, "name": "Tea Agent", "error": str(e)}

    def chat(self, messages, stream=False, model=""):
        agent = self.get_agent()
        user_msg = messages[-1]["content"] if messages else ""
        with self._lock:
            if not agent.current_topic_id:
                agent.current_topic_id = agent.db.create_topic("ACP会话")
            collected = []
            def cb(text):
                if text and not text.startswith("["): collected.append(text)
            ai_msg, used_tools = agent.sess.chat_stream(user_msg, callback=cb, topic_id=agent.current_topic_id)
            full = "".join(collected) or ai_msg
        return {"id": f"chat-{uuid.uuid4().hex[:12]}", "agent_id": self._agent_id, "choices": [{"index": 0, "message": {"role": "assistant", "content": full}, "finish_reason": "stop"}], "tools_used": used_tools or []}

    async def chat_stream(self, messages, model=""):
        agent = self.get_agent()
        user_msg = messages[-1]["content"] if messages else ""
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        def put(event):
            try: loop.call_soon_threadsafe(lambda: queue.put_nowait(event))
            except Exception: pass
        def cb(text):
            if text.startswith("["): return
            put({"type": "content", "text": text})
        thread = threading.Thread(target=self._run_stream, args=(agent, user_msg, cb, put), daemon=True)
        thread.start()
        cid = f"chat-{uuid.uuid4().hex[:12]}"
        now = int(time.time())
        yield f"data: {json.dumps(dict(id=cid, object='chat.chunk', created=now, choices=[dict(index=0, delta=dict(role='assistant'), finish_reason=None)]))}\n\n"
        while True:
            event = await queue.get()
            if event["type"] == "content":
                yield f"data: {json.dumps(dict(id=cid, object='chat.chunk', created=now, choices=[dict(index=0, delta=dict(content=event['text']), finish_reason=None)]))}\n\n"
            elif event["type"] == "done":
                yield f"data: {json.dumps(dict(id=cid, object='chat.chunk', created=now, choices=[dict(index=0, delta={}, finish_reason='stop')]))}\n\n"
                yield "data: [DONE]\n\n"
                break
            elif event["type"] == "error":
                yield f"data: {json.dumps(dict(error=event['error']))}\n\n"
                yield "data: [DONE]\n\n"
                break

    def _run_stream(self, agent, user_msg, cb, put):
        try:
            with self._lock:
                if not agent.current_topic_id:
                    agent.current_topic_id = agent.db.create_topic("ACP流式")
                ai_msg, used_tools = agent.sess.chat_stream(user_msg, callback=cb, topic_id=agent.current_topic_id)
                put({"type": "done", "ai_msg": ai_msg, "tools_used": used_tools or []})
        except Exception as e:
            put({"type": "error", "error": str(e)})

_server_instance = None

def get_server():
    global _server_instance
    if _server_instance is None:
        _server_instance = ACPProtocolServer()
    return _server_instance

async def handle_health(request):
    return JSONResponse({"status": "ok", "server": "acp", "version": __version__})

async def handle_discover_agents(request):
    return JSONResponse(get_server().discover_agents())

async def handle_agent_info(request):
    return JSONResponse(get_server().get_agent_info())

async def handle_agent_chat(request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    if not messages:
        return JSONResponse({"error": "messages required"}, status_code=400)
    if stream:
        gen = get_server().chat_stream(messages)
        return StreamingResponse(gen, media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
    return JSONResponse(get_server().chat(messages))

def create_app(config_path=None):
    global _server_instance
    _server_instance = ACPProtocolServer(config_path=config_path)
    routes = [
        Route("/health", endpoint=handle_health),
        Route("/v1/agents", endpoint=handle_discover_agents),
        Route("/v1/agents/tea-agent", endpoint=handle_agent_info),
        Route("/v1/agents/tea-agent/chat", endpoint=handle_agent_chat, methods=["POST"]),
    ]
    return Starlette(debug=False, routes=routes)

def run_server(host="127.0.0.1", port=8082, config_path=None):
    try:
        import uvicorn
    except ImportError:
        raise ImportError("pip install uvicorn")
    app = create_app(config_path=config_path)
    logger.info(f"ACP Server: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Tea Agent ACP Server")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, config_path=args.config)

if __name__ == "__main__":
    main()
