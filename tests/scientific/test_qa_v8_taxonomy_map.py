"""V8-110: the v8 E01-E13 list maps onto every registry code without renaming any."""
from pathlib import Path
import re

from benchmark.qa.error_registry import ERROR_CODES

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY = ROOT / "docs/quality_assurance/ERROR_TAXONOMY.md"


def _mapping_rows():
    text = TAXONOMY.read_text(encoding="utf-8").replace("\r\n", "\n")
    section = text.split("## Ánh xạ danh sách E01–E13 của v8 (V8-110)", 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| v8")
            and not line.startswith("| ---")]


def test_every_v8_group_and_every_registry_code_appears():
    rows = _mapping_rows()
    groups = [row.split("|")[1].strip() for row in rows]
    assert [g for g in groups if g != "—"] == [f"E{n:02d}" for n in range(1, 14)]
    mapped = set(re.findall(r"`(E\d\d-[A-Z]+)`", "\n".join(rows)))
    assert mapped == set(ERROR_CODES)
