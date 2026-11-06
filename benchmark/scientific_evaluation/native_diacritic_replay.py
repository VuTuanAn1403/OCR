"""Measure native-copy preservation from pinned PDFs and a locked GT scope."""
from __future__ import annotations

from collections import defaultdict
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys
import unicodedata

import pymupdf

from ocr_artifacts.hashing import sha256_file
from ocr_artifacts.digest import sha256_json_compact
from ocr_pdf_io import native_text_extractor

from .cluster_statistics import company_cluster_bootstrap
from .diacritic_acceptance import evaluate_diacritic_acceptance, uncomposed_vietnamese_marks
from .evaluation_protocol import aggregate_text_metrics, text_metrics
from .scorecard_counts import _source
from .stratified_scorecard import _adequate_interval, _precision_plan, _require

SCOPE_SCHEMA = "ocr-native-diacritic-scope-v1"


def runtime_identity():
    distribution = metadata.distribution("PyMuPDF")
    files = {}
    for relative in distribution.files or []:
        name = str(relative).replace("\\", "/")
        if name.startswith("pymupdf/") and (Path(name).suffix.lower() in (".py", ".pyd", ".dll", ".dylib") or ".so" in Path(name).name):
            files[name] = sha256_file(Path(distribution.locate_file(relative)))
    _require(bool(files), "Native reader package identity is unavailable")
    return {"python": {"version": sys.version, "executable_sha256": sha256_file(Path(sys.executable))},
            "pymupdf_version": pymupdf.__version__, "pymupdf_files": files,
            "extractor_sha256": sha256_file(Path(native_text_extractor.__file__))}


def pdf_operation(operation):
    """Capture parser diagnostics before treating a native observation as complete."""
    pymupdf.TOOLS.mupdf_warnings()
    result = operation()
    return result, pymupdf.TOOLS.mupdf_warnings().splitlines()


def _confidence(inputs, records):
    plan = inputs["plan"].get("native_diacritics")
    if not isinstance(plan, dict):
        return {"status": "NOT_EVALUATED", "reason": "LOCKED_NATIVE_PRECISION_PLAN_REQUIRED"}
    family = inputs["artifact"]("statistics.multiple_comparison_family_sha256", "ocr-comparison-family-v1")
    statistics = inputs["protocol"]["statistics"]
    design = _precision_plan(plan, statistics, len(family["tests"]) + 1)
    result = company_cluster_bootstrap(records, records, metric="der", seed=statistics["seed"],
        resamples=statistics["resamples"], confidence=statistics["confidence_level"],
        min_companies=max(design["required_companies"], statistics["minimum_independent_clusters"]),
        retain_zero_denominators=True)
    ci = result["candidate_ci_unadjusted"]
    adequate = (_adequate_interval(ci, design["maximum_ci_width"])
                and len(result["counts_by_document"]) >= design["minimum_documents"]
                and result["counts"]["reference_denominator"] >= design["minimum_denominator"])
    marginal = {key: result[key] for key in ("company_count", "counts_by_company", "counts_by_document", "counts",
                                            "paired_units", "unscored_units", "seed", "resamples", "confidence_level")}
    marginal.update(error_rate=result.get("candidate"), error_rate_ci_unadjusted=ci)
    return {"status": ("PASS" if ci["upper"] <= .0001 else "FAIL") if adequate else "NOT_EVALUATED",
            "method": "company_percentile_absolute_unadjusted", "threshold_error_rate_maximum": .0001,
            "sampling_plan": design, "marginal_confidence": marginal}


def _native_inputs(inputs):
    """Verify metadata without reading held-out transcriptions or PDFs."""
    key = "data.gt_manifest_sha256"
    gt_path = inputs["artifact_path"](key)
    ground_truth = inputs["artifact"](key, "ocr-scorecard-gt-v1")
    scope = ground_truth.get("native_diacritics")
    if not isinstance(scope, dict):
        return {"status": "NOT_EVALUATED", "reason": "LOCKED_NATIVE_APPLICABILITY_SCOPE_REQUIRED"}
    protocol = inputs["protocol"]
    _require(scope.get("schema_version") == SCOPE_SCHEMA and scope.get("status") == "LOCKED"
             and isinstance(scope.get("approved_by"), str) and scope["approved_by"].strip()
             and scope.get("approved_by") == protocol["approved_by"], "Native scope requires the protocol approver and LOCKED status")
    runtime = runtime_identity()
    _require(scope.get("runtime_sha256") == sha256_json_compact(runtime), "Native runtime differs from the locked reader identity")
    approved, locked = datetime.fromisoformat(scope["locked_at"]), datetime.fromisoformat(protocol["locked_at"])
    _require(approved.utcoffset() is not None and locked.utcoffset() is not None and approved <= locked,
             "Native applicability must be locked no later than the protocol")
    planned = {row["unit_id"]: row for row in inputs["sample"]["units"] if "der" in row["metrics"]}
    applicability = {}
    for row in scope["units"]:
        unit_id = row["unit_id"]
        _require(unit_id in planned and unit_id not in applicability and type(row.get("native_applicable")) is bool
                 and isinstance(row.get("reason"), str) and row["reason"].strip(), "Native scope requires unique frozen DER units and applicability reasons")
        applicability[unit_id] = row["native_applicable"]
    _require(applicability.keys() == planned.keys(), "Native scope must cover every frozen DER unit")
    _require(all(unit["region_id"] == "page" for unit in planned.values()), "Native copy measurement requires whole physical page units")
    _require(sha256_file(gt_path) == inputs["verification"]["verified_artifact_hashes"][key], "Native GT manifest changed")
    return {"status": "DECLARED_NATIVE_METADATA_VERIFIED", "gt_path": gt_path, "ground_truth": ground_truth,
            "runtime": runtime, "planned": planned, "applicability": applicability}


