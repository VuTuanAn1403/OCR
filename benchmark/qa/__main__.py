"""CPU-only QA CLI, independent of the product OCR CLI."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .evidence import EvidenceStore, require, write_new_json
from .error_registry import snapshot, validate_registry
from .review_registry import import_review_packet


def analysis_output(path, evidence_root):
    output = path.resolve()
    require(output.is_relative_to(evidence_root.resolve()) and not output.exists(), "Analysis requires a new output inside evidence root")
    require(not any((parent / name).is_file() for parent in output.parents
                    for name in ("COMPLETED.json", "ocr_receipt.json", "batch_input_manifest.json", "packet.json")),
            "Analysis output must be outside publications and review packets")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Verify registry metadata, history and evidence hashes")
    validate.add_argument("--registry", type=Path, required=True)
    validate.add_argument("--evidence-root", type=Path, required=True)
    review = commands.add_parser("import-review", help="Import selected operator signals without asserting OCR defects")
    review.add_argument("--packet", type=Path, required=True)
    review.add_argument("--evidence-root", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--creator", required=True)
    review.add_argument("--created-at", default=None)
    review.add_argument("--historical", action="store_true", help="Explicitly preserve historical source status")
    append = commands.add_parser("append", help="Append records/revisions to an immutable registry snapshot")
    append.add_argument("--registry", type=Path, required=True)
    append.add_argument("--records", type=Path, required=True, help="ocr-error-registry-records-v1 JSON")
    append.add_argument("--evidence-root", type=Path, required=True)
    append.add_argument("--output", type=Path, required=True)
    append.add_argument("--creator", required=True)
    append.add_argument("--created-at", default=None)
    paired = commands.add_parser("paired", help="Recompute evaluator counts and report metric-specific fixes/harms")
    paired.add_argument("--protocol", type=Path, required=True)
    paired.add_argument("--evidence-root", type=Path, required=True)
    paired.add_argument("--output", type=Path, required=True)
    for name in ("artifact-index", "sample", "prediction-inventory", "baseline", "candidate",
                 "baseline-keyword-alignments", "candidate-keyword-alignments",
                 "baseline-reading-order-alignments", "candidate-reading-order-alignments", "formula-pdf-root",
                 "formula-output", "formula-python", "node", "lualatex", "baseline-critical", "candidate-critical",
                 "baseline-cdm", "candidate-cdm"):
        paired.add_argument("--" + name, type=Path)
    report = commands.add_parser("report", help="Build a scoped QA report and optional offline dashboard")
    report.add_argument("--evidence-root", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--include-development-details", action="store_true", help="Include only eligible development operator review details")
    for name in ("registry", "paired", "detector-report", "detector-gt", "detector-extraction", "html"):
        report.add_argument("--" + name, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            store = EvidenceStore(args.evidence_root)
            result = validate_registry(store.json(store.ref(args.registry)), store)
        elif args.command == "import-review":
            created_at = args.created_at or datetime.now(timezone.utc).isoformat()
            value, protected = import_review_packet(args.packet, args.evidence_root, created_at=created_at,
                                                     creator=args.creator, historical=args.historical)
            output = args.output.resolve()
            require(not any(output.is_relative_to(directory) for directory in protected),
                    "Registry output must be outside packet and original publication directories")
            require(output.is_relative_to(args.evidence_root.resolve()), "Output must stay inside evidence root")
            write_new_json(output, value)
            store = EvidenceStore(args.evidence_root)
            result = validate_registry(store.json(store.ref(output)), store)
        elif args.command == "paired":
            from .paired_effects import run
            output = analysis_output(args.output, args.evidence_root)
            args.report = output
            value = run(args)
            write_new_json(output, value)
            print(json.dumps({"schema_version": value["schema_version"], "status": value["status"],
                              "quality_status": "NOT_EVALUATED", "report": str(output)}, ensure_ascii=True))
            return int(value["status"] != "MEASURED")
        elif args.command == "report":
            from .report import build_report
            from .report_view import render, write_html
            output = analysis_output(args.output, args.evidence_root)
            html = analysis_output(args.html, args.evidence_root) if args.html is not None else None
            require(html != output, "JSON report and dashboard must use different paths")
            value = build_report(args)
            content = render(value, html, args.evidence_root) if html is not None else None
            write_new_json(output, value)
            if html is not None:
                write_html(html, content)
            result = {"status": value["status"], "quality_status": value["quality_status"], "report": str(output),
                      "dashboard": str(html) if html is not None else None, "metric_states": value["metric_states"]}
        else:
            store = EvidenceStore(args.evidence_root)
            parent_ref = store.ref(args.registry)
            parent = store.json(parent_ref)
            validate_registry(parent, store)
            records_ref = store.ref(args.records)
            additions = store.json(records_ref)
            require(additions.get("schema_version") == "ocr-error-registry-records-v1"
                    and isinstance(additions.get("records"), list) and additions["records"], "Expected nonempty appended records")
            value = snapshot(parent["records"] + additions["records"],
                             created_at=args.created_at or datetime.now(timezone.utc).isoformat(), creator=args.creator,
                             previous_registry=parent_ref, evidence=parent["evidence"] + [records_ref])
            validate_registry(value, store)
            output = args.output.resolve()
            require(output.is_relative_to(store.root), "Output must stay inside evidence root")
            protected = []
            for record in value["records"]:
                if record["origin"]["kind"] == "operator_review":
                    protected.append(store.path(record["evidence"]["review_packet"]["path"]).parent)
                    protected.append(store.path(record["evidence"]["origin_extraction"]["path"]).parent)
                for run in record["runs"].values():
                    if run and "extraction" in run["artifacts"]:
                        protected.append(store.path(run["artifacts"]["extraction"]["path"]).parent)
            require(not any(output.is_relative_to(directory) for directory in protected),
                    "Registry output must be outside packet and original publication directories")
            write_new_json(output, value)
            result = validate_registry(store.json(store.ref(output)), store)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError) as exc:
        print(json.dumps({"status": "INVALID", "quality_status": "NOT_EVALUATED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
