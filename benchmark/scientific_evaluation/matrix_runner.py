#!/usr/bin/env python3
"""Run the proposal 9.4 configuration matrix and assemble its statistics input.

`run` executes configurations that differ from F by exactly one variable and
writes one `run_record.json` per configuration. A configuration whose
component does not exist yet, or that would equal F for the chosen profile, is
recorded as NOT_APPLICABLE or NOT_IMPLEMENTED with a reason; it is never
silently dropped from the matrix.

B0 is a locked historical commit (proposal 6.5). `--configs B0` runs the base
profile and records the B0 run conditions (clean tree, CPU, balanced profile,
fresh cache, resume off). `assemble` accepts a B0 record only when those hold
and its commit equals `b0_commit` locked in the protocol file, so the current
checkout cannot relabel itself as B0.

With --ground-truth and a source inventory holding verified company IDs, each
run carries paired per-page count records for the company-cluster bootstrap.
A document that fails to convert contributes MISSING_OUTPUT records (maximum
error), never silence. Counts come from ground truth only, never from
confidence or quality scores.

  python -m benchmark.scientific_evaluation.matrix_runner run --pdf inputs/A.pdf inputs/B.pdf \
      --pages 1-5 --output scratch/matrix --configs F A1 A6 V1
  python -m benchmark.scientific_evaluation.matrix_runner assemble --b0 B0/run_record.json \
      --runs scratch/matrix --protocol protocol.json --output scratch/matrix/matrix.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import tempfile
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from benchmark.evaluate import ground_truth_pages
from benchmark.scientific_evaluation.evaluation_protocol import text_metrics
from benchmark.scientific_evaluation.matrix_statistics import CONFIGURATIONS, evaluate_matrix
from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.cli.run_ocr import parse_pages_arg
from src.ocr.collect.catalog import read_sources
from src.ocr.runtime.atomic_io import atomic_write_json, atomic_write_text
from src.ocr.runtime.config import ConfigError, config_hash, get_profile
from src.ocr.runtime.fingerprint import source_fingerprint
from src.ocr.runtime.run_manifest import git_state

RUN_RECORD_SCHEMA = "v6-matrix-run-v2"
NORMALIZATION = "visible_strict_v1"
COUNT_SOURCE = "pages/page-NNNN.md (per-page protocol of run_scientific_benchmark)"
# Errors that mean the environment is broken, not one document: stop the run.
_ENVIRONMENT_ERRORS = (ConfigError, ImportError, MemoryError)

# One variable per configuration, relative to F (proposal 9.4). Overrides are
# derived from the base profile so they only touch keys that profile has.
MATRIX: Dict[str, Dict[str, Any]] = {
    "B0": {"variable": None, "status": "RUNNABLE",
           "description": "Locked baseline: base profile at the B0 commit"},
    "F": {"variable": None, "status": "RUNNABLE", "description": "Full: base profile at the current code"},
    "A1": {"variable": "routing", "status": "RUNNABLE",
           "description": "No native-first routing: OCR every page, no vector tables or native recovery",
           "known_confounds": ["Docling runs with ocr: false and reads the PDF text layer for table cells "
                               "and formulas; table content of A1 is therefore not OCR-only"]},
    "A2": {"variable": "layout_source", "status": "NOT_APPLICABLE",
           "reason": "F uses the heuristic layout because no D1 model is selected (KP-10); A2 would equal F"},
    "A3": {"variable": "diacritic_post_correction", "status": "NOT_APPLICABLE",
           "reason": "F applies no dictionary/BARTpho diacritic correction yet (KP-12)"},
    "A4": {"variable": "scan_table_path", "status": "NOT_APPLICABLE",
           "reason": "F has no hidden-text scan-table path; the C3.5(a) A/B/C experiment is pending (KP-11)"},
    "A5": {"variable": "structure", "status": "NOT_IMPLEMENTED",
           "reason": "Fixed-size chunking in place of the section tree is not implemented"},
    "A6": {"variable": "regional_reocr", "status": "RUNNABLE",
           "description": "Regional re-OCR disabled: fallback flags off and no high-DPI region retry"},
    "V1": {"variable": "tableformer_mode", "status": "RUNNABLE",
           "description": "TableFormer ACCURATE instead of FAST (variant)"},
}
assert tuple(MATRIX) == CONFIGURATIONS


def overrides_for(name: str, base: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """(overrides, reason it is not applicable) for configuration `name`."""
    if name == "A1":
        return {"native_first": False}, None
    if name == "A6":
        render = base.get("render_dpi", 180)
        reocr = (base.get("fallback_enabled") or base.get("fallback_only_on_review")
                 or base.get("fallback_upscale_dpi", render) > render)
        if not reocr:
            return {}, "The base profile has no regional re-OCR path enabled; A6 would equal F"
        overrides = {key: False for key in ("fallback_enabled", "fallback_only_on_review") if key in base}
        if "fallback_upscale_dpi" in base:
            overrides["fallback_upscale_dpi"] = render  # disables the high-DPI region retry
        return overrides, None
    if name == "V1":
        if not base.get("docling", {}).get("enabled"):
            return {}, "The base profile has Docling disabled; V1 would equal F"
        return {"docling": {"table_mode": "accurate"}}, None
    return {}, None


def deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def derive_profile(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides that must name keys the base profile already has, so a
    misspelled key cannot yield a silent copy of F."""
    def check(target: Dict[str, Any], values: Dict[str, Any], path: str) -> None:
        for key, value in values.items():
            if key not in target:
                raise ValueError(f"Override {path}{key} is not configured in the base profile")
            if isinstance(value, dict):
                if not isinstance(target[key], dict):
                    raise ValueError(f"Override {path}{key} expects a mapping in the base profile")
                check(target[key], value, f"{path}{key}.")
    check(base, overrides, "")
    return deep_merge(base, overrides)


