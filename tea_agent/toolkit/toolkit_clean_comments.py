# version: 1.0.0

"""
清理 Python 文件中的无效注释，强化 pydoc 风格注释。
"""

import ast
import logging
import os
import re

logger = logging.getLogger("toolkit.clean_comments")


def toolkit_clean_comments(
    action: str = "auto",
    file_path: str = "",
    dry_run: bool = False
) -> str:
    """
    清理 Python 文件中的无效注释，强化 pydoc 风格注释。

    Args:
        action: 操作类型 (scan/clean/enhance/auto)
        file_path: 文件路径
        dry_run: 仅预览不实际修改

    Returns:
        清理结果
    """
    logger.info(f"clean_comments: action={action}, file={file_path}")

    if not file_path:
        return "❌ 请指定文件路径"

    if not os.path.exists(file_path):
        return f"❌ 文件不存在: {file_path}"

    if action == "scan":
        return _scan_comments(file_path)
    elif action == "clean":
        return _clean_comments(file_path, dry_run)
    elif action == "enhance":
        return _enhance_comments(file_path, dry_run)
    elif action == "auto":
        return _auto_clean(file_path, dry_run)
    else:
        return f"未知操作: {action}"


def _scan_comments(file_path: str) -> str:
    """扫描文件，识别无效注释。"""
    try:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        issues = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # 检查无效注释模式
            if stripped.startswith("#"):
                comment = stripped[1:].strip()

                # 空注释
                if not comment:
                    issues.append({"line": i, "type": "empty", "content": stripped})

                # 过时的 TODO/FIXME/HACK
                elif re.match(r'^(TODO|FIXME|HACK|XXX|TEMP|TEMPORARY)', comment, re.IGNORECASE):
                    issues.append({"line": i, "type": "todo", "content": stripped})

                # 冗余注释（代码自解释）
                elif re.match(r'^(import|from|def|class|return|if|else|for|while|try|except|finally|with|raise|pass|break|continue)', comment):
                    issues.append({"line": i, "type": "redundant", "content": stripped})

                # 无意义注释
                elif comment in ["...", "---", "===", "***", "###"]:
                    issues.append({"line": i, "type": "meaningless", "content": stripped})

            # 检查缺少 pydoc 的类/方法/全局变量
            elif stripped.startswith("class ") or stripped.startswith("def "):
                # 检查前一行是否有 docstring
                if i > 1:
                    prev_line = lines[i-2].strip()
                    if not (prev_line.startswith('"""') or prev_line.startswith("'''")):
                        issues.append({"line": i, "type": "missing_docstring", "content": stripped})

        # 统计
        stats = {}
        for issue in issues:
            t = issue["type"]
            stats[t] = stats.get(t, 0) + 1

        result = f"📊 扫描结果: {file_path}\n"
        result += f"总行数: {len(lines)}\n"
        result += f"问题数: {len(issues)}\n\n"

        if stats:
            result += "问题类型:\n"
            for t, count in stats.items():
                result += f"  - {t}: {count}\n"

        if issues:
            result += "\n详细问题:\n"
            for issue in issues[:20]:  # 只显示前20个
                result += f"  行 {issue['line']}: [{issue['type']}] {issue['content']}\n"
            if len(issues) > 20:
                result += f"  ... 还有 {len(issues) - 20} 个问题\n"

        return result

    except Exception as e:
        return f"❌ 扫描失败: {e}"


def _clean_comments(file_path: str, dry_run: bool = False) -> str:
    """清理无效注释。"""
    try:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        cleaned_lines = []
        removed_count = 0

        for _i, line in enumerate(lines):
            stripped = line.strip()

            # 跳过空注释
            if stripped == "#":
                removed_count += 1
                continue

            # 跳过无意义注释
            if stripped in ["# ...", "# ---", "# ===", "# ***", "# ###"]:
                removed_count += 1
                continue

            # 跳过过时的 TODO/FIXME（可选，这里保留）
            #     removed_count += 1
            #     continue

            cleaned_lines.append(line)

        if dry_run:
            return f"🔍 预览模式: {file_path}\n将删除 {removed_count} 行无效注释"

        # 写入清理后的内容
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(cleaned_lines)

        return f"✅ 清理完成: {file_path}\n删除了 {removed_count} 行无效注释"

    except Exception as e:
        return f"❌ 清理失败: {e}"


def _enhance_comments(file_path: str, dry_run: bool = False) -> str:
    """强化 pydoc 风格注释。"""
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        # 解析 AST
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            return f"❌ 语法错误: {e}"

        content.split("\n")
        enhancements = []

        # 遍历 AST 节点
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # 检查类是否有 docstring
                if not ast.get_docstring(node):
                    enhancements.append({
                        "line": node.lineno,
                        "type": "class",
                        "name": node.name,
                        "suggestion": f'"""{node.name} 类。"""'
                    })

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 检查方法是否有 docstring
                if not ast.get_docstring(node):
                    # 生成参数列表
                    args = []
                    for arg in node.args.args:
                        if arg.arg != "self":
                            args.append(arg.arg)

                    if args:
                        args_str = ", ".join(args)
                        suggestion = f'"""{node.name} 方法。Args: {args_str}。"""'
                    else:
                        suggestion = f'"""{node.name} 方法。"""'

                    enhancements.append({
                        "line": node.lineno,
                        "type": "method",
                        "name": node.name,
                        "suggestion": suggestion
                    })

        if dry_run:
            result = f"🔍 预览模式: {file_path}\n"
            result += f"需要添加 {len(enhancements)} 个 docstring\n\n"
            for e in enhancements[:10]:
                result += f"  行 {e['line']}: [{e['type']}] {e['name']}\n"
                result += f"    建议: {e['suggestion']}\n"
            return result

        # 实际添加 docstring（需要更复杂的逻辑）
        # 这里只是示例，实际实现需要插入到正确位置
        return f"📝 增强建议: {file_path}\n需要添加 {len(enhancements)} 个 docstring"

    except Exception as e:
        return f"❌ 增强失败: {e}"


def _auto_clean(file_path: str, dry_run: bool = False) -> str:
    """自动执行所有操作。"""
    result = f"🔄 自动清理: {file_path}\n\n"

    # 1. 扫描
    scan_result = _scan_comments(file_path)
    result += scan_result + "\n\n"

    # 2. 清理
    clean_result = _clean_comments(file_path, dry_run)
    result += clean_result + "\n\n"

    # 3. 增强建议
    enhance_result = _enhance_comments(file_path, dry_run)
    result += enhance_result

    return result


def meta_toolkit_clean_comments() -> dict:
    return {"type": "function", "function": {"name": "toolkit_clean_comments", "description": "清理 Python 文件中的无效注释，强化 pydoc 风格注释。\n\n功能：\n- scan: 扫描文件，识别无效注释\n- clean: 清理无效注释\n- enhance: 强化 pydoc 风格注释\n- auto: 自动执行所有操作\n\n返回：清理结果", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["scan", "clean", "enhance", "auto"], "description": "操作类型"}, "file_path": {"type": "string", "description": "文件路径"}, "dry_run": {"type": "boolean", "description": "仅预览不实际修改", "default": False}}, "required": ["action", "file_path"]}}}
