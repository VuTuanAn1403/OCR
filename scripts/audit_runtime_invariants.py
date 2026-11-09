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
4. Numeric guard, tables: phase-A OCR lines are the source records of the extraction page
   (``text_evidence.items``: source_id, bbox, text_raw). A cell's sources are the lines
   that overlap its box plus the lines the table provenance maps to it
   (``pages/*.json`` ``tables[].provenance.source_occurrence_mapping``). A number token of
   the cell that none of its sources has is untraced (only a look at the page decides
   why); a number token of a line lying inside the cell that the cell lacks is missing
   from the cell. Cells that repeat the box of an earlier cell of the same table, and
   cells without a provenance mapping, are counted apart: both make the trace weaker.
   (Until 10/11 the check used ``evidence_blocks``, which is not the source list of the
   extraction; that report overstated untraced cells.)

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

SCHEMA = "ocr-v8-runtime-invariants-v2"
NUMBER = re.compile(r"[-+]?\d[\d.,]*%?")
COVER_IOU = 0.5
INSIDE_SHARE = 0.8
EXAMPLES = 20


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
    phase_a = [item for item in ((extraction_page or {}).get("text_evidence") or {}).get("items", []) if item.get("bbox")]
    by_source = {item.get("source_id"): item for item in phase_a}
    mapping = cell_sources(page_record)
    for table in (i for i in items if i.get("kind") == "t"):
        origin = table.get("source") or "unknown"
        seen_boxes = set()
        table_numbers = Counter(n for cell in table.get("cells") or [] for n in numbers(cell.get("text_raw")))
        for cell in table.get("cells") or []:
            box = cell.get("bbox")
            if not box:
                continue
            counts["table_cells"] += 1
            cell_numbers = numbers(cell.get("text_raw"))
            box_key = tuple(round(value, 2) for value in box)
            repeated = box_key in seen_boxes
            seen_boxes.add(box_key)
            overlapping = [i for i in phase_a if _intersection(i["bbox"], box) > 0]
            mapped_ids = mapping.get((table.get("table_id"), cell.get("row"), cell.get("col")))
            mapped = [by_source[s] for s in mapped_ids or () if s in by_source]
            sources = {id(i): i for i in overlapping + mapped}.values()
            untraced = Counter(cell_numbers) - Counter(numbers(" ".join(i.get("text_raw") or "" for i in sources)))
            # A box copied from an earlier cell says nothing about what lies inside this cell.
            contained = [] if repeated else [i for i in overlapping if inside(i["bbox"], box) >= INSIDE_SHARE]
            dropped = Counter(numbers(" ".join(i.get("text_raw") or "" for i in contained))) - Counter(cell_numbers)
            if dropped:
                counts["cells_with_numbers_missing_from_cell"] += 1
                counts[f"cells_with_numbers_missing_from_cell_{origin}"] += 1
                counts["numbers_missing_from_cell"] += sum(dropped.values())
                # Placed in another cell of the table, or absent from the whole table.
                absent = dropped - (table_numbers - Counter(cell_numbers))
                counts["numbers_missing_from_table"] += sum(absent.values())
                counts[f"numbers_missing_from_table_{origin}"] += sum(absent.values())
            if cell_numbers:
                counts["numeric_cells"] += 1
                counts[f"numeric_cells_{origin}"] += 1
                if repeated:
                    counts[f"numeric_cells_repeating_an_earlier_cell_box_{origin}"] += 1
                if mapped_ids is None:
                    counts[f"numeric_cells_without_source_mapping_{origin}"] += 1
            if untraced:
                counts["cells_with_untraced_numbers"] += 1
                counts[f"cells_with_untraced_numbers_{origin}"] += 1
                counts["untraced_numbers"] += sum(untraced.values())
                if repeated:
                    counts["cells_with_untraced_numbers_and_a_repeated_box"] += 1
            if (untraced or dropped) and len(examples["numeric_cells"]) < EXAMPLES:
                examples["numeric_cells"].append({"document": document, "page": page_record.get("page_num"),
                                                  "table": table.get("table_id"), "source": origin, "row": cell.get("row"),
                                                  "col": cell.get("col"), "bbox": box, "repeated_box": repeated,
                                                  "cell_text": cell.get("text_raw"),
                                                  "sources": [i.get("text_raw") for i in sources],
                                                  "untraced": sorted(untraced.elements()),
                                                  "missing_from_cell": sorted(dropped.elements())})
    return dict(counts)


def numbers(text: Optional[str]) -> List[str]:
    return NUMBER.findall(text or "")


def cell_sources(page_record: Dict) -> Dict[tuple, set]:
    """(table_id, row, col) -> source ids, from the table provenance of the page record."""
    mapping: Dict[tuple, set] = {}
    for table in page_record.get("tables") or []:
        occurrences = ((table.get("provenance") or {}).get("source_occurrence_mapping") or {})
        for source_id, places in occurrences.items():
            for place in places:
                mapping.setdefault((table.get("table_id"), place.get("row_idx"), place.get("col_idx")), set()).add(source_id)
    return mapping


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
            "thresholds": {"cover_iou": COVER_IOU, "inside_share": INSIDE_SHARE, "number_token": NUMBER.pattern},
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