def file_set_sha256(paths: List[Path]) -> Optional[str]:
    """Order-independent digest over (name, content) of the given files."""
    if not paths:
        return None
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        digest.update(path.name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def b0_conditions(git: Dict[str, Any], device: str, profile: str) -> Dict[str, Any]:
    """The 6.5 conditions a B0 run must satisfy; fresh cache and resume off are
    guaranteed by this runner. The commit is checked against the protocol at
    assemble time."""
    checks = {"clean_tree": git.get("dirty") is False, "cpu": device == "cpu",
              "profile_balanced": profile == "balanced", "fresh_cache_resume_off": True}
    return {"checks": checks, "met": all(checks.values()), "commit": git.get("commit")}


def _company_inventory(sources: Optional[str]) -> Dict[str, Dict[str, str]]:
    if not sources:
        return {}
    return {row["document_id"]: {"company_id": row["company_id"], "sha256": row["sha256"]}
            for row in read_sources(Path(sources)) if row["company_id"] != "unknown"}


def _verified_company(pdf: str, document_id: str, inventory: Dict[str, Dict[str, str]]) -> Tuple[Optional[str], str]:
    row = inventory.get(document_id)
    if row is None:
        return None, "no verified company_id in the source inventory"
    if hashlib.sha256(Path(pdf).read_bytes()).hexdigest() != row["sha256"]:
        return None, "PDF hash differs from the source inventory"
    return row["company_id"], ""


def _document_gt(gt_dir: Path, document_id: str, pages: Optional[List[int]]) -> Dict[int, Path]:
    """Document-prefixed GT pages within the selection. An unprefixed file
    would be scored against every document, so it is rejected here."""
    selected = ground_truth_pages(gt_dir, document_id)
    if pages:
        selected = {page: path for page, path in selected.items() if page in pages}
    unprefixed = [path.name for path in selected.values() if path.stem.casefold().startswith("page_")]
    if unprefixed:
        raise ValueError(f"Ground truth must be document-prefixed for the matrix: {unprefixed}")
    return selected


def _records_from_counts(base: Dict[str, Any], counts: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = {}
    for metric in ("cer", "wer"):
        if counts.get(metric) is not None:
            detail = counts[metric]
            rows[metric] = {**base, "numerator": detail["substitutions"] + detail["deletions"] + detail["insertions"],
                            "denominator": detail["reference_length"]}
    if counts.get("der") is not None:
        rows["der"] = {**base, "numerator": counts["der"]["diacritic_errors"],
                       "denominator": counts["der"]["ref_diacritics"]}
    return rows


def page_records(doc_dir: Path, gt_dir: Path, company: str) -> Dict[str, List[Dict[str, Any]]]:
    """Paired per-page counts of a converted document."""
    from scripts.run_scientific_benchmark import evaluate_document_scientific

    report = evaluate_document_scientific(doc_dir, gt_dir)
    records: Dict[str, List[Dict[str, Any]]] = {"cer": [], "wer": [], "der": []}
    for page in report.get("page_evaluations", []):
        base = {"company_id": company, "document_id": doc_dir.name, "page": int(page["page_num"]),
                "status": page["status"]}
        for metric, row in _records_from_counts(base, page.get("counts") or {}).items():
            records[metric].append(row)
    return records


def missing_output_records(gt_pages: Dict[int, Path], document_id: str, company: str) -> Dict[str, List[Dict[str, Any]]]:
    """A document without output: every applicable GT page at maximum error."""
    records: Dict[str, List[Dict[str, Any]]] = {"cer": [], "wer": [], "der": []}
    for page, path in sorted(gt_pages.items()):
        metrics = text_metrics(path.read_text(encoding="utf-8"), "", missing=True)
        base = {"company_id": company, "document_id": document_id, "page": page, "status": "MISSING_OUTPUT"}
        for metric, row in _records_from_counts(base, metrics["details"]).items():
            records[metric].append(row)
    return records


def run_configuration(name: str, args: argparse.Namespace, converter: ConvertDocumentUseCase,
                      git: Dict[str, Any], inventory: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    spec = MATRIX[name]
    out = Path(args.output) / name
    record: Dict[str, Any] = {
        "schema": RUN_RECORD_SCHEMA, "configuration": name, "variable": spec["variable"],
        "description": spec.get("description"), "status": spec["status"], "reason": spec.get("reason"),
        "known_confounds": spec.get("known_confounds", []), "run_id": None, "git": git,
        "source_fingerprint": source_fingerprint(), "profile": args.profile,
        "inputs": {"pdf": list(args.pdf), "pages": args.pages}, "config_sha256": None,
        "normalization": NORMALIZATION, "count_source": COUNT_SOURCE, "gt_sha256": None, "splits_sha256": None,
        "documents": [], "failed_documents": [], "quality_status": "NOT_EVALUATED",
        "eligible_for_quality_acceptance": False,
    }
    base = copy.deepcopy(get_profile(converter.profiles, args.profile))
    base["device"] = args.device  # resolved by the converter, including "auto"
    overrides, not_applicable = overrides_for(name, base)
    if record["status"] == "RUNNABLE" and not_applicable:
        record.update(status="NOT_APPLICABLE", reason=not_applicable)
    if record["status"] != "RUNNABLE":
        atomic_write_json(out / "run_record.json", record)
        return record

    profile = derive_profile(base, overrides)
    config_file = out / "profiles.yaml"
    atomic_write_text(config_file, yaml.safe_dump({"profiles": {args.profile: profile}}, allow_unicode=True,
                                                  sort_keys=True))
    record.update(run_id=f"{name}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}",
                  config_sha256=config_hash(profile), overrides=overrides, status="RUNNING")
    # Written before work starts, so an aborted run never leaves an older
    # record that `assemble` could mistake for this one.
    atomic_write_json(out / "run_record.json", record)
    cache = Path(tempfile.mkdtemp(prefix=f"ocr-matrix-{name}-"))
    try:
        with ConvertDocumentUseCase(str(config_file), reuse_docling=True) as run_converter:
            record["device"] = run_converter.resolve_profile(args.profile, args.device)["device"]
            if name == "B0":
                record["b0_conditions"] = b0_conditions(git, record["device"], args.profile)
            _run_documents(name, args, run_converter, record, out, cache, inventory)
    except BaseException as error:
        record.update(status="FAILED", error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
        atomic_write_json(out / "run_record.json", record)
        raise
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    atomic_write_json(out / "run_record.json", record)
    return record


def _run_documents(name: str, args: argparse.Namespace, run_converter: ConvertDocumentUseCase,
                   record: Dict[str, Any], out: Path, cache: Path, inventory: Dict[str, Dict[str, str]]) -> None:
    gt_dir = Path(args.ground_truth) if args.ground_truth else None
    if gt_dir:
        record["gt_sha256"] = file_set_sha256(sorted(gt_dir.glob("*.txt")))
    if args.splits:
        record["splits_sha256"] = hashlib.sha256(Path(args.splits).read_bytes()).hexdigest()
    pages = parse_pages_arg(args.pages)
    records: Dict[str, List[Dict[str, Any]]] = {"cer": [], "wer": [], "der": []}
    quality_problems: List[str] = []
    for pdf in args.pdf:
        document_id = Path(pdf).stem
        entry: Dict[str, Any] = {"pdf": pdf, "document_id": document_id, "status": "COMPLETED"}
        started = time.perf_counter()
        doc = None
        try:
            doc = run_converter.execute(file_path=pdf, profile_name=args.profile, pages=pages,
                                        output_dir=str(out / "output"), resume=False, benchmark=True,
                                        device=args.device, assets_mode=args.assets, cache_dir=str(cache))
        except _ENVIRONMENT_ERRORS:
            raise
        except Exception as error:  # one document failing stays visible in the record
            entry.update(status="FAILED", error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
            print(f"[{name}] {document_id} FAILED: {entry['error']}", flush=True)
        entry["wall_seconds"] = round(time.perf_counter() - started, 3)
        if doc is not None:
            entry.update(document_id=doc.document_id, pages=doc.selected_pages, timing=doc.timing,
                         output=str(out / "output" / doc.document_id))
        else:
            record["failed_documents"].append(document_id)
        record["documents"].append(entry)
        if gt_dir:
            problem = _collect_quality(entry, pdf, gt_dir, pages, inventory, records)
            if problem:
                quality_problems.append(f"{entry['document_id']}: {problem}")

    completed = [d for d in record["documents"] if d["status"] == "COMPLETED"]
    record["status"] = ("COMPLETED" if len(completed) == len(record["documents"])
                        else "COMPLETED_WITH_FAILURES" if completed else "FAILED")
    if not gt_dir:
        record["quality_status_reason"] = "No ground truth supplied"
    elif quality_problems:
        record["quality_status_reason"] = "; ".join(quality_problems)
    elif not any(records.values()):
        record["quality_status_reason"] = "No document-prefixed ground-truth page in the selected pages"
    else:
        record["records_by_metric"] = records
        record["quality_status"] = "COUNTS_RECORDED"


def _collect_quality(entry: Dict[str, Any], pdf: str, gt_dir: Path, pages: Optional[List[int]],
                     inventory: Dict[str, Dict[str, str]], records: Dict[str, List[Dict[str, Any]]]) -> Optional[str]:
    """Add the document's paired records; return why it cannot be counted."""
    company, why = _verified_company(pdf, entry["document_id"], inventory) if Path(pdf).is_file() else \
        (inventory.get(entry["document_id"], {}).get("company_id"), "")
    if not company:
        return why or "no verified company_id in the source inventory"
    try:
        if entry["status"] == "COMPLETED":
            _document_gt(gt_dir, entry["document_id"], pages)  # rejects unprefixed GT
            rows = page_records(Path(entry["output"]), gt_dir, company)
        else:
            rows = missing_output_records(_document_gt(gt_dir, entry["document_id"], pages),
                                          entry["document_id"], company)
    except Exception as error:  # GT problems must not abort the other documents
        return f"ground truth evaluation failed: {type(error).__name__}: {error}"
    for metric, metric_rows in rows.items():
        records[metric].extend(metric_rows)
    return None


_COMPARABLE_FIELDS = ("profile", "source_fingerprint", "inputs")


def _provenance(record: Dict[str, Any]) -> Tuple[Any, ...]:
    git = record.get("git") or {}
    return (git.get("commit"), git.get("uncommitted_diff_sha256"),
            *(json.dumps(record.get(field), sort_keys=True) for field in _COMPARABLE_FIELDS))


def assemble(b0_path: Optional[str], runs_dir: str, protocol_path: str) -> Dict[str, Any]:
    """Build the matrix_statistics payload; every slot keeps a visible status.
    Candidates must come from the same code, profile and inputs as F; B0 must
    meet the 6.5 conditions at the protocol's locked `b0_commit`."""
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    records: Dict[str, Dict[str, Any]] = {}
    slots: Dict[str, Dict[str, Any]] = {}
    for name in CONFIGURATIONS:
        path = Path(b0_path) if name == "B0" and b0_path else Path(runs_dir) / name / "run_record.json"
        if not path.is_file():
            slots[name] = {"status": "NOT_RUN", "reason": f"{path} not found"}
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            slots[name] = {"status": "INVALID_RECORD", "reason": f"{path}: {error}"}
            continue
        if record.get("schema") != RUN_RECORD_SCHEMA or record.get("configuration") != name:
            slots[name] = {"status": "INVALID_RECORD", "reason": f"{path} is not a {name} run record"}
            continue
        slots[name] = {"status": record.get("status"), "reason": record.get("reason"),
                       "quality_status": record.get("quality_status"),
                       "failed_documents": record.get("failed_documents", [])}
        records[name] = record

    reference = records.get("F")
    runs: Dict[str, Dict[str, Any]] = {}
    for name, record in records.items():
        if name == "B0":
            conditions = record.get("b0_conditions") or {}
            locked = protocol.get("b0_commit")
            if not conditions.get("met") or not locked or (record.get("git") or {}).get("commit") != locked:
                slots[name].update(status="NOT_ACCEPTED_AS_B0",
                                   reason="B0 needs the 6.5 conditions and the protocol's locked b0_commit")
                continue
        elif reference is not None and _provenance(record) != _provenance(reference):
            slots[name].update(status="INVALID_RECORD",
                               reason="Different code, profile or inputs than F; more than one variable differs")
            continue
        if str(record.get("status", "")).startswith("COMPLETED") and record.get("records_by_metric"):
            runs[name] = record
    result = evaluate_matrix({"protocol": protocol, "runs": runs})
    result["slots"] = slots
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Execute configurations and write run records")
    run.add_argument("--pdf", nargs="+", required=True)
    run.add_argument("--pages", default=None)
    run.add_argument("--profile", default="balanced")
    run.add_argument("--config", default=None, help="Base profile config (default: config/profiles.yaml)")
    run.add_argument("--device", default="cpu", help="CPU by default: B0 and REQ-01..03 are CPU measurements")
    run.add_argument("--assets", default="none", choices=("png", "jpeg", "none"))
    run.add_argument("--configs", nargs="+", default=[c for c in CONFIGURATIONS if c != "B0"],
                     choices=CONFIGURATIONS)
    run.add_argument("--ground-truth", default=None)
    run.add_argument("--sources", default=None, help="sources.csv with verified company_id (collect sources)")
    run.add_argument("--splits", default=None, help="Locked splits file; its hash is recorded")
    run.add_argument("--output", required=True)
    assemble_parser = sub.add_parser("assemble", help="Combine run records into matrix statistics")
    assemble_parser.add_argument("--runs", required=True, help="Output directory of `run`")
    assemble_parser.add_argument("--b0", default=None, help="B0 run_record.json from the locked commit")
    assemble_parser.add_argument("--protocol", required=True,
                                 help="Protocol JSON for matrix_statistics; holds the locked b0_commit")
    assemble_parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.command == "assemble":
        try:
            result = assemble(args.b0, args.runs, args.protocol)
        except KeyError as error:
            parser.error(f"protocol or run record is missing field {error}")
        except (OSError, ValueError, TypeError) as error:
            parser.error(str(error))
        atomic_write_json(Path(args.output), result)
        print(json.dumps(result["slots"], indent=2))
        return

    if args.ground_truth:
        if not Path(args.ground_truth).is_dir():
            parser.error(f"--ground-truth {args.ground_truth} is not a directory")
        if not args.sources:
            parser.error("--ground-truth needs --sources with verified company IDs for paired counts")
    converter = ConvertDocumentUseCase(args.config or str(Path(__file__).resolve().parents[1] / "baselines/profiles-v61.yaml"))
    git = git_state()
    inventory = _company_inventory(args.sources)
    summary = {}
    for name in args.configs:
        record = run_configuration(name, args, converter, git, inventory)
        summary[name] = {"status": record["status"], "reason": record.get("reason"),
                         "quality_status": record["quality_status"],
                         "failed_documents": record.get("failed_documents", [])}
        print(f"{name}: {summary[name]}", flush=True)
    atomic_write_json(Path(args.output) / "matrix_runs.json",
                      {"schema": RUN_RECORD_SCHEMA, "git": git, "configurations": summary})


if __name__ == "__main__":
    main()
