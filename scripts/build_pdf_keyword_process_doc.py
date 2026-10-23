"""Build the Vietnamese PDF workflow document from its Markdown source.

Document tooling only; this script is not part of the OCR pipeline.
Run with the Codex bundled Python runtime (ReportLab).
"""
from __future__ import annotations

from pathlib import Path
import html
import re

from reportlab.graphics import renderSVG
from reportlab.graphics.shapes import Drawing, Rect, Line, Polygon, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    KeepTogether, Preformatted,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/QUY_TRINH_TU_PDF_DEN_TU_KHOA.md"
OUT = ROOT / "output/pdf/Quy_trinh_PDF_den_tu_khoa_OCR_pdf.pdf"
DIAGRAMS = ROOT / "docs/diagrams/pdf_den_tu_khoa"
INK = colors.HexColor("#172c3b")
TEAL = colors.HexColor("#146f77")
MUTED = colors.HexColor("#516473")
PALE = colors.HexColor("#edf5f6")
BLUE = colors.HexColor("#eef2fa")
GREY = colors.HexColor("#f3f5f6")
WIDTH = A4[0] - 86
# Column fractions for the section 12 tables, keyed by their first header cell.
PARAMETER_TABLES = {
    "Tham số": [.25, .23, .52],
    "Nhóm": [.17, .43, .40],
    "Giới hạn": [.35, .15, .50],
    "Loại lỗi": [.14, .43, .43],
    "Hiện tượng": [.34, .29, .37],
}


def register_fonts():
    font_dir = Path("C:/Windows/Fonts")
    for name, file in [("Arial", "arial.ttf"), ("Arial-Bold", "arialbd.ttf"),
                       ("Arial-Italic", "ariali.ttf"), ("Consolas", "consola.ttf")]:
        pdfmetrics.registerFont(TTFont(name, str(font_dir / file)))
    pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic")


def arrow(d, x1, y1, x2, y2):
    d.add(Line(x1, y1, x2, y2, strokeColor=MUTED, strokeWidth=1))
    if x1 == x2:
        s = 1 if y2 > y1 else -1
        pts = [x2, y2, x2 - 3, y2 - s * 6, x2 + 3, y2 - s * 6]
    else:
        s = 1 if x2 > x1 else -1
        pts = [x2, y2, x2 - s * 6, y2 - 3, x2 - s * 6, y2 + 3]
    d.add(Polygon(pts, fillColor=MUTED, strokeColor=MUTED))


def box(d, x, y, w, h, lines, fill=PALE, font_size=9.2):
    d.add(Rect(x, y, w, h, rx=5, ry=5, strokeColor=colors.HexColor("#bdd2d5"),
               strokeWidth=0.7, fillColor=fill))
    step = font_size + 3.2
    base = y + h / 2 + (len(lines) - 1) * step / 2 - font_size * 0.36
    for n, line in enumerate(lines):
        if pdfmetrics.stringWidth(line, "Arial", font_size) > w - 12:
            raise ValueError(f"Diagram label too wide: {line}")
        d.add(String(x + w / 2, base - n * step, line, textAnchor="middle",
                     fontName="Arial", fontSize=font_size, fillColor=INK))


def snake_diagram(labels, cols, bw, bh, gapx, gapy):
    rows = (len(labels) + cols - 1) // cols
    d = Drawing(WIDTH, rows * bh + (rows - 1) * gapy + 10)
    x0 = (WIDTH - (cols * bw + (cols - 1) * gapx)) / 2
    coords = []
    for i, lines in enumerate(labels):
        r, c = divmod(i, cols)
        if r % 2:
            c = cols - 1 - c
        x, y = x0 + c * (bw + gapx), 5 + (rows - r - 1) * (bh + gapy)
        box(d, x, y, bw, bh, lines, BLUE if i in (2, 4) else PALE)
        coords.append((x, y))
    for (x, y), (nx, ny) in zip(coords, coords[1:]):
        if y == ny:
            if nx > x:
                arrow(d, x + bw, y + bh / 2, nx - 1, ny + bh / 2)
            else:
                arrow(d, x, y + bh / 2, nx + bw + 1, ny + bh / 2)
        else:
            arrow(d, x + bw / 2, y, nx + bw / 2, ny + bh + 1)
    return d


