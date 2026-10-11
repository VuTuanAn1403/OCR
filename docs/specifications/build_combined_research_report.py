"""Assemble specification and detailed design, then author one Word report.

Native Word updates the TOC in a separate render/verification step.
"""
from pathlib import Path
import csv
import hashlib
import json
import re

DOCS = Path(__file__).resolve().parents[1]
SPEC = DOCS / 'PROJECT_SPECIFICATION_RESEARCH_V5.md'
DESIGN = DOCS / 'PROJECT_DETAILED_DESIGN_RESEARCH_V5.md'
REPORT = DOCS / 'PROJECT_REPORT_SPECIFICATION_DESIGN_RESEARCH_V5.md'
BUILDER = DOCS / 'specifications' / 'export_combined_research_report_docx.py'


def demote(text):
    return re.sub(r'^(#{1,5})(?=\s)', r'#\1', text, flags=re.M)


spec_text = SPEC.read_text(encoding='utf-8')
design_text = DESIGN.read_text(encoding='utf-8')
spec_body = spec_text[spec_text.index('## 1.'):]
design_body = design_text[design_text.index('## 18.'):]
front = '''# Báo cáo đặc tả và thiết kế dự án OCR pdf V5

**Phiên bản báo cáo:** 1.0 — **Ngày:** 11/10/2026  
**Đề tài:** trích xuất PDF đa dạng sang Markdown với đánh giá độ chính xác có ground truth độc lập và hiệu năng CPU.  
**Đối tượng sử dụng:** người nghiên cứu, người hướng dẫn và Antigravity triển khai dự án.  
**Thành phần hợp nhất:** đặc tả phiên bản 1.0 ngày 10/10/2026 và thiết kế chi tiết phiên bản 1.0 ngày 11/10/2026.

Báo cáo này xác định sản phẩm cần đáp ứng yêu cầu gì và thiết kế hệ thống thực hiện các yêu cầu đó như thế nào. Phần I giữ nội dung đặc tả, phần II bổ sung thiết kế triển khai, phần III nối yêu cầu với thiết kế và hồ sơ kiểm chứng. Mục lục Word liên kết đến các phần và chương, có số trang được cập nhật khi xuất.

Đây là hồ sơ yêu cầu và thiết kế, chưa phải biên bản nghiệm thu hoặc báo cáo kết quả thực nghiệm. Các quan sát mã nguồn trong phần đặc tả giữ mốc 10/10/2026; thiết kế mục tiêu ngày 11/10/2026 có các interface và contract đề xuất chưa được coi là đã triển khai. Báo cáo không thêm số accuracy, tốc độ hay tuyên bố đã đạt chất lượng nghiên cứu.

Giữ nguyên ba trần thời gian CPU đã xác nhận: native ≤ 0,15; mixed ≤ 1,8; scan ≤ 2,5 giây/trang. Accuracy target tuyệt đối chưa được chốt được ghi NOT_SPECIFIED. Anti cần nộp bằng chứng theo yêu cầu, không thay mục tiêu để phù hợp kết quả.

[[TOC]]

## Phần I Đặc tả dự án

Quy ước PHẢI/NÊN/CÓ THỂ của đặc tả được giữ nguyên. Nhãn OBSERVED_IN_CODE chỉ xác nhận quan sát module, không chứng minh yêu cầu đã được nghiệm thu. Các thông tin hiện trạng bên dưới là đối chiếu lịch sử tại ngày 10/10/2026.

'''
report = front + demote(spec_body) + '\n\n## Phần II Thiết kế hệ thống\n\n'
report += 'Thiết kế sau đây cụ thể hóa yêu cầu của phần I. Interface, kiểu dữ liệu và contract mới là thiết kế đề xuất; mã đang có được nêu ở cột liên hệ để hướng dẫn triển khai. Không có GT hoặc actual runs được tạo trong bước soạn báo cáo.\n\n'
report += demote(design_body)
report += '''

## Phần III Truy vết và kiểm chứng

### 31. Ma trận yêu cầu thiết kế và bằng chứng

Bảng nối đủ 38 yêu cầu của phần I với chương thiết kế tương ứng và phương pháp kiểm chứng. Đây là kế hoạch truy vết; tất cả yêu cầu vẫn có trạng thái NOT_ACCEPTED trong ma trận nguồn cho đến khi được bổ sung evidence thực. Ca A01–A20 là kiểm tra evaluator; S01–S17 là các kịch bản toàn dự án trong chương 15. Các mục DATA_AUDIT, SPLIT_AUDIT và CLAIM_AUDIT là công việc kiểm toán, không phải test đã chạy.

| Yêu cầu | Chương thiết kế | Kiểm chứng | Bằng chứng cần nộp |
|---|---|---|---|
'''
section_map = {
    'FR-01':'19 20 21 28','FR-02':'19 21','FR-03':'21','FR-04':'20 21',
    'FR-05':'19 21 27','FR-06':'20 21','FR-07':'22 25','FR-08':'22 25',
    'FR-09':'22 25','FR-10':'22','FR-11':'22 23 25','FR-12':'22 24',
    'FR-13':'21 22','FR-14':'23 27','FR-15':'23','FR-16':'23',
    'FR-17':'24','FR-18':'20 24','FR-19':'19 21 24','FR-20':'24',
    'FR-21':'20 25 28','FR-22':'24 25','FR-23':'20 24 26','FR-24':'26',
    'NF-01':'20 26 29','NF-02':'19 27 28','NF-03':'23 27',
    'NF-04':'24 28 29','NF-05':'26 28','NF-06':'24 28',
    'SCI-01':'26 30','SCI-02':'25 26','SCI-03':'26 30',
    'SCI-04':'25 29','SCI-05':'26','SCI-06':'25 26',
    'SCI-07':'21 27','SCI-08':'26 29 30',
}
rows=list(csv.DictReader((DOCS/'PROJECT_REQUIREMENTS_TRACEABILITY.csv').open(encoding='utf-8',newline='')))
assert len(rows)==38 and set(section_map)=={r['requirement_id'] for r in rows}
for r in rows:
    values=[r['requirement_id'],', '.join(section_map[r['requirement_id']].split()),
            r['verification_cases'].replace(';',', '),r['required_evidence']]
    report += '| '+' | '.join(v.replace('|','\\|') for v in values)+' |\n'
