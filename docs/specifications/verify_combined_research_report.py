"""Rasterize the native Word preview and check TOC/content provenance."""
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json
import re
import unicodedata
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

DOCS=Path(__file__).resolve().parents[1]
QA=DOCS/'specifications/combined_report_qa'
render=QA/'render'
render.mkdir(exist_ok=True)
word_file=DOCS/'PROJECT_REPORT_SPECIFICATION_DESIGN_RESEARCH_V5.docx'
source=DOCS/'PROJECT_REPORT_SPECIFICATION_DESIGN_RESEARCH_V5.md'
toc=json.loads((QA/'native_word_toc.json').read_text(encoding='utf-8-sig'))
pdf=pdfium.PdfDocument(QA/'native_word_render.pdf')
texts=[]
records=[]
for i in range(len(pdf)):
    page=pdf[i]
    tp=page.get_textpage()
    text=tp.get_text_range()
    texts.append(text)
    output=render/f'page-{i+1:03}.png'
    page.render(scale=2).to_pil().save(output)
    records.append({'page':i+1,'characters':len(text),'image':str(output)})
    tp.close()
    page.close()

def norm(s):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s)).strip()

toc_entries=[]
issues=[]
for entry in toc['TOCText'].split('\r'):
    if not entry.strip():continue
    title,page_str=entry.rsplit('\t',1)
    number=int(page_str)
    # The TOC must point to the actual heading on its stated body page.
    matched=1<=number<=len(pdf) and norm(title) in norm(texts[number-1])
    toc_entries.append({'title':title,'page':number,'heading_found_on_page':matched})
    if not matched:issues.append('TOC target mismatch: '+title)
if len(toc_entries)!=36:issues.append('Expected 3 parts and 33 chapters in TOC')
source_text=source.read_text(encoding='utf-8')
ids=set(re.findall(r'\b(?:FR|NF|SCI)-\d{2}\b',source_text))|set(re.findall(r'\bS\d{2}\b',source_text))
missing_ids=sorted(v for v in ids if v not in '\n'.join(texts))
if missing_ids:issues.append('Missing IDs: '+','.join(missing_ids))
for href in re.findall(r'\[[^\]]+\]\(([^)]+)\)',source_text):
    if '://' in href or href.startswith('#'):continue
    if not (source.parent/href.split('#')[0]).exists():issues.append('Missing local link: '+href)
if 'Mục lục sẽ được cập nhật bằng' in '\n'.join(texts):issues.append('TOC placeholder still present')
if source_text.count('```')%2:issues.append('Unbalanced code fences')
with ZipFile(word_file) as z:
    if z.testzip() is not None:issues.append('Invalid DOCX zip member')

font=ImageFont.truetype(r'C:\Windows\Fonts\calibri.ttf',24)
for start in range(0,len(pdf),9):
    sheet=Image.new('RGB',(1050,1500),'#E6E8EB')
    draw=ImageDraw.Draw(sheet)
    for n,r in enumerate(records[start:start+9]):
        im=Image.open(r['image']);im.thumbnail((330,440))
        x=(n%3)*350+10;y=(n//3)*500+35
        sheet.paste(im,(x,y))
        draw.text((x,y-28),f"Trang {r['page']}",font=font,fill='black')
    sheet.save(QA/f'contact-{start//9+1}.png')

report={
    'renderer':'Microsoft Word native PDF export and bundled pypdfium2 rasterization',
    'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'docx_sha256':hashlib.sha256(word_file.read_bytes()).hexdigest(),
    'page_count':len(pdf),'toc_entries':toc_entries,
    'missing_requirement_or_case_ids':missing_ids,
    'validation_issues':issues,'pages':records,'visual_inspection_status':'PENDING',
}
(QA/'render_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pages':len(pdf),'toc_entries':len(toc_entries),'issues':issues,'page_characters':[(r['page'],r['characters']) for r in records]},ensure_ascii=False))
raise SystemExit(bool(issues))
