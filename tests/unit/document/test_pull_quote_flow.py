"""Separate a pull quote while preserving the complete two-column body."""
import copy
import json

import pytest

from ocr_contracts.document import ExtractedDocument
from ocr_contracts.evidence_block import EvidenceBlock
from ocr_contracts.page import ExtractedPage
from ocr_contracts.page_type import PageType
from ocr_contracts.quality import DocumentQualityReport, PageQualityReport
from ocr_contracts.region import BoundingBox, Region
from ocr_contracts.text_block import TextBlock
from ocr_document.contract_schema import validate_contract_set
from ocr_document.export import DocumentExporter
from ocr_document.region_tree import LayoutItem, infer_region_tree
from ocr_keywords.counter import KeywordCounter


LEFT = ["Chúng tôi chuẩn hóa từng bước trong quá trình vận hành",
        "để đội ngũ dễ dàng kiểm chứng số liệu từng ngày.",
        "Đội dự án ghi lại các phản hồi từ từng bộ phận.",
        "Các bộ phận cùng thống nhất cách lưu hồ sơ",
        "và theo dõi tiến độ trong từng kỳ báo cáo",
        "để tiếp tục phát triển mô hình"]
RIGHT = ["qua dữ liệu thu thập từ các nhóm chuyên môn.",
         "Kết quả tổng hợp được gửi cho người phụ trách",
         "để kiểm tra những vị trí còn cần điều chỉnh.",
         "Các phản hồi được đối chiếu với hồ sơ nguồn",
         "và cập nhật vào danh mục theo thứ tự ưu tiên",
         "trước khi lập báo cáo của kỳ tiếp theo."]
QUOTE = ["“Chuyển đổi số tạo nền tảng", "cho các quyết định tốt hơn.”"]


def _items():
    items = []
    for i, y in enumerate((30, 47, 64, 133, 150, 167)):
        items.extend([LayoutItem(f"L{i}", [24, y, 260, y + 10], LEFT[i]),
                      LayoutItem(f"R{i}", [340, y, 572, y + 10], RIGHT[i])])
    return items + [LayoutItem("Q0", [192, 87, 409, 104], QUOTE[0]),
                    LayoutItem("Q1", [198, 107, 402, 124], QUOTE[1])]


def test_shared_export_keeps_the_body_and_counts_quote_once(tmp_path):
    items = _items()
    blocks = [TextBlock(text=i.text, text_raw=i.text, bbox=i.bbox, page=1, region_id="body", confidence=.9,
                        quality_score=.95) for i in items]
    evidence = [EvidenceBlock(page=1, block_id=i.id, region_id="body", text=i.text, bbox=i.bbox,
                              orientation=0, status="EXTRACTED") for i in items]
    region = Region(region_id="body", bbox=BoundingBox(x0=24, y0=30, x1=572, y1=177), status="EXTRACTED")
    page = ExtractedPage(page_num=1, width=600, height=800, page_type=PageType.MIXED, blocks=blocks,
                         evidence_blocks=evidence, regions=[region],
                         quality=PageQualityReport(page=1, page_type="MIXED"))
    doc = ExtractedDocument(document_id="two-columns", file_path="unused.pdf", file_hash="abcdef0123456789",
                            total_pages=1, pages=[page], selected_pages=[1], manifest={"selected_pages": [1]},
                            quality=DocumentQualityReport(document_id="two-columns", total_pages=1))
    out = DocumentExporter.execute(doc, tmp_path, assets_mode="none", document_layout={"method": "region_tree_graph_v1"})
    extraction, document, structure = [json.loads((out / f"{kind}.json").read_text(encoding="utf-8"))
                                       for kind in ("extraction", "document", "structure")]
    assert validate_contract_set(extraction, document, structure) == []
    assert extraction["pages"][0]["layout_tree"]["type"] == "pull_quote_columns"
    sources = extraction["pages"][0]["items"]
    assert [row["text_raw"] for row in sources] == LEFT + RIGHT + QUOTE
    quotes = [c for c in document["chunks"] if c.get("callout_id")]
    assert len(quotes) == 1 and quotes[0]["needs_review"]
    assert quotes[0]["spans"][0]["block_ids"] == [r["id"] for r in sources[-2:]]
    assert quotes[0]["text_raw"] == " ".join(QUOTE)
    from ocr_pipeline.review_packet import page_candidates

    review = list(page_candidates(doc.document_id, doc.file_hash, extraction["pages"][0], []))
    assert {row["source_id"] for row in review if "PULL_QUOTE_SEPARATED" in row["reasons"]} == {
        row["source_id"] for row in sources[-2:]}
    body = [c["text_corrected"] for c in document["chunks"] if not c.get("callout_id")]
    assert " ".join(body) == " ".join(LEFT + RIGHT)
    assert any("mô hình qua dữ liệu" in text for text in body)
    for name in ("document.md", "result.md"):
        md = (out / name).read_text(encoding="utf-8")
        assert md.count("> “Chuyển đổi số tạo nền tảng cho các quyết định tốt hơn.”") == 1
        assert md.index("trước khi lập báo cáo") < md.index("> “Chuyển đổi số")
        report = KeywordCounter.count_keywords(md, ["chuyển đổi số", "mô hình qua dữ liệu"])
        assert [item.exact_count for item in report.keywords] == [1, 1]

    tampered = copy.deepcopy(document)
    next(chunk for chunk in tampered["chunks"] if chunk.get("callout_id")).pop("callout_id")
    assert any("does not preserve pull quote" in e for e in validate_contract_set(extraction, tampered, structure))


@pytest.mark.parametrize("barrier", ["not_closed", "overlap", "inline", "table"])
def test_ambiguous_quotes_do_not_create_detached_flow(barrier):
    items = _items()
    if barrier == "not_closed":
        items[-1] = LayoutItem("Q1", items[-1].bbox, "cho các quyết định tốt hơn.")
    elif barrier == "overlap":
        items.append(LayoutItem("overlap", [24, 95, 260, 105], "Nội dung thân bài cùng hàng"))
    elif barrier == "inline":
        items[-2] = LayoutItem("Q0", [24, 87, 260, 104], '“một phần tên riêng” viết tiếp trong đoạn')
    else:
        items.append(LayoutItem("table", [120, 86, 500, 127], kind="t"))
    layout = infer_region_tree(items)
    assert set(layout.ordered_ids) == {i.id for i in items}
    assert all("callout_id" not in value for value in layout.assignments.values())
