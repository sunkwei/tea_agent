# @2026-05-01 gen by tea_agent, 跨平台桌面通知
# version: 1.0.0

def toolkit_notify(title: str, message: str, urgency: str = "normal", duration: int = 5000):
    import sys
    import subprocess

    urgency_map = {"low": 0, "normal": 1, "critical": 2}

    # ── Linux ──
    if sys.platform == 'linux':
        try:
            import gi
            gi.require_version('Notify', '0.7')
            from gi.repository import Notify, GLib
            if not Notify.is_initted():
                Notify.init("TeaAgent")
            level = urgency_map.get(urgency, 1)
            n = Notify.Notification.new(title, message)
            n.set_urgency(level)
            n.set_timeout(duration)
            n.show()
            return (0, f"通知已发送: {title}", "")
        except Exception:
            pass

        try:
            subprocess.run(
                ['notify-send', '-u', urgency, '-t', str(duration), title, message],
                timeout=5
            )
            return (0, f"通知已发送: {title}", "")
        except Exception:
            pass

        try:
            subprocess.run(['wall', f'[{title}] {message}'], timeout=3)
            return (0, f"通知已广播: {title}", "")
        except Exception as e:
            return (1, "", f"所有通知方式均失败: {e}")

    # ── macOS ──
    elif sys.platform == 'darwin':
        try:
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(['osascript', '-e', script], timeout=5)
            return (0, f"通知已发送: {title}", "")
        except Exception as e:
            return (1, "", f"macOS 通知失败: {e}")

    # ── Windows ──
    elif sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)
            return (0, f"通知已弹出: {title}", "")
        except Exception:
            try:
                ps = f'''
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
                $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
                $texts = $template.GetElementsByTagName("text")
                $texts[0].AppendChild($template.CreateTextNode("{title}")) > $null
                $texts[1].AppendChild($template.CreateTextNode("{message}")) > $null
                $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
                [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("TeaAgent").Show($toast)
                '''
                subprocess.run(['powershell', '-Command', ps], timeout=10)
                return (0, f"通知已发送: {title}", "")
            except Exception as e:
                return (1, "", f"Windows 通知失败: {e}")

    else:
        return (1, "", f"不支持的操作系统: {sys.platform}")


def meta_toolkit_notify() -> dict:
    return {"type": "function", "function": {"name": "toolkit_notify", "description": "发送桌面系统通知。支持 Linux（GI Notify/notify-send）、macOS（osascript）、Windows（PowerShell Toast）。长时间任务完成后使用。", "parameters": {"type": "object", "properties": {"title": {"type": "string", "description": "通知标题，如 '任务完成'"}, "message": {"type": "string", "description": "通知正文，如 '截图已保存到 screenshot.png'"}, "urgency": {"type": "string", "enum": ["low", "normal", "critical"], "description": "紧急程度，默认 normal", "default": "normal"}, "duration": {"type": "integer", "description": "显示时长（毫秒），默认 5000", "default": 5000}}, "required": ["title", "message"]}}}
