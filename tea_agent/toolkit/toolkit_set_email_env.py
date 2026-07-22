# version: 1.0.0

import os
import logging

logger = logging.getLogger('toolkit')

def toolkit_set_email_env():
    """设置邮件环境变量到当前进程。"""
    email = os.environ.get('EMAIL_ADDRESS', '')
    password = os.environ.get('EMAIL_PASSWORD', '')

    # Try loading from .env if not already set
    if not email or not password:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        if os.path.isfile(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        if k.strip() == 'EMAIL_ADDRESS' and not email:
                            email = v.strip()
                            os.environ['EMAIL_ADDRESS'] = email
                        elif k.strip() == 'EMAIL_PASSWORD' and not password:
                            password = v.strip()
                            os.environ['EMAIL_PASSWORD'] = password

    parts = []
    addr = os.environ.get('EMAIL_ADDRESS', '')
    if addr:
        parts.append(f'EMAIL_ADDRESS={addr}')
    if os.environ.get('EMAIL_PASSWORD'):
        parts.append('EMAIL_PASSWORD=***已设置***')

    msg = ' | '.join(parts) if parts else '未找到邮件配置'
    return {'ok': True, 'message': msg}


def meta_toolkit_set_email_env() -> dict:
    """Meta for toolkit_set_email_env."""
    return {
        'type': 'function',
        'function': {
            'name': 'toolkit_set_email_env',
            'description': '设置邮件环境变量到当前进程',
            'parameters': {'type': 'object', 'properties': {}, 'required': []},
        },
    }
