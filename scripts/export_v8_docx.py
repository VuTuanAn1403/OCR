"""Export the v8 Markdown documents (00-09 and the backlog) to one Word file.

Markdown stays the source of truth; the .docx is a read-only rendering. The
writer uses only the standard library (zipfile + WordprocessingML), so no
package download is needed. Output bytes are deterministic for identical
inputs, which lets the knowledge-map registry track the export by SHA-256.

    python scripts/export_v8_docx.py [--output PATH] [--update-registry]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
V8_DIR = "cai tien v2"
OUTPUT = f"{V8_DIR}/OCR_PDF_V8_BO_TAI_LIEU.docx"
REGISTRY = f"{V8_DIR}/10_TRANG_THAI_V8.json"
BACKLOG = f"{V8_DIR}/06_BACKLOG_V8.csv"
DOCUMENTS = ("00_README.md", "01_RADAR_CONG_NGHE_THEO_TANG.md", "02_KIEM_TOAN_KHOANG_TRONG.md",
             "03_LO_TRINH_V8_THEO_TANG.md", "04_DAC_TA_DO_DAU_9999.md", "05_HOP_DONG_BENCHMARK_ADAPTER.md",
             "07_PHUONG_PHAP_DU_AN_LON_AI.md", "08_TOI_UU_TOKEN.md", "09_LUU_TRU_CAI_TIEN_V7.md")
TEXT_WIDTH = 9638  # A4 (11906 DXA) minus 2 x 1134 DXA margins
FONT = "Times New Roman"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))")
STRIP = re.compile(r"<!--.*?-->|<a id=\"[^\"]*\"></a>")


def _t(text: str) -> str:
    return f'<w:t xml:space="preserve">{escape(unicodedata.normalize("NFC", text))}</w:t>'


class Writer:
    """Collect body XML, external hyperlinks and list numbering."""

    def __init__(self) -> None:
        self.body: list[str] = []
        self.links: list[str] = []
        self.numbered_lists = 0

    def runs(self, text: str, base: str = "") -> str:
        parts = []
        for token in INLINE.split(text.replace("\\|", "|")):
            if not token:
                continue
            if token.startswith("**") and token.endswith("**"):
                parts.append(f"<w:r><w:rPr>{base}<w:b/></w:rPr>{_t(token[2:-2])}</w:r>")
            elif token.startswith("`") and token.endswith("`"):
                parts.append(f'<w:r><w:rPr>{base}<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" '
                             f'w:cs="Consolas"/></w:rPr>{_t(token[1:-1])}</w:r>')
            elif token.startswith("[") and "](" in token:
                label, target = token[1:].split("](", 1)
                target = target[:-1]
                if target.startswith(("http://", "https://")):
                    self.links.append(target)
                    rid = f"rIdLink{len(self.links)}"
                    parts.append(f'<w:hyperlink r:id="{rid}" w:history="1"><w:r><w:rPr>'
                                 f'<w:rStyle w:val="Hyperlink"/>{base}</w:rPr>{_t(label)}</w:r></w:hyperlink>')
                else:
                    parts.append(f"<w:r><w:rPr>{base}</w:rPr>{_t(label)}</w:r>" if base else f"<w:r>{_t(label)}</w:r>")
            else:
                parts.append(f"<w:r><w:rPr>{base}</w:rPr>{_t(token)}</w:r>" if base else f"<w:r>{_t(token)}</w:r>")
        return "".join(parts)

    def paragraph(self, text: str, style: str | None = None, extra: str = "") -> None:
        ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") + extra
        self.body.append(f"<w:p>{f'<w:pPr>{ppr}</w:pPr>' if ppr else ''}{self.runs(text)}</w:p>")

    def page_break(self) -> None:
        self.body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    def code(self, lines: list[str]) -> None:
        for line in lines or [""]:
            self.body.append(f'<w:p><w:pPr><w:pStyle w:val="Code"/></w:pPr><w:r>{_t(line)}</w:r></w:p>')

    def list_item(self, text: str, ordered: bool, level: int, new_list: bool) -> None:
        if ordered and new_list:
            self.numbered_lists += 1
        num = self.numbered_lists + 1 if ordered else 1
        self.paragraph(text, "ListParagraph", f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{num}"/></w:numPr>')

    def table(self, rows: list[list[str]]) -> None:
        columns = max(len(row) for row in rows)
        rows = [row + [""] * (columns - len(row)) for row in rows]
        weights = [max(4, min(40, max(len(row[i]) for row in rows))) for i in range(columns)]
        widths = [TEXT_WIDTH * weight // sum(weights) for weight in weights]
        widths[-1] += TEXT_WIDTH - sum(widths)
        border = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>'
                         for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
        xml = [f'<w:tbl><w:tblPr><w:tblW w:w="{TEXT_WIDTH}" w:type="dxa"/><w:tblBorders>{border}</w:tblBorders>'
               '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:left w:w="80" w:type="dxa"/>'
               '<w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>'
               + "".join(f'<w:gridCol w:w="{width}"/>' for width in widths) + "</w:tblGrid>"]
        for index, row in enumerate(rows):
            header = index == 0
            cells = []
            for width, cell in zip(widths, row):
                shade = '<w:shd w:val="clear" w:color="auto" w:fill="D9E2F3"/>' if header else ""
                runs = self.runs(cell.strip(), "<w:b/>" if header else "")
                cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>'
                             f'<w:p><w:pPr><w:pStyle w:val="TableText"/></w:pPr>{runs}</w:p></w:tc>')
            row_pr = "<w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>" if header else "<w:trPr><w:cantSplit/></w:trPr>"
            xml.append(f"<w:tr>{row_pr}{''.join(cells)}</w:tr>")
        self.body.append("".join(xml) + "</w:tbl>")
        self.body.append('<w:p><w:pPr><w:spacing w:after="0"/></w:pPr></w:p>')


def split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [cell.strip() for cell in cells]


def render_markdown(writer: Writer, text: str) -> None:
    lines = [STRIP.sub("", line.rstrip()) for line in text.replace("\r\n", "\n").split("\n")]
    buffer: list[str] = []
    previous_ordered = False

    def flush() -> None:
        if buffer:
            writer.paragraph(" ".join(buffer))
            buffer.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            block = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            writer.code(block)
            previous_ordered = False
        elif stripped.startswith("|"):
            flush()
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = split_row(lines[index])
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row if cell):
                    rows.append(row)
                index += 1
            writer.table(rows)
            previous_ordered = False
            continue
        elif match := re.match(r"^(#{1,6})\s+(.*)$", line):
            flush()
            level = min(len(match.group(1)), 4)
            writer.paragraph(match.group(2), f"Heading{level}")
            previous_ordered = False
        elif match := re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line):
            flush()
            ordered = match.group(2)[0].isdigit()
            level = min(len(match.group(1)) // 2, 1)
            writer.list_item(match.group(3), ordered, level, ordered and level == 0 and not previous_ordered)
            previous_ordered = ordered or (previous_ordered and level > 0)
        elif stripped.startswith(">"):
            flush()
            writer.paragraph(stripped.lstrip(">").strip(), "Quote")
            previous_ordered = False
        elif not stripped:
            flush()  # blank lines inside a loose list keep its numbering
        elif line.startswith("  "):
            flush()
            indent = 720 * min((len(line) - len(line.lstrip())) // 2, 2)
            writer.paragraph(stripped, None, f'<w:ind w:left="{indent}"/>')
        else:
            buffer.append(stripped)
            previous_ordered = False
        index += 1
    flush()


def backlog_markdown(root: Path) -> str:
    reader = csv.DictReader(io.StringIO((root / BACKLOG).read_bytes().decode("utf-8-sig")))
    lines = ["# Phụ lục: Backlog V8 (rút gọn)", "",
             "Bản đầy đủ là `cai tien v2/06_BACKLOG_V8.csv`.", "",
             "| ID | Tiêu đề | Ưu tiên | Trạng thái | Chặn bởi |", "| --- | --- | --- | --- | --- |"]
    for row in reader:
        cells = [row["id"], row["title_vi"], row["priority"], row["status"], row["blocked_by"] or "—"]
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    return "\n".join(lines) + "\n"


def export_sources() -> list[str]:
    return [f"{V8_DIR}/{name}" for name in DOCUMENTS] + [BACKLOG]


STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}" w:eastAsia="{FONT}"/><w:sz w:val="23"/><w:szCs w:val="23"/><w:lang w:val="vi-VN"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="2400" w:after="240"/><w:jc w:val="center"/></w:pPr><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/><w:b/><w:color w:val="1F3864"/><w:sz w:val="44"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="0" w:after="120"/><w:jc w:val="center"/></w:pPr><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/><w:color w:val="404040"/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="160"/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="1F3864"/></w:pBdr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/><w:b/><w:color w:val="1F3864"/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/><w:b/><w:color w:val="2F5496"/><w:sz w:val="27"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="160" w:after="60"/><w:outlineLvl w:val="3"/></w:pPr><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/><w:b/><w:i/><w:sz w:val="23"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="60"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:ind w:left="567" w:right="567"/><w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="8EAADB"/></w:pBdr></w:pPr><w:rPr><w:i/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/><w:ind w:left="284"/></w:pPr><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="20" w:after="20" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/><w:jc w:val="center"/></w:pPr><w:rPr><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>
</w:styles>"""


