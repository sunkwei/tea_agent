# version: 2.1.0 — Printer-friendly PDF export with table support

import contextlib
import json
import logging
import os
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger("export_pdf")

def _find_db_path():
    try:
        from tea_agent.config import load_config
        cfg = load_config()
        db = cfg.paths.db_path_abs
        if db and os.path.exists(db):
            return db
    except Exception:
        pass
    home_db = str(Path.home() / ".tea_agent" / "chat_history.db")
    if os.path.exists(home_db):
        return home_db
    for p in ["chat_history.db", "tea_agent/chat_history.db"]:
        if os.path.exists(p):
            return p
    return None


def _sanitize(text):
    """Clean text while preserving Unicode."""
    if not text:
        return ""
    return text.replace("\x00", "")


def _detect_content_type(content):
    """Detect whether tool result content is text, code-friendly, or binary.

    Returns: 'text' (short/inline), 'code' (multi-line/output),
             'json' (JSON structure), 'binary' (non-printable).
    """
    if not content:
        return "text"
    # Check for binary content (high ratio of non-printable chars)
    non_printable = sum(1 for c in content if ord(c) < 32 and c not in "\t\n\r")
    if len(content) > 0 and non_printable / max(len(content), 1) > 0.1:
        return "binary"
    stripped = content.strip()
    # Check if it's JSON
    if stripped.startswith(("{", "[")) and stripped.endswith(("}", "]")):
        try:
            json.loads(stripped)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass
        # JSON parse failed, check Python repr (dict/list with single quotes or None/True/False)
        if any(c in stripped for c in ("'", "True", "False", "None")):
            return "code"
    # Check if it's a Python repr tuple (common for toolkit_exec returns)
    if stripped.startswith("(") and stripped.endswith(")") and any(c in stripped for c in (",", "'", '"')):
        return "code"
    # Check if it's a Python list literal
    if stripped.startswith("[") and stripped.endswith("]") and ("'" in stripped or '"' in stripped):
        return "code"
    # Multi-line or long content
    if "\n" in content or len(content) > 200:
        return "code"
    return "text"


def _truncate_content(content, max_chars=5000):
    """Truncate content if too long, appending a note."""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + f"\n\n... [截断: 共 {len(content)} 字符，仅显示前 {max_chars} 字符]"


def _build_full_interactions_md(rounds_data):
    """Convert rounds_json into richly formatted Markdown timeline.

    Produces a structured timeline of:
      Thinking → Tool Call args → Tool Result → next Thinking → ...

    Uses markdown formatting that _render_markdown already supports:
      - --- horizontal rules as round separators
      - ### headings for round numbers
      - > blockquotes for thinking/reasoning content
      - ```code blocks for tool args and results
      - **bold** for labels
    """
    parts = []
    round_num = 0

    for r in rounds_data:
        role = r.get("role")

        if role == "assistant":
            rc = r.get("reasoning_content", "") or ""
            content = r.get("content", "") or ""
            tc = r.get("tool_calls")

            has_thinking = rc.strip()
            has_text = content.strip()
            has_tool_calls = bool(tc)

            if not (has_thinking or has_text or has_tool_calls):
                continue

            # Start a new round
            round_num += 1
            parts.append("\n---\n\n")
            parts.append(f"### 🔄 回合 {round_num}\n\n")

            if has_thinking:
                parts.append("💭 **思考**\n\n")
                for line in rc.strip().split("\n"):
                    safe_line = line.replace("\r", "")
                    parts.append(f"> {safe_line}\n")
                parts.append("\n")

            if has_text:
                # Assistant's text response (intermediate or final)
                parts.append("🤖 **AI 回复**\n\n")
                for line in content.strip().split("\n"):
                    parts.append(f"> {line}\n")
                parts.append("\n")

            if has_tool_calls:
                for t in tc:
                    fn = t.get("function", {})
                    name = fn.get("name", "unknown")
                    raw_args = fn.get("arguments", "")
                    try:
                        args_obj = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        args_pretty = json.dumps(args_obj, indent=2, ensure_ascii=False)
                    except Exception:
                        args_pretty = str(raw_args)

                    parts.append(f"🛠️ **调用工具: `{name}`**\n\n")
                    parts.append(f"```json\n{args_pretty}\n```\n\n")

        elif role == "tool":
            content = r.get("content", "") or ""
            if content.strip():
                ctype = _detect_content_type(content)
                display_content = _truncate_content(content)

                if ctype == "binary":
                    # Show binary content info instead of raw bytes
                    preview = content[:80]
                    printable_preview = "".join(
                        c if 32 <= ord(c) < 127 else "." for c in preview
                    )
                    parts.append(
                        f"📦 **返回结果** *(二进制数据, {len(content)} 字节)*\n\n"
                    )
                    parts.append(f"```\n{printable_preview}\n```\n\n")
                elif ctype == "json":
                    try:
                        obj = json.loads(display_content.strip())
                        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
                        parts.append(f"📥 **返回结果** *(JSON, {len(content)} 字符)*\n\n")
                        parts.append(f"```json\n{pretty}\n```\n\n")
                    except Exception:
                        parts.append(f"📥 **返回结果** *(文本, {len(content)} 字符)*\n\n")
                        parts.append(f"```\n{display_content}\n```\n\n")
                elif ctype == "code":
                    parts.append(f"📥 **返回结果** *(文本, {len(content)} 字符)*\n\n")
                    parts.append(f"```\n{display_content}\n```\n\n")
                else:
                    # Short inline text — split on \n to preserve visual line breaks
                    text_content = content.strip()
                    if "\n" in text_content:
                        parts.append("📥 **返回结果**\n\n")
                        for line in text_content.split("\n"):
                            safe_line = line.replace("\r", "")
                            parts.append(f"> {safe_line}\n")
                        parts.append("\n")
                    else:
                        parts.append(f"📥 **返回结果**\n\n> {text_content}\n\n")

    return "".join(parts)


