#!/usr/bin/env python3
"""VLM fallback challenger (V8-090): select pages by diagnostic, then (when allowed) run a local VLM.

  --select-only   CPU only: report which pages of an output the selection policy would
                  send to a VLM, with reasons. No model, no image is produced.
  --candidate ID --weights DIR
                  Open a catalog VLM from a local directory (never downloaded) and write
                  canonical page_text records under scratch/benchmarks/<experiment>/predictions/.
                  The catalog gate refuses until the candidate is pinned (V8-043).

Product outputs are read only. Every VLM record is review_required; nothing replaces the
product text. Quality stays NOT_EVALUATED and the decision INCONCLUSIVE without GT.

  python scripts/run_vlm_challenger.py --output output/<run> --select-only --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.challengers.vlm import selection  # noqa: E402
from benchmark.challengers.vlm.backends import BackendUnavailable, open_backend  # noqa: E402

SCHEMA = "ocr-v8-vlm-selection-report-v1"


def select_output(output: Path) -> Dict:
    documents, total_pages = [], 0
    for extraction_path in sorted(output.glob("*/extraction.json")):
        doc_dir = extraction_path.parent
        extraction = json.loads(extraction_path.read_bytes())
        extraction_pages = {page["page"]: page for page in extraction["pages"]}
        pages = [json.loads(path.read_bytes()) for path in sorted((doc_dir / "pages").glob("page-*.json"))]
        total_pages += len(pages)
        chosen = selection.select_pages(pages, extraction_pages)
        documents.append({"document": doc_dir.name, "pages": len(pages), "selected": chosen})
    counts = {reason: sum(reason in page["reasons"] for d in documents for page in d["selected"]) for reason in selection.REASONS}
    selected = sum(len(d["selected"]) for d in documents)
    return {"schema_version": SCHEMA, "policy": selection.POLICY, "output": output.as_posix(), "pages": total_pages,
            "selected_pages": selected, "selected_share": round(selected / total_pages, 6) if total_pages else None,
            "reason_counts": counts, "quality_acceptance": "NOT_EVALUATED", "documents": documents}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--candidate")
    parser.add_argument("--weights", type=Path)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; write a new report")
    report = select_output(args.output)
    if not args.select_only:
        if not (args.candidate and args.weights):
            parser.error("a model run needs --candidate and --weights (or use --select-only)")
        try:
            open_backend(args.candidate, args.weights)
        except BackendUnavailable as error:
            print(f"refused: {error}", file=sys.stderr)
            return 3
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print(f"{report['selected_pages']}/{report['pages']} pages selected {report['reason_counts']} -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
