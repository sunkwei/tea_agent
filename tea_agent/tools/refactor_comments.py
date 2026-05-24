"""
Refactor tea_agent Python files:
  1. Remove all inline # comments inside function/method bodies
  2. Ensure all functions/methods/classes have pydoc-style docstrings

Run: python3 tea_agent/tools/refactor_comments.py [--dry-run] [file1.py ...]
"""

import ast
import io
import os
import sys
import tokenize
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DQ3 = chr(34) * 3



def get_function_body_ranges(source: str) -> list:
    """
    Use AST to find (start, end, name) of all function/method bodies

    Args:
        source (str): Description.

    Returns:
        list: Description.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    ranges = []

    class BodyFinder(ast.NodeVisitor):
        """BodyFinder class."""
        def visit_FunctionDef(self, node):
            """
            FunctionDef.

            Args:
                node: Description.
            """
            body_start = node.lineno - 1
            body_end = node.end_lineno - 1
            ranges.append((body_start, body_end, node.name))
            self.generic_visit(node)

    BodyFinder().visit(tree)
    return ranges



def strip_inline_comments(source: str) -> str:
    """
    Remove all # comments: standalone lines and inline trailing comments.
    Preserves shebang (line 1) and encoding declarations.

    Args:
        source (str): Description.

    Returns:
        str: Description.
    """
    lines = source.split('\n')
    lines_to_remove = set()
    lines_to_modify = {}

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return source

    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        lineno = tok.start[0] - 1
        col = tok.start[1]
        comment_text = tok.string.strip()

        if lineno == 0 and comment_text.startswith('!'):
            continue
        if 'coding' in comment_text and lineno <= 1:
            continue

        line = lines[lineno] if lineno < len(lines) else ""
        stripped = line.lstrip()
        if stripped.startswith('#'):
            lines_to_remove.add(lineno)
        elif '#' in line:
            comment_pos = line.find('#', col)
            if comment_pos >= 0:
                lines_to_modify[lineno] = line[:comment_pos].rstrip()

    result = []
    for i, line in enumerate(lines):
        if i in lines_to_remove:
            continue
        if i in lines_to_modify:
            result.append(lines_to_modify[i])
        else:
            result.append(line)

    return '\n'.join(result)



def generate_function_docstring(node: ast.FunctionDef, existing_doc: str = "") -> str:
    """Generate pydoc docstring for a function/method.

    Args:
        node: The AST FunctionDef node.
        existing_doc: Existing docstring text if any.

    Returns:
        Docstring text lines (without quotes, with proper inner indentation).
    """
    is_method = bool(node.args.args) and node.args.args[0].arg in ('self', 'cls')

    summary = ""
    if existing_doc:
        for line in existing_doc.strip().split('\n'):
            line = line.strip()
            if line and not line.startswith(':') and not line.startswith('Args:') \
               and not line.startswith('Returns:') and not line.startswith('Raises:'):
                summary = line.rstrip('.')
                break

    if not summary:
        name = node.name
        for pfx in ['visit_', 'handle_', '_']:
            if name.startswith(pfx) and len(name) > len(pfx):
                name = name[len(pfx):]
                break
        summary = name.replace('_', ' ').strip()
        summary = summary[0].upper() + summary[1:] + "." if summary else f"{node.name}."

    doc_lines = [summary]

    params = []
    for arg in node.args.args:
        if is_method and arg.arg in ('self', 'cls'):
            continue
        params.append(arg.arg)

    type_hints = {}
    for arg in node.args.args:
        if arg.annotation:
            try:
                type_hints[arg.arg] = ast.unparse(arg.annotation)
            except Exception:
                pass

    if params or node.args.vararg or node.args.kwarg:
        doc_lines.append("")
        doc_lines.append("Args:")
        for pname in params:
            ptype = type_hints.get(pname, "")
            desc = f"{pname}: Description."
            if ptype:
                desc = f"{pname} ({ptype}): Description."
            doc_lines.append(f"    {desc}")
        if node.args.vararg:
            doc_lines.append(f"    *{node.args.vararg.arg}: Variable length arguments.")
        if node.args.kwarg:
            doc_lines.append(f"    **{node.args.kwarg.arg}: Keyword arguments.")

    if node.returns:
        try:
            rtype = ast.unparse(node.returns)
            doc_lines.append("")
            doc_lines.append("Returns:")
            doc_lines.append(f"    {rtype}: Description.")
        except Exception:
            pass

    return '\n'.join(doc_lines)


def generate_class_docstring(node: ast.ClassDef) -> str:
    """
    Generate a basic docstring for a class

    Args:
        node (ast.ClassDef): Description.

    Returns:
        str: Description.
    """
    return f"{node.name} class."



def has_docstring_node(node) -> bool:
    """
    Check if AST node already has a docstring

    Args:
        node: Description.

    Returns:
        bool: Description.
    """
    if node.body and isinstance(node.body[0], ast.Expr):
        val = node.body[0].value
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            return True
    return False


def get_existing_doc(node):
    """
    Get existing docstring text from AST node, or empty string

    Args:
        node: Description.
    """
    if has_docstring_node(node):
        return node.body[0].value.value.strip()
    return ""


def looks_like_pydoc(doc: str) -> bool:
    """
    Check if docstring already resembles pydoc format

    Args:
        doc (str): Description.

    Returns:
        bool: Description.
    """
    markers = ['Args:', 'Returns:', 'Raises:', ':param', ':type', ':returns:', ':rtype:']
    return any(m in doc for m in markers)


def format_docstring_block(text: str, base_indent: str) -> str:
    """Wrap docstring text in triple-quotes with proper indentation.

    Args:
        text: The docstring content (without surrounding quotes).
        base_indent: The base indentation (e.g., '        ').

    Returns:
        Complete docstring block as a multi-line string.
    """
    content_lines = text.split('\n')
    if len(content_lines) == 1:
        return f'{base_indent}{DQ3}{content_lines[0]}{DQ3}'

    result = [f'{base_indent}{DQ3}']
    for line in content_lines:
        if line.strip():
            result.append(f'{base_indent}{line}')
        else:
            result.append('')
    result.append(f'{base_indent}{DQ3}')
    return '\n'.join(result)


def insert_docstrings(source: str) -> tuple:
    """Insert/convert docstrings for all functions/classes.

    Returns:
        (new_source, num_added, num_converted)
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, 0, 0

    lines = source.split('\n')
    added = 0
    converted = 0
    edits = []

    class DocProcessor(ast.NodeVisitor):
        """DocProcessor class."""
        def visit_FunctionDef(self, node):
            """
            FunctionDef.

            Args:
                node: Description.
            """
            nonlocal added, converted
            existing = get_existing_doc(node)
            base_indent = ' ' * (node.col_offset + 4)

            if not existing:
                doc_text = generate_function_docstring(node)
                block = format_docstring_block(doc_text, base_indent)
                insert_at = node.body[0].lineno - 1
                edits.append((insert_at, 'insert', block))
                added += 1
            elif not looks_like_pydoc(existing):
                doc_text = generate_function_docstring(node, existing)
                block = format_docstring_block(doc_text, base_indent)
                start = node.body[0].lineno - 1
                end = node.body[0].end_lineno - 1
                edits.append((start, 'replace', (end, block)))
                converted += 1
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            """
            ClassDef.

            Args:
                node: Description.
            """
            nonlocal added
            existing = get_existing_doc(node)
            base_indent = ' ' * (node.col_offset + 4)

            if not existing:
                doc_text = generate_class_docstring(node)
                block = format_docstring_block(doc_text, base_indent)
                insert_at = node.body[0].lineno - 1
                edits.append((insert_at, 'insert', block))
                added += 1
            self.generic_visit(node)

    DocProcessor().visit(tree)

    if not edits:
        return source, 0, 0

    edits.sort(key=lambda e: e[0], reverse=True)

    for edit in edits:
        if edit[1] == 'insert':
            insert_lineno, _, block = edit
            block_lines = block.split('\n')
            for bl in reversed(block_lines):
                lines.insert(insert_lineno, bl)
        elif edit[1] == 'replace':
            start, _, (end, block) = edit
            block_lines = block.split('\n')
            lines[start:end + 1] = block_lines

    return '\n'.join(lines), added, converted



