# @2026-05-23 gen by tea_agent, extracted from tlk.py Toolkit.reload()
"""ToolLoader: 扫描目录、动态加载 toolkit_*.py，提取 func + meta。"""

import os.path as osp
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger("toolkit")


class ToolLoader:
    """工具加载器：扫描 builtin_dir + user_dir，exec() 加载 .py 文件。
    
    使用方式:
        loader = ToolLoader(builtin_dir, user_dir)
        result = loader.reload_all()
        # result = {"funcs": {...}, "metas": {...}, "invalid": [...]}
    """

    def __init__(self, builtin_dir: str, user_dir: str = None):
        self.builtin_dir = builtin_dir
        self.user_dir = user_dir

    @staticmethod
    def check_meta(meta: dict) -> bool:
        """验证 meta 结构合法性。"""
        if "type" not in meta or meta["type"] != "function":
            return False
        func = meta.get("function", {})
        if "description" not in func or "name" not in func:
            return False
        return True

    def reload_all(self) -> dict:
        """扫描所有目录，加载工具，返回 {funcs, metas, invalid}。"""
        result = {"funcs": {}, "metas": {}, "invalid": []}

        dirs_to_load = []
        if osp.exists(self.builtin_dir):
            dirs_to_load.append(("builtin", self.builtin_dir))
        if self.user_dir and osp.exists(self.user_dir):
            dirs_to_load.append(("user", self.user_dir))

        for source, d in dirs_to_load:
            dir_result = self._scan_directory(d, source)
            result["funcs"].update(dir_result["funcs"])
            result["metas"].update(dir_result["metas"])
            result["invalid"].extend(dir_result["invalid"])

        return result

    def _scan_directory(self, directory: str, source_name: str) -> dict:
        """扫描单个目录，加载所有 toolkit_*.py 文件。"""
        result = {"funcs": {}, "metas": {}, "invalid": []}

        try:
            filenames = __import__("os").listdir(directory)
        except OSError:
            return result

        for filename in filenames:
            if not (filename.endswith(".py") and filename.startswith("toolkit_")):
                continue

            name = filename[:-3]
            filepath = osp.join(directory, filename)

            try:
                with open(filepath, encoding="utf-8") as f:
                    code = f.read()

                safe_globals = {"__builtins__": __builtins__}
                local_vars = {}
                exec(code, safe_globals, local_vars)
                safe_globals.update(local_vars)

                func = local_vars.get(name)
                func_meta = local_vars.get(f"meta_{name}")

                if not callable(func):
                    result["invalid"].append(
                        {"name": name, "reason": f"{name} is NOT callable"})
                    continue
                if not callable(func_meta):
                    result["invalid"].append(
                        {"name": name, "reason": f"meta_{name} not callable"})
                    continue

                meta = func_meta()
                if not self.check_meta(meta):
                    result["invalid"].append(
                        {"name": name, "reason": "meta invalid"})
                    continue

                result["funcs"][name] = func
                result["metas"][name] = meta

            except Exception as e:
                result["invalid"].append(
                    {"name": name, "reason": f"{e} ({source_name}: {filename})"})

        return result
