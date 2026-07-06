"""
Tea Agent Gui2 Server — Bottle-based static file + API proxy server.

Mounts the frontend static files and provides API proxy to tea_agent backend.
"""

import logging as _logging
import socket as _socket
import threading as _threading
from pathlib import Path as _Path

_logger = _logging.getLogger('gui2_server')

# Lazy-load backend on first use
_backend_loaded = False

def _ensure_backend():
    global _backend_loaded
    if _backend_loaded:
        return
    _logger.info('Loading tea_agent backend...')
    import tea_agent as _agent
    import tea_agent.server.server as _srv
    global _srv_mod, _agent_mod
    _srv_mod = _srv
    _agent_mod = _agent
    _backend_loaded = True
    _logger.info('Backend loaded successfully')

def create_gui_server(port: int = 0):
    """Create a Bottle server serving frontend files."""
    try:
        import bottle as _bottle
    except ImportError:
        _logger.error('Bottle not installed. Run: pip install bottle')
        raise

    app = _bottle.Bottle()

    # Static directory
    static_dir = _Path(__file__).parent / 'frontend' / 'dist'
    if not static_dir.exists():
        static_dir = _Path(__file__).parent / 'frontend'
    _logger.info(f'Static dir: {static_dir}')

    @app.route('/')
    @app.route('/index.html')
    def index():
        return _bottle.static_file('index.html', root=str(static_dir))

    @app.route('/static/<filepath:path>')
    def static(filepath):
        return _bottle.static_file(filepath, root=str(static_dir))

    # API proxy: health
    @app.route('/api/health')
    def api_health():
        return {'status': 'ok', 'service': 'tea-agent-gui2'}

    # Pick a random free port
    if port == 0:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()

    # Store port on app
    app.server_port = port

    # Start Bottle in a thread
    _threading.Thread(
        target=_bottle.run,
        args=(app,),
        kwargs={'host': '127.0.0.1', 'port': port, 'silent': True},
        daemon=True
    ).start()

    return app
