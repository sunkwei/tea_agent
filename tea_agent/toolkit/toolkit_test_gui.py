## llm generated tool func, created 2026-05-20 by tea_agent
## toolkit_test_gui: 测试 python -m tea_agent.gui 能否正常加载 GUI 组件

import logging
import subprocess
import os
import sys
import time

logger = logging.getLogger("toolkit")

def toolkit_test_gui(timeout: int = 30, debug: bool = True) -> dict:
    """测试 python -m tea_agent.gui 能否正常执行。

    启动带 --debug --timeout 的 GUI 子进程，捕获终端输出，
    超时后自动结束，返回判断结果。

    Args:
        timeout: GUI 超时秒数，默认 30。内部额外等待 margin 10s。
        debug:  传递 --debug 标志，默认 True。

    Returns:
        dict: 包含 success, exit_code, stdout_tail, stderr_tail, duration, diagnosis
    """
    logger.info(f"toolkit_test_gui called: timeout={timeout}, debug={debug}")

    # 构建命令
    cmd = [sys.executable, "-m", "tea_agent.gui"]
    if debug:
        cmd.append("--debug")
    cmd.extend(["--timeout", str(timeout)])

    start_time = time.time()
    result = {
        "success": False,
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "duration": 0,
        "diagnosis": "",
        "command": " ".join(cmd),
        "timeout_used": timeout,
    }

    try:
        # 启动子进程，捕获输出
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=os.getcwd(),
        )

        # 等待进程结束（timeout + 额外 margin）
        total_wait = timeout + 15
        try:
            stdout_data, stderr_data = proc.communicate(timeout=total_wait)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_data, stderr_data = proc.communicate()
            exit_code = proc.returncode
            result["diagnosis"] += "进程超时被强制终止。"

        duration = round(time.time() - start_time, 2)
        result["duration"] = duration
        result["exit_code"] = exit_code

        # 截取尾部输出（最多 2000 字符）
        stdout_tail = (stdout_data or "")[-2000:]
        stderr_tail = (stderr_data or "")[-2000:]
        result["stdout_tail"] = stdout_tail
        result["stderr_tail"] = stderr_tail

        # 诊断判断
        diagnoses = []

        # 检查退出码
        if exit_code == 0:
            diagnoses.append("退出码为 0，进程正常结束")
            result["success"] = True
        elif exit_code is None:
            diagnoses.append("退出码为 None，进程可能被强制终止")
        else:
            diagnoses.append(f"退出码异常: {exit_code}")

        # 检查是否有 Tk 初始化错误
        combined = (stdout_data or "") + (stderr_data or "")
        error_keywords = ["TclError", "_tkinter.TclError", "no display",
                          "couldn't connect to display", "ImportError",
                          "ModuleNotFoundError", "cannot import"]
        found_errors = [kw for kw in error_keywords if kw.lower() in combined.lower()]
        if found_errors:
            diagnoses.append(f"发现错误关键词: {', '.join(found_errors)}")
            result["success"] = False

        # 检查是否有 GUI 成功初始化的标志
        success_indicators = ["TkGUI", "AgentCore", "Dream", "GUI"]
        found_success = [kw for kw in success_indicators if kw in combined]
        if found_success:
            diagnoses.append(f"发现运行标志: {', '.join(found_success)}")

        if not diagnoses:
            diagnoses.append("未发现明确错误或成功标志，请检查输出")

        result["diagnosis"] = " | ".join(diagnoses)

        # 额外检查：如果 duration 远小于 timeout，可能 Tk 立即失败了
        if duration < 5 and exit_code != 0:
            result["diagnosis"] += " | GUI 在 5 秒内异常退出，可能初始化失败"
            result["success"] = False

    except FileNotFoundError:
        result["diagnosis"] = f"找不到 Python 解释器: {sys.executable}"
    except Exception as e:
        result["diagnosis"] = f"执行异常: {type(e).__name__}: {e}"
        result["duration"] = round(time.time() - start_time, 2)

    logger.info(f"toolkit_test_gui result: success={result['success']}, "
                f"exit_code={result['exit_code']}, duration={result['duration']}s")

    return result

def meta_toolkit_test_gui() -> dict:
    """Meta toolkit test gui."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_test_gui",
            "description": "测试 python -m tea_agent.gui 能否正常加载 GUI 组件。启动带 --debug --timeout 的子进程，捕获终端输出，超时后判断是否成功。",
            "parameters": {
                "type": "object",
                "properties": {
                    "timeout": {
                        "type": "integer",
                        "description": "GUI 超时秒数，默认 30",
                        "default": 30
                    },
                    "debug": {
                        "type": "boolean",
                        "description": "传递 --debug 标志，默认 true",
                        "default": True
                    }
                },
                "required": []
            }
        }
    }
