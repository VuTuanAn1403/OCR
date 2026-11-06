"""Source-owned counting, prose continuity, and column proposals remain auditable."""
import pytest

from ocr_contracts.page import ExtractedPage
from ocr_contracts.page_type import PageType
from ocr_contracts.quality import PageQualityReport
from ocr_contracts.table import TableCell, TableStructure
from ocr_contracts.text_block import TextBlock
from ocr_document.ids import page_items
from ocr_document.region_tree import LayoutItem, infer_region_tree
from ocr_document.resolve_document_layout import _reconcile_evidence, RECONCILIATION_METHOD
from ocr_document.section_tree import Line, _starts_new_paragraph, build_structure
from ocr_document.source_identity import lock_text_evidence


def table_page(text, *, block_type="list"):
    block = TextBlock(text=text, text_raw=text, page=1, bbox=[10, 10, 170, 22],
                      block_type=block_type, confidence=.99, quality_score=.99)
    page = ExtractedPage(page_num=1, width=400, height=500, page_type=PageType.MIXED,
                         blocks=[block], quality=PageQualityReport(page=1, page_type="SCANNED"))
    lock_text_evidence(page.blocks, "test-hash", 1, page.metadata)
    page.tables = [TableStructure(table_id="t1", page=1, bbox=[0, 0, 400, 300], num_rows=1, num_cols=1,
        cells=[TableCell(row_idx=0, col_idx=0, text="Cách mạng công nghiệp 4.0 tác", bbox=[0, 0, 300, 100])])]
    page.blocks = []
    return page


def test_list_marker_has_explicit_disposition_and_one_table_occurrence():
    page = table_page("- Cách mạng công nghiệp 4.0 tác")
    _reconcile_evidence(page)
    source, = page.metadata["text_evidence"]["items"]
    decision, = page.metadata["source_dispositions"].values()
    assert source["text_raw"] == "- Cách mạng công nghiệp 4.0 tác"
    assert decision["status"] == "REPLACED_BY_TABLE"
    assert decision["excluded_presentation_tokens"] == ["-"]
    assert page.metadata["source_reconciliation_method"] == RECONCILIATION_METHOD
    assert len(page.tables[0].provenance["source_occurrence_mapping"]) == 1
    assert page.blocks == []


def test_restored_occurrence_can_be_reconciled_later_without_stale_review_evidence():
    page = table_page("- Cách mạng công nghiệp 4.0 tác")
    page.tables[0].cells[0].text = "Khác nội dung"
    _reconcile_evidence(page)
    assert len(page.blocks) == len(page.evidence_blocks) == 1
    page.tables[0].cells[0].text = "Cách mạng công nghiệp 4.0 tác"
    _reconcile_evidence(page)
    assert page.blocks == page.evidence_blocks == []
    assert page.quality.total_blocks == page.quality.review_required_count == 0
    _reconcile_evidence(page)
    assert page.blocks == page.evidence_blocks == []


def test_new_protection_on_a_restored_source_survives_reconciliation_again():
    page = table_page("- Cách mạng công nghiệp 4.0 tác")
    page.tables[0].cells[0].text = "Khác nội dung"
    _reconcile_evidence(page)
    page.blocks[0].protected_from_furniture = True
    page.tables[0].cells[0].text = "Cách mạng công nghiệp 4.0 tác"
    _reconcile_evidence(page)
    assert len(page.blocks) == 1 and page.blocks[0].protected_from_furniture
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "KEPT_FOR_REVIEW"
    assert page.tables[0].provenance["derived_from_source_ids"] == []


@pytest.mark.parametrize("text,kind", [("- 120", "list"), ("- USD 120", "list"),
                                      ("- EUR 120", "list"), ("- Cách mạng công nghiệp 4.0 tác", "paragraph")])
def test_numeric_sign_or_prose_dash_cannot_be_ignored_as_a_list_marker(text, kind):
    page = table_page(text, block_type=kind)
    page.tables[0].cells[0].text = text.removeprefix("- ")
    _reconcile_evidence(page)
    assert page.blocks[0].text_raw == text
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "KEPT_FOR_REVIEW"


def test_modern_structure_cannot_override_rejected_source_ownership_with_a_substring():
    page = table_page("công nghiệp 4.0", block_type="text")
    # Two occurrences without cell geometry cannot establish unique ownership.
    page.tables[0].cells[0].bbox = None
    page.tables[0].cells[0].text = "công nghiệp 4.0 công nghiệp 4.0"
    _reconcile_evidence(page)
    structure = build_structure([page_items("hash", page)], layout_method="region_tree_graph_v1")
    assert not any(reason == "table_cell" for reason in structure.dropped.values())
    assert any(kind == "paragraph" and value.text == "công nghiệp 4.0" for kind, value in structure.flow)


