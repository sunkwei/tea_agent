# version: 1.0.0

import logging
import os
import smtplib
import ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger('toolkit')

def toolkit_send_email(
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    attachments: list | None = None,
    smtp_server: str = 'smtp.gmail.com',
    smtp_port: int = 587,
    sender: str | None = None,
    email: str = '',
    password: str = '',
):
    """通过 SMTP 发送电子邮件。

    Args:
        to: 收件人邮箱，多个用逗号分隔
        subject: 邮件主题
        body: 邮件正文（纯文本或 Markdown）
        html: HTML 正文（可选，不填则从 body 自动生成 HTML）
        cc: 抄送邮箱，逗号分隔
        bcc: 密送邮箱，逗号分隔
        attachments: 附件文件路径列表
        smtp_server: SMTP 服务器，默认 smtp.gmail.com
        smtp_port: SMTP 端口，默认 587 (TLS)
        sender: 发件人名称/邮箱
        email: 邮箱账号（默认从 EMAIL_ADDRESS 环境变量读取）
        password: 邮箱密码（默认从 EMAIL_PASSWORD 环境变量读取）
    """
    # Resolve credentials
    email = email or os.environ.get('EMAIL_ADDRESS', '')
    password = password or os.environ.get('EMAIL_PASSWORD', '')

    if not email or not password:
        return {'ok': False, 'error': '缺少邮箱账号或密码。请传入 email/password 参数，或设置 EMAIL_ADDRESS/EMAIL_PASSWORD 环境变量。'}

    sender = sender or email

    if attachments is None:
        attachments = []

    if isinstance(attachments, list | tuple):
        pass
    else:
        attachments = [attachments]

    # Build message
    msg = MIMEMultipart('alternative')
    msg['From'] = sender
    msg['To'] = to
    msg['Subject'] = subject

    if cc:
        msg['Cc'] = cc
    # Bcc is handled at send time, not in headers

    # Attach body
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    if html:
        msg.attach(MIMEText(html, 'html', 'utf-8'))
    else:
        # Auto-generate simple HTML from plain text
        safe_body = body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>\n')
        auto_html = f'<html><body><pre style="font-family:sans-serif;font-size:14px;line-height:1.6">{safe_body}</pre></body></html>'
        msg.attach(MIMEText(auto_html, 'html', 'utf-8'))

    # Attach files
    for fpath in attachments:
        if not os.path.isfile(fpath):
            logger.warning(f'附件不存在，跳过: {fpath}')
            continue
        try:
            with open(fpath, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            encoders.encode_base64(part)
            fname = os.path.basename(fpath)
            part.add_header('Content-Disposition', 'attachment', filename=('utf-8', '', fname))
            msg.attach(part)
        except Exception as e:
            logger.warning(f'附件添加失败: {fpath} - {e}')

    # Resolve all recipients
    all_recipients = [r.strip() for r in to.split(',') if r.strip()]
    if cc:
        all_recipients += [r.strip() for r in cc.split(',') if r.strip()]
    if bcc:
        all_recipients += [r.strip() for r in bcc.split(',') if r.strip()]

    # Send
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(email, password)
            server.sendmail(sender, all_recipients, msg.as_string())
        return {'ok': True, 'message': f'邮件已发送到 {to}', 'recipients': len(all_recipients)}
    except smtplib.SMTPAuthenticationError:
        return {'ok': False, 'error': 'SMTP 认证失败。请检查邮箱账号和密码，Gmail 需使用应用专用密码而非登录密码。'}
    except smtplib.SMTPException as e:
        return {'ok': False, 'error': f'SMTP 错误: {e}'}
    except Exception as e:
        logger.exception('发送邮件失败')
        return {'ok': False, 'error': f'发送失败: {e}'}


def meta_toolkit_send_email() -> dict:
    """Meta for toolkit_send_email."""
    return {
        'type': 'function',
        'function': {
            'name': 'toolkit_send_email',
            'description': '通过 SMTP 发送电子邮件。支持纯文本/HTML、附件、多收件人。默认使用 Gmail SMTP (smtp.gmail.com:587 TLS)。密码优先从环境变量 EMAIL_PASSWORD 读取，其次从参数 password 获取。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'to': {'type': 'string', 'description': '收件人邮箱，多个用逗号分隔'},
                    'subject': {'type': 'string', 'description': '邮件主题'},
                    'body': {'type': 'string', 'description': '邮件正文（纯文本或 Markdown 格式）'},
                    'html': {'type': 'string', 'description': 'HTML 正文（可选，不填则从 body 自动生成 HTML）'},
                    'cc': {'type': 'string', 'description': '抄送邮箱，逗号分隔（可选）'},
                    'bcc': {'type': 'string', 'description': '密送邮箱，逗号分隔（可选）'},
                    'attachments': {'type': 'array', 'items': {'type': 'string'}, 'description': '附件文件路径列表（可选）'},
                    'smtp_server': {'type': 'string', 'description': 'SMTP 服务器地址，默认 smtp.gmail.com', 'default': 'smtp.gmail.com'},
                    'smtp_port': {'type': 'integer', 'description': 'SMTP 端口，默认 587 (TLS)', 'default': 587},
                    'sender': {'type': 'string', 'description': '发件人邮箱，默认从 email 参数推断'},
                    'email': {'type': 'string', 'description': '邮箱账号，默认从 EMAIL_ADDRESS 环境变量读取'},
                    'password': {'type': 'string', 'description': '邮箱密码/应用专用密码，默认从 EMAIL_PASSWORD 环境变量读取'},
                },
                'required': ['to', 'subject', 'body'],
            },
        },
    }
