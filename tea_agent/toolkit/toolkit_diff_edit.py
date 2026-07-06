# @2026-06-26 gen by tea-agent, Diff-first 单文件编辑 — 生成 unified diff 预览后原子应用
"""
toolkit_diff_edit — Diff-first 单文件编辑引擎

工作流:
  1. 读取文件 → 匹配 old_text → 归一化换行符
  2. 生成 unified diff 预览
  3. 冲突检测（重复/不存在）
  4. 自动 .bak 时间戳备份
  5. 应用修改 → 返回 diff + 摘要

与 toolkit_edit 比较:
  - 相同接口: file_path / old_text / new_text
  - 额外返回 unified diff 原文 + 行数统计
  - 冲突检测更完善（重复匹配警告）

与 toolkit_diff 比较:
  - 单文件设计，接口更简洁
  - 不做 git stash / lint / test（轻量级）
"""

import difflib
import os
import shutil
from datetime import datetime


def _normalize_newlines(text: str) -> str:
    """统一换行符为 \\n"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _generate_diff(file_path: str, old_text: str, new_text: str) -> str:
    """生成 unified diff 格式的差异对比"""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        n=3,
    )
    return "".join(diff)


def _count_changes(diff: str) -> dict:
    """统计 diff 中的增删行数"""
    added = 0
    removed = 0
    for line in diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {"added": added, "removed": removed}


def toolkit_diff_edit(
    file_path: str,
    old_text: str,
    new_text: str,
    preview: bool = False,
    backup: bool = True,
) -> dict:
    """Diff-first 单文件编辑。

    Args:
        file_path: 目标文件路径（绝对或相对当前目录）
        old_text:  要替换的旧文本（必须精确匹配）
        new_text:  替换后的新文本
        preview:   仅生成 diff 预览，不修改文件
        backup:    是否创建 .bak 时间戳备份

    Returns:
        {
            "ok": bool,
            "diff": str,          # unified diff 原文
            "summary": str,       # 变更摘要（如 "1 file changed, +3/-2 lines"）
            "file_path": str,
            "applied": bool,      # 是否已应用修改
            "bak_path": str|None, # 备份文件路径
            "error": str|None,
        }
    """
    full_path = os.path.abspath(file_path)

    # 1. 读取文件
    if not os.path.exists(full_path):
        return {
            "ok": False, "diff": "", "summary": "",
            "file_path": file_path, "applied": False,
            "bak_path": None,
            "error": f"文件不存在: {file_path}",
        }

    with open(full_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    # 2. 归一化换行符
    content = _normalize_newlines(content)
    old_norm = _normalize_newlines(old_text)
    new_norm = _normalize_newlines(new_text)

    # 3. 冲突检测
    if old_norm not in content:
        return {
            "ok": False, "diff": "", "summary": "",
            "file_path": file_path, "applied": False,
            "bak_path": None,
            "error": f"old_text 在 {file_path} 中未找到（可能已被修改或格式不匹配）",
        }

    occurrences = content.count(old_norm)
    if occurrences > 1:
        # 生成 diff 但警告
        diff = _generate_diff(file_path, old_text, new_text)
        counts = _count_changes(diff)
        return {
            "ok": False, "diff": diff,
            "summary": f"警告: old_text 出现 {occurrences} 次，无法唯一确定",
            "file_path": file_path, "applied": False,
            "bak_path": None,
            "error": f"冲突: old_text 在文件中出现 {occurrences} 次",
        }

    # 4. 生成 diff
    diff = _generate_diff(file_path, old_text, new_text)
    counts = _count_changes(diff)
    file_changed = "+" if counts["added"] or counts["removed"] else "="
    summary = (
        f"{1 if file_changed != '=' else 0} file changed, "
        f"+{counts['added']}/-{counts['removed']} lines"
    )

    # 5. 预览模式
    if preview:
        return {
            "ok": True, "diff": diff, "summary": f"[预览] {summary}",
            "file_path": file_path, "applied": False,
            "bak_path": None, "error": None,
        }

    # 6. 备份
    bak_path = None
    if backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak_path = f"{full_path}.bak.{ts}"
        try:
            shutil.copy2(full_path, bak_path)
        except Exception as e:
            return {
                "ok": False, "diff": diff, "summary": summary,
                "file_path": file_path, "applied": False,
                "bak_path": None,
                "error": f"备份失败: {e}",
            }

    # 7. 应用修改
    try:
        new_content = content.replace(old_norm, new_norm, 1)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        # 恢复备份
        if bak_path and os.path.exists(bak_path):
            shutil.copy2(bak_path, full_path)
        return {
            "ok": False, "diff": diff, "summary": summary,
            "file_path": file_path, "applied": False,
            "bak_path": bak_path,
            "error": f"写入失败: {e}",
        }

    return {
        "ok": True, "diff": diff, "summary": summary,
        "file_path": file_path, "applied": True,
        "bak_path": bak_path, "error": None,
    }


# ── Meta ────────────────────────────────────────────────

def meta_toolkit_diff_edit():
    """Meta for toolkit_diff_edit."""
    return {
        "type": "function",
        "function": {
            "name": "toolkit_diff_edit",
            "description": (
                "Diff-first 单文件编辑工具。接受 file_path/old_text/new_text，"
                "自动生成 unified diff 预览后应用。相比 toolkit_edit 多了 diff 输出和冲突检测。"
                "返回 diff 原文及修改状态。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "目标文件路径",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "要替换的旧文本（精确匹配）",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "替换后的新文本",
                    },
                    "preview": {
                        "type": "boolean",
                        "description": "仅生成 diff 预览，不实际修改文件，默认 false",
                    },
                    "backup": {
                        "type": "boolean",
                        "description": "是否创建 .bak 备份，默认 true",
                    },
                },
                "required": ["file_path", "old_text", "new_text"],
            },
        },
    }