@pytest.mark.parametrize("text", ["I. Lưu chuyển tiền từ hoạt động kinh doanh",
                                 "2. Điều chỉnh cho các khoản", "PHẦN I TỔNG QUAN"])
def test_unresolved_source_inside_a_table_cannot_create_a_document_section(text):
    page = table_page(text, block_type="title")
    _reconcile_evidence(page)
    frozen = page.blocks[0].model_dump()
    structure = build_structure([page_items("hash", page)], layout_method="region_tree_graph_v1")
    assert structure.sections == []
    assert any(kind == "paragraph" and value.text == text for kind, value in structure.flow)
    assert structure.dropped == {}
    assert page.blocks[0].model_dump() == frozen


@pytest.mark.parametrize("case", ["outside", "other_review", "legacy"])
def test_table_source_guard_preserves_other_heading_behavior(case):
    page = table_page("PHẦN I TỔNG QUAN", block_type="title")
    _reconcile_evidence(page)
    if case == "outside":
        page.tables[0].bbox = [0, 200, 400, 300]
    elif case == "other_review":
        page.blocks[0].review_reason_codes = ["OTHER_REVIEW"]
    method = "legacy" if case == "legacy" else "region_tree_graph_v1"
    structure = build_structure([page_items("hash", page)], layout_method=method)
    assert len(structure.sections) == 1
    assert structure.sections[0].heading.text == "PHẦN I TỔNG QUAN"


def test_unresolved_table_text_cannot_be_attached_as_a_heading_translation():
    page = table_page("CASH FLOWS FROM OPERATING ACTIVITIES", block_type="text")
    _reconcile_evidence(page)
    page.blocks[0].bbox = [10, 42, 370, 54]
    page.blocks[0].font_size = 10
    page.blocks[0].is_bold = True
    page.tables[0].bbox = [0, 40, 400, 300]
    heading = TextBlock(text="PHẦN I TỔNG QUAN", page=1, bbox=[10, 10, 370, 40],
                        font_size=18, is_bold=True, block_type="title", source="native")
    page.blocks.insert(0, heading)
    items = page_items("hash", page)
    # Use a valid explicit flow with the ambiguous text adjacent to a heading.
    items.sort(key=lambda i: (i.kind != "b", i.bbox[1]))
    structure = build_structure([items], layout_method="region_tree_graph_v1")
    assert len(structure.sections) == 1
    assert structure.sections[0].heading.title_en is None
    assert any(kind == "paragraph" and value.text == page.blocks[1].text for kind, value in structure.flow)


def test_unresolved_table_rows_cannot_be_dropped_as_a_table_of_contents():
    texts = ["I. Hoạt động kinh doanh 10", "II. Tài sản ngắn hạn 20", "III. Nợ phải trả 30",
             "IV. Vốn chủ sở hữu 40", "V. Các khoản dự phòng 50", "VI. Hàng tồn kho 60"]
    page = table_page(texts[0], block_type="text")
    page.blocks = [TextBlock(text=text, text_raw=text, page=1, bbox=[10, 10+30*n, 390, 22+30*n],
                            block_type="text", review_reason_codes=["TABLE_SOURCE_UNMAPPED"])
                   for n, text in enumerate(texts)]
    structure = build_structure([page_items("hash", page)], layout_method="region_tree_graph_v1")
    assert structure.toc is None and structure.sections == [] and structure.dropped == {}
    visible = " ".join(v.text for kind, v in structure.flow if kind == "paragraph")
    assert all(text in visible for text in texts)


@pytest.mark.parametrize("evidence", ["title", "document_index"])
def test_a_real_explicit_toc_keeps_entries_even_when_extracted_as_a_table(evidence):
    texts = ["MỤC LỤC" if evidence == "title" else "MUCLUC", "I. Hoạt động kinh doanh 10",
             "II. Tài sản ngắn hạn 20", "III. Nợ phải trả 30", "IV. Vốn chủ sở hữu 40"]
    page = table_page(texts[0], block_type="text")
    page.blocks = [TextBlock(text=text, text_raw=text, page=1, bbox=[10, 10+30*n, 390, 22+30*n],
                            block_type="document_index" if evidence == "document_index" and n else "text",
                            review_reason_codes=["TABLE_SOURCE_UNMAPPED"])
                   for n, text in enumerate(texts)]
    structure = build_structure([page_items("hash", page)], layout_method="region_tree_graph_v1")
    assert structure.toc is not None and structure.toc.pages == [1]
    assert len(structure.toc.entries) == 4
    ids = {i.id for i in page_items("hash", page) if i.block and i.block.text in texts[1:]}
    assert all(structure.dropped[i] == "toc_entry" for i in ids)


