"""compare_parser_candidate.page_diagnostic: coverage, pair order agreement and table matches (V8-095)."""
from scripts.compare_parser_candidate import page_diagnostic


def test_order_coverage_and_tables_are_counted():
    page = {"ordered_item_ids": ["a", "b", "c", "t"], "items": [
        {"id": "a", "kind": "b", "bbox": [10, 10, 50, 20]},
        {"id": "b", "kind": "b", "bbox": [10, 100, 50, 110]},
        {"id": "c", "kind": "b", "bbox": [400, 400, 450, 410]},  # outside every parser block
        {"id": "t", "kind": "t", "bbox": [10, 200, 100, 300]}]}
    blocks = [{"order_index": 1, "bbox": [0, 0, 60, 30], "region_class": "text"},     # holds a, read second
              {"order_index": 0, "bbox": [0, 90, 60, 120], "region_class": "text"},   # holds b, read first
              {"order_index": 2, "bbox": [10, 200, 100, 300], "region_class": "table"}]
    result = page_diagnostic(page, blocks)
    assert result["covered"] == 3 and result["production_items"] == 4
    # pairs across blocks: (a,b) disagrees, (a,t) and (b,t) agree
    assert (result["pairs"], result["agreeing_pairs"]) == (3, 2)
    assert (result["parser_tables"], result["production_tables"], result["tables_matched"]) == (1, 1, 1)
