#!/usr/bin/env python3
"""VLM fallback challenger (V8-090): select pages by diagnostic, then (when allowed) run a local VLM.

  --select-only   CPU only: report which pages of an output the selection policy would
                  send to a VLM, with reasons. No model, no image is produced.
  --candidate ID --weights DIR --pdf-root DIR --experiment-id EXP-V8-VLM-YYYYMMDD-NNN
                  Open a catalog VLM from a local directory (never downloaded here, checked
                  against benchmark/challengers/vlm/pins/<ID>.json) and write canonical
                  page_text records to scratch/benchmarks/<experiment>/predictions/<document>.jsonl.
                  --max-pages N stops after N pages, for a first VRAM check.

Product outputs are read only. Every VLM record is review_required; nothing replaces the
product text. Quality stays NOT_EVALUATED and the decision INCONCLUSIVE without GT.

  python scripts/run_vlm_challenger.py --output output/<run> --select-only --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.challengers import experiment  # noqa: E402
from benchmark.challengers.vlm import adapter, selection  # noqa: E402
from benchmark.challengers.vlm.backends import BackendUnavailable, open_backend  # noqa: E402

SCHEMA = "ocr-v8-vlm-selection-report-v1"
RENDER_DPI = 144


def select_output(output: Path) -> Dict:
    documents, total_pages = [], 0
    for extraction_path in sorted(output.glob("*/extraction.json")):
        doc_dir = extraction_path.parent
        extraction = json.loads(extraction_path.read_bytes())
        extraction_pages = {page["page"]: page for page in extraction["pages"]}
        pages = [json.loads(path.read_bytes()) for path in sorted((doc_dir / "pages").glob("page-*.json"))]
        total_pages += len(pages)
        chosen = selection.select_pages(pages, extraction_pages)
        documents.append({"document": doc_dir.name, "pdf_sha16": extraction.get("doc_sha16"), "pages": len(pages),
                          "selected": chosen})
    counts = {reason: sum(reason in page["reasons"] for d in documents for page in d["selected"]) for reason in selection.REASONS}
    selected = sum(len(d["selected"]) for d in documents)
    return {"schema_version": SCHEMA, "policy": selection.POLICY, "output": output.as_posix(), "pages": total_pages,
            "selected_pages": selected, "selected_share": round(selected / total_pages, 6) if total_pages else None,
            "reason_counts": counts, "quality_acceptance": "NOT_EVALUATED", "documents": documents}


def product_texts(extraction: Dict) -> Dict[int, str]:
    texts = {}
    for page in extraction["pages"]:
        items = {item["id"]: item for item in page.get("items", ())}
        order = page.get("ordered_item_ids") or list(items)
        texts[page["page"]] = "\n".join(items[i].get("text_corrected") or "" for i in order if i in items)
    return texts


def run_model(report: Dict, args) -> Dict:
    import pymupdf

    backend = open_backend(args.candidate, args.weights)
    base = experiment.create_experiment_dirs(ROOT / "scratch" / "benchmarks", args.experiment_id)
    prompt = adapter.PROMPTS[args.prompt]
    run_id = f"{args.experiment_id}:{dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec='seconds')}"
    done, summary = 0, []
    for document in report["documents"]:
        if args.max_pages is not None and done >= args.max_pages:
            break
        if not document["selected"]:
            continue
        doc_dir = Path(report["output"]) / document["document"]
        extraction = json.loads((doc_dir / "extraction.json").read_bytes())
        texts = product_texts(extraction)
        pdf_path = next(p for p in sorted(args.pdf_root.glob("*.pdf"))
                        if hashlib.sha256(p.read_bytes()).hexdigest()[:16] == extraction["doc_sha16"])
        selected = document["selected"]
        if args.max_pages is not None:
            selected = selected[:args.max_pages - done]
        with pymupdf.open(pdf_path) as pdf:
            def render(number, pdf=pdf):
                page = pdf[number - 1]
                pixmap = page.get_pixmap(dpi=RENDER_DPI, alpha=False)
                return pixmap.tobytes("png"), (page.rect.width, page.rect.height)
            records = adapter.run(document["document"], selected, render, lambda n: texts.get(n, ""), backend, run_id, prompt)
        lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        (base / "predictions" / f"{document['document']}.jsonl").write_text(lines, encoding="utf-8")
        done += len(records)
        summary.append({"document": document["document"], "pages": len(records),
                        "missing_output": sum(r["status"] == "MISSING_OUTPUT" for r in records)})
    manifest = {"experiment_id": args.experiment_id, "run_id": run_id, "candidate": args.candidate,
                "model_version": backend.model_version, "generation": getattr(backend, "generation", None),
                "prompt": args.prompt, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "render_dpi": RENDER_DPI, "selection_policy": selection.POLICY, "documents": summary,
                "quality_acceptance": "NOT_EVALUATED", "decision_options": ["INCONCLUSIVE"]}
    (base / "manifests" / "vlm_run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--candidate")
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--pdf-root", type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--prompt", choices=sorted(adapter.PROMPTS), default="vi")
    parser.add_argument("--max-pages", type=int)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; write a new report")
    report = select_output(args.output)
    if not args.select_only:
        if not (args.candidate and args.weights and args.pdf_root and args.experiment_id):
            parser.error("a model run needs --candidate, --weights, --pdf-root and --experiment-id (or use --select-only)")
        try:
            report["model_run"] = run_model(report, args)
        except BackendUnavailable as error:
            print(f"refused: {error}", file=sys.stderr)
            return 3
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print(f"{report['selected_pages']}/{report['pages']} pages selected {report['reason_counts']} -> {args.report}")
    if "model_run" in report:
        print(f"model run: {report['model_run']['documents']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
