"""Spec-11 reading-order challenger (V8-071): R-RO rules, invariants and agreement."""
import itertools
import random

from benchmark.challengers import reading_order_rules as rules


def _item(name, box, role="text", kind="b", text=None):
    return {"id": name, "kind": kind, "bbox": list(box), "role_final": role, "text_corrected": text if text is not None else name}


def _two_columns():
    return [
        _item("header", (40, 10, 300, 20), "running_header"),
        _item("L1", (40, 60, 280, 72)), _item("L2", (40, 76, 280, 88)), _item("L3", (40, 92, 280, 104)),
        _item("R1", (320, 60, 560, 72)), _item("R2", (320, 76, 560, 88)), _item("R3", (320, 92, 560, 104)),
        _item("footer", (40, 800, 300, 810), "running_footer"), _item("number", (540, 800, 560, 810), "page_number"),
    ]


def test_columns_are_read_left_then_right_between_header_and_footer():
    result = rules.order_page(_two_columns(), (600, 840))
    assert result["order"] == ["header", "L1", "L2", "L3", "R1", "R2", "R3", "footer", "number"]
    assert result["columns"] == 2 and result["streams"]["footer"] == ["footer", "number"]


def test_a_spanning_block_interrupts_the_columns():
    items = [_item("L-top", (40, 60, 280, 72)), _item("R-top", (320, 60, 560, 72)),
             _item("title", (40, 120, 560, 140), "section_header"),
             _item("L-low", (40, 200, 280, 212)), _item("R-low", (320, 200, 560, 212))]
    result = rules.order_page(items, (600, 840))
    assert result["order"] == ["L-top", "R-top", "title", "L-low", "R-low"]
    assert result["spanning_items"] == ["title"]


def test_caption_follows_its_table_and_the_table_keeps_its_cells_together():
    items = [_item("intro", (40, 40, 560, 52)),
             _item("table", (40, 60, 560, 200), None, "t"),
             _item("cell-b", (300, 70, 400, 80)), _item("cell-a", (50, 70, 150, 80)), _item("cell-c", (50, 150, 150, 160)),
             _item("caption", (40, 205, 300, 215), "caption"),
             _item("after", (40, 260, 560, 272))]
    result = rules.order_page(items, (600, 840))
    assert result["order"] == ["intro", "table", "cell-a", "cell-b", "cell-c", "caption", "after"]


def test_caption_above_a_picture_is_read_before_it():
    items = [_item("body", (40, 40, 560, 52)), _item("picture", (100, 120, 500, 300), None, "i"),
             _item("caption", (100, 100, 300, 112), "caption"), _item("tail", (40, 400, 560, 412))]
    # the caption sits above the picture: read it right before the picture
    assert rules.order_page(items, (600, 840))["order"] == ["body", "caption", "picture", "tail"]


def test_a_full_page_background_does_not_merge_the_lines():
    items = _two_columns() + [_item("background", (0, 0, 600, 840), None, "i", "")]
    result = rules.order_page(items, (600, 840))
    assert result["order"] == ["header", "background", "L1", "L2", "L3", "R1", "R2", "R3", "footer", "number"]


def test_every_item_once_and_the_same_order_for_any_input_order():
    items = _two_columns() + [_item("table", (40, 300, 560, 500), None, "t"), _item("cell", (60, 320, 200, 340)),
                              {"id": "nobox", "kind": "b", "bbox": None, "role_final": "text"}]
    expected = rules.order_page(items, (600, 840))["order"]
    assert sorted(expected) == sorted(i["id"] for i in items) and expected[-3] == "nobox"
    rng = random.Random(11)
    for _ in range(20):
        shuffled = items[:]
        rng.shuffle(shuffled)
        assert rules.order_page(shuffled, (600, 840))["order"] == expected


def test_pair_agreement_counts_concordant_pairs():
    reference = list("abcdef")
    candidate = list("bacdfe")
    brute = sum((reference.index(x) < reference.index(y)) == (candidate.index(x) < candidate.index(y))
                for x, y in itertools.combinations(reference, 2))
    result = rules.pair_agreement(reference, candidate)
    assert result["pairs"] == 15 and result["agreeing_pairs"] == brute == 13
    assert rules.pair_agreement(["a"], ["a"])["agreement"] is None


def test_page_continuation_needs_an_open_sentence_and_a_lower_case_start():
    page1 = rules.order_page([_item("p1", (40, 60, 560, 72), text="Doanh thu năm nay tăng do")], (600, 840))
    page2 = rules.order_page([_item("p2", (40, 60, 560, 72), text="giá bán cao hơn.")], (600, 840))
    page3 = rules.order_page([_item("p3", (40, 60, 560, 72), text="Kết thúc.")], (600, 840))
    assert rules.continuation_edges([page1, page2]) == [{"from": "p1", "to": "p2", "kind": "page"}]
    assert rules.continuation_edges([page2, page3]) == []


def test_rule_violations_flag_headers_and_footers_inside_the_body():
    items = _two_columns()
    bad = ["L1", "header", "L2", "footer", "L3", "R1", "R2", "R3", "number"]
    assert rules.rule_violations(bad, items) == {"header_after_body": 1, "footer_before_body": 1}
    assert rules.rule_violations(rules.order_page(items, (600, 840))["order"], items) == {
        "header_after_body": 0, "footer_before_body": 0}