@pytest.mark.parametrize("chapters,expected_toc", [([1, 2, 3], True), ([1, 1, 1], False)])
def test_multi_chapter_navigation_keeps_a_toc_without_a_text_title(chapters, expected_toc):
    texts = [f"CHƯƠNG {n}" for n in chapters] + [f"Nội dung báo cáo {n}" for n in range(10, 70, 10)]
    page = table_page(texts[0], block_type="text")
    page.tables[0].bbox = [0, 0, 400, 500]
    page.blocks = [TextBlock(text=text, text_raw=text, page=1, bbox=[10, 10+30*n, 390, 22+30*n],
                            block_type="text", review_reason_codes=["TABLE_SOURCE_UNMAPPED"])
                   for n, text in enumerate(texts)]
    structure = build_structure([page_items("hash", page)], layout_method="region_tree_graph_v1")
    assert (structure.toc is not None) == expected_toc
    if not expected_toc:
        assert structure.dropped == {}


def line(text, box, *, column="c1", article="a1"):
    return Line("id", 1, text, box, None, False, "text", "primary_ocr",
                column_id=column, article_group_id=article)


def test_title_case_continuation_allows_small_detector_overlap_in_same_column():
    previous = line("Xây dựng và củng cố uy tín để Quỹ Đổi", [994.54, 560.82, 1157.14, 574.55])
    current = line("Mới Sáng Tạo Vingroup", [1000.6, 574.1, 1158.05, 587.36])
    assert not _starts_new_paragraph(previous, current)


def test_heading_body_gap_article_or_column_boundary_stays_separate():
    previous = line("báo cáo tài chính", [122, 232, 435, 246])
    assert _starts_new_paragraph(previous, line("Số liệu so sánh", [122, 260, 545, 273]))
    assert _starts_new_paragraph(previous, line("Số liệu so sánh", [450, 245, 580, 259], column="c2"))
    assert _starts_new_paragraph(previous, line("Số liệu so sánh", [122, 245, 435, 259], article="a2"))


def test_fused_lines_do_not_force_following_prose_to_interleave_columns():
    items = [LayoutItem("fused", [10, 0, 350, 10], "Một dòng OCR phủ hai cột cần review")]
    for i in range(6):
        items.extend([LayoutItem(f"L{i}", [10, 20 + 14*i, 170, 31 + 14*i], "Nội dung bên trái"),
                      LayoutItem(f"R{i}", [180 if i == 3 else 190, 20 + 14*i, 350, 31 + 14*i], "Nội dung bên phải")])
    result = infer_region_tree(items)
    assert result.ordered_ids == ["fused"] + [f"L{i}" for i in range(6)] + [f"R{i}" for i in range(6)]
    assert len(result.ordered_ids) == len(set(result.ordered_ids)) == len(items)
    assert any(r["code"] == "PROVISIONAL_COLUMN_GUTTER" for r in result.review)
    assert result.assignments["L0"]["column_id"] != result.assignments["R0"]["column_id"]


@pytest.mark.parametrize("kind", ["t", "f", "i"])
def test_spanning_table_does_not_interleave_prose_columns_above_it(kind):
    items = [LayoutItem("table", [10, 95, 350, 170], kind=kind)]
    for i in range(6):
        items.extend([LayoutItem(f"L{i}", [10, 20 + 14*i, 170, 31 + 14*i], "Nội dung bên trái"),
                      LayoutItem(f"R{i}", [190, 20 + 14*i, 350, 31 + 14*i], "Nội dung bên phải")])
    result = infer_region_tree(items)
    assert result.ordered_ids == [f"L{i}" for i in range(6)] + [f"R{i}" for i in range(6)] + ["table"]
    assert items[0].bbox == [10, 95, 350, 170]


def test_crossing_atomic_structure_never_gets_split_or_lost_in_a_gutter_proposal():
    items = [LayoutItem("table", [10, 62, 350, 84], kind="t")]
    for i in range(6):
        top = 20 + i * 14 if i < 3 else 104 + (i - 3) * 14
        items.extend([LayoutItem(f"L{i}", [10, top, 170, top + 11], "Nội dung bên trái"),
                      LayoutItem(f"R{i}", [190, top, 350, top + 11], "Nội dung bên phải")])
    result = infer_region_tree(items)
    assert len(result.ordered_ids) == len(set(result.ordered_ids)) == len(items)
    assert result.ordered_ids.index("R2") < result.ordered_ids.index("table") < result.ordered_ids.index("L3")
