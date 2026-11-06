"""A column wrap may restore literal words only with traceable layout evidence."""
from dataclasses import replace

import pytest

from ocr_contracts.document import ExtractedDocument
from ocr_contracts.quality import DocumentQualityReport
from ocr_contracts.region import BoundingBox, ContentType, Region
from ocr_contracts.text_block import TextBlock
from ocr_document.document_contracts import build_document_json, render_document_md
from ocr_document.ids import Item
from ocr_document.section_tree import build_structure
from ocr_keywords.counter import KeywordCounter


def columns(*, images=False):
    items = []
    texts = [
        ["Nghiên cứu công nghệ hiện đại", "phát triển các ứng dụng mới", "với ngân sách 3,1 tỷ đồng", "và tập trung vào lĩnh vực trí"],
        ["tuệ nhân tạo cho sản xuất", "và các dịch vụ công nghệ", "phục vụ doanh nghiệp trong", "nước và khu vực toàn cầu."],
    ]
    for col in range(2):
        if images and col:
            region = Region(region_id="picture", content_type=ContentType.IMAGE,
                bbox=BoundingBox(x0=200, y0=10, x1=360, y1=80), status="PRESERVED")
            items.append(Item("image", "i", 1, [200, 10, 360, 80], region=region))
        for row, text in enumerate(texts[col]):
            box = [10 + 190 * col, 100 + row * 14, 170 + 190 * col, 111 + row * 14]
            sid = f"s{col}-{row}"
            block = TextBlock(text=text, text_raw=text, page=1, bbox=box, block_type="text",
                confidence=.99, quality_score=.99, column_id=f"c{col}", article_group_id="article", source_id=sid)
            items.append(Item(sid, "b", 1, box, block=block))
    return items


def structure(items, method="region_tree_graph_v1"):
    return build_structure([items], layout_method=method)


def count(result, keyword="trí tuệ nhân tạo"):
    markdown = render_document_md(None, result, assets_mode="none")
    return KeywordCounter.count_keywords(markdown, [keyword]).total_matches


@pytest.mark.parametrize("images", [False, True])
def test_column_wrap_restores_literal_keyword_and_keeps_raw_sources(images):
    items = columns(images=images)
    before = [(item.id, item.block.model_dump()) for item in items if item.block]
    result = structure(items)
    assert count(result) == 1
    assert [(item.id, item.block.model_dump()) for item in items if item.block] == before
    paragraphs = [value for kind, value in result.flow if kind == "paragraph"]
    assert len(paragraphs) == 1
    assert [line.item_id for line in paragraphs[0].lines] == [item.id for item in items if item.block]
    assert "3,1 tỷ đồng" in paragraphs[0].text
    doc = ExtractedDocument(document_id="test", file_path="fixture.pdf", file_hash="test", total_pages=1,
        quality=DocumentQualityReport(document_id="test", total_pages=1),
        manifest={"document_layout": {"method": "region_tree_graph_v1"}})
    chunk, = [chunk for chunk in build_document_json(doc, result, "fixture")["chunks"]
              if chunk["type"] == "paragraph"]
    assert chunk["needs_review"]
    record, = chunk["continuations"]
    assert record["before_item_id"] == record["before_source_id"] == "s0-3"
    assert record["after_item_id"] == record["after_source_id"] == "s1-0"
    assert record["method"] == "aligned-column-continuation-v1"
    assert record["moved_image_ids"] == (["image"] if images else [])
    if images:
        assert [kind for kind, _ in result.flow] == ["item", "paragraph"]
        assert result.flow[0][1].id == "image"


@pytest.mark.parametrize("case", ["article", "unknown_article", "unknown_column", "stop", "uppercase", "bullet",
    "short_line", "top", "bottom", "width", "font", "bold", "heading", "page", "table", "trailing_table",
    "section_in_column", "inline_image", "unplaced"])
def test_unproven_column_boundaries_do_not_create_a_keyword(case):
    items = columns(images=case == "inline_image")
    left, right = items[3], items[-4]
    if case == "article":
        right.block.article_group_id = "another"
    elif case == "unknown_article":
        for item in items:
            item.block.article_group_id = None
    elif case == "unknown_column":
        right.block.column_id = None
    elif case == "stop":
        left.block.text += "."
    elif case == "uppercase":
        right.block.text = "Tuệ nhân tạo cho sản xuất"
    elif case == "bullet":
        right.block.text = "• tuệ nhân tạo cho sản xuất"
    elif case == "short_line":
        left.bbox[2] -= 60
    elif case in {"top", "bottom", "width"}:
        for item in items[-4:]:
            if case == "top":
                item.bbox[1] += 50
                item.bbox[3] += 50
            elif case == "bottom":
                item.bbox[1] -= 50
                item.bbox[3] -= 50
            else:
                item.bbox[2] += 100
    elif case == "font":
        left.block.font_size, right.block.font_size = 10, 15
    elif case == "bold":
        right.block.is_bold = True
    elif case == "heading":
        right.block.block_type = "section_header"
    elif case == "page":
        items[-4:] = [replace(item, page=2) for item in items[-4:]]
    elif case in {"table", "trailing_table"}:
        from ocr_contracts.table import TableStructure
        table = TableStructure(table_id="table", page=1, bbox=[180, 70, 190, 90], num_rows=1, num_cols=1)
        if case == "trailing_table":
            table.bbox = [10, 154, 170, 190]
            items.append(Item("table", "t", 1, table.bbox, table=table))
        else:
            items.insert(4, Item("table", "t", 1, table.bbox, table=table))
    elif case == "section_in_column":
        items[1].block.block_type = "section_header"
        items[1].block.text = "NÂNG CAO PHÚC LỢI CHO CỘNG ĐỒNG"
    elif case == "inline_image":
        items[4].bbox[3] = 130
    elif case == "unplaced":
        left.bbox.clear()
    assert count(structure(items)) == 0


def test_legacy_flow_and_title_case_false_keyword_remain_separate():
    assert count(structure(columns(), method="legacy")) == 0
    items = columns()
    items[3].block.text = "báo cáo tài chính"
    items[4].block.text = "Số liệu so sánh của doanh nghiệp"
    assert count(structure(items), "tài chính số") == 0


def test_repeated_render_retains_one_image_and_one_source_occurrence():
    items = columns(images=True)
    first = structure(items)
    second = structure(items)
    assert render_document_md(None, first, "none") == render_document_md(None, second, "none")
    assert count(first) == count(second) == 1
    assert sum(kind == "item" for kind, _ in second.flow) == 1
