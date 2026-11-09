#!/usr/bin/env python3
"""Run the proposal 9.4 configuration matrix on the product pipeline (V8-042).

`run` executes configurations that differ from F by exactly one variable and
writes one `run_record.json` per configuration. Every document goes through
`ocr_pipeline.cli.main` in a child process (`benchmark/product_run.py`): CUDA,
every page, the unified profile, a fresh output and no `--resume`. A
configuration whose component does not exist in the unified pipeline, or that
would equal F, is recorded as NOT_APPLICABLE or NOT_IMPLEMENTED with a reason;
it is never silently dropped from the matrix.

F and B0 run the base configuration file unchanged with the product's default
`--assets png` and compact output, so their receipts carry the same
`ocr_identity` as a baseline lock of that file (the identity includes both). Each ablation runs a
derived file that keeps the base declarations and changes only its variable.

B0 is a locked commit (proposal 6.5, adapted to the product): `--configs B0`
runs the base configuration and records the B0 run conditions (clean tree,
CUDA, the unified profile, fresh output without resume). `assemble` accepts a
B0 record only when those hold and its commit equals `b0_commit` locked in the
protocol file, so the current checkout cannot relabel itself as B0.

With --ground-truth and a source inventory holding verified company IDs, each
run carries paired per-page count records for the company-cluster bootstrap.
OCR always processes every page; --score-pages only limits the GT pages that
are scored. A document that fails contributes MISSING_OUTPUT records (maximum
error), never silence. Counts come from ground truth only, never from
confidence or quality scores.

  python -m benchmark.scientific_evaluation.matrix_runner run --pdf inputs/A.pdf inputs/B.pdf \
      --output output/<new>/matrix --configs F A6 V1
  python -m benchmark.scientific_evaluation.matrix_runner assemble --b0 B0/run_record.json \
      --runs output/<new>/matrix --protocol protocol.json --output output/<new>/matrix/matrix.json
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from benchmark import product_run
from benchmark.evaluate import ground_truth_pages
from benchmark.scientific_evaluation.evaluation_protocol import text_metrics
from benchmark.scientific_evaluation.matrix_statistics import CONFIGURATIONS, evaluate_matrix
from ocr_artifacts.atomic_io import atomic_write_json
from ocr_runtime.config import ConfigError, config_hash
from ocr_runtime.pipeline_policy import PROFILE

RUN_RECORD_SCHEMA = "v8-matrix-run-v1"
NORMALIZATION = "visible_strict_v1"
COUNT_SOURCE = "pages/page-NNNN.md (per-page protocol of run_scientific_benchmark)"
SOURCE_COLUMNS = ("document_id", "company_id", "sha256")

# One variable per configuration, relative to F (proposal 9.4). Overrides are
# derived from the base profile so they only touch keys that profile has.
MATRIX: Dict[str, Dict[str, Any]] = {
    "B0": {"variable": None, "status": "RUNNABLE",
           "description": "Locked baseline: the base configuration at the protocol's b0_commit"},
    "F": {"variable": None, "status": "RUNNABLE", "description": "Full: the base configuration at the current code"},
    "A1": {"variable": "routing", "status": "NOT_APPLICABLE",
           "reason": "The unified pipeline OCRs every page; validate_profile requires native_first=false, "
                     "so there is no native-first routing to disable and A1 would equal F"},
    "A2": {"variable": "layout_source", "status": "NOT_IMPLEMENTED",
           "reason": "The unified profile has no supported second layout source; layout candidates are "
                     "challengers (benchmark/challengers, V8-070), not profile variants"},
    "A3": {"variable": "diacritic_post_correction", "status": "NOT_APPLICABLE",
           "reason": "F applies no dictionary/BARTpho diacritic post-correction (V8-030 pending)"},
    "A4": {"variable": "scan_table_path", "status": "NOT_APPLICABLE",
           "reason": "F has no hidden-text scan-table path; the C3.5(a) A/B/C experiment is pending (KP-11)"},
    "A5": {"variable": "structure", "status": "NOT_IMPLEMENTED",
           "reason": "Fixed-size chunking in place of the section tree is not implemented"},
    "A6": {"variable": "regional_reocr", "status": "RUNNABLE",
           "description": "Regional re-OCR disabled: fallback flags off and no high-DPI region retry "
                          "(diacritic_retry and short_token_retry)"},
    "V1": {"variable": "tableformer_mode", "status": "RUNNABLE",
           "description": "TableFormer ACCURATE instead of FAST (variant)"},
}
assert tuple(MATRIX) == CONFIGURATIONS

# Region retries at a higher DPI than the page render.
_REGION_RETRIES = ("diacritic_retry", "short_token_retry")


def overrides_for(name: str, base: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """(overrides, reason it is not applicable) for configuration `name`."""
    if name == "A6":
        render = base.get("render_dpi", 180)
        overrides: Dict[str, Any] = {}
        for key in ("fallback_enabled", "fallback_only_on_review"):
            if base.get(key):
                overrides[key] = False
        if base.get("fallback_upscale_dpi", render) > render:
            overrides["fallback_upscale_dpi"] = render  # disables the v6 high-DPI region retry
        for key in _REGION_RETRIES:
            if isinstance(base.get(key), dict) and base[key].get("enabled"):
                overrides[key] = {"enabled": False}
        if not overrides:
            return {}, "The base profile has no regional re-OCR path enabled; A6 would equal F"
        return overrides, None
    if name == "V1":
        docling = base.get("docling", {})
        if not docling.get("enabled"):
            return {}, "The base profile has Docling disabled; V1 would equal F"
        if docling.get("table_mode") == "accurate":
            return {}, "The base profile already uses TableFormer ACCURATE; V1 would equal F"
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


def b0_conditions(git: Dict[str, Any], device: Optional[str], profile: Optional[str]) -> Dict[str, Any]:
    """The 6.5 conditions for the product: clean tree, CUDA, the unified profile.
    A fresh output without resume is guaranteed by product_run. The commit is
    checked against the protocol at assemble time."""
    checks = {"clean_tree": git.get("dirty") is False, "cuda": device == product_run.PRODUCT_DEVICE,
              "unified_profile": profile == PROFILE, "fresh_output_resume_off": True}
    return {"checks": checks, "met": all(checks.values()), "commit": git.get("commit")}


def normalize_company_id(value: Any) -> str:
    """The company identifier as `collect sources` writes it: NFC, stripped and case-folded,
    so one company is one bootstrap cluster. Blank or any spelling of 'unknown' is 'unknown'.
    Mirrors src/ocr/collect/catalog.py::company_id, which runners may not import (V8-042)."""
    if not isinstance(value, str) or not value.strip() or value.strip().casefold() == "unknown":
        return "unknown"
    result = unicodedata.normalize("NFC", value).strip().casefold()
    if any(char.isspace() for char in result):
        raise ValueError(f"company_id must be a stable identifier, not a company display name: {value!r}")
    return result


def read_source_inventory(path: Path) -> List[Dict[str, str]]:
    """Rows of a sources.csv (collect sources); only the columns the matrix needs are required."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(SOURCE_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Source inventory is missing columns: {sorted(missing)}")
        rows = list(reader)
    for number, row in enumerate(rows, start=1):
        # csv fills a short row with None and puts the surplus of a long row under the key None.
        if None in row or any(row[column] is None for column in SOURCE_COLUMNS):
            raise ValueError(f"Source inventory data row {number} does not match the header columns")
    if not rows or len({row["document_id"].casefold() for row in rows}) != len(rows):
        raise ValueError("Source inventory is empty or contains duplicate document IDs")
    for row in rows:
        row["company_id"] = normalize_company_id(row["company_id"])
        row["sha256"] = row["sha256"].strip().lower()  # compared with hexdigest(), which is lower case
        if len(row["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["sha256"]):
            raise ValueError("Source SHA-256 is invalid")
    return rows


def _company_inventory(sources: Optional[str]) -> Dict[str, Dict[str, str]]:
    if not sources:
        return {}
    return {row["document_id"]: {"company_id": row["company_id"], "sha256": row["sha256"]}
            for row in read_source_inventory(Path(sources)) if row["company_id"] != "unknown"}


def document_ids(pdfs: List[str]) -> List[str]:
    """Output directory name of each input PDF. Names that collide after NFC case folding
    (as run_batch rejects them) would share one fresh output, so they are refused up front."""
    ids = [Path(pdf).stem for pdf in pdfs]
    keys = [unicodedata.normalize("NFC", document_id).casefold() for document_id in ids]
    if len(set(keys)) != len(keys):
        raise ValueError("Matrix inputs must have distinct document IDs (PDF filenames)")
    return ids


def _verified_company(pdf: str, document_id: str, inventory: Dict[str, Dict[str, str]],
                      pdf_sha256: Optional[str] = None) -> Tuple[Optional[str], str]:
    """`pdf_sha256` is the digest product_run already took of this PDF; it is hashed only without one."""
    row = inventory.get(document_id)
    if row is None:
        return None, "no verified company_id in the source inventory"
    if (pdf_sha256 or product_run.file_sha256(Path(pdf))) != row["sha256"]:
        return None, "PDF hash differs from the source inventory"
    return row["company_id"], ""


def parse_score_pages(value: Optional[str]) -> Optional[List[int]]:
    """'1,3-5' -> [1, 3, 4, 5]; None scores every GT page."""
    if value is None:
        return None
    pages: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"Invalid page selection: {value!r}")
        low, dash, high = part.partition("-")
        if not low.isdigit() or (dash and not high.isdigit()):  # '3-' is not 'page 3'
            raise ValueError(f"Invalid page selection: {value!r}")
        start, end = int(low), int(high or low)
        if start < 1 or end < start:
            raise ValueError(f"Invalid page selection: {value!r}")
        pages.update(range(start, end + 1))
    return sorted(pages)


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


def page_records(doc_dir: Path, gt_dir: Path, company: str,
                 pages: Optional[List[int]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Paired per-page counts of a converted document, limited to the scored pages."""
    from scripts.run_scientific_benchmark import evaluate_document_scientific

    report = evaluate_document_scientific(doc_dir, gt_dir)
    records: Dict[str, List[Dict[str, Any]]] = {"cer": [], "wer": [], "der": []}
    for page in report.get("page_evaluations", []):
        if pages and int(page["page_num"]) not in pages:
            continue
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


def run_configuration(name: str, args: argparse.Namespace, git: Dict[str, Any],
                      inventory: Dict[str, Dict[str, str]],
                      run_document: Callable[..., Dict[str, Any]] = product_run.run_product) -> Dict[str, Any]:
    spec = MATRIX[name]
    out = Path(args.output) / name
    if (out / "run_record.json").exists():
        raise ValueError(f"Matrix output must be fresh: {out} already holds a run record")
    document_ids(args.pdf)  # before any record is written or any document is run
    config_path, base = product_run.base_profile(args.config)
    record: Dict[str, Any] = {
        "schema": RUN_RECORD_SCHEMA, "configuration": name, "variable": spec["variable"],
        "description": spec.get("description"), "status": spec["status"], "reason": spec.get("reason"),
        "known_confounds": spec.get("known_confounds", []), "run_id": None, "git": git,
        **product_run.code_identity(), "entry_point": product_run.ENTRY_POINT, "profile": PROFILE,
        "base_config": str(config_path), "base_config_sha256": product_run.file_sha256(config_path),
        "inputs": {"pdf": list(args.pdf), "score_pages": args.score_pages}, "config_sha256": None,
        "normalization": NORMALIZATION, "count_source": COUNT_SOURCE, "gt_sha256": None, "splits_sha256": None,
        "documents": [], "failed_documents": [], "quality_status": "NOT_EVALUATED",
        "eligible_for_quality_acceptance": False,
    }
    overrides, not_applicable = overrides_for(name, base)
    if record["status"] == "RUNNABLE" and not_applicable:
        record.update(status="NOT_APPLICABLE", reason=not_applicable)
    if record["status"] != "RUNNABLE":
        atomic_write_json(out / "run_record.json", record)
        return record

    profile = derive_profile(base, overrides)
    # F and B0 use the base file itself, so their ocr_identity matches a lock of that file.
    run_config = product_run.write_config(config_path, profile, out / "profiles.yaml") if overrides else config_path
    record.update(run_id=f"{name}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}",
                  config_sha256=config_hash(profile), config=str(run_config),
                  config_file_sha256=product_run.file_sha256(run_config), overrides=overrides, status="RUNNING")
    # Written before work starts, so an aborted run never leaves an older
    # record that `assemble` could mistake for this one.
    atomic_write_json(out / "run_record.json", record)
    try:
        _run_documents(name, args, record, out, run_config, inventory, run_document)
    except BaseException as error:
        record.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        atomic_write_json(out / "run_record.json", record)
        raise
    if name == "B0":
        devices = {document.get("device") for document in record["documents"]}
        record["b0_conditions"] = b0_conditions(git, devices.pop() if len(devices) == 1 else None, PROFILE)
    atomic_write_json(out / "run_record.json", record)
    return record


def _run_documents(name: str, args: argparse.Namespace, record: Dict[str, Any], out: Path, run_config: Path,
                   inventory: Dict[str, Dict[str, str]], run_document: Callable[..., Dict[str, Any]]) -> None:
    gt_dir = Path(args.ground_truth) if args.ground_truth else None
    if gt_dir:
        record["gt_sha256"] = file_set_sha256(sorted(gt_dir.glob("*.txt")))
    if args.splits:
        record["splits_sha256"] = hashlib.sha256(Path(args.splits).read_bytes()).hexdigest()
    pages = parse_score_pages(args.score_pages)
    records: Dict[str, List[Dict[str, Any]]] = {"cer": [], "wer": [], "der": []}
    quality_problems: List[str] = []
    for pdf in args.pdf:
        document_id = Path(pdf).stem
        run = run_document(pdf, out / "output" / document_id, config=run_config, assets=args.assets,
                           output_mode=args.output_mode)
        manifest = product_run.read_json(Path(run["output"]) / "manifest.json") or {}
        entry: Dict[str, Any] = {**run, "device": manifest.get("device"), "pages": manifest.get("selected_pages"),
                                 "total_pages": manifest.get("total_pages")}
        if entry["status"] != "COMPLETED":
            entry["error"] = f"product exit code {run['returncode']}; see {run['log']}"
            record["failed_documents"].append(document_id)
            print(f"[{name}] {document_id} FAILED: {entry['error']}", flush=True)
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
        record["quality_status_reason"] = "No document-prefixed ground-truth page in the scored pages"
    else:
        record["records_by_metric"] = records
        record["quality_status"] = "COUNTS_RECORDED"


def _collect_quality(entry: Dict[str, Any], pdf: str, gt_dir: Path, pages: Optional[List[int]],
                     inventory: Dict[str, Dict[str, str]], records: Dict[str, List[Dict[str, Any]]]) -> Optional[str]:
    """Add the document's paired records; return why it cannot be counted."""
    company, why = _verified_company(pdf, entry["document_id"], inventory, entry.get("pdf_sha256")) \
        if Path(pdf).is_file() else \
        (inventory.get(entry["document_id"], {}).get("company_id"), "")
    if not company:
        return why or "no verified company_id in the source inventory"
    try:
        if entry["status"] == "COMPLETED":
            _document_gt(gt_dir, entry["document_id"], pages)  # rejects unprefixed GT
            rows = page_records(Path(entry["output"]), gt_dir, company, pages)
        else:
            rows = missing_output_records(_document_gt(gt_dir, entry["document_id"], pages),
                                          entry["document_id"], company)
    except Exception as error:  # GT problems must not abort the other documents
        return f"ground truth evaluation failed: {type(error).__name__}: {error}"
    for metric, metric_rows in rows.items():
        records[metric].extend(metric_rows)
    return None


_COMPARABLE_FIELDS = ("profile", "source_fingerprint", "base_config_sha256", "inputs")


def _provenance(record: Dict[str, Any]) -> Tuple[Any, ...]:
    git = record.get("git") or {}
    return (git.get("commit"), git.get("uncommitted_diff_sha256"),
            *(json.dumps(record.get(field), sort_keys=True) for field in _COMPARABLE_FIELDS))


def assemble(b0_path: Optional[str], runs_dir: str, protocol_path: str) -> Dict[str, Any]:
    """Build the matrix_statistics payload; every slot keeps a visible status.
    Candidates must come from the same code, base config and inputs as F; B0
    must meet the 6.5 conditions at the protocol's locked `b0_commit`."""
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
                               reason="Different code, base config or inputs than F; more than one variable differs")
            continue
        if str(record.get("status", "")).startswith("COMPLETED") and record.get("records_by_metric"):
            runs[name] = record
    result = evaluate_matrix({"protocol": protocol, "runs": runs})
    result["slots"] = slots
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Execute configurations through ocr_pipeline.cli.main and write run records")
    run.add_argument("--pdf", nargs="+", required=True)
    run.add_argument("--score-pages", default=None,
                     help="GT pages to score, e.g. '1-5'; OCR always processes every page")
    run.add_argument("--config", default=None, help="Base configuration (default: OCR_CONFIG_PATH, then "
                                                    "config/profiles.yaml)")
    # The product default: ocr_identity includes the assets mode, so F matches a baseline lock only with png.
    run.add_argument("--assets", default="png", choices=product_run.ASSET_MODES)
    run.add_argument("--output-mode", default="compact", choices=product_run.OUTPUT_MODES)
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
    try:
        document_ids(args.pdf)
        parse_score_pages(args.score_pages)
        product_run.base_profile(args.config)
        inventory = _company_inventory(args.sources)
    except (ConfigError, ValueError) as error:
        parser.error(str(error))
    git = product_run.git_state()
    summary = {}
    for name in args.configs:
        record = run_configuration(name, args, git, inventory)
        summary[name] = {"status": record["status"], "reason": record.get("reason"),
                         "quality_status": record["quality_status"],
                         "failed_documents": record.get("failed_documents", [])}
        print(f"{name}: {summary[name]}", flush=True)
    atomic_write_json(Path(args.output) / "matrix_runs.json",
                      {"schema": RUN_RECORD_SCHEMA, "git": git, "configurations": summary})


if __name__ == "__main__":
    main()
