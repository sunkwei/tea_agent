"""
Tea Agent GUI2 — 本地 Web 服务 + 浏览器界面。

新一代纯 Web 桌面界面。
采用 tea_agent.server 统一后端，通过 SSE (Server-Sent Events)
实现实时流式对话，交互流畅、零依赖。

特点:
  - 📋 右侧任务面板（Plan + TODO 实时跟踪）
  - 🧠 思维链展示（思考过程 + 工具调用可视化）
  - 🔧 60+ 内置工具，实时显示调用参数和结果
  - 🖼️ 图片上传 / 屏幕截图
  - ⚡ 多配置切换 / 热切换模型
  - 🌓 深色/浅色主题

用法:
    python -m tea_agent.gui2                          # 启动 Web UI 并打开浏览器
    python -m tea_agent.gui2 --config my_agent.yaml    # 指定配置文件
    python -m tea_agent.gui2 --port 8080               # 指定端口
    python -m tea_agent.gui2 --host 0.0.0.0            # 监听所有地址
    python -m tea_agent.gui2 --no-browser              # 不自动打开浏览器
    python -m tea_agent.gui2 --debug                   # 调试模式

架构:
    gui2/
    ├── __init__.py          ← 入口：启动 Starlette 服务 + 打开浏览器
    ├── __main__.py          ← python -m tea_agent.gui2 入口
    ├── server.py            ← Bottle-based 静态文件 + API 代理服务
    └── frontend/            ← 前端静态文件（HTML/JS/CSS）

    后端路由由 tea_agent.server 提供：
    ├── server.py            ← Starlette 应用 + SSE 流式 API
    ├── route_handlers.py    ← 所有 API 路由
    └── static/              ← 前端静态文件（HTML/JS/CSS）

    前端展示 server/static/index.html + app.js + style.css
"""

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

# ── 配置日志 ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gui2")

# ── 确保项目路径 ─────────────────────────────────────────
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _open_browser(url: str, delay: float = 0.8):
    """延迟打开浏览器，等服务器就绪。"""
    import webbrowser

    def _open():
        time.sleep(delay)
        logger.info(f"🌐 打开浏览器: {url}")
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def main():
    """主入口：启动 Starlette Web 服务 + 自动打开浏览器。"""
    parser = argparse.ArgumentParser(
        description="Tea Agent GUI2 — Web 界面",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m tea_agent.gui2
  python -m tea_agent.gui2 --config my_agent.yaml --no-browser
  python -m tea_agent.gui2 --port 8080 --host 0.0.0.0
        """,
    )
    parser.add_argument("--config", type=str, default=None,
                        help="配置文件路径（默认自动查找 config.yaml）")
    parser.add_argument("--port", type=int, default=8080,
                        help="HTTP 服务端口（默认 8080）")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--no-browser", action="store_true",
                        help="不自动打开浏览器")
    parser.add_argument("--debug", action="store_true",
                        help="启用调试模式（输出更多日志）")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("gui2").setLevel(logging.DEBUG)
        logging.getLogger("api_server").setLevel(logging.DEBUG)
        logger.debug("调试模式已启用")

    # ── 抑制 uvicorn 访问日志（太嘈杂） ──
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

    logger.info(f"☕ Tea Agent GUI2 启动中...")
    logger.info(f"   配置: {args.config or '(自动查找)'}")
    logger.info(f"   地址: http://{args.host}:{args.port}")

    # ── 导入 server 模块（延迟加载，避免未安装 starlette/uvicorn 时报错） ──
    try:
        from tea_agent.server.server import create_app
    except ImportError as e:
        logger.error(f"缺少依赖: {e}")
        logger.error("请安装: pip install starlette uvicorn")
        sys.exit(1)

    # ── 创建 Starlette 应用 ──
    app = create_app(config_path=args.config)

    # ── 自动打开浏览器 ──
    if not args.no_browser:
        url = f"http://{args.host}:{args.port}"
        if args.host == "0.0.0.0":
            url = f"http://127.0.0.1:{args.port}"
        _open_browser(url)

    # ── 启动 uvicorn 服务（阻塞，直到 Ctrl+C） ──
    try:
        import uvicorn
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info" if args.debug else "warning",
            access_log=args.debug,
        )
    except KeyboardInterrupt:
        logger.info("👋 GUI2 服务已停止")
    except Exception as e:
        logger.error(f"启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
