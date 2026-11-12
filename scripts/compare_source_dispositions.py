#!/usr/bin/env python3
"""Per-source disposition transitions between two outputs of the same PDFs (V8-080).

CPU only, read-only. Phase-A sources (``text_evidence``) keep their ``source_id`` when phase A
is byte-identical; this tool checks that, then counts how each source's disposition changed
(``VISIBLE_OR_FURNITURE``, ``REPLACED_BY_TABLE``, ``KEPT_FOR_REVIEW`` ...). A source that leaves
the body must be owned by exactly one table or formula of the candidate (the extraction
validator enforces this); the report lists any that is neither visible nor owned.

  python scripts/compare_source_dispositions.py --baseline output/<a> --candidate output/<b> --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SCHEMA = "ocr-v8-source-disposition-transitions-v1"


def _pages(path: Path):
    return {p["page"]: p for p in json.loads(path.read_bytes())["pages"]}


def compare(baseline: Path, candidate: Path) -> dict:
    docs = sorted(p.parent.name for p in candidate.glob("*/COMPLETED.json") if (baseline / p.parent.name / "COMPLETED.json").is_file())
    transitions, phase_a_differs, unowned, per_doc = Counter(), [], [], {}
    for doc in docs:
        a, b = _pages(baseline / doc / "extraction.json"), _pages(candidate / doc / "extraction.json")
        counts = Counter()
        for page, pb in b.items():
            pa = a.get(page, {})
            ea = [(i["source_id"], i.get("text_raw"), i.get("bbox")) for i in (pa.get("text_evidence") or {}).get("items", [])]
            eb = [(i["source_id"], i.get("text_raw"), i.get("bbox")) for i in (pb.get("text_evidence") or {}).get("items", [])]
            if ea != eb:
                phase_a_differs.append({"document": doc, "page": page})
                continue
            da, db = pa.get("source_dispositions") or {}, pb.get("source_dispositions") or {}
            owned = {sid for item in pb["items"] if item["kind"] in ("t", "f")
                     for sid in item.get("derived_from_source_ids", [])}
            visible = {item.get("source_id") for item in pb["items"] if item["kind"] == "b"}
            for sid, _, _ in eb:
                key = (da.get(sid, {}).get("status"), db.get(sid, {}).get("status"))
                counts[key] += 1
                if sid not in owned and sid not in visible:
                    unowned.append({"document": doc, "page": page, "source_id": sid, "status": key[1]})
        per_doc[doc] = {f"{x}->{y}": n for (x, y), n in sorted(counts.items(), key=str) if x != y}
        transitions.update(counts)
    return {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED",
            "baseline": baseline.as_posix(), "candidate": candidate.as_posix(), "documents": docs,
            "phase_a_differs": phase_a_differs, "sources_neither_visible_nor_owned": unowned,
            "changed": {f"{x}->{y}": n for (x, y), n in sorted(transitions.items(), key=str) if x != y},
            "unchanged": sum(n for (x, y), n in transitions.items() if x == y), "per_document": per_doc}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    report = compare(args.baseline, args.candidate)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"changed": report["changed"], "unchanged": report["unchanged"],
                      "phase_a_differs": len(report["phase_a_differs"]),
                      "neither_visible_nor_owned": len(report["sources_neither_visible_nor_owned"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
