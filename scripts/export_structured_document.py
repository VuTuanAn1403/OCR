#!/usr/bin/env python3
"""Export finished documents to DOCX and XLSX with table structure kept (V8-130).

CPU only: reads each document's document.json, never runs OCR and never edits
the source output. For every document it writes `<doc>.docx`,
`<doc>_tables.xlsx` and a manifest entry with the source and output SHA-256,
collision warnings and the read-back round trip of every table.

  python scripts/export_structured_document.py output/<run>/<doc> [...] --output scratch/<new>
  python scripts/export_structured_document.py output/<run> --output scratch/<new>   # every document
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ocr_reporting.structured_export import TEXT_FIELDS, docx_bytes, round_trip, xlsx_bytes  # noqa: E402


def documents(inputs):
    for item in inputs:
        item = Path(item)
        if (item / "document.json").is_file():
            yield item
        else:
            yield from sorted(path.parent for path in item.glob("*/document.json"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", type=Path, help="Document directories or run directories")
    parser.add_argument("--output", type=Path, required=True, help="Fresh directory for the exports")
    parser.add_argument("--text-field", choices=TEXT_FIELDS, default="text_corrected")
    args = parser.parse_args(argv)
    if args.output.exists() and any(args.output.iterdir()):
        parser.error(f"{args.output} is not empty; exports never overwrite")
    found = list(documents(args.inputs))
    if not found:
        parser.error("no document.json found")
    args.output.mkdir(parents=True, exist_ok=True)
    entries = []
    for folder in found:
        source = (folder / "document.json").read_bytes()
        document = json.loads(source)
        docx, docx_warnings = docx_bytes(document, args.text_field)
        xlsx, _ = xlsx_bytes(document, args.text_field)
        name = folder.name
        (args.output / f"{name}.docx").write_bytes(docx)
        (args.output / f"{name}_tables.xlsx").write_bytes(xlsx)
        check = round_trip(document, docx, xlsx, args.text_field)
        entries.append({"document": str(folder), "document_json_sha256": hashlib.sha256(source).hexdigest(),
                        "docx_sha256": hashlib.sha256(docx).hexdigest(), "xlsx_sha256": hashlib.sha256(xlsx).hexdigest(),
                        "warnings": docx_warnings, "round_trip": check})
        print(f"{name}: {check['tables']} tables, {len(docx_warnings)} warnings, {check['status']}")
    manifest = {"schema_version": "structured-export-v1", "text_field": args.text_field,
                "quality_acceptance": "NOT_EVALUATED", "documents": entries}
    (args.output / "export_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                                     encoding="utf-8")
    return 0 if all(entry["round_trip"]["status"] == "ROUND_TRIP_OK" for entry in entries) else 1


if __name__ == "__main__":
    sys.exit(main())
