"""读取并解析 pyproject.toml，提取项目元数据"""
import logging
import sys
from pathlib import Path

logger = logging.getLogger("toolkit")

def toolkit_read_pyproject(path: str = ".") -> dict:
    """
    读取并解析 pyproject.toml 提取项目元数据。
    自动处理 Python 版本兼容（3.11+ tomllib / tomli / toml 回退）。
    
    Returns:
        dict: {"ok": True, "name": ..., "version": ..., ...} 或 {"ok": False, "error": ...}
    """
    logger.info(f"toolkit_read_pyproject called: path={path!r}")
    pyproject_path = Path(path) / "pyproject.toml"
    if not pyproject_path.exists():
        return {"ok": False, "error": f"未找到 pyproject.toml: {pyproject_path}"}
    
    try:
        if sys.version_info >= (3, 11):
            import tomllib
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
        else:
            loaded = False
            for lib_name in ["tomli", "toml"]:
                try:
                    lib = __import__(lib_name)
                    if lib_name == "toml":
                        with open(pyproject_path, "r") as f:
                            data = lib.load(f)
                    else:
                        with open(pyproject_path, "rb") as f:
                            data = lib.load(f)
                    loaded = True
                    break
                except ImportError:
                    continue
            if not loaded:
                return {"ok": False, "error": "无可用 TOML 解析器。请安装 tomli (Python<3.11) 或升级到 Python 3.11+"}
        
        project = data.get("project", {})
        return {
            "ok": True,
            "name": project.get("name", "Unknown"),
            "version": project.get("version", "Unknown"),
            "description": project.get("description", ""),
            "requires_python": project.get("requires-python", ""),
            "dependencies": project.get("dependencies", []),
            "optional_dependencies": list(project.get("optional-dependencies", {}).keys()),
            "build_system": data.get("build-system", {}).get("requires", [])
        }
    except Exception as e:
        logger.warning(f"toolkit_read_pyproject error: {e}")
        return {"ok": False, "error": str(e)}

def meta_toolkit_read_pyproject() -> dict:
    """
    Meta toolkit read pyproject

    Returns:
        dict: Description.
    """
    return {
        "type": "function",
        "function": {
            "name": "toolkit_read_pyproject",
            "description": "Read and parse pyproject.toml to extract project metadata (name, version, deps).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "default": ".",
                        "description": "Path to the project directory containing pyproject.toml"
                    }
                },
                "required": []
            }
        }
    }
