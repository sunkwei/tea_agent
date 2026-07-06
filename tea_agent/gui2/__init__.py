"""
Tea Agent GUI2 — pywebview + Bottle + Vanilla JS SPA

现代 WebView 界面，替代老旧的 Tkinter GUI。

用法:
    python -m tea_agent.gui2
"""

import logging as _logging
import os as _os
import sys as _sys
import threading as _threading

_logger = _logging.getLogger('gui2')

# ── 后端服务器 ────────────────────────────────────
# ── WebView 窗口 ──────────────────────────────────
import webview as _webview

from tea_agent.gui2.server import create_gui_server

_window = None
_server = None

def _start_gui(port: int, debug: bool, maximized: bool):
    """创建并启动 pywebview 窗口"""
    global _window
    url = f'http://127.0.0.1:{port}'
    _logger.info(f'GUI URL: {url}')

    # 创建窗口
    _window = _webview.create_window(
        title='Tea Agent',
        url=url,
        width=1200,
        height=800,
        resizable=True,
        fullscreen=False,
        maximized=maximized,
        min_size=(800, 600),
        text_select=True,
    )
    _webview.start(debug=debug, http_server=False)

def main(port: int = 0, debug: bool = False, maximized: bool = False):
    """主入口：启动服务器 + 打开 GUI 窗口"""
    global _server

    # 创建并启动后端服务器
    _server = create_gui_server(port=port)
    actual_port = _server.server_port
    _logger.info(f'GUI backend started on port {actual_port}')

    # 在新线程启动 pywebview
    gui_thread = _threading.Thread(
        target=_start_gui,
        args=(actual_port, debug, maximized),
        daemon=True
    )
    gui_thread.start()
    gui_thread.join()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Tea Agent GUI')
    parser.add_argument('--port', type=int, default=0, help='GUI server port (0=auto)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--maximized', action='store_true', help='Start maximized')
    args = parser.parse_args()
    main(port=args.port, debug=args.debug, maximized=args.maximized)