def _levels(kind: str) -> str:
    texts = ("•", "◦") if kind == "bullet" else ("%1.", "%2.")
    xml = []
    for level, text in enumerate(texts):
        fmt = "bullet" if kind == "bullet" else ("decimal" if level == 0 else "lowerLetter")
        text = text if kind == "bullet" or level == 0 else "%2)"
        xml.append(f'<w:lvl w:ilvl="{level}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/>'
                   f'<w:lvlText w:val="{text}"/><w:lvlJc w:val="left"/><w:pPr>'
                   f'<w:ind w:left="{720 + 360 * level}" w:hanging="360"/></w:pPr></w:lvl>')
    return "".join(xml)


def numbering(lists: int) -> str:
    nums = ['<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>']
    for number in range(2, lists + 2):
        nums.append(f'<w:num w:numId="{number}"><w:abstractNumId w:val="1"/>'
                    '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:numbering xmlns:w="{W_NS}">'
            f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>{_levels("bullet")}'
            f'</w:abstractNum><w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>'
            f'{_levels("decimal")}</w:abstractNum>{"".join(nums)}</w:numbering>')


def package(writer: Writer, title: str, date: str) -> bytes:
    rels = [f'<Relationship Id="rIdStyles" Type="{R_NS}/styles" Target="styles.xml"/>',
            f'<Relationship Id="rIdNumbering" Type="{R_NS}/numbering" Target="numbering.xml"/>',
            f'<Relationship Id="rIdFooter" Type="{R_NS}/footer" Target="footer1.xml"/>']
    rels += [f'<Relationship Id="rIdLink{i}" Type="{R_NS}/hyperlink" Target="{escape(url, {chr(34): "&quot;"})}" '
             'TargetMode="External"/>' for i, url in enumerate(writer.links, 1)]
    section = ('<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter"/>'
               '<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
               'w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{W_NS}" '
                f'xmlns:r="{R_NS}"><w:body>{"".join(writer.body)}{section}</w:body></w:document>')
    footer = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:ftr xmlns:w="{W_NS}" xmlns:r="{R_NS}">'
              '<w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/>'
              '</w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
        '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{R_NS}/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        f'<Relationship Id="rId3" Type="{R_NS}/extended-properties" Target="docProps/app.xml"/></Relationships>',
        "docProps/core.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{escape(title)}</dc:title>'
        '<dc:creator>OCR PDF</dc:creator><dc:language>vi-VN</dc:language>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{date}T00:00:00Z</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{date}T00:00:00Z</dcterms:modified></cp:coreProperties>',
        "docProps/app.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties '
        'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        '<Application>OCR PDF scripts/export_v8_docx.py</Application></Properties>',
        "word/_rels/document.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>',
        "word/document.xml": document,
        "word/styles.xml": STYLES,
        "word/numbering.xml": numbering(writer.numbered_lists),
        "word/footer1.xml": footer,
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode("utf-8"))
    return stream.getvalue()


