# @2026-05-01 gen by tea_agent, 跨平台提权执行命令
# version: 1.0.1

import subprocess
import shutil
import os
import sys
import ctypes

def toolkit_sudo_gui(app: str, args: list, prompt: str = "请输入管理员密码"):
    """跨平台提权执行命令"""

    # ── Windows: UAC 弹窗 ──
    if sys.platform == 'win32':
        try:
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                'runas',
                app,
                ' '.join(args) if args else '',
                None,
                1
            )
            if result > 32:
                return (0, f"UAC 提权已触发: {app} {' '.join(args)}", "")
            elif result == 1223:
                return (1223, "", "用户取消了 UAC 提权")
            else:
                return (result, "", f"ShellExecute 失败，错误码: {result}")
        except Exception as e:
            ps_cmd = f"Start-Process -FilePath '{app}' -ArgumentList '{' '.join(args)}' -Verb RunAs"
            result = subprocess.run(
                ['powershell', '-Command', ps_cmd],
                capture_output=True, text=True
            )
            return (result.returncode, result.stdout, result.stderr)

    # ── Linux/macOS: GUI 密码框 + sudo ──
    dialog_cmd = None

    if shutil.which('kdialog'):
        dialog_cmd = ['kdialog', '--password', prompt]
    elif shutil.which('zenity'):
        dialog_cmd = ['zenity', '--password', '--title', '管理员权限']
    elif os.environ.get('SSH_ASKPASS'):
        dialog_cmd = [os.environ['SSH_ASKPASS'], prompt]
    else:
        result = subprocess.run(
            ['sudo'] + [app] + args,
            capture_output=True, text=True
        )
        return (result.returncode, result.stdout, result.stderr)

    pwd_result = subprocess.run(dialog_cmd, capture_output=True, text=True)
    if pwd_result.returncode != 0:
        return (pwd_result.returncode, "", "用户取消了密码输入")

    password = pwd_result.stdout.strip()
    if not password:
        return (1, "", "密码不能为空")

    result = subprocess.run(
        ['sudo', '-S'] + [app] + args,
        input=password + '\n',
        capture_output=True, text=True
    )

    password = '\x00' * len(password)
    del password

    return (result.returncode, result.stdout, result.stderr)


def meta_toolkit_sudo_gui() -> dict:
    return {"type": "function", "function": {"name": "toolkit_sudo_gui", "description": "跨平台提权执行命令。Linux弹出GUI密码框+sudo，Windows弹出UAC对话框。自动检测OS选择正确方式。", "parameters": {"type": "object", "properties": {"app": {"type": "string", "description": "要执行的程序路径，如 apt、systemctl、msiexec"}, "args": {"type": "array", "items": {"type": "string"}, "description": "命令行参数列表"}, "prompt": {"type": "string", "description": "[Linux] 密码框提示文字", "default": "请输入管理员密码"}}, "required": ["app", "args"]}}}
