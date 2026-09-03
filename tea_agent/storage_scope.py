"""
存储作用域解析模块 — 项目级(.tea_agent_run) 与用户级(~/.tea_agent) 分层。

背景（Storage 模式重构）：
- 保留用户级 db：$HOME/.tea_agent/ 下（config、用户默认 data_dir）
- 新增项目级 db：启动目录的 .tea_agent_run/ 下，主题/会话/记忆默认落这里
- 回退规则：启动目录不可写（无法创建 .tea_agent_run）时才使用用户级 db

作用域取值（由环境变量 TEA_STORAGE_SCOPE 或 config paths.storage_scope 决定）：
- "auto"（默认）: 启动目录可写 → 项目级；否则回退用户级
- "project"      : 强制项目级（不可写时同样回退用户级，保证可用）
- "user"         : 强制用户级（旧行为，数据全在 ~/.tea_agent）

用法：
    from tea_agent.storage_scope import resolve_db_path, project_run_dir
    db = resolve_db_path(user_db_abs="/home/u/.tea_agent/chat_history.db",
                         db_path_cfg="ds_flash.db")
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "PROJECT_RUN_DIR",
    "VALID_SCOPES",
    "project_run_dir",
    "resolve_scope",
    "resolve_db_path",
]

PROJECT_RUN_DIR = ".tea_agent_run"

VALID_SCOPES = ("auto", "project", "user")


def _home_abs() -> str:
    """返回用户主目录绝对路径（异常时回退 /）。"""
    try:
        return os.path.abspath(os.path.expanduser("~"))
    except Exception:
        return os.path.abspath("/")


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
    - 不可创建 / 不可写 → 返回 None（调用方回退用户级 db）

    Args:
        cwd: 启动目录；默认 os.getcwd()

    Returns:
        项目运行目录绝对路径；不可用时 None
    """
    base = os.path.abspath(cwd or os.getcwd())
    home = _home_abs()
    if os.path.normcase(base) == os.path.normcase(home):
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


def resolve_db_path(
    user_db_abs: str,
    db_path_cfg: str = "",
    cwd: str | None = None,
    storage_scope_cfg: str | None = None,
) -> str:
    """解析实际使用的会话 db 路径（项目级优先，用户级回退）。

    优先级：
    1. scope == "user"                    → 用户级 db（旧行为）
    2. db_path 显式绝对路径                → 尊重显式（不项目化）
    3. scope 为 auto/project 且项目可写     → <项目>/.tea_agent_run/<basename>
    4. 其余                               → 用户级 db

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
        return user_db_abs
    # 用户显式指定了绝对 db 路径 → 尊重自定义位置
    if db_path_cfg and os.path.isabs(os.path.expanduser(db_path_cfg)):
        return user_db_abs
    run = project_run_dir(cwd)
    if run is None:
        return user_db_abs
    fname = os.path.basename(user_db_abs) or "chat_history.db"
    return os.path.join(run, fname)
