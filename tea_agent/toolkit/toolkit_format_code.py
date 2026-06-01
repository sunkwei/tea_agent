## llm generated tool func, created Mon Jun  1 09:29:04 2026
# version: 1.0.0

"""
代码格式化工具

支持 Python (black) 和 C/C++ (clang-format) 格式化。
"""

import os
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("toolkit.format_code")


def toolkit_format_code(
    action: str = "format",
    path: str = ".",
    language: str = "auto",
    style: str = ""
) -> str:
    """
    代码格式化工具。
    
    Args:
        action: 操作类型：format=格式化，check=检查
        path: 文件或目录路径
        language: 语言类型，默认 auto 自动检测
        style: 格式化风格
    
    Returns:
        格式化结果或错误信息
    """
    path = os.path.abspath(path)
    
    # 检测语言
    if language == "auto":
        language = _detect_language(path)
    
    # 根据语言选择格式化工具
    if language == "python":
        return _format_python(action, path, style)
    elif language == "cpp":
        return _format_cpp(action, path, style)
    else:
        return f"❌ 不支持的语言: {language}"


def _detect_language(path: str) -> str:
    """自动检测语言类型。"""
    if os.path.isfile(path):
        ext = Path(path).suffix.lower()
        if ext in ('.py', '.pyw', '.pyi'):
            return "python"
        elif ext in ('.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hxx', '.cu', '.cuh'):
            return "cpp"
    elif os.path.isdir(path):
        # 检查目录中的文件类型
        py_files = list(Path(path).rglob("*.py"))
        cpp_files = list(Path(path).rglob("*.cpp")) + list(Path(path).rglob("*.h"))
        
        if py_files:
            return "python"
        elif cpp_files:
            return "cpp"
    
    return "unknown"


def _format_python(action: str, path: str, style: str) -> str:
    """Python 格式化 (black)。"""
    # 检查 black 是否安装
    try:
        subprocess.run(["python", "-m", "black", "--version"], 
                      capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # 尝试安装 black
        logger.info("black 未安装，正在安装...")
        try:
            subprocess.run(["pip", "install", "black"], 
                          capture_output=True, check=True)
        except:
            return "❌ black 未安装，请运行: pip install black"
    
    # 构建命令
    cmd = ["python", "-m", "black"]
    
    if action == "check":
        cmd.append("--check")
        cmd.append("--diff")
    
    if style:
        cmd.extend(["--line-length", style])
    else:
        cmd.extend(["--line-length", "88"])  # black 默认
    
    cmd.append(path)
    
    # 执行格式化
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if action == "check":
            if result.returncode == 0:
                return f"✅ {path} 格式符合规范"
            else:
                return f"⚠️ {path} 格式不符合规范:\n{result.stdout}"
        else:
            if result.returncode == 0:
                return f"✅ {path} 格式化完成\n{result.stdout}"
            else:
                return f"❌ 格式化失败:\n{result.stderr}"
    
    except subprocess.TimeoutExpired:
        return "❌ 格式化超时"
    except Exception as e:
        return f"❌ 格式化错误: {e}"


def _format_cpp(action: str, path: str, style: str) -> str:
    """C/C++ 格式化 (clang-format)。"""
    # 检查 clang-format 是否安装
    try:
        subprocess.run(["clang-format", "--version"], 
                      capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "❌ clang-format 未安装，请安装 LLVM 工具链"
    
    # 构建命令
    cmd = ["clang-format"]
    
    if action == "check":
        cmd.append("--dry-run")
        cmd.append("--Werror")
    
    if style:
        cmd.extend(["--style", style])
    else:
        cmd.extend(["--style", "Google"])  # 默认 Google 风格
    
    if os.path.isfile(path):
        cmd.append(path)
    elif os.path.isdir(path):
        # 递归处理目录中的 C/C++ 文件
        results = []
        for ext in ('*.c', '*.cpp', '*.cc', '*.h', '*.hpp'):
            for file in Path(path).rglob(ext):
                result = _format_cpp(action, str(file), style)
                results.append(result)
        return "\n".join(results)
    
    # 执行格式化
    try:
        if action == "format":
            # 格式化并写回文件
            result = subprocess.run(
                cmd + ["-i"],  # -i 原地格式化
                capture_output=True,
                text=True,
                timeout=60
            )
        else:
            # 检查模式
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
        
        if result.returncode == 0:
            if action == "check":
                return f"✅ {path} 格式符合规范"
            else:
                return f"✅ {path} 格式化完成"
        else:
            return f"⚠️ {path} 格式问题:\n{result.stderr or result.stdout}"
    
    except subprocess.TimeoutExpired:
        return "❌ 格式化超时"
    except Exception as e:
        return f"❌ 格式化错误: {e}"


def _check_tool_installed(tool_name: str) -> bool:
    """检查工具是否已安装。"""
    try:
        subprocess.run([tool_name, "--version"], 
                      capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# 工具元信息
TOOL_META = {
    "type": "function",
    "function": {
        "name": "toolkit_format_code",
        "description": "代码格式化工具。支持 Python (black) 和 C/C++ (clang-format)。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["format", "check"], "description": "操作类型"},
                "path": {"type": "string", "description": "文件或目录路径"},
                "language": {"type": "string", "enum": ["python", "cpp", "auto"], "description": "语言类型"},
                "style": {"type": "string", "description": "格式化风格"}
            },
            "required": ["action", "path"]
        }
    }
}


def meta_toolkit_format_code() -> dict:
    return {"type": "function", "function": {"name": "toolkit_format_code", "description": "代码格式化工具。支持 Python (black) 和 C/C++ (clang-format) 格式化。\n\n功能：\n- 格式化单个文件或目录\n- 检查格式是否符合规范\n- 自动检测语言并选择格式化工具\n\n返回：格式化结果或错误信息", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["format", "check"], "description": "操作类型：format=格式化，check=检查"}, "path": {"type": "string", "description": "文件或目录路径"}, "language": {"type": "string", "enum": ["python", "cpp", "auto"], "description": "语言类型，默认 auto 自动检测"}, "style": {"type": "string", "description": "格式化风格，如 black 默认、Google、LLVM 等"}}, "required": ["action", "path"]}}}
