#!/usr/bin/env python3
"""Paired, GT-free comparison of two batch outputs of the same PDFs (V8-080, V8-100, V8-140).

CPU only and read-only. For each document present and SUCCEEDED in both runs it reports:

* the spec-13 runtime invariants of ``audit_runtime_invariants.build`` (drops, untraced
  numbers, repeated cell boxes, source mapping), as baseline, candidate and delta;
* literal keyword counts (``keyword_counts.json`` ``canonical_counts``) per keyword, with
  every keyword whose count differs;
* ``result.md`` sha256, so an unchanged reading text is visible at a glance.

A delta in an invariant counter is a change in a property that must hold without GT; it is
not an accuracy result. Keyword differences need a look at the page (no keyword GT), so
quality stays NOT_EVALUATED.

  python scripts/compare_run_invariants.py --baseline output/<a> --candidate output/<b> \
      --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts import audit_runtime_invariants as audit  # noqa: E402

SCHEMA = "ocr-v8-run-invariant-comparison-v1"


def _documents(output: Path) -> Dict[str, Path]:
    return {path.parent.name: path.parent for path in sorted(output.glob("*/COMPLETED.json"))}


def _keyword_counts(doc_dir: Path) -> Dict[str, int]:
    path = doc_dir / "keyword_counts.json"
    return json.loads(path.read_bytes())["canonical_counts"] if path.is_file() else {}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def compare(baseline: Path, candidate: Path) -> Dict:
    base_docs, cand_docs = _documents(baseline), _documents(candidate)
    shared = sorted(set(base_docs) & set(cand_docs))
    base_audit = {d["document"]: d["counts"] for d in audit.build(baseline)["documents"] if d["document"] in shared}
    cand_audit = {d["document"]: d["counts"] for d in audit.build(candidate)["documents"] if d["document"] in shared}
    documents, totals = [], {"baseline": {}, "candidate": {}}
    keyword_changes = 0
    for name in shared:
        b, c = base_audit.get(name, {}), cand_audit.get(name, {})
        keys = sorted(set(b) | set(c))
        for side, counts in (("baseline", b), ("candidate", c)):
            for key in keys:
                totals[side][key] = totals[side].get(key, 0) + counts.get(key, 0)
        kb, kc = _keyword_counts(base_docs[name]), _keyword_counts(cand_docs[name])
        changed = {k: {"baseline": kb.get(k, 0), "candidate": kc.get(k, 0)}
                   for k in sorted(set(kb) | set(kc)) if kb.get(k, 0) != kc.get(k, 0)}
        keyword_changes += len(changed)
        documents.append({
            "document": name,
            "result_md_identical": _sha(base_docs[name] / "result.md") == _sha(cand_docs[name] / "result.md"),
            "keyword_total": {"baseline": sum(kb.values()), "candidate": sum(kc.values())},
            "keyword_changes": changed,
            "invariant_delta": {k: c.get(k, 0) - b.get(k, 0) for k in keys if c.get(k, 0) != b.get(k, 0)},
        })
    keys = sorted(set(totals["baseline"]) | set(totals["candidate"]))
    return {"schema_version": SCHEMA, "quality_acceptance": "NOT_EVALUATED",
            "baseline": baseline.as_posix(), "candidate": candidate.as_posix(),
            "documents_compared": shared,
            "documents_only_in_baseline": sorted(set(base_docs) - set(cand_docs)),
            "documents_only_in_candidate": sorted(set(cand_docs) - set(base_docs)),
            "invariant_totals": {k: {"baseline": totals["baseline"].get(k, 0),
                                     "candidate": totals["candidate"].get(k, 0)} for k in keys},
            "keyword_keys_changed": keyword_changes, "documents": documents}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="New JSON report (never overwritten)")
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    report = compare(args.baseline, args.candidate)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"documents": len(report["documents_compared"]),
                      "keyword_keys_changed": report["keyword_keys_changed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
