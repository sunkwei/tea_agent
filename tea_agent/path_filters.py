"""项目树遍历的目录排除集 —— 唯一事实源。

## 为什么需要这个模块

本项目历史上在多处扫描器里**各自维护内联排除列表**，且普遍漏掉
``node_modules`` / ``build_mini_dist`` 等目录。后果不是「慢一点」而是
**正确性事故**（2026-09-23 实测）：

- ``toolkit_explr``：文档/索引产物混入 **344 条** ``node_modules`` 伪路径，
  ``docs/API参考.md`` 把第三方捆绑的 Python 当本项目 API 记录；
  ``symbol_index.json`` 从 1.9 MB 膨胀到 48 MB（符号数 8865 → 59182）
- ``auto_fix`` / ``toolkit_format_code``：会**改写文件**——一旦扫进
  ``node_modules`` 下第三方 Python，就会去「修复/格式化」别人的代码
- ``toolkit_code_review`` / ``toolkit_batch_process``：报告与批量替换同样被污染

## 用法

目录遍历一律经由 ``prune_dirs``（``os.walk`` 就地裁剪）或 ``iter_files``
（带裁剪的递归遍历），**不要**再写内联 `dirs[:] = [...]`：

    for f in iter_files(root, "*.py"):
        ...

    for dirpath, dirs, files in os.walk(root):
        prune_dirs(dirs)      # 先裁剪再处理 files
        ...

新增扫描器时若确实需要额外排除目录，用 ``extra=`` 传参，别另起一套列表。
"""

from __future__ import annotations

import fnmatch
import os

#: 默认排除的目录名（按名字匹配，任意层级）
PRUNE_DIRS: frozenset[str] = frozenset({
    # 版本控制 / 缓存 / 运行产物
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tea_agent_run", ".tox", ".noxtest",
    # 虚拟环境
    ".venv", "venv", "env", ".env",
    # 第三方依赖
    "node_modules", "site-packages", "bower_components",
    # 构建产物
    "build", "build_mini_dist", "build_nuitka_dist", "dist", "target",
    "out", "output", ".eggs",
    # 其它
    "tmp", ".cache",
})


def prune_dirs(dirs, extra=()) -> None:
    """就地裁剪 ``os.walk`` 的 ``dirs`` 列表。

    **必须传原始的 dirs 列表本身**：``os.walk`` 的裁剪是就地生效语义，
    返回新列表等于没排除（顶层目录仍会被递归进入）。

    Args:
        dirs: ``os.walk`` 产出的目录名列表（原地修改）
        extra: 本次额外排除的目录名（可迭代）
    """
    skip = PRUNE_DIRS if not extra else (PRUNE_DIRS | set(extra))
    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip]


def is_junk_path(path: str, extra=()) -> bool:
    """判断路径（文件或目录）是否落在被排除的目录内。

    用于已经拿到完整路径、无法在遍历时裁剪的场景（如对 ``rglob``
    结果做兜底过滤、或校验用户显式传入的单个文件路径）。

    Args:
        path: 待判断的路径（绝对或相对均可）
        extra: 额外视为垃圾的目录名

    Returns:
        True 表示该路径位于排除目录内，应当跳过。
    """
    skip = PRUNE_DIRS if not extra else (PRUNE_DIRS | set(extra))
    parts = str(path).replace("\\", "/").split("/")
    return any(p in skip for p in parts[:-1])


def iter_files(root: str, pattern: str = "*.py", extra=()):
    """带目录裁剪的递归文件遍历。

    替代 ``Path(root).rglob(pattern)`` —— 后者会进入 ``node_modules`` /
    ``build`` 等目录，既拖慢速度，也会把第三方文件当项目源码。

    Args:
        root: 遍历根目录
        pattern: 文件名通配（``fnmatch`` 语法，如 ``*.py``）
        extra: 额外排除的目录名

    Yields:
        str: 命中的文件绝对路径
    """
    root = os.path.abspath(root)
    if os.path.isfile(root):
        if fnmatch.fnmatch(os.path.basename(root), pattern):
            yield root
        return
    for dirpath, dirs, files in os.walk(root):
        prune_dirs(dirs, extra)
        for fn in files:
            if fnmatch.fnmatch(fn, pattern):
                yield os.path.join(dirpath, fn)
