"""将 ~/.tea_agent/dump_20260722/ 下的所有 markdown 合并为单个 PDF"""
import os, glob, sys
from fpdf import FPDF

def main():
    path = os.path.expanduser('~/.tea_agent/dump_20260722')
    files = sorted(glob.glob(os.path.join(path, '*.md')))
    if not files:
        print('❌ 未找到 dump 文件')
        sys.exit(1)

    pdf = FPDF(orientation='P', format='A4')
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # SimHei for Chinese support
    font_path = 'C:/Windows/Fonts/simhei.ttf'
    pdf.add_font('SimHei', '', font_path)

    # Title page
    pdf.set_font('SimHei', '', 20)
    pdf.ln(40)
    pdf.cell(0, 15, 'Tea Agent 对话记录', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('SimHei', '', 11)
    pdf.ln(5)
    pdf.cell(0, 8, f'共 {len(files)} 个主题  |  仅最终消息', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(5)

    for i, f in enumerate(files):
        name = os.path.basename(f).replace('.md', '')
        title = name.split('_', 1)[-1] if '_' in name else name

        with open(f, 'r', encoding='utf-8') as fh:
            raw = fh.read()

        pdf.add_page()
        # Topic header with background
        pdf.set_font('SimHei', '', 13)
        pdf.set_fill_color(235, 240, 248)
        pdf.cell(0, 10, f'  #{i+1}  {title[:80]}', fill=True, new_x='LMARGIN', new_y='NEXT')
        pdf.ln(3)

        pdf.set_font('SimHei', '', 9)
        lines = raw.split('\n')
        for line in lines:
            line = line.rstrip()
            if not line:
                pdf.ln(2)
                continue
            if line.startswith('# ') or line.startswith('## ') or line.startswith('### '):
                pdf.set_font('SimHei', '', 11)
                pdf.ln(1)
                text = line.lstrip('#').strip()
                pdf.multi_cell(0, 6, text)
                pdf.set_font('SimHei', '', 9)
            elif line.startswith('- ') or line.startswith('* '):
                pdf.multi_cell(0, 4.5, '  ' + line)
            else:
                # Check if line is too long, wrap manually
                if len(line) > 90:
                    # Split into chunks
                    words = line.split('  ')
                    current = ''
                    for w in words:
                        if len(current) + len(w) + 2 > 90:
                            pdf.multi_cell(0, 4.5, current)
                            current = w
                        else:
                            current = (current + '  ' + w) if current else w
                    if current:
                        pdf.multi_cell(0, 4.5, current)
                else:
                    pdf.multi_cell(0, 4.5, line)

    out_path = os.path.join(os.getcwd(), 'chat_history_all.pdf')
    pdf.output(out_path)
    sz = os.path.getsize(out_path)
    print(f'✅ PDF generated: {out_path}')
    print(f'   Size: {sz//1024} KB, Pages: {pdf.pages_count}, Topics: {len(files)}')

if __name__ == '__main__':
    main()
