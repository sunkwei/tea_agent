"""将 dump 目录所有 markdown 文件合并为单个 PDF，使用更健壮的文本处理"""
import os, glob, sys
from fpdf import FPDF

def clean_text(text):
    """清理可能引起 PDF 渲染问题的字符"""
    # Replace tabs with spaces
    text = text.replace('\t', '  ')
    # Replace problematic unicode chars
    text = text.replace('\u2028', '\n').replace('\u2029', '\n')
    # Remove zero-width characters
    for ch in ['\u200b', '\u200c', '\u200d', '\ufeff', '\u00ad']:
        text = text.replace(ch, '')
    return text

def safe_multicell(pdf, w, h, txt):
    """Safe version of multi_cell that handles edge cases"""
    txt = clean_text(txt)
    if not txt.strip():
        pdf.ln(h)
        return
    try:
        pdf.multi_cell(w, h, txt)
    except Exception as e:
        # Fallback: try line by line
        for line in txt.split('\n'):
            line = line.strip()
            if not line:
                pdf.ln(h)
                continue
            try:
                pdf.multi_cell(w, h, line)
            except:
                # If still fails, try writing character by character
                try:
                    pdf.cell(0, h, f'[complex content: {len(line)} chars]', new_x='LMARGIN', new_y='NEXT')
                except:
                    pdf.ln(h)

def main():
    path = os.path.expanduser('~/.tea_agent/dump_20260722')
    files = sorted(glob.glob(os.path.join(path, '*.md')))
    if not files:
        print('❌ 未找到 dump 文件')
        sys.exit(1)

    print(f'Found {len(files)} markdown files')
    
    pdf = FPDF(orientation='P', format='A4')
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    font_path = 'C:/Windows/Fonts/simhei.ttf'
    pdf.add_font('SimHei', '', font_path)

    # Title page
    pdf.set_font('SimHei', '', 20)
    pdf.ln(50)
    pdf.cell(0, 15, 'Tea Agent 对话记录', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('SimHei', '', 12)
    pdf.ln(5)
    pdf.cell(0, 8, f'导出时间: 2026-07-22', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 8, f'共 {len(files)} 个主题  |  仅最终消息', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(10)

    for i, f in enumerate(files):
        name = os.path.basename(f).replace('.md', '')
        title = name.split('_', 1)[-1] if '_' in name else name
        # Truncate very long titles
        if len(title) > 80:
            title = title[:77] + '...'

        with open(f, 'r', encoding='utf-8') as fh:
            raw = fh.read()

        pdf.add_page()
        # Topic header
        pdf.set_font('SimHei', '', 13)
        pdf.set_fill_color(235, 240, 248)
        try:
            pdf.cell(0, 10, f'  #{i+1}  {title}', fill=True, new_x='LMARGIN', new_y='NEXT')
        except:
            pdf.cell(0, 10, f'  #{i+1}', fill=True, new_x='LMARGIN', new_y='NEXT')
        pdf.ln(4)

        # Process content line by line
        lines = raw.split('\n')
        content_mode = False  # Are we in a code block?
        
        for line in lines:
            line = line.rstrip()
            
            # Code block detection
            if line.startswith('```') or line.startswith('~~~'):
                content_mode = not content_mode
                continue
            
            if not line.strip():
                pdf.ln(2)
                continue
                
            # Skip horizontal rules
            if line.strip().startswith('---') and len(line.strip()) >= 3 and set(line.strip()) == {'-'}:
                # Draw a line
                pdf.set_draw_color(200, 200, 200)
                pdf.line(pdf.l_margin, pdf.y, pdf.w - pdf.r_margin, pdf.y)
                pdf.ln(3)
                continue
            
            text = clean_text(line)
            if not text.strip():
                continue
            
            # Choose font based on content
            if content_mode:
                pdf.set_font('SimHei', '', 7)
            elif line.startswith('### '):
                pdf.set_font('SimHei', '', 11)
                text = text.lstrip('#').strip()
            elif line.startswith('## '):
                pdf.set_font('SimHei', '', 11)
                text = text.lstrip('#').strip()
            elif line.startswith('# '):
                pdf.set_font('SimHei', '', 12)
                text = text.lstrip('#').strip()
            elif line.startswith('- ') or line.startswith('* '):
                pdf.set_font('SimHei', '', 8)
                text = '  ' + text
            elif line.startswith('> '):
                pdf.set_font('SimHei', '', 8)
                text = '  ' + text
            else:
                pdf.set_font('SimHei', '', 8)
            
            safe_multicell(pdf, 0, 5, text)
            
            # Reset font
            if not content_mode:
                pdf.set_font('SimHei', '', 8)

    out_path = os.path.join(os.getcwd(), 'chat_history_all.pdf')
    pdf.output(out_path)
    sz = os.path.getsize(out_path)
    print(f'✅ PDF: {out_path} ({sz//1024}KB, {pdf.pages_count} pages, {len(files)} topics)')

if __name__ == '__main__':
    main()
