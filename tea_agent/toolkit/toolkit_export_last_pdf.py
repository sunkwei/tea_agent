## llm generated tool func, created Wed May 27 13:15:16 2026
# version: 1.0.11

import sqlite3
import json
import os
from pathlib import Path

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

def toolkit_export_last_pdf(output_path="last.pdf"):
    db_path = _find_db_path()
    if not db_path:
        return {"error": "chat_history.db not found"}
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT topic_id, title FROM topics ORDER BY rowid DESC LIMIT 1")
    topic_row = c.fetchone()
    if not topic_row:
        conn.close()
        return {"error": "No topics found in database"}
    
    topic_id = topic_row["topic_id"]
    topic_title = _sanitize(topic_row["title"] or "Untitled")
    
    c.execute(
        "SELECT * FROM conversations WHERE topic_id = ? ORDER BY stamp DESC LIMIT 1",
        (topic_id,)
    )
    conv = c.fetchone()
    if not conv:
        conn.close()
        return {"error": f"No conversations found for topic {topic_id}"}
    
    conv_id = conv["id"]
    user_msg_raw = conv["user_msg"]
    ai_msg = conv["ai_msg"]
    stamp = conv["stamp"]
    
    try:
        user_msg_data = json.loads(user_msg_raw)
        if isinstance(user_msg_data, dict):
            user_msg = user_msg_data.get("text", user_msg_raw)
        else:
            user_msg = str(user_msg_data)
    except (json.JSONDecodeError, TypeError):
        user_msg = str(user_msg_raw)
    
    c.execute(
        "SELECT * FROM agent_rounds WHERE conversation_id = ? ORDER BY id ASC",
        (conv_id,)
    )
    rounds = c.fetchall()
    conn.close()
    
    reasoning_parts = []
    for r in rounds:
        role = r["role"]
        content = r["content"] or ""
        tool_calls_raw = r["tool_calls"]
        tool_calls = None
        if tool_calls_raw:
            try:
                tool_calls = json.loads(tool_calls_raw) if isinstance(tool_calls_raw, str) else tool_calls_raw
            except Exception:
                logger.exception("operation failed")
        if tool_calls and not content.strip():
            continue
        if role == "tool":
            continue
        if role == "assistant" and content:
            reasoning_parts.append(content)
    
    reasoning_text = "\n\n".join(reasoning_parts)
    
    # Sanitize all text
    user_msg = _sanitize(user_msg)
    reasoning_text = _sanitize(reasoning_text)
    ai_msg = _sanitize(ai_msg)
    
    try:
        from fpdf import FPDF
        
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
        
        # Title Page
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
        
        # User Message
        pdf.set_font(font_name, "", 16)
        pdf.set_text_color(40, 40, 80)
        pdf.cell(0, 12, "User Request", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.set_font(font_name, "", 11)
        pdf.set_text_color(50, 50, 50)
        pdf.multi_cell(0, 6, user_msg)
        pdf.ln(10)
        
        # Reasoning
        if reasoning_text.strip():
            pdf.add_page()
            pdf.set_font(font_name, "", 16)
            pdf.set_text_color(40, 40, 80)
            pdf.cell(0, 12, "Thinking Process", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
            
            paragraphs = reasoning_text.split("\n\n")
            for para in paragraphs:
                if para.strip():
                    if para.strip().startswith("```"):
                        code_content = para.strip().strip("```").strip()
                        pdf.set_fill_color(245, 245, 250)
                        pdf.set_text_color(60, 60, 80)
                        pdf.set_font(font_name, "", 9)
                        for line in code_content.split("\n"):
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
        
        # AI Response
        pdf.add_page()
        pdf.set_font(font_name, "", 16)
        pdf.set_text_color(40, 40, 80)
        pdf.cell(0, 12, "AI Response", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        
        lines = ai_msg.split("\n")
        in_code_block = False
        code_buffer = []
        
        for line in lines:
            stripped = line.strip()
            
            if stripped.startswith("```"):
                if in_code_block:
                    pdf.set_fill_color(240, 240, 248)
                    pdf.set_text_color(50, 50, 80)
                    pdf.set_font(font_name, "", 9)
                    for cl in code_buffer:
                        if cl.strip():
                            pdf.multi_cell(0, 4.5, cl, fill=True)
                        else:
                            pdf.ln(2)
                    pdf.ln(3)
                    code_buffer = []
                    in_code_block = False
                    pdf.set_font(font_name, "", 11)
                    pdf.set_text_color(50, 50, 50)
                else:
                    in_code_block = True
                    code_buffer = []
                continue
            
            if in_code_block:
                code_buffer.append(line)
                continue
            
            if stripped.startswith("### "):
                pdf.set_font(font_name, "", 12)
                pdf.set_text_color(60, 60, 100)
                pdf.multi_cell(0, 7, stripped[4:])
                pdf.set_font(font_name, "", 11)
                pdf.set_text_color(50, 50, 50)
            elif stripped.startswith("## "):
                pdf.set_font(font_name, "", 13)
                pdf.set_text_color(50, 50, 90)
                pdf.multi_cell(0, 8, stripped[3:])
                pdf.set_font(font_name, "", 11)
                pdf.set_text_color(50, 50, 50)
            elif stripped.startswith("# "):
                pdf.set_font(font_name, "", 14)
                pdf.set_text_color(40, 40, 80)
                pdf.multi_cell(0, 9, stripped[2:])
                pdf.set_font(font_name, "", 11)
                pdf.set_text_color(50, 50, 50)
            elif stripped.startswith("- **") or stripped.startswith("- "):
                pdf.set_x(pdf.l_margin + 5)
                pdf.multi_cell(0, 6, line)
            elif stripped == "---" or stripped == "***":
                pdf.set_draw_color(180, 180, 200)
                pdf.set_line_width(0.3)
                pdf.line(30, pdf.get_y(), pdf.w - 30, pdf.get_y())
                pdf.ln(5)
            else:
                pdf.multi_cell(0, 6, line)
        
        if code_buffer:
            pdf.set_fill_color(240, 240, 248)
            pdf.set_text_color(50, 50, 80)
            pdf.set_font(font_name, "", 9)
            for cl in code_buffer:
                if cl.strip():
                    pdf.multi_cell(0, 4.5, cl, fill=True)
                else:
                    pdf.ln(2)
        
        pdf.output(output_path)
        return {"success": True, "output": output_path, "topic": topic_title, "stamp": stamp}
    
    except ImportError:
        return {"error": "fpdf2 not installed. Run: pip install fpdf2"}
    except Exception as e:
        return {"error": f"PDF generation failed: {str(e)}"}


def meta_toolkit_export_last_pdf() -> dict:
    return {"type": "function", "function": {"name": "toolkit_export_last_pdf", "description": "导出当前会话的最后一条 user+AI 消息（含思考过程，忽略工具调用轮）为简洁优美的 PDF 文件，保存为 last.pdf", "parameters": {"type": "object", "properties": {"output_path": {"type": "string", "description": "PDF 输出路径，默认 last.pdf", "default": "last.pdf"}}, "required": []}}}
