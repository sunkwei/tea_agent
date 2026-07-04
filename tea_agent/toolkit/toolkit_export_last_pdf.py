## llm generated tool func, created Wed May 27 13:15:16 2026
# version: 1.0.12

import sqlite3
import json
import os
from pathlib import Path
import logging

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

def _setup_fonts(pdf):
    """跨平台中文字体查找：Windows → Linux → macOS"""
    cn_fonts = [
        # Windows
        "C:/Windows/Fonts/simfang.ttf",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttf",
        # Linux (Noto Sans CJK)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/google-noto-cjk/NotoSansCJK-Regular.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for fp in cn_fonts:
        if os.path.exists(fp):
            try:
                pdf.add_font("F", "", fp)
                return "F"
            except Exception:
                continue
    return "Helvetica"

def _sanitize(text):
    """Remove characters that fpdf2 cannot render"""
    # Remove emoji and other non-printable chars
    result = []
    for ch in text:
        cp = ord(ch)
        # Keep ASCII printable, CJK, common symbols
        if cp == 0x09 or cp == 0x0A or cp == 0x0D:  # tab, newline, carriage return
            result.append(' ')
        elif 0x20 <= cp <= 0x7E:  # ASCII printable
            result.append(ch)
        elif 0x4E00 <= cp <= 0x9FFF:  # CJK Unified
            result.append(ch)
        elif 0x3000 <= cp <= 0x303F:  # CJK Symbols
            result.append(ch)
        elif 0xFF00 <= cp <= 0xFFEF:  # Fullwidth forms
            result.append(ch)
        elif cp in (0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026):  # Common punctuation
            result.append(ch)
        elif 0x2000 <= cp <= 0x206F:  # General Punctuation
            result.append(ch)
        elif 0x2100 <= cp <= 0x214F:  # Letterlike Symbols
            result.append(ch)
        elif 0x2150 <= cp <= 0x218F:  # Number Forms
            result.append(ch)
        elif 0x2190 <= cp <= 0x21FF:  # Arrows
            result.append(ch)
        elif 0x2200 <= cp <= 0x22FF:  # Math Operators
            result.append(ch)
        elif 0x2500 <= cp <= 0x257F:  # Box Drawing
            result.append(ch)
        elif 0x2580 <= cp <= 0x259F:  # Block Elements
            result.append(ch)
        elif 0x25A0 <= cp <= 0x25FF:  # Geometric Shapes
            result.append(ch)
        # Skip everything else (emoji, special symbols, etc.)
    return ''.join(result)


# ═══════════════════════════════════════════════════════════════
#  Public API — export_topic_pdf (for server route)
# ═══════════════════════════════════════════════════════════════

def _make_pdf(topic_title, stamp, user_msg, ai_msg, reasoning_text, output_path):
    """Generate PDF from extracted conversation data (fpdf2)."""
    try:
        from fpdf import FPDF
    except ImportError:
        raise ImportError("fpdf2 not installed. Run: pip install fpdf2")

    class PDF(FPDF):
        def header(self):
            if self.page_no() > 1:
                self.set_font("F", "", 10)
                self.set_text_color(120, 120, 120)
                self.cell(0, 8, topic_title, align="L", new_x="LMARGIN", new_y="NEXT")
                self.ln(12)

        def footer(self):
            self.set_y(-15)
            self.set_font("F", "", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    pdf = PDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    font_name = _setup_fonts(pdf)

    # Title page
    pdf.add_page()
    pdf.ln(30)
    pdf.set_font(font_name, "", 28)
    pdf.set_text_color(40, 40, 80)
    pdf.cell(0, 15, topic_title, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font(font_name, "", 14)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, f"Topic: {topic_title}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, f"Date: {stamp}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_draw_color(60, 60, 120)
    pdf.set_line_width(0.5)
    pdf.line(30, pdf.get_y(), pdf.w - 30, pdf.get_y())
    pdf.ln(15)

    # User message
    pdf.set_font(font_name, "", 16)
    pdf.set_text_color(40, 40, 80)
    pdf.cell(0, 12, "User Request", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font(font_name, "", 11)
    pdf.set_text_color(50, 50, 50)
    pdf.multi_cell(0, 6, user_msg)
    pdf.ln(10)

    # Thinking / reasoning
    if reasoning_text.strip():
        pdf.add_page()
        pdf.set_font(font_name, "", 16)
        pdf.set_text_color(40, 40, 80)
        pdf.cell(0, 12, "Thinking Process", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        for para in reasoning_text.split("\n\n"):
            if not para.strip():
                continue
            if para.strip().startswith("```"):
                code = para.strip().strip("```").strip()
                pdf.set_fill_color(245, 245, 250)
                pdf.set_text_color(60, 60, 80)
                pdf.set_font(font_name, "", 9)
                for line in code.split("\n"):
                    if line.strip():
                        pdf.multi_cell(0, 4.5, line, fill=True)
                    else:
                        pdf.ln(2)
                pdf.ln(3)
            else:
                pdf.set_text_color(80, 80, 80)
                pdf.set_font(font_name, "", 10)
                pdf.multi_cell(0, 5, para.strip())
                pdf.ln(2)
        pdf.ln(8)

    # AI response
    pdf.add_page()
    pdf.set_font(font_name, "", 16)
    pdf.set_text_color(40, 40, 80)
    pdf.cell(0, 12, "AI Response", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    in_code, buf = False, []
    for line in ai_msg.split("\n"):
        s = line.strip()
        if s.startswith("```"):
            if in_code:
                pdf.set_fill_color(240, 240, 248)
                pdf.set_text_color(50, 50, 80)
                pdf.set_font(font_name, "", 9)
                for cl in buf:
                    pdf.multi_cell(0, 4.5, cl, fill=True) if cl.strip() else pdf.ln(2)
                pdf.ln(3); buf = []; in_code = False
                pdf.set_font(font_name, "", 11)
                pdf.set_text_color(50, 50, 50)
            else:
                in_code = True; buf = []
            continue
        if in_code:
            buf.append(line); continue
        if s.startswith("### "):
            pdf.set_font(font_name, "", 12)
            pdf.set_text_color(60, 60, 100)
            pdf.multi_cell(0, 7, s[4:])
            pdf.set_font(font_name, "", 11)
            pdf.set_text_color(50, 50, 50)
        elif s.startswith("## "):
            pdf.set_font(font_name, "", 13)
            pdf.set_text_color(50, 50, 90)
            pdf.multi_cell(0, 8, s[3:])
            pdf.set_font(font_name, "", 11)
            pdf.set_text_color(50, 50, 50)
        elif s.startswith("# "):
            pdf.set_font(font_name, "", 14)
            pdf.set_text_color(40, 40, 80)
            pdf.multi_cell(0, 9, s[2:])
            pdf.set_font(font_name, "", 11)
            pdf.set_text_color(50, 50, 50)
        elif s in ("---", "***"):
            pdf.set_draw_color(180, 180, 200)
            pdf.set_line_width(0.3)
            pdf.line(30, pdf.get_y(), pdf.w - 30, pdf.get_y())
            pdf.ln(5)
        else:
            pdf.multi_cell(0, 6, line)
    if buf:
        pdf.set_fill_color(240, 240, 248)
        pdf.set_text_color(50, 50, 80)
        pdf.set_font(font_name, "", 9)
        for cl in buf:
            pdf.multi_cell(0, 4.5, cl, fill=True) if cl.strip() else pdf.ln(2)

    pdf.output(output_path)
    return output_path


def export_topic_pdf(topic_id: str, output_path: str = None) -> str:
    """Export a specific topic's last conversation as PDF.
    
    Args:
        topic_id: Topic UUID.
        output_path: Output path (default: 'export_{topic_id[:8]}.pdf').
    
    Returns:
        Path to the generated PDF file.
    """
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

    c.execute(
        "SELECT * FROM conversations WHERE topic_id = ? ORDER BY stamp DESC LIMIT 1",
        (topic_id,),
    )
    conv = c.fetchone()
    if not conv:
        conn.close()
        raise ValueError(f"No conversations for topic {topic_id}")
    conv_id, user_raw, ai_msg, stamp = conv["id"], conv["user_msg"], conv["ai_msg"], conv["stamp"]

    # Parse user_msg
    try:
        data = json.loads(user_raw)
        user_msg = data.get("text", user_raw) if isinstance(data, dict) else str(data)
    except Exception:
        user_msg = str(user_raw)

    # Agent rounds
    c.execute(
        "SELECT * FROM agent_rounds WHERE conversation_id = ? ORDER BY id ASC",
        (conv_id,),
    )
    rounds = c.fetchall()
    conn.close()

    reasoning = []
    for r in rounds:
        role, content = r["role"], (r["content"] or "")
        tc_raw = r["tool_calls"]
        tc = None
        if tc_raw:
            try:
                tc = json.loads(tc_raw) if isinstance(tc_raw, str) else tc_raw
            except Exception:
                pass
        if (tc and not content.strip()) or role == "tool":
            continue
        if role == "assistant" and content:
            reasoning.append(content)

    user_msg = _sanitize(user_msg)
    reasoning_text = _sanitize("\n\n".join(reasoning))
    ai_msg = _sanitize(ai_msg)
    output_path = output_path or f"export_{topic_id[:8]}.pdf"

    return _make_pdf(topic_title, stamp, user_msg, ai_msg, reasoning_text, output_path)


def toolkit_export_last_pdf(output_path="last.pdf"):
    """Toolkit: export last conversation of latest topic as PDF."""
    db_path = _find_db_path()
    if not db_path:
        return {"error": "chat_history.db not found"}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT topic_id, title FROM topics ORDER BY rowid DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if not row:
        return {"error": "No topics found"}
    try:
        path = export_topic_pdf(row["topic_id"], output_path)
        return {"success": True, "output": path, "topic": _sanitize(row["title"] or "Untitled")}
    except Exception as e:
        return {"error": str(e)}


def meta_toolkit_export_last_pdf() -> dict:
    return {"type": "function", "function": {"name": "toolkit_export_last_pdf", "description": "导出当前会话的最后一条 user+AI 消息（含思考过程，忽略工具调用轮）为简洁优美的 PDF 文件，保存为 last.pdf", "parameters": {"type": "object", "properties": {"output_path": {"type": "string", "description": "PDF 输出路径，默认 last.pdf", "default": "last.pdf"}}, "required": []}}}
