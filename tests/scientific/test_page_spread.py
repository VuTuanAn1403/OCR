import pytest

from benchmark.challengers.page_spread import (
    SpreadClassification,
    SpreadDecision,
    classify_page_spread,
    map_box_to_logical,
    map_box_to_physical,
    split_2up_logical_pages,
)


def test_portrait_page_confirmed_1up():
    # A4 portrait: 595 x 842 points (aspect ~ 0.706)
    res = classify_page_spread(width=595.0, height=842.0)
    assert res.decision == SpreadDecision.CONFIRMED_1UP
    assert res.aspect_ratio < 1.0
    assert "portrait" in res.reasons[0].lower()


def test_landscape_2up_clean_center_gutter_confirmed_2up():
    # Landscape spread: 1190 x 842 (aspect ~ 1.413)
    # 2-UP page: Left column has words, Right column has words, NO words crossing center (x in 571..618)
    words = [
        # Left page words (x in 50..500)
        [50, 100, 150, 120],
        [60, 130, 200, 150],
        [70, 160, 220, 180],
        [80, 190, 250, 210],
        [90, 220, 260, 240],
        # Right page words (x in 650..1100)
        [650, 100, 750, 120],
        [660, 130, 800, 150],
        [670, 160, 820, 180],
        [680, 190, 850, 210],
        [690, 220, 860, 240],
    ]
    res = classify_page_spread(width=1190.0, height=842.0, words_bbox=words)
    assert res.decision == SpreadDecision.CONFIRMED_2UP
    assert res.center_words_count == 0
    assert res.split_x == 595.0


def test_landscape_1up_wide_table_spanners_confirmed_1up():
    # Landscape spread: 1190 x 842
    # Wide table row spanning across the center gutter (e.g. 400..800)
    words = [
        [50, 100, 150, 120],
        [350, 200, 850, 230],  # wide table header cutting across center
        [700, 100, 800, 120],
    ]
    res = classify_page_spread(width=1190.0, height=842.0, words_bbox=words)
    assert res.decision == SpreadDecision.CONFIRMED_1UP
    assert "wide" in res.reasons[0].lower()


def test_pure_scan_landscape_with_projection_gutter():
    # Pure scan image (no text words), but visual projection shows a deep ink valley at 50%
    n = 1000
    proj = [100.0] * n
    # Dip in the middle 450..550 (white/light gutter)
    for i in range(480, 520):
        proj[i] = 5.0
    res = classify_page_spread(width=1000.0, height=700.0, words_bbox=(), vertical_projection=proj)
    assert res.decision == SpreadDecision.CONFIRMED_2UP
    assert res.gutter_score >= 0.50


def test_pure_scan_landscape_without_contrast_is_uncertain():
    # Pure scan with flat projection or no signal -> UNCERTAIN (defaults to safe 1-UP)
    proj = [50.0] * 1000
    res = classify_page_spread(width=1000.0, height=700.0, words_bbox=(), vertical_projection=proj)
    assert res.decision == SpreadDecision.UNCERTAIN


def test_split_and_coordinate_roundtrip():
    width, height = 1190.0, 842.0
    split_x = 595.0
    left, right = split_2up_logical_pages(physical_page=42, width=width, height=height, split_x=split_x)

    assert left.logical_page_id == "42_L"
    assert left.crop_box == (0.0, 0.0, 595.0, 842.0)
    assert right.logical_page_id == "42_R"
    assert right.crop_box == (595.0, 0.0, 1190.0, 842.0)

    # Test coordinate mapping:
    # 1. Box on Left half: [50, 100, 200, 130] in local coords
    local_l = [50.0, 100.0, 200.0, 130.0]
    phys_l = map_box_to_physical(local_l, side="L", split_x=split_x)
    assert phys_l == (50.0, 100.0, 200.0, 130.0)

    side_l, mapped_back_l = map_box_to_logical(phys_l, split_x=split_x)
    assert side_l == "L"
    assert mapped_back_l == (50.0, 100.0, 200.0, 130.0)

    # 2. Box on Right half: [50, 100, 200, 130] in local coords
    local_r = [50.0, 100.0, 200.0, 130.0]
    phys_r = map_box_to_physical(local_r, side="R", split_x=split_x)
    assert phys_r == (645.0, 100.0, 795.0, 130.0)

    side_r, mapped_back_r = map_box_to_logical(phys_r, split_x=split_x)
    assert side_r == "R"
    assert mapped_back_r == (50.0, 100.0, 200.0, 130.0)

