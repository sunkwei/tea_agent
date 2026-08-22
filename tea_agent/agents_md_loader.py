"""
AGENTS.md 分层指令加载器 — 借鉴 OpenAI Codex agents_md.rs

三级分层：
  1. 用户级: ~/.tea_agent/AGENTS.md（跨项目通用指令）
  2. 项目级: 从项目根到 cwd 路径上收集的所有 AGENTS.md（拼接）
  3. 本地覆盖: AGENTS.override.md（优先级最高，追加在最后）

字节预算：project_doc_max_bytes 限制项目文档总量，超出即截断，
防止 AGENTS.md 无限膨胀挤占上下文（对应 Codex project_doc_max_bytes）。

用法：
    from tea_agent.agents_md_loader import load_agents_md, find_project_root

    loaded = load_agents_md(cwd=".", max_bytes=16*1024)
    text = loaded.text          # 拼接后的文本（LoadedAgentsMd.text 属性）
    sources = loaded.sources    # 来源文件列表（LoadedAgentsMd.sources 属性）
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("agents_md_loader")

__all__ = [
    "find_project_root",
    "collect_project_agents_md",
    "load_user_agents_md",
    "load_agents_md",
    "DEFAULT_PROJECT_ROOT_MARKERS",
    "DEFAULT_MAX_BYTES",
]

DEFAULT_PROJECT_ROOT_MARKERS = (".git",)
DEFAULT_MAX_BYTES = 32 * 1024  # 32KB 项目文档预算
DEFAULT_USER_AGENTS_MD = os.path.join("~", ".tea_agent", "AGENTS.md")
OVERRIDE_FILENAME = "AGENTS.override.md"


@dataclass
class LoadedAgentsMd:
    """加载结果。

    Attributes:
        text: 拼接后的指令文本（已应用字节预算）
        sources: 来源文件绝对路径列表（按优先级顺序）
        total_bytes: 原始总字节数
        truncated: 是否被字节预算截断
    """

    text: str = ""
    sources: list[str] = field(default_factory=list)
    total_bytes: int = 0
    truncated: bool = False


def find_project_root(
    cwd: str | None = None,
    markers: tuple[str, ...] = DEFAULT_PROJECT_ROOT_MARKERS,
) -> str:
    """从 cwd 向上查找项目根目录（含 markers 的最深祖先）。

    Args:
        cwd: 起始目录（默认当前工作目录）
        markers: 项目根标记文件/目录（默认 .git）

    Returns:
        项目根绝对路径；找不到时返回 cwd 本身
    """
    cwd = os.path.abspath(cwd or os.getcwd())
    if not markers:
        return cwd

    current = cwd
    while True:
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return cwd
        current = parent


def _read_file(path: str) -> str:
    """读取文本文件（UTF-8，失败返回空串）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.debug(f"读取 {path} 失败: {e}")
        return ""


def collect_project_agents_md(cwd: str | None = None) -> list[str]:
    """收集项目级 AGENTS.md（项目根 → cwd 路径上所有）。

    Args:
        cwd: 起始目录

    Returns:
        按优先级排列的文件绝对路径列表
    """
    cwd = os.path.abspath(cwd or os.getcwd())
    root = find_project_root(cwd)

    files: list[str] = []
    # 从项目根向下收集到 cwd（根级优先）
    current = root
    while True:
        md_path = os.path.join(current, "AGENTS.md")
        if os.path.isfile(md_path):
            files.append(md_path)
        if current == cwd:
            break
        # 当前目录必须是 cwd 的祖先，否则停止
        if not cwd.startswith(current):
            break
        remaining = os.path.relpath(cwd, current)
        if remaining == "." or remaining.startswith(".."):
            break
        next_segment = remaining.split(os.sep)[0]
        current = os.path.join(current, next_segment)

    # 本地覆盖（最高优先级，追加在最后）
    override = os.path.join(cwd, OVERRIDE_FILENAME)
    if os.path.isfile(override):
        files.append(override)

    return files


def load_user_agents_md() -> list[str]:
    """收集用户级 AGENTS.md（~/.tea_agent/AGENTS.md）。"""
    path = os.path.expanduser(DEFAULT_USER_AGENTS_MD)
    if os.path.isfile(path):
        return [path]
    return []


def load_agents_md(
    cwd: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    include_user: bool = True,
    include_project: bool = True,
) -> LoadedAgentsMd:
    """加载 AGENTS.md 分层指令。

    Args:
        cwd: 起始目录（默认当前工作目录）
        max_bytes: 项目文档字节预算（截断上限）
        include_user: 是否包含用户级指令
        include_project: 是否包含项目级指令

    Returns:
        LoadedAgentsMd 结果
    """
    sources: list[str] = []
    if include_user:
        sources.extend(load_user_agents_md())
    if include_project:
        sources.extend(collect_project_agents_md(cwd))

    if not sources:
        return LoadedAgentsMd()

    parts: list[str] = []
    total = 0
    truncated = False
    used_sources: list[str] = []

    for path in sources:
        content = _read_file(path).strip()
        if not content:
            continue
        # 带来源标记，便于模型理解指令层级
        # 相对路径标签；跨盘（Windows）时 os.path.relpath 抛 ValueError，回退为原始路径
        try:
            label = os.path.relpath(path, os.getcwd())
        except ValueError:
            label = path
        block = f"### [{label}]\n{content}"
        # 预算按 UTF-8 字节计数（中文 1 字 3 字节，len() 字符数会低估 ~3x）
        block_bytes = len(block.encode("utf-8"))
        if max_bytes > 0 and total + block_bytes > max_bytes:
            # 截断当前块（保留头部，UTF-8 安全切字节）
            remaining = max_bytes - total
            if remaining > 100:
                truncated_block = block.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
                parts.append(truncated_block + "\n... [已截断: 超出字节预算]")
                total += len(truncated_block.encode("utf-8"))
                truncated = True
                used_sources.append(path)
            break
        parts.append(block)
        total += block_bytes
        used_sources.append(path)

    text = "\n\n".join(parts)
    if not text:
        return LoadedAgentsMd()

    return LoadedAgentsMd(
        text=text,
        sources=used_sources,
        total_bytes=total,
        truncated=truncated,
    )