# ═══════════════════════════════════════════════════════════════
#  Font setup — cross-platform CJK support
# ═══════════════════════════════════════════════════════════════

def _setup_fonts(pdf):
    """Register fonts for CJK + code. Returns (body_font, code_font)."""
    body_font = code_font = None

    # ── Body fonts (CJK-capable) ──
    body_candidates = [
        ("C:/Windows/Fonts/msyh.ttc", "YaHei"),
        ("C:/Windows/Fonts/msyhbd.ttc", "YaHei-Bold"),
        ("C:/Windows/Fonts/simsun.ttc", "SimSun"),
        ("C:/Windows/Fonts/simfang.ttf", "FangSong"),
        ("/System/Library/Fonts/PingFang.ttc", "PingFang"),
        ("/System/Library/Fonts/STHeiti Light.ttc", "Heiti"),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "Noto"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto"),
    ]
    for fp, _name in body_candidates:
        if os.path.exists(fp):
            try:
                pdf.add_font("Body", "", fp)
                body_font = "Body"
                # Try bold variant
                bold_fp = fp.replace("msyh.ttc", "msyhbd.ttc").replace("Regular", "Bold").replace("NotoSansCJK-Regular.ttc", "NotoSansCJK-Bold.ttc").replace("simfang.ttf", "simfang.ttf")
                if "msyh" in fp and os.path.exists("C:/Windows/Fonts/msyhbd.ttc"):
                    pdf.add_font("Body", "B", "C:/Windows/Fonts/msyhbd.ttc")
                elif os.path.exists(bold_fp):
                    pdf.add_font("Body", "B", bold_fp)
                else:
                    pdf.add_font("Body", "B", fp)
                logger.info(f"Body font: {fp}")
                break
            except Exception:
                continue

    # ── Code fonts (monospace) ──
    code_candidates = [
        ("C:/Windows/Fonts/consola.ttf", "Consolas"),
        ("C:/Windows/Fonts/cour.ttf", "Courier New"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "DejaVu Mono"),
        ("/Library/Fonts/Arial Unicode.ttf", "Arial Unicode"),
    ]
    for fp, _name in code_candidates:
        if os.path.exists(fp):
            try:
                pdf.add_font("Code", "", fp)
                code_font = "Code"
                logger.info(f"Code font: {fp}")
                break
            except Exception:
                continue

    if not body_font:
        body_font = "Helvetica"
    if not code_font:
        code_font = "Courier"
    return body_font, code_font


# ═══════════════════════════════════════════════════════════════
#  Markdown → fpdf2 rendering
# ═══════════════════════════════════════════════════════════════