def diagrams():
    overview = snake_diagram([
        ["1  PDF và danh sách từ khoá"],
        ["2  Kiểm cấu hình CUDA model", "Đóng băng input và từ điển"],
        ["3  Pha A GPU", "OCR mọi trang và layout"],
        ["4  Checkpoint pha A", "Chờ cây process thoát"],
        ["5  Pha B GPU", "OCR bridge và Docling"],
        ["6  Export CPU", "Bố cục và result.md cùng JSON"],
        ["7  Kiểm đủ trang và nguồn", "Đếm literal trong result.md"],
        ["8  Excel từng PDF", "Kiểm artifact và completion"],
        ["9  SQLite và ma trận Excel", "Đọc lại và xác nhận revision"],
        ["10  Chuyển sang PDF tiếp theo"],
    ], 2, 235, 39, 26, 15)
    ocr = snake_diagram([
        ["1  Trang PDF", "Render 180 DPI"],
        ["2  Resize và RGB", "Chuẩn hoá NCHW"],
        ["3  Detector ONNX", "PP OCRv4 trên CUDA"],
        ["4  Map xác suất", "Contour và box"],
        ["5  Crop vùng chữ", "Thêm lề 2 pixel"],
        ["6  VietOCR Seq2Seq", "Batch 4 trên CUDA"],
        ["7  Chuẩn hoá NFC", "Bảo vệ bằng chứng số"],
        ["8  Text và bbox", "Chữ gốc và xác suất"],
        ["9  Lưu evidence", "Đưa sang pha cấu trúc"],
    ], 3, 150, 40, 20, 18)
    d = Drawing(WIDTH, 236)
    bw, bh = 228, 36
    box(d, 8, 196, bw, bh, ["result.md", "NFC và casefold"])
    box(d, WIDTH - 8 - bw, 196, bw, bh, ["keywords.txt và snapshot", "Canonical và display"])
    # Two inputs feed the same matcher through an orthogonal junction.
    for cx in (8 + bw / 2, WIDTH - 8 - bw / 2):
        d.add(Line(cx, 196, cx, 181, strokeColor=MUTED, strokeWidth=1))
    d.add(Line(8 + bw / 2, 181, WIDTH - 8 - bw / 2, 181, strokeColor=MUTED, strokeWidth=1))
    arrow(d, WIDTH / 2, 181, WIDTH / 2, 168)
    levels = [
        (132, ["re.escape và re.finditer", "Literal từng keyword không chồng lấn"]),
        (88, ["Ánh xạ canonical sang display", "Tính hai tổng tương ứng"]),
        (44, ["keyword_counts.json và Excel riêng", "Kiểm hash mapping và workbook"]),
        (0, ["SQLite và ma trận Excel", "Xác nhận revision trước PDF tiếp theo"]),
    ]
    for y, lines in levels:
        box(d, (WIDTH - 360) / 2, y, 360, 36, lines)
    for upper, lower in [(132, 88), (88, 44), (44, 0)]:
        arrow(d, WIDTH / 2, upper, WIDTH / 2, lower + 37)
    return {"overview": overview, "ocr": ocr, "keywords": d}


def inline(s):
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r'<font name="Consolas" size="8.5">\1</font>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(https?://[^\s<]+)", r'<link href="\1" color="#146f77">\1</link>', s)
    return s


