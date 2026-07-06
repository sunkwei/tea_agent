# version: 1.0.0

import logging

logger = logging.getLogger("toolkit")

def toolkit_notify(title: str, message: str, urgency: str = "normal", duration: int = 5000):
    """Toolkit notify.

    Args:
        title: Description.
        message: Description.
        urgency: Description.
        duration: Description.
    """
    logger.info(f"toolkit_notify called: title={repr(title)[:80]}, message={repr(message)[:80]}, urgency={urgency!r}, duration={duration!r}")

    import subprocess
    import sys

    urgency_map = {"low": 0, "normal": 1, "critical": 2}

    if sys.platform == 'linux':
        # 1) GI Notify（最原生）
        try:
            import gi
            gi.require_version('Notify', '0.7')
            from gi.repository import Notify
            if not Notify.is_initted():
                Notify.init("TeaAgent")
            n = Notify.Notification.new(title, message)
            n.set_urgency(urgency_map.get(urgency, 1))
            n.set_timeout(duration)
            n.show()
            return (0, f"通知已发送: {title}", "")
        except Exception:
            logger.exception("operation failed")


        # 2) notify-send (D-Bus 标准通知，KDE Plasma 通知中心收录)
        try:
            subprocess.run(
                ['notify-send', '--app-name=TeaAgent',
                 f'--urgency={urgency}', f'--expire-time={duration}',
                 '--hint=int:transient:0',
                 title, message],
                timeout=5, capture_output=True,
            )
            return (0, f"通知已发送: {title}", "")
        except Exception:
            logger.exception("operation failed")


        # 3) kdialog (KDE)
        try:
            subprocess.run(
                ['kdialog', '--passivepopup', message, str(duration // 1000), '--title', title],
                timeout=5, capture_output=True,
            )
            return (0, f"通知已发送: {title}", "")
        except Exception:
            logger.exception("operation failed")


        # 4) zenity (GNOME/通用)
        try:
            subprocess.run(
                ['zenity', '--notification', '--text', f'{title}\n{message}',
                 f'--timeout={duration // 1000}'],
                timeout=5, capture_output=True,
            )
            return (0, f"通知已发送: {title}", "")
        except Exception:
            logger.exception("operation failed")


        # 5) wall 广播（最后手段）
        try:
            subprocess.run(['wall', f'[{title}] {message}'], timeout=3)
            return (0, f"通知已广播: {title}", "")
        except Exception as e:
            return (1, "", f"所有通知方式均失败: {e}")

    elif sys.platform == 'darwin':
        try:
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(['osascript', '-e', script], timeout=5)
            return (0, f"通知已发送: {title}", "")
        except Exception as e:
            return (1, "", f"macOS 通知失败: {e}")

    elif sys.platform == 'win32':
        # ── 系统通知区 Toast（主方案）──
        # PowerShell + Windows.UI.Notifications，非阻塞通知栏弹出
        try:
            app_id = "TeaAgent.TeaAgent.TeaAgent"
            ps_register = '''
$shortcutPath = "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\TeaAgent.lnk"
if (-not (Test-Path $shortcutPath)) {
    $WshShell = New-Object -ComObject WScript.Shell
    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Save()
}
'''
            subprocess.run(['powershell', '-NoProfile', '-Command', ps_register],
                           timeout=10, capture_output=True)
            ps_toast = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = @($template.GetElementsByTagName("text"))
$null = $texts[0].AppendChild($template.CreateTextNode("{title}"))
$null = $texts[1].AppendChild($template.CreateTextNode("{message}"))
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{app_id}").Show($toast)
'''
            subprocess.run(['powershell', '-NoProfile', '-Command', ps_toast],
                           timeout=10, capture_output=True)
            return (0, f"通知已发送: {title}", "")
        except Exception as e:
            return (1, "", f"Windows 通知失败: {e}")

    else:
        return (1, "", f"不支持的操作系统: {sys.platform}")

def meta_toolkit_notify() -> dict:
    """Meta toolkit notify."""
    return {"type": "function", "function": {"name": "toolkit_notify", "description": "发送桌面系统通知。支持 Linux（GI Notify/notify-send）、macOS（osascript）、Windows（PowerShell Toast）。长时间任务完成后使用。", "parameters": {"type": "object", "properties": {"title": {"type": "string", "description": "通知标题，如 '任务完成'"}, "message": {"type": "string", "description": "通知正文，如 '截图已保存到 screenshot.png'"}, "urgency": {"type": "string", "enum": ["low", "normal", "critical"], "description": "紧急程度，默认 normal", "default": "normal"}, "duration": {"type": "integer", "description": "显示时长（毫秒），默认 5000", "default": 5000}}, "required": ["title", "message"]}}}