def _render_markdown(pdf, text, body_font, code_font, indent=0, text_color=(50, 50, 50)):
    """Render markdown text using fpdf2.

    Supports: headings, bold, italic, inline code, code blocks (pygments),
    unordered lists, ordered lists, blockquotes, horizontal rules,
    tables, paragraphs.
    """
    if not text.strip():
        return

    from pygments.lexers import PythonLexer, get_lexer_by_name, guess_lexer

    lines = text.split("\n")
    i = 0
    in_code_block = False
    code_buffer = []
    code_lang = ""
    list_type = None
    list_counter = 0

    def _flush_code_block():
        nonlocal code_buffer, code_lang
        if not code_buffer:
            return
        code_text = "\n".join(code_buffer)
        try:
            lexer = get_lexer_by_name(code_lang, stripall=True) if code_lang else guess_lexer(code_text)
        except Exception:
            lexer = PythonLexer()

        left_margin = pdf.l_margin + indent
        all_lines = code_text.split("\n")
        line_h = 5.0  # Match body text line height

        # Thin top border
        pdf.set_draw_color(200, 200, 215)
        pdf.set_line_width(0.3)
        pdf.line(left_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(1)

        # Render each line — let write() handle wrapping, then advance correctly
        for line_text in all_lines:
            # Page break check
            if pdf.get_y() + line_h > pdf.h - pdf.b_margin:
                pdf.add_page()

            # Start of this line
            y_before = pdf.get_y()
            pdf.set_x(left_margin + 3)

            for ttype, tval in lexer.get_tokens(line_text):
                color = _pygments_to_rgb(ttype)
                pdf.set_text_color(*color)
                safe_val = "".join(c for c in tval if ord(c) >= 32 or c in "\t")
                if not safe_val:
                    continue
                try:
                    pdf.get_string_width(safe_val)
                    pdf.write(line_h, safe_val)
                except Exception:
                    pdf.set_font(body_font, "", 8)
                    for ch in safe_val:
                        try:
                            pdf.get_string_width(ch)
                            pdf.write(line_h, ch)
                        except Exception:
                            pass
                    pdf.set_font(code_font, "", 8)
                    pdf.set_text_color(*color)

            # Advance to next line.
            # If write() wrapped (long line), y already advanced — don't double-advance.
            # If write() didn't wrap, advance by exactly one line_h.
            if pdf.get_y() <= y_before:
                pdf.set_y(y_before + line_h)

        # Bottom border
        pdf.set_draw_color(200, 200, 215)
        pdf.set_line_width(0.3)
        pdf.line(left_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(4)

        code_buffer = []
        pdf.set_text_color(*text_color)
        pdf.set_font(body_font, "", 10)

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── Code block ──
        if stripped.startswith("```"):
            if in_code_block:
                _flush_code_block()
                in_code_block = False
                code_lang = ""
                i += 1
                continue
            else:
                in_code_block = True
                code_lang = stripped[3:].strip()
                code_buffer = []
                i += 1
                continue
        if in_code_block:
            code_buffer.append(line)
            i += 1
            continue

        # ── Empty line ──
        if not stripped:
            if list_type:
                list_type = None
            pdf.ln(2)
            i += 1
            continue

        # ── Tables ──
        if "|" in stripped and i + 1 < len(lines) and re.match(r"^\s*\|[-:\s|]+\|\s*$", lines[i + 1]):
            # This is a table
            _flush_table(pdf, lines, i, body_font, code_font)
            # Skip to after the table
            while i < len(lines) and "|" in lines[i]:
                i += 1
            pdf.ln(5)
            continue

        # ── Headings ──
        if stripped.startswith("### "):
            pdf.ln(2)
            pdf.set_font(body_font, "B", 12)
            pdf.set_text_color(60, 60, 100)
            _render_inline(pdf, stripped[4:], body_font, text_color=(60, 60, 100))
            pdf.ln(5)
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*text_color)
            i += 1
            continue
        if stripped.startswith("## "):
            pdf.ln(3)
            pdf.set_font(body_font, "B", 14)
            pdf.set_text_color(50, 50, 90)
            _render_inline(pdf, stripped[3:], body_font, text_color=(50, 50, 90))
            pdf.ln(7)
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*text_color)
            i += 1
            continue
        if stripped.startswith("# "):
            pdf.ln(4)
            pdf.set_font(body_font, "B", 18)
            pdf.set_text_color(40, 40, 80)
            _render_inline(pdf, stripped[2:], body_font, text_color=(40, 40, 80))
            pdf.ln(9)
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*text_color)
            i += 1
            continue

        # ── Horizontal rule ──
        if stripped in ("---", "***", "___"):
            pdf.set_draw_color(190, 190, 210)
            pdf.set_line_width(0.3)
            y = pdf.get_y() + 3
            pdf.line(pdf.l_margin + indent, y, pdf.w - pdf.r_margin, y)
            pdf.ln(7)
            i += 1
            continue

        # ── Blockquote ──
        if stripped.startswith("> "):
            content = stripped[2:]
            # Left bar (thin)
            pdf.set_draw_color(180, 180, 200)
            pdf.set_line_width(0.5)
            y0 = pdf.get_y()
            pdf.set_x(pdf.l_margin + indent + 6)
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(90, 90, 100)
            _render_inline(pdf, content, body_font, text_color=(90, 90, 100))
            y1 = pdf.get_y()
            # Draw vertical bar
            pdf.line(pdf.l_margin + indent + 2, y0, pdf.l_margin + indent + 2, y1)
            pdf.ln(5)
            i += 1
            continue

        # ── Lists ──
        ul_match = re.match(r"^(\s*)[-*+]\s+(.*)", stripped)
        ol_match = re.match(r"^(\s*)\d+[.)]\s+(.*)", stripped)
        if ul_match:
            indent_level = len(ul_match.group(1)) // 2
            bullet = "•" if indent_level == 0 else "◦" if indent_level == 1 else "▪"
            content = ul_match.group(2)
            pdf.set_x(pdf.l_margin + indent + 10 + indent_level * 8)
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*text_color)
            pdf.write(5, f"{bullet} ")
            _render_inline(pdf, content, body_font, text_color=text_color)
            pdf.ln(6)
            list_type = "ul"
            i += 1
            continue
        elif ol_match:
            indent_level = len(ol_match.group(1)) // 2
            list_counter += 1
            content = ol_match.group(2)
            pdf.set_x(pdf.l_margin + indent + 10 + indent_level * 8)
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*text_color)
            pdf.write(5, f"{list_counter}. ")
            _render_inline(pdf, content, body_font, text_color=text_color)
            pdf.ln(6)
            list_type = "ol"
            i += 1
            continue
        else:
            list_counter = 0

        # ── Regular paragraph ──
        pdf.set_x(pdf.l_margin + indent)
        pdf.set_font(body_font, "", 10)
        pdf.set_text_color(*text_color)
        _render_inline(pdf, stripped, body_font, text_color=text_color)
        pdf.ln(6)
        i += 1

    if in_code_block and code_buffer:
        _flush_code_block()