def build():
    register_fonts()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    DIAGRAMS.mkdir(parents=True, exist_ok=True)
    figs = diagrams()
    for key, drawing in figs.items():
        renderSVG.drawToFile(drawing, str(DIAGRAMS / f"{key}.svg"))

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("BodyVI", fontName="Arial", fontSize=10.1, leading=14.2,
                              textColor=INK, spaceAfter=7.3, splitLongWords=True))
    styles.add(ParagraphStyle("TitleVI", fontName="Arial-Bold", fontSize=23, leading=29,
                              textColor=colors.black, spaceAfter=11))
    styles.add(ParagraphStyle("HeadingVI", fontName="Arial-Bold", fontSize=15.2, leading=20,
                              textColor=INK, spaceBefore=4, spaceAfter=10, keepWithNext=True))
    styles.add(ParagraphStyle("SubVI", fontName="Arial-Bold", fontSize=11.7, leading=16,
                              textColor=TEAL, spaceBefore=8, spaceAfter=6, keepWithNext=True))
    styles.add(ParagraphStyle("CellVI", fontName="Arial", fontSize=8.7, leading=11.7,
                              textColor=INK, splitLongWords=True, spaceAfter=0))
    styles.add(ParagraphStyle("HeadCellVI", parent=styles["CellVI"], fontName="Arial-Bold",
                              textColor=colors.white))
    styles.add(ParagraphStyle("CodeVI", fontName="Consolas", fontSize=8.25, leading=12,
                              textColor=INK, backColor=GREY, borderPadding=8,
                              spaceBefore=3, spaceAfter=9))
    styles.add(ParagraphStyle("BulletVI", parent=styles["BodyVI"], leftIndent=12,
                              firstLineIndent=-9, spaceAfter=5))
    styles.add(ParagraphStyle("CaptionVI", parent=styles["BodyVI"], fontSize=8.8, leading=12,
                              textColor=MUTED, alignment=TA_CENTER, spaceAfter=10))
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    story = []
    i, pending_diagram = 0, None
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s == "<pagebreak/>":
            story.append(PageBreak())
            i += 1
            continue
        if s.startswith("<!-- diagram:"):
            pending_diagram = s.split(":", 1)[1].split()[0]
            i += 1
            continue
        if s.startswith("```"):
            lang = s[3:]
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            if lang == "mermaid":
                (DIAGRAMS / f"{pending_diagram}.mmd").write_text("\n".join(code) + "\n", encoding="utf-8")
                story += [figs[pending_diagram], Spacer(1, 7)]
                pending_diagram = None
            else:
                # Preformatted code is kept readable at a fixed font size.
                story.append(Preformatted("\n".join(code), styles["CodeVI"], maxLineLength=91))
            continue
        if s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[:\- ]+", c) for c in cells):
                    rows.append(cells)
                i += 1
            n = len(rows[0])
            widths = {2: [WIDTH * .32, WIDTH * .68],
                      3: [WIDTH * .26, WIDTH * .49, WIDTH * .25],
                      4: [WIDTH * .23, WIDTH * .18, WIDTH * .23, WIDTH * .36]}[n]
            # Example semantics table needs more room for the text source.
            if rows[0][0].startswith("Văn bản"):
                widths = [WIDTH * .36, WIDTH * .20, WIDTH * .13, WIDTH * .31]
            if rows[0][0] == "Môi trường":
                widths = [WIDTH * .25, WIDTH * .32, WIDTH * .43]
            if rows[0][0] == "Nội dung":
                widths = [WIDTH * .20, WIDTH * .39, WIDTH * .41]
            if rows[0][0] in PARAMETER_TABLES:
                widths = [WIDTH * f for f in PARAMETER_TABLES[rows[0][0]]]
            parsed = [[Paragraph(inline(c), styles["HeadCellVI" if j == 0 else "CellVI"])
                       for c in row] for j, row in enumerate(rows)]
            table = Table(parsed, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), TEAL),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY]),
                ("LINEBELOW", (0, 0), (-1, 0), .5, TEAL),
                ("LINEBELOW", (0, 1), (-1, -1), .25, colors.HexColor("#dce4e7")),
            ]))
            story += [table, Spacer(1, 9)]
            continue
        if s.startswith("### "):
            story.append(Paragraph(inline(s[4:]), styles["SubVI"]))
        elif s.startswith("## "):
            story.append(Paragraph(inline(s[3:]), styles["HeadingVI"]))
        elif s.startswith("# "):
            story.append(Paragraph(inline(s[2:]), styles["TitleVI"]))
        elif s.startswith("- "):
            story.append(Paragraph("• " + inline(s[2:]), styles["BulletVI"]))
        elif re.match(r"^\d+\. ", s):
            story.append(Paragraph(inline(s), styles["BulletVI"]))
        else:
            text_lines = [s]
            while i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith(("#", "|", "```", "<", "- ")):
                if re.match(r"^\d+\. ", lines[i + 1]):
                    break
                i += 1
                text_lines.append(lines[i].strip())
            story.append(Paragraph(inline(" ".join(text_lines)), styles["BodyVI"]))
        i += 1

    def page_chrome(canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setFillColor(MUTED)
            canvas.setFont("Arial", 8)
            canvas.drawString(43, A4[1] - 28, "OCR_pdf  |  Quy trình từ PDF đến từ khoá  |  V6.3")
        canvas.setFont("Arial", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(43, 25, "21/10/2026")
        canvas.drawRightString(A4[0] - 43, 25, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=43, rightMargin=43,
                            topMargin=46, bottomMargin=43, title="Quy trình từ PDF đến kết quả đếm từ khoá",
                            author="OCR_pdf", subject="Tài liệu kỹ thuật pipeline V6.3")
    doc.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome)
    print(OUT)


if __name__ == "__main__":
    build()
