"""Generate scorecard counts from locked GT and existing canonical CUDA artifacts."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import yaml

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file
from ocr_pipeline.analysis_run import verify_extraction_source
from ocr_pipeline.completion import verify_completed
from ocr_pipeline.document import valid_ocr

from . import keyword_acceptance
from .cluster_statistics import ERROR_RATIOS
from .evaluation_protocol import aggregate_text_metrics, text_metrics
from .formula_scorecard import METRICS as FORMULA_METRICS
from .markdown_evaluator import parse_markdown_artifacts
from .stratified_scorecard import _load, _require, verified_inputs
from .structured_scoreboard import evaluate_structure

STRUCTURE_METRICS = ("teds_content", "teds_structure", "numeric_cell_exact", "reading_order",
                     "layout_recall", "layout_errors_per_gt")


def _source(root: Path, record: dict) -> tuple[Path, bytes]:
    relative = Path(record["path"])
    path = (root / relative).resolve()
    _require(not relative.is_absolute() and path.is_relative_to(root), "Evidence path escapes its manifest directory")
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == record["sha256"], f"Frozen evidence changed: {path}")
    return path, raw


def _count(unit_id, status, numerator, denominator, **evidence):
    return {"unit_id": unit_id, "status": status, "numerator": numerator, "denominator": denominator,
            "evidence": evidence}


def _text_counts(unit_id, metric, details, reference_sha256):
    evidence = {}
    if metric == "der":
        marks = details["diacritic_marks"]
        if marks["uncomposed_reference_marks"]:
            return {"unit_id": unit_id, "status": "NOT_EVALUATED", "reason": "REFERENCE_MARKS_REQUIRE_ADJUDICATION",
                    "evidence": {"reference_sha256": reference_sha256, "diacritic_gate": marks}}
        evidence["diacritic_gate"] = marks
        if "dser_strict" in details["details"]:
            evidence["dser_strict"] = details["details"]["dser_strict"]
    counts = aggregate_text_metrics([details])["counts"][metric]
    return _count(unit_id, details["status"], counts["errors"], counts["reference_length"],
                  reference_sha256=reference_sha256, detail=details["details"][metric], **evidence)


def _structure_count(unit_id, metric, row, reference_sha256):
    status = "MISSING_OUTPUT" if row["prediction_status"] == "MISSING_OUTPUT" else "MEASURED"
    if metric.startswith("teds") and "tables" in row:
        tables = row["tables"]
        field = "teds_sum" if metric == "teds_content" else "teds_structure_sum"
        return _count(unit_id, status, tables[field], tables["gt_table_count"],
                      reference_sha256=reference_sha256, missing=tables["missing_table_count"],
                      spurious=tables["spurious_table_count"])
    if metric == "numeric_cell_exact" and "numeric_cells" in row:
        numeric = row["numeric_cells"]
        return _count(unit_id, status, numeric["location_tp"], numeric["location_tp"] + numeric["location_fn"],
                      reference_sha256=reference_sha256, missing=numeric["location_fn"], extra=numeric["location_fp"])
    if metric == "reading_order" and "reading_order" in row:
        order = row["reading_order"]
        if order["status"] == "NOT_EVALUATED":
            return {"unit_id": unit_id, "status": "NOT_EVALUATED", "reason": order["reason"]}
        alignment = {"alignment_sha256": order["alignment_sha256"]} if "alignment_sha256" in order else {}
        return _count(unit_id, status, order["correct_pairs"], order["gt_pairs"],
                      reference_sha256=reference_sha256, missing_nodes=order["missing_nodes"],
                      duplicate_predictions=order["duplicate_predictions"], **alignment)
    if metric in ("layout_recall", "layout_errors_per_gt") and "layout" in row:
        layout = row["layout"]
        tp, fp, fn = (layout[key] for key in ("tp", "fp", "fn"))
        return _count(unit_id, status, tp if metric == "layout_recall" else fp + fn, tp + fn,
                      reference_sha256=reference_sha256, tp=tp, fp=fp, fn=fn,
                      reference_categories=layout["reference_categories"])
    return None


def _keyword_counts(directory, publication, evidence, gt_root, alignment_entry):
    if evidence is None or alignment_entry is None:
        return {}
    alignment_root, alignment_record = alignment_entry
    _, raw_gt = _source(gt_root, evidence)
    ground_truth = json.loads(raw_gt.decode("utf-8-sig"))
    _require(ground_truth.get("intended_partition", "holdout") == "holdout",
             "Development pilot annotations cannot be used for the holdout scorecard")
    _, raw_alignment = _source(alignment_root, alignment_record)
    alignment = json.loads(raw_alignment.decode("utf-8-sig"))
    _require(alignment.get("ground_truth_sha256") == evidence["sha256"], "Keyword alignment GT checksum mismatch")
    dictionary = directory.parent / "keyword_dictionary.snapshot.json"
    observed = keyword_acceptance.inventory(directory, json.loads(dictionary.read_text(encoding="utf-8")))
    _require(observed["identity"]["pdf_sha256"] == publication["pdf_sha256"]
             and observed["identity"]["result_md_sha256"] == publication["result_md_sha256"],
             "Keyword publication differs from the canonical prediction")
    report = keyword_acceptance.evaluate(observed, ground_truth, alignment)
    if report["status"] == "NOT_EVALUATED":
        return {}
    matched = Counter(row["reference"]["unit_id"] for row in report["correct"])
    missing = Counter(row["unit_id"] for row in report["missing"])
    extra = Counter(row["unit_id"] for row in report["extra"])
    return {(loc["physical_page"], key): {"numerator": matched[key], "denominator": matched[key] + missing[key],
                                         "missing": missing[key], "extra": extra[key]}
            for key, loc in report["unit_locations"].items()}


def _document_counts(units, publication, gt, gt_root, alignment_entry, policy, *, reading_order_alignment=None):
    directory = Path(publication["source_dir"]).resolve()
    _require(directory.name == publication["id"] and gt["pdf_sha256"] == publication["pdf_sha256"],
             "Canonical document or GT PDF identity mismatch")
    proof = verify_extraction_source(directory)
    fields = ("ocr_identity", "ocr_receipt_sha256", "completion_sha256", "result_md_sha256", "total_pages")
    _require(all(proof[field] == publication[field] for field in fields), "Canonical prediction changed since inventory")
    metrics = {metric for unit in units for metric in unit["metrics"]}
    pages, structure, keywords = {}, {}, {}
    if metrics.intersection(ERROR_RATIOS):
        parsed = parse_markdown_artifacts(directory / "result.md", policy=policy)
        _require(not parsed["duplicate_page_markers"] and
                 all(1 <= page <= publication["total_pages"] for page in parsed["pages_text"]) and
                 (parsed["pages_text"] or not parsed["raw_text"].strip()),
                 "Final Markdown requires unambiguous page markers")
        pages = parsed["pages_text"]
    structure_gt = gt.get("structure")
    options = {}
    if reading_order_alignment is not None:
        _require(structure_gt is not None and "reading_order" in metrics,
                 "Reading order alignment requires structured GT and a reading order sample unit")
        alignment_root, alignment_record = reading_order_alignment
        path, _ = _source(alignment_root, alignment_record)
        options = {"reading_order_alignment": path, "expected_alignment_sha256": alignment_record["sha256"],
                   "alignment_partition": "holdout"}
    if structure_gt and metrics.intersection(STRUCTURE_METRICS):
        path, raw = _source(gt_root, structure_gt)
        if metrics.intersection(("layout_recall", "layout_errors_per_gt")):
            _require(json.loads(raw.decode("utf-8-sig")).get("intended_partition") == "holdout",
                     "Layout scorecard requires structured GT declared for holdout")
        report = evaluate_structure(directory, path, expected_pdf_sha256=publication["pdf_sha256"],
                                    include_layout_ap=False, **options)
        _require(report["ground_truth_sha256"] == structure_gt["sha256"], "Structure GT changed during evaluation")
        structure = {row["page"]: row for row in report["pages"]}
    if "keyword_recall" in metrics:
        keywords = _keyword_counts(directory, publication, gt.get("keywords"), gt_root, alignment_entry)
    for unit in units:
        key, page, region = (unit[field] for field in ("unit_id", "page", "region_id"))
        text_ref = gt.get("text_pages", {}).get(str(page))
        details = None
        if text_ref and any(metric in ERROR_RATIOS for metric in unit["metrics"]):
            _, raw = _source(gt_root, text_ref)
            details = text_metrics(raw.decode("utf-8-sig"), pages.get(page, ""), missing=page not in pages, policy=policy)
        for metric in unit["metrics"]:
            if metric in FORMULA_METRICS:
                continue
            row = None
            if metric == "keyword_recall":
                keyword = keywords.get((page, region))
                if keyword is not None:
                    row = _count(key, "MEASURED", **keyword, reference_sha256=gt["keywords"]["sha256"],
                                 alignment_sha256=alignment_entry[1]["sha256"])
            else:
                _require(region == "page", f"{metric} requires whole-page sample units with region_id=page")
                if metric in ERROR_RATIOS and details is not None:
                    row = _text_counts(key, metric, details, text_ref["sha256"])
                elif metric in STRUCTURE_METRICS and page in structure:
                    row = _structure_count(key, metric, structure[page], structure_gt["sha256"])
            yield metric, row or {"unit_id": key, "status": "NOT_EVALUATED", "reason": "NO_SCORABLE_REFERENCE"}
    _require(valid_ocr(directory, publication["ocr_identity"]) and verify_completed(directory)
             and sha256_file(directory / "ocr_receipt.json") == publication["ocr_receipt_sha256"]
             and sha256_file(directory / "COMPLETED.json") == publication["completion_sha256"],
             "Canonical prediction changed while generating counts")


def export_counts(args):
    return count_verified_predictions(verified_inputs(args), args.side, args.keyword_alignments,
                                      reading_order_alignments=getattr(args, "reading_order_alignments", None),
                                      output=args.output)


def _alignments(path, schema, inputs, side_name):
    if path is None:
        return {}
    index = _load(path, schema)
    _require(index["prediction_inventory_sha256"] == inputs["prediction_hash"] and index["side"] == side_name,
             "Alignments belong to a different inventory or side")
    root = path.resolve().parent
    return {key: (root, row) for key, row in index["documents"].items()}


def count_verified_predictions(inputs, side_name, keyword_alignments=None, *, reading_order_alignments=None,
                               formula_counts=None, output=None):
    gt_key = "data.gt_manifest_sha256"
    gt_path = inputs["artifact_path"](gt_key)
    gt = inputs["artifact"](gt_key, "ocr-scorecard-gt-v1")
    alignments = _alignments(keyword_alignments, "ocr-keyword-alignment-index-v1", inputs, side_name)
    order_alignments = _alignments(reading_order_alignments, "ocr-reading-order-alignment-index-v1", inputs, side_name)
    units = defaultdict(list)
    for unit in inputs["sample"]["units"]:
        units[unit["document_id"]].append(unit)
    side = inputs["predictions"][side_name]
    publications = {row["id"]: row for row in side["documents"]}
    _require((alignments.keys() | order_alignments.keys()) <= units.keys(),
             "Alignment includes a document outside the sample")
    _require(output is None or all(not output.resolve().is_relative_to(Path(row["source_dir"]).resolve())
                 for name in ("baseline", "candidate") for row in inputs["predictions"][name]["documents"]),
             "Counts must be written outside the canonical document directories")
    records = defaultdict(list)
    policy = inputs["protocol"]["evaluation"]["normalization"]
    for document_id, document_units in units.items():
        evidence = gt["documents"].get(document_id, {"pdf_sha256": publications[document_id]["pdf_sha256"]})
        for metric, row in _document_counts(document_units, publications[document_id], evidence,
                                            gt_path.parent, alignments.get(document_id), policy,
                                            reading_order_alignment=order_alignments.get(document_id)):
            records[metric].append(row)
    for metric in FORMULA_METRICS:
        planned = {unit["unit_id"] for unit in inputs["sample"]["units"] if metric in unit["metrics"]}
        if formula_counts is None:
            rows = [{"unit_id": key, "status": "NOT_EVALUATED", "reason": "SOURCE_FORMULA_COUNTS_REQUIRED"}
                    for key in sorted(planned)]
        else:
            rows = formula_counts["records_by_metric"][metric]
            _require({row["unit_id"] for row in rows} == planned and len(rows) == len(planned),
                     "Formula counts must cover the frozen metric units exactly")
        if planned:
            records[metric].extend(rows)
    return {
        "schema_version": "ocr-paired-counts-v1", "producer": "canonical-scorecard-counts-v1",
        "run_id": f"{side_name}:{sha256_json_compact(side)}", "normalization": policy,
        "protocol_sha256": inputs["verification"]["protocol_sha256"],
        "sample_sha256": inputs["plan"]["sample_sha256"], "prediction_inventory_sha256": inputs["prediction_hash"],
        "prediction_manifest_sha256": sha256_json_compact(side),
        "gt_sha256": inputs["verification"]["verified_artifact_hashes"][gt_key],
        "records_by_metric": dict(records), "acceptance_status": "NOT_EVALUATED",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("protocol", "artifact-index", "sample", "prediction-inventory", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    parser.add_argument("--side", required=True, choices=("baseline", "candidate"))
    parser.add_argument("--keyword-alignments", type=Path)
    parser.add_argument("--reading-order-alignments", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Counts must use a new output path")
    try:
        result = export_counts(args)
    except (OSError, KeyError, TypeError, ValueError, OverflowError, yaml.YAMLError) as error:
        parser.error(str(error))
    atomic_write_json(args.output, result)
    return int(not result["records_by_metric"] or any(row["status"] == "NOT_EVALUATED"
               for records in result["records_by_metric"].values() for row in records))


if __name__ == "__main__":
    raise SystemExit(main())
