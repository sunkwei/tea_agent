!/usr/bin/env python
"""
Multi-Agent 辩论赛 — 双 Session 对抗辩论服务器。

启动:  python demo/multi_agent/server.py [--port 8083]

特点:
- 左右两个独立 Agent，各自使用不同配置/模型
- 实时 SSE 流式推送每轮辩论
- 50 轮循环对抗
- 完整上下文传递，对方观点始终可见
"""

import asyncio
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

# 确保 tea_agent 在 path 中
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from tea_agent.onlinesession import OnlineToolSession
from tea_agent.store import Storage, get_storage

# ── 复用已有的配置缓存和 Session 工厂 ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tea_agent" / "server"))
from server import _load_config_cached, _create_session_from_cfg, _ChatAgentProxy

logger = logging.getLogger("debate_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

MAX_ROUNDS = 50
DEBATE_SYSTEM_PROMPT = """你是一个辩论赛选手。你将参与一场多轮辩论。
- 对方刚才的发言会以 "[对方]" 前缀提供
- 你需要针对对方观点进行反驳、补充或回应
- 保持逻辑清晰、有理有据
- 如果对方有逻辑漏洞，请指出
- 如果同意对方某观点，可以承认并深化
- 不要简单重复之前的论据
- 回复控制在 300 字以内"""

INIT_SYSTEM_PROMPT = """你是一个辩论赛选手。这是辩论的第一轮，你需要开篇立论。
- 清晰陈述你的核心观点
- 给出 2-3 个支持论据
- 回复控制在 300 字以内"""


class DebateServer:
    """双 Agent 辩论服务器"""

    def __init__(self):
        self._storage: Optional[Storage] = None
        self._toolkit = None
        self._debates: dict[str, "DebateSession"] = {}

    def _get_storage(self) -> Storage:
        if self._storage is None:
            self._storage = get_storage()
        return self._storage

    def _get_toolkit(self):
        if self._toolkit is None:
            from tea_agent import tlk
            cfg = _load_config_cached(None)
            tool_dir = str(Path(cfg.paths.toolkit_dir_abs))
            Path(tool_dir).mkdir(parents=True, exist_ok=True)
            self._toolkit = tlk.Toolkit(tool_dir)
            tlk.toolkit = self._toolkit
            logger.info(f"Toolkit ready: {len(self._toolkit.func_map)} tools")
        return self._toolkit

    def create_session(self, config_path: Optional[str] = None):
        """为辩论方创建独立的 OnlineToolSession"""
        cfg = _load_config_cached(config_path)
        toolkit = self._get_toolkit()
        session = _create_session_from_cfg(cfg, toolkit, storage=None)
        logger.info(f"Session created: {cfg.main_model.model_name} @ {cfg.main_model.api_url}")
        return session

    def list_config_files(self):
        """扫描可用的配置文件"""
        configs_dir = Path.home() / ".tea_agent"
        if not configs_dir.exists():
            return []
        results = []
        for fpath in sorted(configs_dir.glob("*.yaml")):
            try:
                cfg = _load_config_cached(str(fpath))
                results.append({
                    "path": str(fpath),
                    "filename": fpath.name,
                    "model": cfg.main_model.model_name or "unknown",
                })
            except Exception:
                pass
        return results

    def run_debate_sync(self, debate_id: str, queue: asyncio.Queue, event_loop):
        """运行辩论主循环（同步版本，在独立线程中执行）"""
        debate = self._debates.get(debate_id)
        if not debate:
            return

        def _put(event: dict):
            try:
                event_loop.call_soon_threadsafe(lambda: queue.put_nowait(event))
            except Exception:
                pass

        try:
            left_session = self.create_session(debate.left_config)
            right_session = self.create_session(debate.right_config)

            _put({"type": "status", "text": f"🟢 辩论开始！主题: {debate.topic}",
                  "round": 0, "max_rounds": MAX_ROUNDS})
            _put({"type": "meta", "left_model": debate.left_model_name,
                  "right_model": debate.right_model_name})

            # ── 第 1 轮：左方立论 ──
            _put({"type": "round_start", "round": 1, "speaker": "left",
                  "label": "🔵 甲方 开篇立论"})

            left_prompt = f"辩论主题: {debate.topic}\n\n请就以上主题发表你的开篇立论。"

            left_text = _sync_chat(left_session, left_prompt, INIT_SYSTEM_PROMPT)
            if left_text.startswith("API调用错误") or left_text.startswith("（发言失败"):
                _put({"type": "error", "error": f"甲方发言失败: {left_text}"})
                return
            debate.add_round(1, "left", left_text)
            _put({"type": "round_done", "round": 1, "speaker": "left",
                  "text": left_text})

            # ── 循环 49 轮 ──
            for rnd in range(2, MAX_ROUNDS + 1):
                if debate.cancelled:
                    _put({"type": "cancelled", "text": "辩论已终止"})
                    return

                # 确定本轮发言方
                if rnd % 2 == 0:
                    speaker = "right"
                    label = f"🔴 乙方 第{rnd}轮反驳"
                    opponent_text = debate.rounds[-1]["text"]
                    opponent_name = "甲方"
                else:
                    speaker = "left"
                    label = f"🔵 甲方 第{rnd}轮回击"
                    opponent_text = debate.rounds[-1]["text"]
                    opponent_name = "乙方"

                _put({"type": "round_start", "round": rnd, "speaker": speaker,
                      "label": label})

                # 构建上下文（最近几轮 + 当前对方发言）
                history = _build_debate_context(debate.rounds, current_speaker=speaker,
                                                 topic=debate.topic, max_history=6)
                prompt = f"{history}\n\n[对方({opponent_name})刚才说]:\n{opponent_text}\n\n请针对以上发言进行反驳或回应。"

                session = left_session if speaker == "left" else right_session
                response_text = _sync_chat(session, prompt, DEBATE_SYSTEM_PROMPT)
                if response_text.startswith("API调用错误") or response_text.startswith("（发言失败"):
                    _put({"type": "error",
                          "error": f"{'甲方' if speaker=='left' else '乙方'}发言失败 (第{rnd}轮): {response_text}"})
                    break
                debate.add_round(rnd, speaker, response_text)

                _put({"type": "round_done", "round": rnd, "speaker": speaker,
                      "text": response_text})

            _put({"type": "debate_done", "total_rounds": MAX_ROUNDS,
                  "rounds": debate.rounds})

        except Exception as e:
            logger.exception(f"Debate error: {e}")
            _put({"type": "error", "error": str(e)})
        finally:
            # 清理
            for s in [left_session, right_session]:
                try:
                    if hasattr(s, 'close'):
                        s.close()
                except Exception:
                    pass


def _sync_chat(session: OnlineToolSession, user_message: str,
               system_prompt_override: str = "") -> str:
    """同步对话，直接返回 AI 文本（不使用工具调用）。"""
    # 临时替换 system prompt
    old_messages = session.messages[:]
    if system_prompt_override:
        session.messages = [{"role": "system", "content": system_prompt_override}]

    result_text = ""

    def cb(text: str):
        nonlocal result_text
        if text and not text.startswith("[TOOL") and not text.startswith("[THINK"):
            result_text += text

    try:
        ai_msg, _ = session.chat_stream(user_message, callback=cb, topic_id="")
        return ai_msg or result_text or "（无响应）"
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return f"（发言失败: {e}）"
    finally:
        # 恢复 messages（避免污染）
        session.messages = old_messages


def _build_debate_context(rounds: list, current_speaker: str,
                           topic: str, max_history: int = 6) -> str:
    """构建辩论上下文，包含最近几轮和主题"""
    recent = rounds[-max_history:] if len(rounds) > max_history else rounds
    lines = [f"辩论主题: {topic}", ""]
    for r in recent:
        name = "甲方" if r["speaker"] == "left" else "乙方"
        lines.append(f"--- 第{r['round']}轮 [{name}] ---")
        lines.append(r["text"])
        lines.append("")
    return "\n".join(lines)


class DebateSession:
    """辩论会话元数据"""

    def __init__(self, debate_id: str, topic: str,
                 left_config: str, left_model_name: str,
                 right_config: str, right_model_name: str):
        self.debate_id = debate_id
        self.topic = topic
        self.left_config = left_config
        self.left_model_name = left_model_name
        self.right_config = right_config
        self.right_model_name = right_model_name
        self.rounds: list = []
        self.cancelled = False
        self.created_at = time.time()

    def add_round(self, rnd: int, speaker: str, text: str):
        self.rounds.append({"round": rnd, "speaker": speaker, "text": text})


# ═══════════════════════════════════════════════
#  HTTP Server
# ═══════════════════════════════════════════════

from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse, FileResponse, HTMLResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

_server: Optional[DebateServer] = None


def get_server() -> DebateServer:
    global _server
    if _server is None:
        _server = DebateServer()
    return _server


async def handle_root(request):
    """GET / — 提供辩论 UI"""
    index_path = Path(__file__).parent / "static" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return HTMLResponse("<h1>Multi-Agent Debate</h1><p>index.html not found</p>")


async def handle_configs(request):
    """GET /api/configs — 列出可用配置"""
    configs = get_server().list_config_files()
    # 也检查默认配置
    from tea_agent.config import load_config
    try:
        default_cfg = load_config(None)
        configs.insert(0, {
            "path": "",
            "filename": "(默认配置)",
            "model": default_cfg.main_model.model_name or "unknown",
        })
    except Exception:
        pass
    return JSONResponse({"configs": configs})


async def handle_start_debate(request):
    """POST /api/debate/start — 启动辩论"""
    body = await request.json()
    topic = (body.get("topic") or "").strip()
    left_config = body.get("left_config") or None
    right_config = body.get("right_config") or None

    if not topic:
        return JSONResponse({"error": "请填写辩论主题"}, status_code=400)

    debate_id = uuid.uuid4().hex[:8]
    server = get_server()

    # 获取模型名用于显示
    left_cfg = _load_config_cached(left_config) if left_config else _load_config_cached(None)
    right_cfg = _load_config_cached(right_config) if right_config else _load_config_cached(None)

    debate = DebateSession(
        debate_id=debate_id, topic=topic,
        left_config=left_config or "", left_model_name=left_cfg.main_model.model_name,
        right_config=right_config or "", right_model_name=right_cfg.main_model.model_name,
    )
    server._debates[debate_id] = debate

    queue: asyncio.Queue = asyncio.Queue()
    event_loop = asyncio.get_running_loop()

    async def event_stream():
        # 在后台线程中同步运行辩论
        thread = threading.Thread(
            target=server.run_debate_sync,
            args=(debate_id, queue, event_loop),
            daemon=True,
        )
        thread.start()

        while True:
            event = await queue.get()
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            if event.get("type") in ("debate_done", "error", "cancelled"):
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def handle_cancel(request):
    """POST /api/debate/cancel — 取消辩论"""
    body = await request.json()
    debate_id = (body.get("debate_id") or "").strip()
    server = get_server()
    debate = server._debates.get(debate_id)
    if debate:
        debate.cancelled = True
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "Debate not found"}, status_code=404)


def create_app():
    global _server
    _server = DebateServer()

    static_dir = str(Path(__file__).parent / "static")
    routes = [
        Route("/", endpoint=handle_root),
        Route("/api/configs", endpoint=handle_configs),
        Route("/api/debate/start", endpoint=handle_start_debate, methods=["POST"]),
        Route("/api/debate/cancel", endpoint=handle_cancel, methods=["POST"]),
        Mount("/static", app=StaticFiles(directory=static_dir), name="static"),
    ]
    return Starlette(debug=False, routes=routes)


def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Multi-Agent Debate Server")
    parser.add_argument("--port", type=int, default=8083, help="HTTP 端口 (默认 8083)")
    args = parser.parse_args()

    app = create_app()
    logger.info(f"Debate Server: http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