def _flush_table(pdf, lines, start_idx, body_font, code_font):
    """Parse and render a markdown table starting at start_idx."""
    # Collect all table rows
    table_lines = []
    i = start_idx
    while i < len(lines) and "|" in lines[i]:
        table_lines.append(lines[i].strip())
        i += 1

    if len(table_lines) < 2:
        return

    # Parse header
    header = [h.strip() for h in table_lines[0].split("|")[1:-1]]
    # Parse alignment (skip separator row)
    alignments = []
    if len(table_lines) > 1:
        sep = table_lines[1]
        parts = sep.split("|")[1:-1]
        for p in parts:
            p = p.strip()
            if p.startswith(":") and p.endswith(":"):
                alignments.append("C")
            elif p.endswith(":"):
                alignments.append("R")
            elif p.startswith(":"):
                alignments.append("L")
            else:
                alignments.append("L")
    else:
        alignments = ["L"] * len(header)

    # Parse data rows
    data_rows = []
    for row_line in table_lines[2:]:
        cells = [c.strip() for c in row_line.split("|")[1:-1]]
        data_rows.append(cells)

    num_cols = len(header)
    if not num_cols:
        return

    # Calculate column widths (proportional)
    avail_w = pdf.w - pdf.l_margin - pdf.r_margin
    col_w = avail_w / min(num_cols, 6)  # limit columns
    col_w = min(col_w, 60)  # max 60mm per column
    col_widths = [col_w] * num_cols

    # Adjust last column to fill remaining width
    total = sum(col_widths)
    if total < avail_w:
        col_widths[-1] += avail_w - total

    # Check page break
    row_h = 7
    total_h = (len(data_rows) + 1) * row_h + 4
    if pdf.get_y() + total_h > pdf.h - pdf.b_margin:
        pdf.add_page()

    # Render table using fpdf2's table API
    try:
        from fpdf import FontFace

        h_style = FontFace(family=body_font, emphasis="B", size_pt=9, color=(40, 40, 80))
        FontFace(family=body_font, emphasis="", size_pt=9, color=(50, 50, 50))

        with pdf.table(
            col_widths=col_widths,
            align="L",
            borders_layout="SINGLE_TOP_LINE",
            first_row_as_headings=True,
            markdown=False,
            cell_fill_mode="NONE",
            headings_style=h_style,
            line_height=row_h,
        ) as tbl:
            # Header
            row_h_obj = tbl.row()
            for h in header:
                row_h_obj.cell(h)

            # Data rows
            for row_data in data_rows:
                row_h_obj = tbl.row()
                for ci, cell_text in enumerate(row_data):
                    # Handle inline formatting in table cells
                    row_h_obj.cell(cell_text)
    except Exception:
        # Fallback: simple text rendering
        # Guard against inconsistent column counts (data row > header cols)
        nc = len(col_widths)
        pdf.set_font(body_font, "B", 9)
        pdf.set_text_color(40, 40, 80)
        for hi, h in enumerate(header):
            pdf.cell(col_widths[hi] if hi < nc else 20, 7, h, border=1)
        pdf.ln()
        pdf.set_font(body_font, "", 9)
        pdf.set_text_color(50, 50, 50)
        for row_data in data_rows:
            for ci, cell_text in enumerate(row_data):
                w = col_widths[ci] if ci < nc else 20
                pdf.cell(w, 7, cell_text, border=1)
            pdf.ln()


