"""
Tea Agent Gui2 Server — Bottle-based static file + API proxy server.

Mounts the frontend static files and provides API endpoints for
memory management, config management, model switching, etc.
"""

import json
import logging as _logging
import os
import socket as _socket
import threading as _threading
import uuid
from pathlib import Path as _Path
from functools import wraps

_logger = _logging.getLogger('gui2_server')

# Lazy-load backend on first use
_backend_loaded = False
_srv_mod = None
_agent_mod = None

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
    """Create a Bottle server serving frontend files + API endpoints."""
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

    # ── CORS middleware ──
    def _cors(fn):
        @wraps(fn)
        def _wrapper(*args, **kwargs):
            resp = fn(*args, **kwargs)
            if isinstance(resp, dict):
                resp = _bottle.HTTPResponse(
                    body=json.dumps(resp, ensure_ascii=False),
                    status=200,
                    headers={
                        'Content-Type': 'application/json; charset=utf-8',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
                        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
                    }
                )
            elif isinstance(resp, _bottle.HTTPResponse):
                resp.set_header('Access-Control-Allow-Origin', '*')
                resp.set_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
                resp.set_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            return resp
        return _wrapper

    # ── Static File Routes ──
    @app.route('/')
    @app.route('/index.html')
    def index():
        resp = _bottle.static_file('index.html', root=str(static_dir))
        resp.set_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        resp.set_header('Pragma', 'no-cache')
        resp.set_header('Expires', '0')
        return resp

    @app.route('/static/<filepath:path>')
    def static(filepath):
        return _bottle.static_file(filepath, root=str(static_dir))

    # ── Health ──
    @app.route('/api/health')
    @_cors
    def api_health():
        return {'status': 'ok', 'service': 'tea-agent-gui2', 'version': '2.0'}

    # ── Handle OPTIONS for CORS ──
    @app.route('/api/<:re:.*>', method='OPTIONS')
    @_cors
    def api_options():
        return {}

    # ═══════════════════════════════════════════════════════════
    #  Memory API
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/memory', method='GET')
    @_cors
    def api_list_memory():
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            memories = server.list_memories()
            return {'ok': True, 'data': memories, 'total': len(memories)}
        except Exception as e:
            _logger.exception('list_memory failed')
            return {'ok': False, 'error': str(e)}

    @app.route('/api/memory', method='POST')
    @_cors
    def api_create_memory():
        try:
            data = json.loads(_bottle.request.body.read() or '{}')
            content = data.get('content', '').strip()
            if not content:
                return {'ok': False, 'error': 'content required'}
            category = data.get('category', 'general')
            priority = data.get('priority', 2)
            _ensure_backend()
            server = _srv_mod.get_server()
            result = server.create_memory(content, category=category, priority=priority)
            return {'ok': True, 'data': result}
        except Exception as e:
            _logger.exception('create_memory failed')
            return {'ok': False, 'error': str(e)}

    @app.route('/api/memory/<mem_id>', method='DELETE')
    @_cors
    def api_delete_memory(mem_id):
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            ok = server.delete_memory(mem_id)
            return {'ok': ok, 'deleted': True}
        except Exception as e:
            _logger.exception('delete_memory failed')
            return {'ok': False, 'error': str(e)}

    # ═══════════════════════════════════════════════════════════
    #  Config API
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/config', method='GET')
    @_cors
    def api_get_config():
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            info = server.get_config_info()
            return {'ok': True, 'data': info}
        except Exception as e:
            _logger.exception('get_config failed')
            return {'ok': False, 'error': str(e)}

    @app.route('/api/config', method='PUT')
    @_cors
    def api_update_config():
        try:
            data = json.loads(_bottle.request.body.read() or '{}')
            _ensure_backend()
            server = _srv_mod.get_server()
            result = server.update_config(data)
            return {'ok': result['ok'], 'updated': result.get('updated', []), 'errors': result.get('errors', [])}
        except Exception as e:
            _logger.exception('update_config failed')
            return {'ok': False, 'error': str(e)}

    @app.route('/api/configs', method='GET')
    @_cors
    def api_list_configs():
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            result = server.list_config_files(check_valid=True)
            active_config_path = ''
            active_config_filename = ''
            try:
                agent = server.get_agent()
                if agent and agent._config_path:
                    active_config_path = agent._config_path
                    active_config_filename = _Path(active_config_path).name
            except Exception:
                pass
            return {
                'ok': True,
                'data': result.get('configs', result if isinstance(result, list) else []),
                'any_valid': result.get('any_valid', True),
                'active_config_path': active_config_path,
                'active_config_filename': active_config_filename,
            }
        except Exception as e:
            _logger.exception('list_configs failed')
            return {'ok': False, 'error': str(e)}

    @app.route('/api/config/create', method='POST')
    @_cors
    def api_create_config():
        try:
            data = json.loads(_bottle.request.body.read() or '{}')
            filename = (data.get('filename') or '').strip()
            main_model_name = (data.get('main_model_name') or '').strip()
            main_api_url = (data.get('main_api_url') or '').strip()
            main_api_key = (data.get('main_api_key') or '').strip()
            cheap_model_name = (data.get('cheap_model_name') or '').strip()
            cheap_api_url = (data.get('cheap_api_url') or '').strip()
            cheap_api_key = (data.get('cheap_api_key') or '').strip()

            errors = []
            if not filename: errors.append('filename required')
            if not main_model_name: errors.append('main_model_name required')
            if not main_api_url: errors.append('main_api_url required')
            if not main_api_key: errors.append('main_api_key required')
            if errors:
                return {'ok': False, 'errors': errors}

            _ensure_backend()
            server = _srv_mod.get_server()
            fpath = server.create_config_file(
                filename=filename,
                main_model_name=main_model_name,
                main_api_url=main_api_url,
                main_api_key=main_api_key,
                cheap_model_name=cheap_model_name,
                cheap_api_url=cheap_api_url,
                cheap_api_key=cheap_api_key,
            )
            server.switch_config(fpath)
            return {'ok': True, 'config_path': fpath, 'filename': filename}
        except Exception as e:
            _logger.exception('create_config failed')
            return {'ok': False, 'error': str(e)}

    @app.route('/api/config/upload', method='POST')
    @_cors
    def api_upload_config():
        try:
            from tea_agent.config import load_config
            upload = _bottle.request.files.get('file')
            if not upload:
                return {'ok': False, 'error': '请选择文件'}
            filename = upload.filename or ''
            if not filename.endswith(('.yaml', '.yml')):
                return {'ok': False, 'error': '仅支持 .yaml / .yml 文件'}
            content = upload.file.read()
            if not content or not content.strip():
                return {'ok': False, 'error': '文件内容为空'}
            _ensure_backend()
            server = _srv_mod.get_server()
            configs_dir = server._get_configs_dir()
            configs_dir.mkdir(parents=True, exist_ok=True)
            dest_path = configs_dir / filename
            if dest_path.exists():
                from datetime import datetime
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                dest_path = configs_dir / f'{dest_path.stem}_{stamp}.yaml'
            if isinstance(content, bytes):
                dest_path.write_bytes(content)
            else:
                dest_path.write_text(content.decode('utf-8'), encoding='utf-8')
            try:
                cfg = load_config(str(dest_path))
                if not cfg.main_model.is_configured:
                    dest_path.unlink()
                    return {'ok': False, 'error': '配置无效：必须包含 main_model 的 api_url、api_key 和 model_name'}
            except Exception:
                dest_path.unlink()
                return {'ok': False, 'error': '配置解析失败'}
            try:
                server.switch_config(str(dest_path))
            except Exception:
                pass
            return {'ok': True, 'filename': dest_path.name, 'path': str(dest_path)}
        except Exception as e:
            _logger.exception('upload_config failed')
            return {'ok': False, 'error': str(e)}

    # ═══════════════════════════════════════════════════════════
    #  Model API
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/model', method='GET')
    @_cors
    def api_get_model():
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            info = server.get_config_info()
            return {'ok': True, 'data': info}
        except Exception as e:
            _logger.exception('get_model failed')
            return {'ok': False, 'error': str(e)}

    @app.route('/api/model', method='POST')
    @_cors
    def api_switch_model():
        try:
            data = json.loads(_bottle.request.body.read() or '{}')
            _ensure_backend()
            server = _srv_mod.get_server()

            api_key = (data.get('api_key') or '').strip()
            api_url = (data.get('api_url') or '').strip()
            model_name = (data.get('model_name') or '').strip()
            cheap_api_key = (data.get('cheap_api_key') or '').strip()
            cheap_api_url = (data.get('cheap_api_url') or '').strip()
            cheap_model_name = (data.get('cheap_model_name') or '').strip()

            errors = []
            if not api_key: errors.append('api_key required')
            if not api_url: errors.append('api_url required')
            if not model_name: errors.append('model_name required')
            if errors:
                return {'ok': False, 'errors': errors}

            def _float_or_none(key):
                v = data.get(key)
                return float(v) if v is not None and str(v).strip() else None
            def _int_or_none(key):
                v = data.get(key)
                return int(v) if v is not None and str(v).strip() else None

            temperature = _float_or_none('temperature')
            max_tokens = _int_or_none('max_tokens')
            top_p = _float_or_none('top_p')
            max_context_tokens = _int_or_none('max_context_tokens')
            options = data.get('options')
            cheap_temperature = _float_or_none('cheap_temperature')
            cheap_max_tokens = _int_or_none('cheap_max_tokens')
            cheap_top_p = _float_or_none('cheap_top_p')
            cheap_max_context_tokens = _int_or_none('cheap_max_context_tokens')
            cheap_options = data.get('cheap_options')

            server.switch_model(
                api_key, api_url, model_name,
                cheap_api_key, cheap_api_url, cheap_model_name,
                temperature=temperature, max_tokens=max_tokens,
                top_p=top_p, max_context_tokens=max_context_tokens,
                options=options,
                cheap_temperature=cheap_temperature, cheap_max_tokens=cheap_max_tokens,
                cheap_top_p=cheap_top_p, cheap_max_context_tokens=cheap_max_context_tokens,
                cheap_options=cheap_options,
            )
            masked_key = (api_key[:6] + '...' + api_key[-4:]) if len(api_key) > 12 else '***'
            result = {'ok': True, 'model': model_name, 'api_url': api_url, 'api_key_masked': masked_key}
            if cheap_model_name:
                cheap_masked = (cheap_api_key[:6] + '...' + cheap_api_key[-4:]) if len(cheap_api_key) > 12 else '***'
                result['cheap_model'] = {'model': cheap_model_name, 'api_url': cheap_api_url, 'api_key_masked': cheap_masked}
            return result
        except Exception as e:
            _logger.exception('switch_model failed')
            return {'ok': False, 'error': str(e)}

    @app.route('/api/model/config', method='POST')
    @_cors
    def api_switch_model_config():
        try:
            data = json.loads(_bottle.request.body.read() or '{}')
            config_path = (data.get('config_path') or '').strip()
            if not config_path:
                return {'ok': False, 'error': 'config_path required'}
            _ensure_backend()
            server = _srv_mod.get_server()
            result = server.switch_config(config_path)
            if not result.get('ok'):
                return {'ok': False, 'error': result.get('error', 'switch failed')}
            return {'ok': True, 'config_path': config_path}
        except Exception as e:
            _logger.exception('switch_model_config failed')
            return {'ok': False, 'error': str(e)}

    # ═══════════════════════════════════════════════════════════
    #  Session / Topic API
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/sessions', method='GET')
    @_cors
    def api_list_sessions():
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            sessions = server.list_sessions(limit=20)
            return {'ok': True, 'data': sessions}
        except Exception as e:
            _logger.exception('list_sessions failed')
            return {'ok': False, 'error': str(e)}

    @app.route('/api/topic/<topic_id>', method='GET')
    @_cors
    def api_get_topic(topic_id):
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            info = server.get_topic_info(topic_id)
            if not info:
                return {'ok': False, 'error': 'Topic not found'}
            return {'ok': True, 'data': info}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    @app.route('/api/topic/<topic_id>', method='PUT')
    @_cors
    def api_rename_topic(topic_id):
        try:
            data = json.loads(_bottle.request.body.read() or '{}')
            new_title = (data.get('title') or '').strip()
            if not new_title:
                return {'ok': False, 'error': 'title required'}
            _ensure_backend()
            server = _srv_mod.get_server()
            ok = server.rename_topic(topic_id, new_title)
            return {'ok': ok, 'title': new_title}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    @app.route('/api/topic/<topic_id>', method='DELETE')
    @_cors
    def api_delete_topic(topic_id):
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            ok = server.delete_session(topic_id)
            return {'ok': ok}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    @app.route('/api/topic/<topic_id>/conversations', method='GET')
    @_cors
    def api_get_conversations(topic_id):
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            limit = int(_bottle.request.query.get('limit', '50'))
            convs = server.get_topic_conversations(topic_id, limit=limit)
            return {'ok': True, 'data': convs}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ═══════════════════════════════════════════════════════════
    #  Screenshot API
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/screenshot/full', method='GET')
    @_cors
    def api_screenshot_full():
        try:
            _ensure_backend()
            server = _srv_mod.get_server()
            result = server.screenshot_full()
            return result
        except Exception as e:
            _logger.exception('screenshot_full failed')
            return {'ok': False, 'error': str(e)}

    # ═══════════════════════════════════════════════════════════
    #  Search API
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/search', method='GET')
    @_cors
    def api_search():
        try:
            q = _bottle.request.query.get('q', '').strip()
            limit = int(_bottle.request.query.get('limit', '20'))
            if not q:
                return {'ok': False, 'error': 'query required'}
            _ensure_backend()
            server = _srv_mod.get_server()
            results = server.search(q, limit=limit)
            return {'ok': True, 'data': results}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ═══════════════════════════════════════════════════════════
    #  Pick a random free port
    # ═══════════════════════════════════════════════════════════

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
