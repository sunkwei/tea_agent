"""存储作用域解析 —— 项目级(.tea_agent_run) 与临时目录回退。

## 默认行为（TEA_STORAGE_SCOPE 未设置 / auto）

1. **启动目录可写** → ``<启动目录>/.tea_agent_run/storage.db``（项目级，随项目隔离）
2. **启动目录 == 用户主目录** → ``~/.tea_agent/storage.db``
   （主目录即项目，有意不另建 ``.tea_agent_run`` 以免污染 ``~``）
3. **启动目录不可写**（无法创建 / 无权限 / 无磁盘空间）→ 系统临时目录
   ``<tempdir>/tea_agent_<项目名>_<hash8>.db``，且每轮会话结束时**明确提示**用户
   手动复制到可靠位置（见 ``storage_notice``）
4. **临时目录也不可用** → 最后兜底用户级 ``~/.tea_agent/``（并告警）

## 显式配置优先

- ``storage_scope=user`` → 用户级（durable，用户主动选择，不提示）
- 显式 ``data_dir`` / 绝对 ``db_path`` → 尊重用户配置，不自动项目化

## 旧库迁移

同目录下若存在旧名 ``chat_history.db`` 而新名 ``storage.db`` 不存在，自动改名
（连带 ``-wal`` / ``-shm``，避免留下半套 WAL 导致数据不一致）。
迁移失败时**沿用旧路径**而不是新建空库 —— 宁可名字旧，也不能让用户看不到历史。

用法::

    from tea_agent.storage_scope import resolve_db_path, storage_notice
    db = resolve_db_path(user_db_abs="/home/u/.tea_agent/storage.db")
    if notice := storage_notice(db):
        print(notice)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "PROJECT_RUN_DIR",
    "DEFAULT_DB_NAME",
    "LEGACY_DB_NAME",
    "VALID_SCOPES",
    "project_run_dir",
    "temp_db_path",
    "is_temp_fallback",
    "storage_notice",
    "resolve_scope",
    "resolve_db_path",
]

PROJECT_RUN_DIR = ".tea_agent_run"

#: 项目级 / 用户级 db 的默认文件名
DEFAULT_DB_NAME = "storage.db"

#: 历史文件名（自动迁移，见模块 docstring）
LEGACY_DB_NAME = "chat_history.db"

VALID_SCOPES = ("auto", "project", "user")


def _home_abs() -> str:
    """返回用户主目录绝对路径（异常时回退 /）。"""
    try:
        return os.path.abspath(os.path.expanduser("~"))
    except Exception:
        return os.path.abspath("/")


def _same_path(a: str, b: str) -> bool:
    """跨平台比较两个路径是否指向同一位置（Windows 大小写不敏感）。"""
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def _is_home_dir(cwd: str | None = None) -> bool:
    """启动目录是否就是用户主目录。"""
    return _same_path(os.path.abspath(cwd or os.getcwd()), _home_abs())


def resolve_scope(storage_scope_cfg: str | None = None) -> str:
    """解析最终存储作用域。

    优先级：环境变量 TEA_STORAGE_SCOPE > config paths.storage_scope > "auto"。
    非法值一律回退 "auto"。

    Args:
        storage_scope_cfg: config 中 paths.storage_scope 字段值

    Returns:
        "auto" | "project" | "user"
    """
    env = os.environ.get("TEA_STORAGE_SCOPE", "").strip().lower()
    if env in VALID_SCOPES:
        return env
    cfg = (storage_scope_cfg or "").strip().lower()
    if cfg in VALID_SCOPES:
        return cfg
    return "auto"


def project_run_dir(cwd: str | None = None) -> str | None:
    """定位（必要时创建）启动目录下的 .tea_agent_run 项目运行目录。

    规则：
    - 启动目录 == 用户主目录时不创建（主目录走用户级 db，避免污染 ~）
    - 目录已存在 / 可创建且可写 → 返回绝对路径
    - 不可创建 / 不可写 → 返回 None（调用方回退临时目录）

    Args:
        cwd: 启动目录；默认 os.getcwd()

    Returns:
        项目运行目录绝对路径；不可用时 None
    """
    base = os.path.abspath(cwd or os.getcwd())
    if _is_home_dir(base):
        return None
    run = os.path.join(base, PROJECT_RUN_DIR)
    try:
        os.makedirs(run, exist_ok=True)
        # 写探针验证可写（Windows 上 os.access 对 ACL 可能误报）
        probe = os.path.join(run, ".write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return run
    except OSError:
        return None


def temp_db_path(cwd: str | None = None) -> str:
    """临时回退 db 路径：``<tempdir>/tea_agent_<项目名>_<hash8>.db``。

    按项目目录派生（同一项目在多次启动间复用同一临时库，保证会话连续性），
    且文件名可读、带 ``tea_agent_`` 前缀便于用户识别与手动复制。

    Args:
        cwd: 启动目录；默认 os.getcwd()

    Returns:
        临时 db 绝对路径
    """
    base = os.path.abspath(cwd or os.getcwd())
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(base)) or "session"
    digest = hashlib.sha1(base.encode("utf-8", "replace")).hexdigest()[:8]
    return os.path.join(tempfile.gettempdir(), f"tea_agent_{name[:24]}_{digest}.db")


def is_temp_fallback(db_path: str) -> bool:
    """判断 db 路径是否为「临时目录回退」产物。

    判定依据：位于系统临时目录下且文件名带 ``tea_agent_`` 前缀。
    任何异常一律返回 False（宁可漏提示，不可误报）。
    """
    if not db_path:
        return False
    try:
        tmp = os.path.abspath(tempfile.gettempdir())
        p = os.path.abspath(db_path)
        if os.path.commonpath([tmp, p]) != tmp:
            return False
    except Exception:
        return False
    base = os.path.basename(p)
    return base.startswith("tea_agent_") and base.endswith(".db")


def storage_notice(db_path: str) -> str | None:
    """返回需要向用户明示的存储提示；无需提示时返回 None。

    仅对「临时目录回退」发声 —— 这是唯一会让用户**丢数据**的情形
    （系统重启 / 清理临时文件即消失），必须每轮提示直到用户搬走。

    Args:
        db_path: 实际使用的 db 路径

    Returns:
        提示文本；无需提示时 None
    """
    if not is_temp_fallback(db_path):
        return None
    return (
        "\n\n---\n"
        f"⚠️ **存储位置提示**：当前 storage.db 为 `{db_path}`\n\n"
        "启动目录无法创建 `.tea_agent_run`（无权限 / 无磁盘空间 / 只读），"
        "数据已写入**系统临时目录**，重启或清理临时文件后**可能丢失**。\n\n"
        "**需要手动复制到可靠的存储位置。**\n"
    )


def _migrate_legacy_db(target: str) -> str:
    """把旧名 db（``chat_history.db``）迁移为 ``storage.db``。

    仅在「目标不存在 + 旧文件存在 + 目标确为默认名」时执行；连带 ``-wal`` /
    ``-shm`` 一起搬，避免留下半套 WAL 导致数据不一致。

    迁移失败时**返回旧路径**（而非新路径）—— 否则调用方会新建一个空库，
    用户会以为历史丢失。宁可文件名旧，也不能让数据不可见。

    Args:
        target: 期望使用的 db 路径

    Returns:
        实际应使用的 db 路径
    """
    try:
        if os.path.basename(target) != DEFAULT_DB_NAME:
            return target  # 用户显式命名 → 不迁移
        if os.path.exists(target):
            return target
        d = os.path.dirname(target) or "."
        legacy = os.path.join(d, LEGACY_DB_NAME)
        if not os.path.exists(legacy):
            return target
        os.replace(legacy, target)
        for suffix in ("-wal", "-shm"):
            lf, tf = legacy + suffix, target + suffix
            if os.path.exists(lf):
                os.replace(lf, tf)
        logger.info("存储库已迁移: %s → %s", legacy, target)
        return target
    except Exception as e:
        logger.warning("存储库迁移失败，沿用旧路径: %s", e)
        try:
            legacy = os.path.join(os.path.dirname(target) or ".", LEGACY_DB_NAME)
            return legacy if os.path.exists(legacy) else target
        except Exception:
            return target


def _ensure_parent_writable(path: str) -> bool:
    """确认路径所在目录可写（写探针，避免 os.access 在 ACL 下误报）。"""
    try:
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".tea_agent_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def resolve_db_path(
    user_db_abs: str,
    db_path_cfg: str = "",
    cwd: str | None = None,
    storage_scope_cfg: str | None = None,
) -> str:
    """解析实际使用的会话 db 路径。

    优先级：
    1. scope == "user"                    → 用户级 db（旧行为，durable）
    2. db_path 显式绝对路径                → 尊重显式（不项目化）
    3. 启动目录 == 主目录                   → 用户级 db（主目录即项目）
    4. scope 为 auto/project 且项目可写     → <项目>/.tea_agent_run/storage.db
    5. 项目目录不可用                      → 系统临时目录（**会提示用户备份**）
    6. 临时目录也不可用                    → 用户级 db（最后兜底）

    注：db 文件名沿用 ``user_db_abs`` 的 basename —— 未配置时为
    ``storage.db``；用户配置了相对 ``db_path`` 时尊重其自定义名。

    Args:
        user_db_abs: 用户级 db 绝对路径（config 原有解析结果）
        db_path_cfg: config 中 paths.db_path 原始配置值（用于绝对路径判定）
        cwd: 启动目录
        storage_scope_cfg: config paths.storage_scope

    Returns:
        实际 db 绝对路径
    """
    scope = resolve_scope(storage_scope_cfg)
    if scope == "user":
        return _migrate_legacy_db(user_db_abs)
    # 用户显式指定了绝对 db 路径 → 尊重自定义位置
    if db_path_cfg and os.path.isabs(os.path.expanduser(db_path_cfg)):
        return _migrate_legacy_db(user_db_abs)

    fname = os.path.basename(user_db_abs) or DEFAULT_DB_NAME

    run = project_run_dir(cwd)
    if run is not None:
        return _migrate_legacy_db(os.path.join(run, fname))

    # 启动目录 == 主目录：主目录即项目，用用户级 db（durable，无需提示）
    if _is_home_dir(cwd):
        return _migrate_legacy_db(user_db_abs)

    # 项目目录不可用 → 临时目录回退（会向用户提示手动备份）
    tmp_db = temp_db_path(cwd)
    if _ensure_parent_writable(tmp_db):
        logger.warning(
            "启动目录不可写，storage.db 回退到临时目录: %s（数据可能丢失，请手动备份）",
            tmp_db,
        )
        return tmp_db

    # 临时目录也不可用 → 最后兜底用户级
    logger.warning(
        "临时目录亦不可写，storage.db 回退到用户级: %s", user_db_abs
    )
    return _migrate_legacy_db(user_db_abs)