def _render_inline(pdf, text, body_font, text_color=(50, 50, 50)):
    """Render inline markdown: **bold**, *italic*, `code`, [links](url)."""
    pattern = r"(\*\*(.+?)\*\*|__(.+?)__|\*(.+?)\*|_(.+?)_|`(.+?)`|\[(.+?)\]\((.+?)\))"
    parts = []
    last_end = 0

    for m in re.finditer(pattern, text):
        if m.start() > last_end:
            parts.append(("text", text[last_end : m.start()]))

        if m.group(2) is not None:  # **bold**
            parts.append(("bold", m.group(2)))
        elif m.group(3) is not None:  # __bold__
            parts.append(("bold", m.group(3)))
        elif m.group(4) is not None:  # *italic*
            parts.append(("italic", m.group(4)))
        elif m.group(5) is not None:  # _italic_
            parts.append(("italic", m.group(5)))
        elif m.group(6) is not None:  # `code`
            parts.append(("code", m.group(6)))
        elif m.group(7) is not None:  # [link](url)
            parts.append(("link", m.group(7), m.group(8)))

        last_end = m.end()

    if last_end < len(text):
        parts.append(("text", text[last_end:]))

    if not parts:
        parts = [("text", text)]

    for part in parts:
        kind = part[0]
        if kind == "text":
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*text_color)
            pdf.write(5, part[1])
        elif kind == "bold":
            pdf.set_font(body_font, "B", 10)
            pdf.set_text_color(40, 40, 70)
            pdf.write(5, part[1])
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*text_color)
        elif kind == "italic":
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*text_color)
            pdf.write(5, part[1])
        elif kind == "code":
            try:
                pdf.set_font("Code", "", 9)
            except Exception:
                pdf.set_font(body_font, "", 9)
            pdf.set_text_color(180, 40, 70)
            pdf.write(5, part[1])
            pdf.set_text_color(*text_color)
            pdf.set_font(body_font, "", 10)
        elif kind == "link":
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(60, 80, 180)
            pdf.write(5, part[1])
            pdf.set_text_color(*text_color)


def _pygments_to_rgb(ttype):
    """Convert pygments token type to RGB color tuple (printer-friendly)."""
    ttype_str = str(ttype)
    if "Keyword" in ttype_str:
        return (180, 40, 80)    # dark pink/red
    if "String" in ttype_str:
        return (140, 110, 30)   # dark yellow
    if "Comment" in ttype_str:
        return (120, 120, 120)  # gray
    if "Name.Function" in ttype_str:
        return (60, 130, 60)    # green
    if "Name.Class" in ttype_str:
        return (60, 130, 60)    # green
    if "Name.Decorator" in ttype_str:
        return (110, 70, 180)   # purple
    if "Name.Builtin" in ttype_str:
        return (180, 40, 80)    # dark pink
    if "Number" in ttype_str:
        return (110, 70, 180)   # purple
    if "Operator" in ttype_str:
        return (80, 80, 80)     # dark gray
    if "Punctuation" in ttype_str:
        return (100, 100, 100)  # gray
    return (60, 60, 60)         # dark gray


# ═══════════════════════════════════════════════════════════════
#  PDF generation via fpdf2
# ═══════════════════════════════════════════════════════════════