report += '''

### 32. Hồ sơ bàn giao và cách sử dụng báo cáo

Anti triển khai theo chương 16 và 30, cập nhật từng yêu cầu bằng evidence path/hash và snapshot thực. File thiết kế không phải evidence rằng đã có implementation. Không đánh dấu hoàn thành accuracy/performance nếu chưa có GT, regime đã khóa, actual runs và kết quả đáp ứng phạm vi.

| Hồ sơ | Nội dung phải có | Cổng nghiệm thu |
|---|---|---|
| Source và môi trường | Source snapshot, dirty patch nếu có, exact versions, model/provider/config hashes | G0 G1 |
| Sản phẩm | Markdown/JSON/assets/alignment, status/errors và queue reconciliation | G1 |
| Evaluator | Golden reference outputs, parity scope, A01–A20 và adapter versions | G2 |
| Dữ liệu | Dataset/split/GT manifests, rights, coverage và human review evidence | G3 |
| Thực nghiệm | Actual baseline/ablation runs, CPU timings, counts/CI và failure records | G4 G5 |
| Bài nghiên cứu | Claim registry, raw evidence links, related work, giới hạn và reproducibility review | G6 |

Khi mã, config, weights, dataset, GT hoặc metric policy thay đổi, phải xác định phần artifact/comparison bị invalidated rồi chạy lại phạm vi cần thiết. Không tự cập nhật baseline, chép outputs cũ hoặc đổi threshold để đóng task.

Mục lục trong Word là trường có thể cập nhật. Sau khi người dùng chỉnh nội dung hoặc phân trang, chọn mục lục và cập nhật toàn bộ để đồng bộ số trang. Các headings dùng style Word để điều hướng và tái tạo mục lục; số trang trong bản xuất này được tính từ chính file Word cuối.

### 33. Nguồn tài liệu và lịch sử hợp nhất

Nguồn nội dung chính là [đặc tả V5](PROJECT_SPECIFICATION_RESEARCH_V5.md), [thiết kế chi tiết V5](PROJECT_DETAILED_DESIGN_RESEARCH_V5.md) và [ma trận yêu cầu](PROJECT_REQUIREMENTS_TRACEABILITY.csv). Phương pháp metric chi tiết và công trình liên quan theo [protocol](RESEARCH_PROTOCOL_V5.md), [nguồn tham chiếu](references/ACCURACY_SOURCES.md), [BibTeX](references/accuracy_metrics.bib) và [kế hoạch evaluator A01–A20](ANTIGRAVITY_ACCURACY_IMPLEMENTATION.md).

| Phiên bản | Ngày | Thay đổi |
|---|---|---|
| Đặc tả 1.0 | 10/10/2026 | Yêu cầu toàn dự án, dữ liệu/metrics/CPU và gates G0–G6 |
| Thiết kế 1.0 | 11/10/2026 | Kiến trúc, interface, dữ liệu, thuật toán, runtime/cache/export và evaluator |
| Báo cáo hợp nhất 1.0 | 11/10/2026 | Ghép đủ hai phần, bổ sung truy vết và mục lục Word có số trang |

Các nguồn nghiên cứu được liên kết tại chương 13. Citation hỗ trợ kiểm tra phương pháp; không chứng nhận accuracy hoặc thay thực nghiệm. Báo cáo này không đổi số liệu mục tiêu thành kết quả đã đo.
'''
REPORT.write_text(report,encoding='utf-8')

