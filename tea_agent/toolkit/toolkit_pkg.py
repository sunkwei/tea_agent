## llm generated tool func, created Fri May  1 09:50:24 2026
# version: 1.0.0


def toolkit_pkg(action: str, packages: str = None, module: str = None):
    """
    智能 Python 包管理工具。
    自动检测缺失模块并安装，支持批量操作。
    """
    import subprocess, sys, importlib, os

    def _pip_install(pkgs):
        """安装包列表"""
        if isinstance(pkgs, str):
            pkgs = [p.strip() for p in pkgs.split(",")]
        args = [sys.executable, "-m", "pip", "install", "--quiet"] + pkgs
        r = subprocess.run(args, capture_output=True, text=True, timeout=120)
        return r.returncode == 0, r.stdout, r.stderr

    def _check_module(name):
        """检查模块是否可导入"""
        try:
            importlib.import_module(name)
            return True
        except ImportError:
            return False

    def _get_version(name):
        """获取已安装包的版本"""
        try:
            mod = importlib.import_module(name)
            for attr in ["__version__", "version", "VERSION"]:
                v = getattr(mod, attr, None)
                if v and isinstance(v, str):
                    return v
            # 尝试 pkg_resources
            try:
                import pkg_resources
                return pkg_resources.get_distribution(name).version
            except:
                pass
        except:
            pass
        return None

    def _list_installed():
        """列出关键包"""
        key_pkgs = {
            "PIL": "Pillow",
            "jieba": "jieba",
            "mss": "mss",
            "numpy": "numpy",
            "requests": "requests",
            "pytesseract": "pytesseract",
            "pydantic": "pydantic",
            "yaml": "PyYAML",
            "duckduckgo_search": "duckduckgo-search",
        }
        results = []
        for imp_name, pkg_name in key_pkgs.items():
            ok = _check_module(imp_name)
            ver = _get_version(imp_name) if ok else None
            results.append({"module": imp_name, "package": pkg_name, "installed": ok, "version": ver})
        return results

    # 常用包别名映射
    ALIASES = {
        "pillow": "Pillow",
        "pil": "Pillow",
        "opencv": "opencv-python",
        "cv2": "opencv-python",
        "sklearn": "scikit-learn",
        "yaml": "PyYAML",
        "duckduckgo": "duckduckgo-search",
    }

    if action == "list":
        pkgs = _list_installed()
        installed = [p for p in pkgs if p["installed"]]
        missing = [p for p in pkgs if not p["installed"]]
        return {
            "total": len(pkgs),
            "installed": len(installed),
            "missing": len(missing),
            "installed_packages": installed,
            "missing_packages": missing,
        }

    elif action == "check" and module:
        ok = _check_module(module)
        ver = _get_version(module) if ok else None
        return {"module": module, "installed": ok, "version": ver}

    elif action == "install" and packages:
        pkg_list = []
        for p in packages.split(","):
            p = p.strip()
            pkg_list.append(ALIASES.get(p.lower(), p))

        ok, stdout, stderr = _pip_install(pkg_list)
        # 验证
        verified = {}
        for p in pkg_list:
            # 尝试找到对应的 import 名
            imp_name = p.replace("-", "_").lower()
            verified[p] = _check_module(imp_name)

        return {
            "success": ok,
            "packages": pkg_list,
            "verified": verified,
            "all_installed": all(verified.values()),
            "stdout": stdout[-500:] if stdout else "",
        }

    elif action == "ensure":
        """确保依赖就绪 — 检查并自动安装缺失的"""
        pkgs = _list_installed()
        missing = [p["package"] for p in pkgs if not p["installed"] and p["package"] != "unknown"]
        installed = []
        if missing:
            ok, stdout, stderr = _pip_install(missing)
            if ok:
                installed = missing
        return {
            "previously_missing": missing,
            "installed_now": installed,
            "all_ok": len(missing) == 0 or len(installed) == len(missing),
        }

    else:
        return {
            "error": f"未知 action: {action}",
            "supported": ["list", "check", "install", "ensure"],
            "examples": [
                "toolkit_pkg(action='list')",
                "toolkit_pkg(action='check', module='jieba')",
                "toolkit_pkg(action='install', packages='jieba,Pillow')",
                "toolkit_pkg(action='ensure')",
            ],
        }


def meta_toolkit_pkg() -> dict:
    return {"type": "function", "function": {"name": "toolkit_pkg", "description": "智能 Python 包管理工具。list=列出关键依赖状态, check=检查单个模块, install=安装包(支持别名如pil→Pillow), ensure=自动安装所有缺失依赖。支持批量逗号分隔。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "check", "install", "ensure"], "description": "操作类型"}, "packages": {"type": "string", "description": "[install] 包名，逗号分隔。支持别名：pil/pillow→Pillow, yaml→PyYAML, cv2→opencv-python"}, "module": {"type": "string", "description": "[check] 模块名，如 jieba, PIL, requests"}}, "required": ["action"]}}}
