"""V8-010: ground truth by construction is complete, image-only, labelled stress-test-only
and byte-for-byte reproducible from its manifest parameters."""
import json
import unicodedata

import pytest

from benchmark.ground_truth_tools import synthetic_diacritics as synthetic

FONT = synthetic.default_font()
needs_font = pytest.mark.skipif(FONT is None, reason="no TrueType font with Vietnamese glyphs on this machine")


def test_grid_covers_every_vowel_tone_and_case_and_the_stroke():
    words = synthetic.syllable_grid(seed=3, repeats=1)
    assert len(words) == len(synthetic.VOWELS) * len(synthetic.TONES) * 2
    text = " ".join(words)
    for vowel in synthetic.VOWELS:
        for tone in synthetic.TONES:
            composed = unicodedata.normalize("NFC", vowel + tone)
            assert composed in text and composed.upper() in text, (vowel, tone)
    assert "đ" in text
    assert text == unicodedata.normalize("NFC", text)
    assert synthetic.syllable_grid(seed=3, repeats=1) == words  # seeded


def test_wrapping_never_drops_or_reorders_words():
    words = ["một", "hai", "ba", "bốn", "năm"]
    lines = synthetic.wrap_words(words, lambda line: len(line) <= 8)
    assert " ".join(lines).split() == words and all(len(line) <= 8 or " " not in line for line in lines)


def test_degradation_is_seeded_and_blur_keeps_the_image_shape():
    import numpy as np
    gray = np.full((20, 30), 255, dtype=np.uint8)
    gray[5:15, 10:20] = 0
    first = synthetic.degrade(gray, sigma=10, blur=1, seed=7)
    assert first.shape == gray.shape and first.dtype == np.uint8
    assert (first == synthetic.degrade(gray, sigma=10, blur=1, seed=7)).all()
    assert not (first == synthetic.degrade(gray, sigma=10, blur=1, seed=8)).all()
    assert (synthetic.degrade(gray, sigma=0, blur=0, seed=1) == gray).all()


@needs_font
def test_build_writes_image_only_pdf_with_matching_gt_and_manifest(tmp_path):
    import pymupdf
    manifest = synthetic.build(tmp_path / "a", font=FONT, dpi=72, seed=1, grid_repeats=1, noise_sigma=6, blur=1)
    assert manifest["validity"] == "STRESS_TEST_ONLY" and manifest["eligible_for_quality_acceptance"] is False
    assert manifest["font"]["sha256"] == synthetic.sha256_file(FONT)
    pdf = tmp_path / "a" / manifest["pdf"]["path"]
    assert manifest["pdf"]["document_id"] == "SYN_synthetic_diacritics"
    with pymupdf.open(pdf) as document:
        assert document.page_count == manifest["pdf"]["pages"] >= 1
        assert all(page.get_text().strip() == "" for page in document)  # OCR has to read every page
        assert all(page.get_images() for page in document)
    total = 0
    for page in manifest["pages"]:
        gt = tmp_path / "a" / page["gt_path"]
        assert gt.name == f"syn_page_{page['page']:04d}.txt"
        assert synthetic.sha256_file(gt) == page["gt_sha256"]
        total += page["slots"]["total"]
    assert total == manifest["slots_total"]["total"] > 0
    assert json.loads((tmp_path / "a" / "manifest.json").read_text(encoding="utf-8")) == manifest


@needs_font
def test_identical_arguments_give_identical_bytes_and_noise_changes_them(tmp_path):
    first = synthetic.build(tmp_path / "a", font=FONT, dpi=72, seed=2, grid_repeats=1, noise_sigma=5)
    second = synthetic.build(tmp_path / "b", font=FONT, dpi=72, seed=2, grid_repeats=1, noise_sigma=5)
    assert first["pdf"]["sha256"] == second["pdf"]["sha256"]
    assert [p["gt_sha256"] for p in first["pages"]] == [p["gt_sha256"] for p in second["pages"]]
    clean = synthetic.build(tmp_path / "c", font=FONT, dpi=72, seed=2, grid_repeats=1, noise_sigma=0)
    assert clean["pdf"]["sha256"] != first["pdf"]["sha256"]
    assert [p["gt_sha256"] for p in clean["pages"]] == [p["gt_sha256"] for p in first["pages"]]


@needs_font
def test_known_text_is_rendered_and_output_must_be_fresh(tmp_path):
    known = tmp_path / "known.txt"
    known.write_text("Cổ đông\nHội đồng quản trị\n", encoding="utf-8")
    manifest = synthetic.build(tmp_path / "a", font=FONT, dpi=72, grid_repeats=1, text_files=[known])
    text = "".join((tmp_path / "a" / page["gt_path"]).read_text(encoding="utf-8") for page in manifest["pages"])
    assert "Cổ đông\nHội đồng quản trị\n" in text
    assert manifest["text_sources"][1]["sha256"] == synthetic.sha256_file(known)
    with pytest.raises(ValueError, match="fresh"):
        synthetic.build(tmp_path / "a", font=FONT, dpi=72, grid_repeats=1)
    with pytest.raises(ValueError, match="Prefix"):
        synthetic.build(tmp_path / "b", font=FONT, prefix="a_b")


@needs_font
def test_score_reads_constructed_gt_and_refuses_changed_gt(tmp_path, monkeypatch):
    import scripts.run_scientific_benchmark as runner
    monkeypatch.setattr(runner, "capture_environment_metadata", lambda _: {})
    manifest = synthetic.build(tmp_path / "set", font=FONT, dpi=72, grid_repeats=1)
    prediction = tmp_path / "out" / manifest["pdf"]["document_id"]
    (prediction / "pages").mkdir(parents=True)
    for page in manifest["pages"]:
        text = (tmp_path / "set" / page["gt_path"]).read_text(encoding="utf-8")
        (prediction / "pages" / f"page-{page['page']:04d}.md").write_text(text, encoding="utf-8")
    (prediction / "manifest.json").write_text(json.dumps({"selected_pages": [p["page"] for p in manifest["pages"]]}),
                                              encoding="utf-8")
    report = synthetic.score(tmp_path / "set" / "manifest.json", prediction)
    assert report["validity"] == "STRESS_TEST_ONLY" and report["quality_acceptance"] == "NOT_EVALUATED"
    assert report["micro_dser_strict"] == 0 and report["counts"]["dser_strict"]["errors"] == 0
    slots = report["counts"]["dser_strict"]["reference_length"]
    assert report["dser_strict_upper_bound"]["value"] == pytest.approx(1 - 0.05 ** (1 / slots))  # 0 errors
    with pytest.raises(ValueError, match="not document"):
        synthetic.score(tmp_path / "set" / "manifest.json", tmp_path / "out")
    (tmp_path / "set" / manifest["pages"][0]["gt_path"]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        synthetic.score(tmp_path / "set" / "manifest.json", prediction)