# Reuse the verified layout engine without altering the previous deliverable.
builder=(DOCS/'specifications/export_research_spec_docx.py').read_text(encoding='utf-8')
replacements={
    "SOURCE = ROOT / 'PROJECT_SPECIFICATION_RESEARCH_V5.md'":"SOURCE = ROOT / 'PROJECT_REPORT_SPECIFICATION_DESIGN_RESEARCH_V5.md'",
    "OUTPUT = ROOT / 'PROJECT_SPECIFICATION_RESEARCH_V5.docx'":"OUTPUT = ROOT / 'PROJECT_REPORT_SPECIFICATION_DESIGN_RESEARCH_V5.docx'",
    "QA = ROOT / 'specifications' / 'word_qa'":"QA = ROOT / 'specifications' / 'combined_report_qa'",
    "'OCR pdf V5  •  Đặc tả nghiên cứu'":"'OCR pdf V5  •  Đặc tả và thiết kế'",
    "p.add_run('Đặc tả dự án OCR pdf V5').add_break()":"p.add_run('Báo cáo đặc tả và thiết kế').add_break()",
    "p.add_run('phục vụ nghiên cứu khoa học')":"p.add_run('dự án OCR pdf V5')",
    "doc.core_properties.title='Đặc tả dự án OCR pdf V5 phục vụ nghiên cứu khoa học'":"doc.core_properties.title='Báo cáo đặc tả và thiết kế dự án OCR pdf V5'",
    "doc.core_properties.comments='Xuất từ đặc tả Markdown phiên bản 1.0. Không chứa kết quả thực nghiệm mới.'":"doc.core_properties.comments='Báo cáo hợp nhất ngày 11/10/2026. Nội dung thiết kế đề xuất, không chứa kết quả thực nghiệm mới.'",
    "if in_final_decisions and int(m[1])<5:":"if False:",
}
for old,new in replacements.items():
    assert old in builder,old
    builder=builder.replace(old,new)

# More width for the compact evidence matrix; report chapter headings are nested.
builder=builder.replace("if n==4:\n        if headers[0].strip()", "if n==4:\n        if headers[0].strip()=='Yêu cầu':\n            return [.67,1.00,1.25,3.88]\n        if headers[0].strip()")
builder=builder.replace("p.paragraph_format.keep_with_next=(row_idx==0)","p.paragraph_format.keep_with_next=(row_idx==0)")
builder=builder.replace("set_font(r, size=base_size, bold=header, color=base_color)","set_font(r, size=base_size, bold=header, color=base_color)")

# Native TOC field with an explicit cached placeholder, materialized by Word.
toc_handler='''    if s=='[[TOC]]':
        doc.add_page_break()
        p=doc.add_paragraph()
        p.paragraph_format.space_after=Pt(14)
        set_font(p.add_run('Mục lục'),size=18,bold=True)
        p=doc.add_paragraph()
        p._p.append(element('w:r'))
        r=element('w:r')
        r.append(element('w:fldChar', **{'w:fldCharType':'begin'}))
        p._p.append(r)
        r=element('w:r')
        instr=element('w:instrText')
        instr.set(qn('xml:space'),'preserve')
        instr.text=' TOC \\\\o "1-2" \\\\h \\\\z \\\\u '
        r.append(instr);p._p.append(r)
        r=element('w:r');r.append(element('w:fldChar', **{'w:fldCharType':'separate'}));p._p.append(r)
        p.add_run('Mục lục sẽ được cập nhật bằng Microsoft Word khi xuất báo cáo')
        r=element('w:r');r.append(element('w:fldChar', **{'w:fldCharType':'end'}));p._p.append(r)
        doc.add_page_break()
        i+=1
        continue
'''
needle="    if s.startswith('```'):"
assert needle in builder
builder=builder.replace(needle,toc_handler+needle)
heading_needle="            doc.add_paragraph(title, style='Heading '+str(depth-1))"
heading_replacement="            hp=doc.add_paragraph(title, style='Heading '+str(depth-1))\n            if depth==2 and not title.startswith('Phần I '):\n                hp.paragraph_format.page_break_before=True"
assert heading_needle in builder
builder=builder.replace(heading_needle,heading_replacement)

# Word TOC styles must remain black and readable after native field expansion.
style_needle="doc.styles['Title'].font.size=Pt(22)"
style_setup='''for toc_name in ['TOC 1','TOC 2','TOC 3']:
    if toc_name not in doc.styles:
        doc.styles.add_style(toc_name,1)
    ts=doc.styles[toc_name]
    ts.font.name='Calibri'
    ts.font.size=Pt(11)
    ts.font.color.rgb=RGBColor(0,0,0)
    ts.paragraph_format.space_after=Pt(5)
'''
builder=builder.replace(style_needle,style_setup+style_needle)
BUILDER.write_text(builder,encoding='utf-8')

headings=re.findall(r'^### (\d+)\.',report,re.M)
assert [int(n) for n in headings]==list(range(1,34)),headings
assert report.count('```')%2==0
manifest={
    'report':str(REPORT),'chapters':len(headings),
    'inputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [SPEC,DESIGN,DOCS/'PROJECT_REQUIREMENTS_TRACEABILITY.csv']},
    'report_sha256':hashlib.sha256(REPORT.read_bytes()).hexdigest(),
    'requirements':len(rows),'status':'AUTHORING_INPUTS_NOT_EMPIRICAL_EVIDENCE',
}
(DOCS/'specifications/combined_report_sources.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
exec(compile(BUILDER.read_text(encoding='utf-8'),str(BUILDER),'exec'), {'__file__':str(BUILDER),'__name__':'__main__'})