def process_file(filepath: str, dry_run: bool = False) -> dict:
    """Process one Python file, applying comment stripping and docstring generation.

    Args:
        filepath (str): Path to the Python file.
        dry_run (bool): If True, preview only.

    Returns:
        dict: Statistics about changes made.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        original = f.read()

    after_comments = strip_inline_comments(original)
    comments_removed = len(original.split('\n')) - len(after_comments.split('\n'))

    after_docs, added, converted = insert_docstrings(after_comments)

    result = after_docs

    stats = {
        'file': filepath,
        'changed': result != original,
        'comments_removed': comments_removed,
        'docstrings_added': added,
        'docstrings_converted': converted,
    }

    if stats['changed'] and not dry_run:
        bak = filepath + '.bak.refactor'
        with open(bak, 'w', encoding='utf-8') as f:
            f.write(original)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(result)

    return stats



def main():
    """Main entry point"""
    import argparse
    ap = argparse.ArgumentParser(description="Refactor comments and docstrings")
    ap.add_argument('--dry-run', action='store_true', help='Preview only')
    ap.add_argument('files', nargs='*', help='Specific files to process')
    args = ap.parse_args()

    if args.files:
        files = args.files
    else:
        files = []
        tea_dir = PROJECT_ROOT / 'tea_agent'
        for root, dirs, filenames in os.walk(tea_dir):
            dirs[:] = [d for d in dirs if '__pycache__' not in d]
            for fn in filenames:
                if fn.endswith('.py') and not fn.endswith('.bak'):
                    files.append(os.path.join(root, fn))

    total_comments = 0
    total_added = 0
    total_converted = 0
    changed_files = 0

    for fpath in sorted(files):
        try:
            stats = process_file(fpath, dry_run=args.dry_run)
            if stats['changed']:
                changed_files += 1
                total_comments += stats['comments_removed']
                total_added += stats['docstrings_added']
                total_converted += stats['docstrings_converted']
                tag = "[DRY-RUN]" if args.dry_run else "[OK]"
                print(f"  {tag} {stats['file']}: "
                      f"-{stats['comments_removed']} comments, "
                      f"+{stats['docstrings_added']} docs, "
                      f"~{stats['docstrings_converted']} converted")
        except Exception as e:
            print(f"  [ERR] {fpath}: {e}")

    tag = "Would change" if args.dry_run else "Changed"
    print(f"\n{tag} {changed_files} files. "
          f"Comments removed: {total_comments}, "
          f"Docstrings added: {total_added}, "
          f"Docstrings converted: {total_converted}")


if __name__ == '__main__':
    main()
