"""scripts/check_vietnamese_charset.py: a model must be able to emit all 146 Vietnamese letters."""
import json
import unicodedata
from pathlib import Path

from scripts import check_vietnamese_charset as charset

ROOT = Path(__file__).resolve().parents[2]


def test_alphabet_is_the_146_composed_letters():
    letters = charset.vietnamese_letters()
    assert len(letters) == len(set(letters)) == 146
    assert all(letter == unicodedata.normalize("NFC", letter) and len(letter) == 1 for letter in letters)
    assert {"đ", "Đ", "ố", "Ở", "ậ", "ỹ", "Ư"} <= set(letters)


def test_full_dictionary_passes_and_the_pp_ocrv6_gap_fails(tmp_path):
    full = tmp_path / "full_dict.txt"
    full.write_text("\n".join(["a", "b", *charset.vietnamese_letters()]), encoding="utf-8")
    assert charset.check(full)["status"] == "PASS"
    # Shape of the PP-OCRv6 dictionary (issue #18254): Latin-1 accents and ă â ê ô ơ ư đ, but only Ạ ồ above U+1EA0.
    gap = tmp_path / "ppocrv6_like_dict.txt"
    gap.write_text("\n".join(list("aăâeêioôơuưyđáàãéèíìóòúùýĐ") + ["Ạ", "ồ"]), encoding="utf-8")
    result = charset.check(gap)
    assert result["status"] == "FAIL" and {"ố", "ở", "ậ", "ả", "ữ", "ỹ", "ạ"} <= set(result["missing"])
    assert "ồ" not in result["missing"]


def test_tokenizers_byte_level_is_reported_apart_from_explicit_coverage(tmp_path):
    byte_level = tmp_path / "bytes.json"
    byte_level.write_text(json.dumps({"model": {"type": "BPE", "vocab": {"Ġthe": 0, "a": 1}},
                                      "pre_tokenizer": {"type": "ByteLevel"}}), encoding="utf-8")
    assert charset.check(byte_level)["status"] == "BYTE_FALLBACK"
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps({"model": {"type": "WordPiece",
                                              "vocab": {letter: index for index, letter in
                                                        enumerate(charset.vietnamese_letters())}}}),
                        encoding="utf-8")
    assert charset.check(explicit)["status"] == "PASS"


def test_production_vietocr_vocab_covers_every_letter_and_cli_reports(tmp_path, capsys):
    report = tmp_path / "report.json"
    assert charset.main([str(ROOT / "models/vietocr/base.yml"), "--report", str(report)]) == 0
    (result,) = json.loads(report.read_text(encoding="utf-8"))
    assert result["kind"] == "vietocr_vocab" and result["covered"] == 146
    gap = tmp_path / "gap.txt"
    gap.write_text("a\n", encoding="utf-8")
    assert charset.main([str(gap)]) == 1
