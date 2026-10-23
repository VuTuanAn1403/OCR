"""ocr_text: Vietnamese normalization and numeric protection, stdlib only (P05a)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unicodedata

from ocr_text.numeric_guard import preserves_numeric_evidence, protected_numeric_fragments
from ocr_text.unicode_normalizer import UnicodeNormalizer

ROOT = Path(__file__).resolve().parents[3]


def test_nfc_and_nfd_vietnamese_normalize_identically():
    word = "Chuyển đổi số"
    assert UnicodeNormalizer.normalize(unicodedata.normalize("NFD", word)) == UnicodeNormalizer.normalize(word)
    assert unicodedata.is_normalized("NFC", UnicodeNormalizer.normalize(unicodedata.normalize("NFD", word)))


def test_numeric_guard_protects_signs_percentages_dates_codes_and_units():
    assert protected_numeric_fragments("Lãi -12,5% ngày 31/12/2020, mã 01-GTGT, 1 250 000 triệu đồng") == [
        "-12,5%", "31/12/2020,", "01-GTGT,", "1 250 000 triệu đồng"]  # current regex keeps a trailing comma
    assert not preserves_numeric_evidence("-12,5%", "12,5%")       # sign
    assert not preserves_numeric_evidence("năm 2020", "năm 2021")  # date/year
    assert not preserves_numeric_evidence("5 tỷ", "5 triệu")       # adjacent unit
    assert preserves_numeric_evidence("Doanh thu 2020 tăng", "Doanh thu 2020 tang")  # text-only fix


def test_import_uses_standard_library_only():
    code = ("import json, sys\nimport ocr_text.unicode_normalizer, ocr_text.numeric_guard, ocr_text.text_cleaner\n"
            "print(json.dumps(sorted(m for m in sys.modules if not m.startswith(('ocr_text','encodings')) "
            "and m.split('.')[0] in {'pydantic','numpy','yaml','psutil','pymupdf','src'})))")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "src", capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