def _make_pdf(topic_title, stamp, user_msg, ai_msg, reasoning_text, output_path):
    """Generate a clean, printer-friendly PDF from conversation data.

    Features:
    - Clean white background (printer-friendly, no wasted ink)
    - Elegant cover page with thin-line design
    - Section headers with subtle left accent
    - Full markdown rendering (headings, bold, italic, lists, blockquotes)
    - Syntax-highlighted code blocks (pygments, printer-safe colors)
    - Markdown table rendering via fpdf2 table API
    - Inline code styling
    - Page numbers and running headers
    - Cross-platform CJK font support
    """
    from fpdf import FPDF

    class ExportPDF(FPDF):
        def __init__(self, title):
            super().__init__()
            self._title = title
            self._body_font = "Body"

        def header(self):
            if self.page_no() <= 1:
                return
            self.set_font(self._body_font, "", 8)
            self.set_text_color(140, 140, 160)
            self.cell(0, 6, self._title, align="L", new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(210, 210, 225)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(4)

        def footer(self):
            if self.page_no() <= 1:
                return
            self.set_y(-15)
            self.set_font(self._body_font, "", 8)
            self.set_text_color(150, 150, 170)
            self.cell(0, 10, f"— {self.page_no()} —", align="C")

    pdf = ExportPDF(topic_title)
    pdf.set_auto_page_break(auto=True, margin=22)

    # Setup fonts
    body_font, code_font = _setup_fonts(pdf)
    pdf._body_font = body_font

    # ── Cover Page ──
    pdf.add_page()
    _draw_cover(pdf, topic_title, stamp, body_font)

    # ── User Request ──
    _draw_section_header(pdf, "User Request", body_font, symbol="◆", color=(60, 80, 200))
    _render_markdown(pdf, user_msg, body_font, code_font, text_color=(50, 50, 50))

    # ── Thinking Process ──
    if reasoning_text.strip():
        pdf.add_page()
        _draw_section_header(pdf, "Thinking Process", body_font, symbol="◇", color=(200, 150, 20))
        _render_markdown(pdf, reasoning_text, body_font, code_font, text_color=(80, 70, 30))

    # ── AI Response ──
    pdf.add_page()
    _draw_section_header(pdf, "AI Response", body_font, symbol="●", color=(20, 160, 100))
    _render_markdown(pdf, ai_msg, body_font, code_font, text_color=(50, 50, 50))

    pdf.output(output_path)
    return output_path


def _draw_cover(pdf, title, stamp, body_font):
    """Draw a clean, printer-friendly cover page."""
    page_w = pdf.w

    # Thin decorative top line
    pdf.set_draw_color(200, 200, 220)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, 40, page_w - pdf.r_margin, 40)

    # Label
    pdf.set_y(55)
    pdf.set_font(body_font, "", 10)
    pdf.set_text_color(140, 140, 160)
    pdf.cell(0, 10, "CONVERSATION EXPORT", align="C", new_x="LMARGIN", new_y="NEXT")

    # Title
    pdf.ln(15)
    pdf.set_font(body_font, "B", 28)
    pdf.set_text_color(30, 30, 50)
    pdf.multi_cell(0, 15, title, align="C")
    pdf.ln(5)

    # Small decorative line
    pdf.set_draw_color(60, 80, 200)
    pdf.set_line_width(0.8)
    cx = page_w / 2
    pdf.line(cx - 15, pdf.get_y(), cx + 15, pdf.get_y())
    pdf.ln(12)

    # Date
    pdf.set_font(body_font, "", 11)
    pdf.set_text_color(120, 120, 140)
    pdf.cell(0, 10, stamp, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Bottom line
    pdf.set_draw_color(200, 200, 220)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, 270, page_w - pdf.r_margin, 270)

    # Footer
    pdf.set_y(280)
    pdf.set_font(body_font, "", 9)
    pdf.set_text_color(160, 160, 180)
    pdf.cell(0, 10, "Generated by Tea Agent", align="C", new_x="LMARGIN", new_y="NEXT")


def _draw_section_header(pdf, title, body_font, symbol="◆", color=(60, 80, 200)):
    """Draw a section header with subtle left accent."""
    pdf.ln(4)

    # Thin left accent line
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.8)
    y0 = pdf.get_y()
    pdf.line(pdf.l_margin, y0, pdf.l_margin, y0 + 12)

    # Title text
    pdf.set_x(pdf.l_margin + 5)
    pdf.set_font(body_font, "B", 14)
    pdf.set_text_color(*[max(c - 30, 0) for c in color])
    pdf.cell(0, 12, f"{symbol}  {title}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Subtle underline
    pdf.set_draw_color(200, 200, 220)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)


# ═══════════════════════════════════════════════════════════════
#  Full-topic multi-conversation renderer
# ═══════════════════════════════════════════════════════════════