def render(documents: list[str], meta: dict) -> bytes:
    """Render Markdown texts (in order) after a title page into .docx bytes."""
    writer = Writer()
    title = "Bộ tài liệu nâng cấp OCR PDF v8.0"
    writer.paragraph(title, "Title")
    writer.paragraph("Bản Word tổng hợp, chỉ để đọc; nguồn chuẩn là Markdown trong `cai tien v2/`.", "Subtitle")
    writer.paragraph(f"HEAD xác minh `{meta.get('verified_head', '')[:7]}` · ngày {meta.get('last_verified', '')} "
                     f"· mã nguồn {meta.get('pipeline_version', '')}", "Subtitle")
    writer.paragraph("Chất lượng OCR: NOT_EVALUATED (chưa có Ground Truth độc lập).", "Subtitle")
    for text in documents:
        writer.page_break()
        render_markdown(writer, text)
    return package(writer, title, meta.get("last_verified") or "2026-01-01")


def build(root: Path) -> tuple[bytes, list[str]]:
    registry = json.loads((root / REGISTRY).read_bytes().decode("utf-8"))
    sources = export_sources()
    texts = [(root / rel).read_bytes().decode("utf-8") for rel in sources[:-1]]
    texts.append(backlog_markdown(root))
    return render(texts, registry), sources


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".export-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def text_sha256(path: Path) -> str:
    """Same rule as check_knowledge_map.sha256_file: text hashed with LF endings."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def update_registry(root: Path, output: str, data: bytes, sources: list[str]) -> None:
    """Replace only the trailing `exports` array so hand formatting is kept."""
    path = root / REGISTRY
    text = path.read_bytes().decode("utf-8")
    before = json.loads(text)
    entry = {"path": output, "sha256": hashlib.sha256(data).hexdigest(),
             "sources": [{"path": rel, "sha256": text_sha256(root / rel)} for rel in sources]}
    block = json.dumps([entry], ensure_ascii=False, indent=2).replace("\n", "\n  ")
    start = text.rfind('"exports":')
    if start < 0:
        raise ValueError("Registry has no exports key")
    updated = text[:start] + '"exports": ' + block + "\n}\n"
    after = json.loads(updated)
    if {k: v for k, v in after.items() if k != "exports"} != {k: v for k, v in before.items() if k != "exports"}:
        raise ValueError("Refusing to change registry fields other than exports")
    path.write_bytes(updated.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default=OUTPUT, help="path relative to the checkout")
    parser.add_argument("--update-registry", action="store_true", help="record export and source SHA-256")
    args = parser.parse_args(argv)
    try:
        target = (ROOT / args.output).resolve()
        if not target.is_relative_to(ROOT.resolve()):
            raise ValueError("--output must stay inside the checkout")
        output = target.relative_to(ROOT.resolve()).as_posix()
        if args.update_registry and output != OUTPUT:
            raise ValueError(f"--update-registry only records the canonical export {OUTPUT}")
        data, sources = build(ROOT)
        write_atomic(target, data)
        if args.update_registry:
            update_registry(ROOT, output, data, sources)
        print(f"Wrote {output}: {len(data)} B, sha256 {hashlib.sha256(data).hexdigest()}")
        return 0
    except (OSError, UnicodeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Cannot export DOCX: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