def check_native_readiness(inputs):
    metadata = _native_inputs(inputs)
    if metadata["status"] != "DECLARED_NATIVE_METADATA_VERIFIED":
        return metadata
    plan = inputs["plan"].get("native_diacritics")
    if not isinstance(plan, dict):
        return {"status": "NOT_EVALUATED", "reason": "LOCKED_NATIVE_PRECISION_PLAN_REQUIRED"}
    family = inputs["artifact"]("statistics.multiple_comparison_family_sha256", "ocr-comparison-family-v1")
    design = _precision_plan(plan, inputs["protocol"]["statistics"], len(family["tests"]) + 1)
    _require(bool(metadata["planned"]) and any(metadata["applicability"].values()),
             "Native release measurement requires a nonempty native DER scope")
    return {"status": "DECLARED_NATIVE_INPUTS_READY", "runtime_sha256": sha256_json_compact(metadata["runtime"]),
            "expected_units": len(metadata["planned"]), "native_units": sum(metadata["applicability"].values()),
            "required_companies": design["required_companies"]}


def recompute_native_diacritics(inputs):
    """Applicability is pinned in the GT manifest before any held-out scores."""
    metadata = _native_inputs(inputs)
    if metadata["status"] != "DECLARED_NATIVE_METADATA_VERIFIED":
        return metadata
    key = "data.gt_manifest_sha256"
    gt_path, ground_truth, runtime, planned, applicability = (metadata[key] for key in (
        "gt_path", "ground_truth", "runtime", "planned", "applicability"))
    expected = {unit_id for unit_id, applies in applicability.items() if applies}
    by_document = defaultdict(list)
    for unit_id, unit in planned.items():
        by_document[unit["document_id"]].append((unit_id, unit))
    publications = {row["id"]: row for row in inputs["predictions"]["candidate"]["documents"]}
    companies = {row["document_id"]: row["company_id"] for row in inputs["split"]["documents"] if row["split"] == "holdout"}
    references, raw_text, nfc_text, provenance, records, details = {}, {}, {}, {}, [], []
    parser_warnings = {}
    watched = {gt_path: sha256_file(gt_path)}
    _require(watched[gt_path] == inputs["verification"]["verified_artifact_hashes"][key], "Native GT manifest changed")
    for document_id, units in by_document.items():
        publication = publications[document_id]
        pdf_path = Path(publication["pdf_path"])
        _require(sha256_file(pdf_path) == publication["pdf_sha256"], "Native source PDF changed")
        watched[pdf_path] = publication["pdf_sha256"]
        gt = ground_truth["documents"].get(document_id, {})
        _require(gt.get("pdf_sha256") == publication["pdf_sha256"], "Native GT PDF identity differs")
        pdf, opening_warnings = pdf_operation(lambda: pymupdf.open(pdf_path))
        with pdf:
            page_count, count_warnings = pdf_operation(lambda: len(pdf))
            opening_warnings.extend(count_warnings)
            _require(page_count == publication["total_pages"], "Native measurement requires physical page identity")
            extractor = native_text_extractor.NativeTextExtractor(pdf)
            for unit_id, unit in units:
                page_number = unit["page"]
                _require(unit["pdf_sha256"] == publication["pdf_sha256"] and type(page_number) is int
                         and 1 <= page_number <= len(pdf), "Native unit PDF or page differs")
                evidence = gt.get("text_pages", {}).get(str(page_number)) if applicability[unit_id] else None
                if applicability[unit_id]:
                    references[unit_id] = None
                    if evidence is not None:
                        path, raw = _source(gt_path.parent, evidence)
                        watched[path] = evidence["sha256"]
                        references[unit_id] = raw.decode("utf-8-sig")
                if opening_warnings:
                    parser_warnings[unit_id] = {"phase": "open_pdf", "messages": opening_warnings}
                    continue
                trace, warnings = pdf_operation(lambda: pdf[page_number - 1].get_texttrace())
                if warnings:
                    parser_warnings[unit_id] = {"phase": "text_objects", "messages": warnings}
                    continue
                has_text = any(span.get("chars") for span in trace)
                _require(has_text == applicability[unit_id], "Declared native applicability differs from PDF text objects")
                if not applicability[unit_id]:
                    continue
                blocks, warnings = pdf_operation(lambda: extractor.extract_blocks(page_number))
                if warnings:
                    parser_warnings[unit_id] = {"phase": "native_copy", "messages": warnings}
                    continue
                _require(all(block.text == unicodedata.normalize("NFC", block.text_raw) for block in blocks),
                         "Native output must apply only NFC to the raw copy")
                raw_text[unit_id] = "\n".join(block.text_raw for block in blocks)
                nfc_text[unit_id] = "\n".join(block.text for block in blocks)
                _require(nfc_text[unit_id] == unicodedata.normalize("NFC", raw_text[unit_id]), "Native joined copy differs from NFC")
                if references[unit_id] is not None:
                    if not uncomposed_vietnamese_marks(references[unit_id]):
                        measured = text_metrics(references[unit_id], nfc_text[unit_id])
                        details.append(measured)
                        der = measured["details"]["der"]
                        records.append({"unit_id": unit_id, "company_id": companies[document_id],
                            "document_id": document_id, "page": page_number, "region_id": "page", "status": "MEASURED",
                            "numerator": der["diacritic_errors"] + measured["diacritic_marks"]["uncomposed_prediction_marks"],
                            "denominator": der["ref_diacritics"]})
                provenance[unit_id] = {"document_id": document_id, "pdf_sha256": publication["pdf_sha256"], "page": page_number,
                    "reference_sha256": evidence["sha256"] if evidence else None,
                    "raw_text_sha256": hashlib.sha256(raw_text[unit_id].encode()).hexdigest(),
                    "nfc_text_sha256": hashlib.sha256(nfc_text[unit_id].encode()).hexdigest(),
                    "blocks": [{"producer_ref": block.producer_ref, "bbox": block.bbox,
                                "text_raw": block.text_raw, "text_nfc": block.text} for block in blocks]}
    raw_report = evaluate_diacritic_acceptance(expected, references, raw_text)
    nfc_report = evaluate_diacritic_acceptance(expected, references, nfc_text)
    confidence = _confidence(inputs, records) if nfc_report["status"] == "PASS" else {
        "status": "NOT_EVALUATED", "reason": "COMPLETE_PASSING_NATIVE_POINT_MEASUREMENT_REQUIRED"}
    status = ("FAIL" if "FAIL" in (nfc_report["status"], confidence["status"]) else
              "PASS" if nfc_report["status"] == confidence["status"] == "PASS" else "NOT_EVALUATED")
    if parser_warnings and status != "FAIL":
        status = "NOT_EVALUATED"
    _require(all(sha256_file(path) == digest for path, digest in watched.items()), "Native evidence changed during measurement")
    _require(runtime_identity() == runtime, "Native reader changed during measurement")
    metrics = aggregate_text_metrics(details)
    return {"status": status, "native_raw": raw_report, "native_nfc": nfc_report, "native_confidence": confidence,
            "native_text_metrics_raw": deepcopy(metrics), "native_text_metrics_nfc": metrics,
            "text_metrics_normalization": "visible_strict_v1_NFC", "source_units": provenance,
            "excluded_scan_unit_ids": sorted(set(planned) - expected - parser_warnings.keys()), "gt_sha256": watched[gt_path],
            "parser_warnings": parser_warnings,
            "unverified_applicability_unit_ids": sorted(parser_warnings),
            "runtime": runtime, "runtime_sha256": sha256_json_compact(runtime),
            "quality_acceptance": "NOT_EVALUATED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Record native-copy reader identity without scoring or OCR", allow_abbrev=False)
    parser.add_argument("--runtime-report", type=Path, required=True)
    args = parser.parse_args(argv)
    path = args.runtime_report.resolve()
    if path.exists() or any((parent / marker).is_file() for parent in path.parents
                            for marker in ("COMPLETED.json", "batch_input_manifest.json")):
        parser.error("Use a new native runtime report outside publications")
    try:
        runtime = runtime_identity()
        report = {"schema_version": "ocr-native-copy-runtime-v1", "status": "SOURCE_IDENTITY_ONLY",
                  "runtime": runtime, "runtime_sha256": sha256_json_compact(runtime), "quality_acceptance": "NOT_EVALUATED"}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("Native reader identity recorded; quality is NOT_EVALUATED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