def _make_full_topic_pdf(topic_title, conversations, output_path):
    """Render multiple conversations (user + ai only) as a single PDF.

    Args:
        topic_title: Topic title for cover.
        conversations: list of dicts with keys 'user_msg', 'ai_msg', 'stamp'.
        output_path: Output PDF path.
    """
    from fpdf import FPDF

    class ExportPDF(FPDF):
        def __init__(self, title):
            super().__init__()
            self._title = title
            self._body_font = "Helvetica"
            self._code_font = "Courier"

        def header(self):
            if self.page_no() <= 1:
                return
            if hasattr(self, '_body_font'):
                self.set_font(self._body_font, "", 8)
            self.set_text_color(140, 140, 160)
            self.cell(0, 6, self._title, align="L", new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(210, 210, 225)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(4)

        def footer(self):
            if self.page_no() <= 1:
                return
            self.set_y(-15)
            if hasattr(self, '_body_font'):
                self.set_font(self._body_font, "", 8)
            self.set_text_color(150, 150, 170)
            self.cell(0, 10, f"— {self.page_no()} —", align="C")

    pdf = ExportPDF(topic_title)
    pdf.set_auto_page_break(auto=True, margin=22)

    # Setup fonts
    body_font, code_font = _setup_fonts(pdf)
    pdf._body_font = body_font
    pdf._code_font = code_font

    # Cover
    pdf.add_page()
    _draw_cover(pdf, topic_title, conversations[0]["stamp"] if conversations else "", body_font)

    # Each conversation
    for idx, conv in enumerate(conversations, 1):
        pdf.add_page()
        stamp = conv.get("stamp", "")
        _draw_section_header(pdf, f"Conversation {idx} — {stamp}", body_font,
                             symbol="◆", color=(60, 80, 200))

        # User message
        pdf.set_font(body_font, "B", 10)
        pdf.set_text_color(60, 80, 200)
        pdf.cell(0, 8, "User", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(body_font, "", 10)
        pdf.set_text_color(50, 50, 50)
        _render_markdown(pdf, _sanitize(conv["user_msg"]), body_font, code_font, text_color=(50, 50, 50))
        pdf.ln(4)

        # Thinking Process (if filter=full)
        reasoning_text = conv.get("reasoning_text", "")
        if reasoning_text.strip():
            pdf.add_page()
            _draw_section_header(pdf, f"Thinking Process — Conversation {idx}", body_font,
                                 symbol="◇", color=(200, 150, 20))
            _render_markdown(pdf, reasoning_text, body_font, code_font, text_color=(80, 70, 30))

        # AI response
        pdf.set_font(body_font, "B", 10)
        pdf.set_text_color(20, 160, 100)
        pdf.cell(0, 8, "AI Response", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(body_font, "", 10)
        pdf.set_text_color(50, 50, 50)
        _render_markdown(pdf, _sanitize(conv["ai_msg"]), body_font, code_font, text_color=(50, 50, 50))

        # Separator if not last
        if idx < len(conversations):
            pdf.ln(4)
            pdf.set_draw_color(210, 210, 225)
            pdf.set_line_width(0.3)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)

    pdf.output(output_path)
    return output_path


# ═══════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════

def export_topic_pdf(topic_id: str, output_path: str = None,
                     db_path: str = None, mode: str = "latest",
                     filter_mode: str = "final") -> str:
    """Export a topic's conversations as PDF.

    Args:
        topic_id: Topic UUID.
        output_path: Output file path.
        db_path: Optional database path (auto-detect if None).
        mode: 'latest' (single conversation) or 'full_topic' (all conversations).
        filter_mode: 'final' (user + AI final only) or 'full' (with reasoning).

    Returns:
        Path to the generated PDF file.
    """
    if db_path is None:
        db_path = _find_db_path()
    if not db_path:
        raise FileNotFoundError("chat_history.db not found")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT title FROM topics WHERE topic_id = ?", (topic_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Topic {topic_id} not found")
    topic_title = _sanitize(row["title"] or "Untitled")

    if mode == "full_topic":
        # ── Fetch ALL conversations for this topic ──
        c.execute(
            "SELECT * FROM conversations WHERE topic_id = ? ORDER BY stamp ASC",
            (topic_id,),
        )
        all_conv = c.fetchall()
        conn.close()
        if not all_conv:
            raise ValueError(f"No conversations for topic {topic_id}")

        conversations = []
        for conv in all_conv:
            user_raw = conv["user_msg"]
            try:
                data = json.loads(user_raw)
                user_msg = data.get("text", user_raw) if isinstance(data, dict) else str(data)
            except Exception:
                user_msg = str(user_raw)

            reasoning_text = ""
            if filter_mode == "full":
                rounds_json_raw = conv["rounds_json"]
                if rounds_json_raw:
                    with contextlib.suppress(Exception):
                        rounds_data = json.loads(rounds_json_raw) if isinstance(rounds_json_raw, str) else rounds_json_raw
                        reasoning_text = _build_full_interactions_md(rounds_data)

            conversations.append({
                "user_msg": _sanitize(user_msg),
                "ai_msg": _sanitize(conv["ai_msg"]),
                "stamp": conv["stamp"],
                "reasoning_text": reasoning_text,
            })

        output_path = output_path or f"export_{topic_id[:8]}_full.pdf"
        return _make_full_topic_pdf(topic_title, conversations, output_path)

    else:
        # ── mode == "latest": fetch the last conversation only ──
        c.execute(
            "SELECT * FROM conversations WHERE topic_id = ? ORDER BY stamp DESC LIMIT 1",
            (topic_id,),
        )
        conv = c.fetchone()
        if not conv:
            conn.close()
            raise ValueError(f"No conversations for topic {topic_id}")
        _conv_id, user_raw, ai_msg, stamp = conv["id"], conv["user_msg"], conv["ai_msg"], conv["stamp"]

        try:
            data = json.loads(user_raw)
            user_msg = data.get("text", user_raw) if isinstance(data, dict) else str(data)
        except Exception:
            user_msg = str(user_raw)

        user_msg = _sanitize(user_msg)
        ai_msg = _sanitize(ai_msg)

        if filter_mode == "full":
            # Full interaction timeline from rounds_json: thinking + tool calls + tool returns
            rounds_json_raw = conv["rounds_json"]
            reasoning_text = ""
            if rounds_json_raw:
                with contextlib.suppress(Exception):
                    rounds_data = json.loads(rounds_json_raw) if isinstance(rounds_json_raw, str) else rounds_json_raw
                    reasoning_text = _build_full_interactions_md(rounds_data)
        else:
            reasoning_text = ""

        conn.close()
        output_path = output_path or f"export_{topic_id[:8]}.pdf"
        return _make_pdf(topic_title, stamp, user_msg, ai_msg, reasoning_text, output_path)


def toolkit_export_last_pdf(output_path="last.pdf", mode="latest", filter="final",
                            topic_id=None):
    """Toolkit: export topic conversation(s) as PDF.

    Args:
        output_path: PDF output path, default 'last.pdf'.
        mode: 'latest' = last conversation only, 'full_topic' = all conversations in topic.
        filter: 'final' = user + AI final msg only (no thinking),
                'full' = include reasoning process.
        topic_id: specific topic UUID to export. If None, use the latest topic.

    Returns:
        dict with success/error info.
    """
    db_path = _find_db_path()
    if not db_path:
        return {"error": "chat_history.db not found"}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if topic_id:
        # Verify topic exists
        c.execute("SELECT topic_id, title FROM topics WHERE topic_id = ?", (topic_id,))
    else:
        c.execute("SELECT topic_id, title FROM topics ORDER BY rowid DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if not row:
        return {
            "error": "No topics found" if not topic_id
                    else f"Topic '{topic_id}' not found"
        }
    try:
        path = export_topic_pdf(row["topic_id"], output_path, mode=mode, filter_mode=filter)
        return {
            "success": True,
            "output": path,
            "topic": _sanitize(row["title"] or "Untitled"),
            "topic_id": row["topic_id"],
            "mode": mode,
        }
    except Exception as e:
        return {"error": str(e)}


def meta_toolkit_export_last_pdf() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "toolkit_export_last_pdf",
            "description": "导出指定主题的对话为 PDF。支持选择完整主题/最新对话，仅含 user+AI 最终消息（无思考过程）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "output_path": {
                        "type": "string",
                        "description": "PDF 输出路径，默认 last.pdf",
                        "default": "last.pdf"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["latest", "full_topic"],
                        "description": "'latest'=仅最新对话, 'full_topic'=完整主题全部对话",
                        "default": "latest"
                    },
                    "filter": {
                        "type": "string",
                        "enum": ["final", "full"],
                        "description": "'final'=仅 user+AI 最终消息(默认), 'full'=含推理过程",
                        "default": "final"
                    },
                    "topic_id": {
                        "type": "string",
                        "description": "指定导出的主题 UUID。不填则自动导出最新主题。用 toolkit_query_chat_history action='topic' 可查看所有 topic_id。",
                        "default": ""
                    }
                },
                "required": []
            }
        }
    }
