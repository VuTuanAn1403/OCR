#!/usr/bin/env python3
"""Spec-13 runtime invariants of an existing output, without GT (V8-080, V8-120).

CPU only and read-only. Spec 13 section 4 and the numeric guard of layer 3 state what
must hold on any run, labelled or not. This tool counts violations; it fixes nothing.

1. No silent drop: every recognised evidence block of a page (``pages/*.json``) must be
   in ``extraction.json``. A block rejected for low confidence or as a hallucination that
   no extraction item covers is a drop. Text that is only kept in the page evidence is
   reported as such.
2. Provenance: every extraction text item carries ``bbox``, ``source_id`` and a
   ``confidence`` (or ``confidence_source`` saying why there is none).
3. Numeric guard, text: the number tokens (``[-+]?digit[digits , .]*%?``) of
   ``text_corrected`` must equal those of ``text_raw`` in order; post-processing may not
   change a number. A dash restored between words is not a number and is not counted.
4. Numeric guard, tables: phase-A OCR lines are the page's evidence blocks (rejected ones
   excluded). A protected character ``0-9 , . - %`` in a table cell that no phase-A line
   overlapping the cell has is untraced (the cell box may be off, or the text may come
   from elsewhere: only a look at the page decides); a protected character of a phase-A
   line lying inside the cell that the cell lacks is missing from the cell.

  python scripts/audit_runtime_invariants.py --output output/<run> --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence

SCHEMA = "ocr-v8-runtime-invariants-v1"
PROTECTED = set("0123456789,.-%")
NUMBER = re.compile(r"[-+]?\d[\d.,]*%?")
COVER_IOU = 0.5
INSIDE_SHARE = 0.8
EXAMPLES = 20


def protected(text: Optional[str]) -> str:
    return "".join(char for char in (text or "") if char in PROTECTED)


def _area(box: Sequence[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(a: Sequence[float], b: Sequence[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    inter = _intersection(a, b)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def inside(inner: Sequence[float], outer: Sequence[float]) -> float:
    return _intersection(inner, outer) / _area(inner) if _area(inner) > 0 else 0.0


def audit_page(page_record: Dict, extraction_page: Optional[Dict], document: str, examples: Dict[str, List]) -> Dict:
    counts: Counter = Counter()
    items = (extraction_page or {}).get("items", [])
    text_items = [i for i in items if i.get("kind") == "b"]
    for block in page_record.get("evidence_blocks", []):
        status = block.get("status", "")
        counts[f"evidence_{status}"] += 1
        if not status.startswith("REJECTED") or not (block.get("text") or "").strip() or not block.get("bbox"):
            continue
        covered = any(item.get("bbox") and iou(block["bbox"], item["bbox"]) >= COVER_IOU for item in text_items)
        if not covered:
            counts[f"dropped_{status}"] += 1
            counts[f"dropped_{status}_{block.get('content_type') or 'UNKNOWN'}"] += 1
            if len(examples["dropped"]) < EXAMPLES:
                examples["dropped"].append({"document": document, "page": page_record.get("page_num"), "status": status,
                                            "content_type": block.get("content_type"), "text": block.get("text"),
                                            "confidence": block.get("confidence"), "bbox": block.get("bbox")})
    for item in text_items:
        counts["text_items"] += 1
        missing = [key for key in ("bbox", "source_id") if not item.get(key)]
        if item.get("confidence") is None and not item.get("confidence_source"):
            missing.append("confidence")
        if missing:
            counts["provenance_missing"] += 1
        if NUMBER.findall(item.get("text_raw") or "") != NUMBER.findall(item.get("text_corrected") or ""):
            counts["numeric_changed_by_postprocessing"] += 1
            if len(examples["numeric_text"]) < EXAMPLES:
                examples["numeric_text"].append({"document": document, "page": page_record.get("page_num"),
                                                 "id": item.get("id"), "text_raw": item.get("text_raw"),
                                                 "text_corrected": item.get("text_corrected")})
    phase_a = [{"bbox": block["bbox"], "text_raw": block.get("text") or ""} for block in page_record.get("evidence_blocks", [])
               if block.get("bbox") and not str(block.get("status", "")).startswith("REJECTED")]
    for table in (i for i in items if i.get("kind") == "t"):
        for cell in table.get("cells") or []:
            box = cell.get("bbox")
            cell_chars = protected(cell.get("text_raw"))
            if not box:
                continue
            counts["table_cells"] += 1
            overlapping = [i for i in phase_a if _intersection(i["bbox"], box) > 0]
            source = Counter(protected(" ".join(i.get("text_raw") or "" for i in overlapping)))
            invented = Counter(cell_chars) - source
            contained = [i for i in overlapping if inside(i["bbox"], box) >= INSIDE_SHARE]
            dropped = Counter(protected(" ".join(i.get("text_raw") or "" for i in contained))) - Counter(cell_chars)
            origin = table.get("source") or "unknown"
            if cell_chars:
                counts["numeric_cells"] += 1
                counts[f"numeric_cells_{origin}"] += 1
            if invented:
                counts["cells_with_untraced_numeric_chars"] += 1
                counts[f"cells_with_untraced_numeric_chars_{origin}"] += 1
                counts["untraced_numeric_chars"] += sum(invented.values())
                if not overlapping:
                    counts["cells_without_phase_a_line"] += 1
            if dropped:
                counts["cells_with_numeric_chars_missing_from_cell"] += 1
                counts[f"cells_with_numeric_chars_missing_from_cell_{origin}"] += 1
                counts["numeric_chars_missing_from_cell"] += sum(dropped.values())
            if (invented or dropped) and len(examples["numeric_cells"]) < EXAMPLES:
                examples["numeric_cells"].append({"document": document, "page": page_record.get("page_num"),
                                                  "table": table.get("table_id"), "source": table.get("source"), "row": cell.get("row"), "col": cell.get("col"),
                                                  "cell_text": cell.get("text_raw"),
                                                  "ocr_inside": [i.get("text_raw") for i in contained],
                                                  "untraced": "".join(sorted(invented.elements())),
                                                  "missing_from_cell": "".join(sorted(dropped.elements()))})
    return dict(counts)


def build(output: Path) -> Dict:
    totals: Counter = Counter()
    examples: Dict[str, List] = {"dropped": [], "numeric_text": [], "numeric_cells": []}
    documents = []
    pages_with_drop = 0
    for extraction_path in sorted(output.glob("*/extraction.json")):
        doc_dir = extraction_path.parent
        extraction = json.loads(extraction_path.read_bytes())
        by_page = {page["page"]: page for page in extraction["pages"]}
        doc_counts: Counter = Counter()
        for page_path in sorted((doc_dir / "pages").glob("page-*.json")):
            record = json.loads(page_path.read_bytes())
            counts = audit_page(record, by_page.get(record.get("page_num")), doc_dir.name, examples)
            pages_with_drop += bool(counts.get("dropped_REJECTED_LOW_CONFIDENCE") or counts.get("dropped_REJECTED_HALLUCINATION"))
            doc_counts.update(counts)
        totals.update(doc_counts)
        documents.append({"document": doc_dir.name, "counts": dict(sorted(doc_counts.items()))})
    return {"schema_version": SCHEMA, "output": output.as_posix(), "quality_acceptance": "NOT_EVALUATED",
            "thresholds": {"cover_iou": COVER_IOU, "inside_share": INSIDE_SHARE, "protected": "".join(sorted(PROTECTED))},
            "totals": dict(sorted(totals.items())), "pages_with_dropped_lines": pages_with_drop,
            "examples": examples, "documents": documents}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; write a new report")
    report = build(args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print(json.dumps({"pages_with_dropped_lines": report["pages_with_dropped_lines"], **report["totals"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
