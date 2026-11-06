"""Project formula diagnostics to PDF counts and paired company statistics."""
from __future__ import annotations

import argparse
from collections import defaultdict
import math
from pathlib import Path

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.hashing import sha256_file
from src.ocr.collect.catalog import read_sources

from . import formula_alignment, formula_cdm, formula_content
from .cluster_statistics import company_cluster_bootstrap

SCHEMA = "ocr-formula-scorecard-v1"
METRICS = ("formula_detection_recall", "formula_detection_errors_per_gt", "formula_text_cer",
           "formula_text_exact", "formula_cdm_mean", "formula_critical_error_rate")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _index(rows, field):
    result = {row[field]: row for row in rows}
    _require(len(result) == len(rows), f"Duplicate formula {field}")
    return result


def _read(path, schema):
    value, digest = formula_content._read(path)
    _require(isinstance(value, dict) and value.get("schema_version") == schema, f"Unexpected schema in {path}")
    return value, digest


def _cdm_scores(directory, pairs, pairs_hash, *, verified_pair_path=None):
    if verified_pair_path is not None:
        _require(sha256_file(verified_pair_path) == pairs_hash, "Formula pairs changed before CDM recomputation")
        return formula_cdm.verify_comparison(directory, verified_pair_path)
    artifact, digest = _read(directory / "comparison.json", formula_cdm.SCHEMA)
    source, input_hash = formula_content._read(directory / "input.json")
    runtime_hash = sha256_file(directory / "runtime.json")
    _require(source.get("sha256") == pairs_hash and artifact.get("method") in (formula_cdm.METHOD, formula_cdm.LEGACY_METHOD)
             and artifact.get("runtime_sha256") == runtime_hash, "CDM input, method or runtime identity differs")
    rows = _index(artifact["details"], "id")
    _require(rows.keys() == pairs.keys() and artifact["pairs"] == len(pairs), "CDM report must account for every pair")
    scores = {}
    for key, row in rows.items():
        pair = pairs[key]
        if row["status"] == "NOT_EVALUATED":
            _require(row["cdm_f1"] is None, "Unscored CDM row cannot supply a score")
            continue
        _require(row["status"] == "MEASURED" and pair.get("reference_format", "LATEX") == "LATEX"
                 and (pair["prediction"] is None or pair.get("prediction_format", "LATEX") == "LATEX"),
                 "Invalid measured CDM representation or status")
        tp, fp, fn, ref, pred = (row[field] for field in ("tp", "fp", "fn", "reference_characters", "prediction_characters"))
        _require(all(type(value) is int and value >= 0 for value in (tp, fn, ref)) and 0 < ref and tp + fn == ref,
                 "CDM reference character counts differ")
        if pred is None:
            _require(pair["prediction"] is not None and tp == 0 and fp is None
                     and row["reason"] == "PREDICTION_RENDER_FAILED" and row["prediction_error_kind"] == "CONTENT_RENDER_FAILURE",
                     "Missing CDM prediction character count requires a declared content render failure")
            score = 0.0
        else:
            _require(type(pred) is int and type(fp) is int and fp >= 0 and tp + fp == pred
                     and (pred > 0 or pair["prediction"] is None and row["reason"] == "MISSING_PREDICTION")
                     and (pair["prediction"] is not None or pred == 0), "CDM prediction character counts differ")
            score = 2 * tp / (ref + pred)
        _require(type(row["cdm_f1"]) in (int, float) and row["cdm_f1"] == score, "CDM score differs from raw counts")
        scores[key] = score
    return scores, {"comparison_sha256": digest, "input_sha256": input_hash, "runtime_sha256": runtime_hash}


def _load_run(alignment_path, pairs_path, critical_path, cdm_dir, sample, sample_hash):
    alignment, digest = _read(alignment_path, formula_alignment.REPORT_SCHEMA)
    documents = _index(alignment["documents"], "document_id")
    _require(documents and type(alignment["iou_threshold"]) in (int, float) and 0 < alignment["iou_threshold"] <= 1,
             "Missing formula document universe or invalid localization threshold")
    pages = {key: _index(doc["pages"], "page") for key, doc in documents.items()}
    if "holdout_sample_sha256" in alignment:
        _require(sample_hash is not None and alignment["holdout_sample_sha256"] == sample_hash,
                 "Holdout alignment requires its exact sample file")
        planned = _index(sample["documents"], "document_id")
        _require(pages.keys() == planned.keys() and all(pages[key].keys() == set(planned[key]["pages"])
                 and all(row["annotated"] is True for row in pages[key].values()) for key in pages),
                 "Holdout alignment must cover every sampled page exactly")
    else:
        for key, doc in documents.items():
            _require(pages[key].keys() == set(range(1, doc["total_pages"] + 1)), "Formula alignment must cover every physical page")
    pairs, content, cdm = {}, {}, {}
    evidence = {"alignment_sha256": digest, "annotation_sha256": alignment["annotation_sha256"],
                "pairs_sha256": None, "critical_review_sha256": None, "cdm": None}
    if "holdout_sample_sha256" in alignment:
        evidence["holdout_sample_sha256"] = sample_hash
    if alignment["cdm_pair_count"]:
        _require(pairs_path is not None, "Alignment contains references and requires its exact pair file")
        report = formula_content.evaluate(pairs_path, alignment_path=alignment_path, critical_review_path=critical_path)
        pair_rows, pairs_hash = formula_content._read(pairs_path)
        _require(report["alignment_sha256"] == digest and report["pairs_sha256"] == pairs_hash,
                 "Formula inputs changed during evaluation")
        pairs = _index(pair_rows, "id")
        content = _index(report["details"], "id")
        evidence.update(pairs_sha256=pairs_hash, critical_review_sha256=report["critical_review_sha256"])
        if cdm_dir is not None:
            cdm, evidence["cdm"] = _cdm_scores(cdm_dir, pairs, pairs_hash,
                verified_pair_path=pairs_path if "holdout_sample_sha256" in alignment else None)
    else:
        _require(pairs_path is None and critical_path is None and cdm_dir is None and alignment["cdm_pairs_sha256"] is None,
                 "Pair evidence supplied for an empty formula pair universe")
        _require(not any(page.get("references") for doc in documents.values() for page in doc["pages"]),
                 "Formula references exist outside the declared pair universe")
    return {"documents": documents, "pages": pages, "pairs": pairs, "content": content, "cdm": cdm,
            "iou_threshold": alignment["iou_threshold"], "localization_scope": alignment["localization_scope"],
            "evidence": evidence}


def _localization(page):
    _require(type(page["annotated"]) is bool, "Formula annotation state must be explicit")
    if not page["annotated"]:
        _require(page["counts"] is None and not page.get("references"), "Unannotated page cannot contribute counts")
        return None
    references = _index(page["references"], "id")
    matched = _index(page["matches"], "reference_id")
    missed = page["missing"]
    _require(len(set(missed)) == len(missed) and not (set(missed) & matched.keys())
             and matched.keys() | set(missed) == references.keys(), "Formula matching must partition reference IDs")
    candidates = _index(page["candidates"], "id")
    visible = {key for key, row in candidates.items() if row["visibility"] != "suppressed"}
    predictions = ([row["prediction_id"] for row in matched.values()] + page["spurious"]
                   + [row["prediction_id"] for row in (*page["duplicates"], *page["ignored"])])
    _require(len(predictions) == len(visible) == page["prediction_count"] and set(predictions) == visible,
             "Formula matching must partition visible prediction IDs")
    counts = {"tp": len(matched), "fp": len(page["spurious"]) + len(page["duplicates"]), "fn": len(missed)}
    _require(page["counts"] == counts, "Formula localization counts differ from dispositions")
    return counts


def _plan(candidate, sources, sample):
    catalog = _index(sources, "document_id")
    wanted = _index(sample["documents"], "document_id") if sample is not None else None
    documents = candidate["documents"]
    keys = wanted.keys() if wanted is not None else documents.keys()
    _require(keys and keys <= documents.keys() and keys <= catalog.keys(), "Sample documents missing from alignment or source catalog")
    plan = {}
    for doc_id in keys:
        doc, row = documents[doc_id], catalog[doc_id]
        _require(row["status"] == "OK" and row["sha256"] == doc["pdf_sha256"] and int(row["pages"]) == doc["total_pages"],
                 f"Source catalog identity differs for {doc_id}")
        if wanted is None:
            pages = list(range(1, doc["total_pages"] + 1))
        else:
            declared = wanted[doc_id]
            pages = declared["pages"]
            _require(declared["pdf_sha256"] == doc["pdf_sha256"] and isinstance(pages, list) and pages
                     and all(type(p) is int and 1 <= p <= doc["total_pages"] for p in pages)
                     and len(set(pages)) == len(pages), f"Invalid formula sample scope for {doc_id}")
        for page in sorted(pages):
            plan[doc_id, page] = row["company_id"]
    return plan


def _reference_signature(page):
    fields = ("id", "bbox", "format", "content_raw", "placement", "equation_label", "pair_id")
    references = sorted((tuple(ref[field] for field in fields) for ref in page.get("references", [])), key=lambda row: row[0])
    ignores = sorted(page.get("ignore_regions", []), key=lambda row: row["id"])
    return page["annotated"], page["coordinate_space"], references, ignores


def _paired_pages(baseline, candidate, plan):
    _require((baseline["evidence"]["annotation_sha256"], baseline["iou_threshold"], baseline["localization_scope"]) ==
             (candidate["evidence"]["annotation_sha256"], candidate["iou_threshold"], candidate["localization_scope"]),
             "Paired formula runs require identical annotations and localization policy")
    _require(baseline["evidence"].get("holdout_sample_sha256") == candidate["evidence"].get("holdout_sample_sha256"),
             "Paired formula runs require the same holdout replay scope")
    documents = {doc_id for doc_id, _ in plan}
    for doc_id in documents:
        _require(doc_id in baseline["documents"], "Baseline lacks a sampled document")
        left, right = (run["documents"][doc_id] for run in (baseline, candidate))
        _require((left["pdf_sha256"], left["total_pages"]) == (right["pdf_sha256"], right["total_pages"])
                 and left["completion_sha256"] != right["completion_sha256"],
                 "Paired formula runs require the same PDF and distinct publications")
    for doc_id, page in plan:
        left, right = (run["pages"][doc_id][page] for run in (baseline, candidate))
        _require(_reference_signature(left) == _reference_signature(right), "Paired formula reference pages differ")


def _project(run, plan):
    records = defaultdict(list)
    localization = {}

    def emit(metric, key, numerator=None, denominator=None, *, region="page", placement=None):
        document, page = key
        records[metric].append({"company_id": plan[key], "document_id": document, "page": page, "region_id": region,
                                "placement": placement, "status": "MEASURED" if denominator is not None else "NOT_EVALUATED",
                                "numerator": numerator, "denominator": denominator})

    for key in plan:
        doc_id, number = key
        page = run["pages"][doc_id][number]
        counts = _localization(page)
        localization[key] = counts
        if counts is None:
            for metric in METRICS:
                emit(metric, key)
            continue
        tp, fp, fn = (counts[key] for key in ("tp", "fp", "fn"))
        emit("formula_detection_recall", key, tp, tp + fn)
        emit("formula_detection_errors_per_gt", key, fp + fn, tp + fn)
        matched = {row["reference_id"] for row in page["matches"]}
        for ref in page["references"]:
            pair_id, placement = ref["pair_id"], ref["placement"]
            _require(placement in formula_alignment.PLACEMENTS and pair_id in run["pairs"], "Invalid formula placement or pair identity")
            row = run["content"][pair_id]
            kwargs = {"region": pair_id, "placement": placement}
            if ref["format"] == "TEXT":
                text = row["text"]
                if text["status"] == "MEASURED":
                    text_counts = text["counts"]
                    errors = sum(text_counts[name] for name in ("substitutions", "deletions", "insertions"))
                    emit("formula_text_cer", key, errors, text_counts["reference_codepoints"], **kwargs)
                    emit("formula_text_exact", key, int(text["exact"]), 1, **kwargs)
                else:
                    emit("formula_text_cer", key, **kwargs)
                    emit("formula_text_exact", key, **kwargs)
            elif ref["format"] == "LATEX":
                score = run["cdm"].get(pair_id)
                emit("formula_cdm_mean", key, score, 1 if score is not None else None, **kwargs)
            critical = row["critical"]
            complete = critical.keys() == set(formula_content.CRITICAL_CATEGORIES) and all(
                item["status"] != "UNRESOLVED" for item in critical.values())
            errors = int(any(item["status"] == "ERROR" for item in critical.values())) if complete else None
            emit("formula_critical_error_rate", key, errors, 1 if complete else None, **kwargs)
            emit("formula_detection_recall_by_placement", key, int(ref["id"] in matched), 1, **kwargs)
    return records, localization


def _group(rows):
    measured = [row for row in rows if row["status"] == "MEASURED"]
    numerator = sum(row["numerator"] for row in measured) if measured else None
    denominator = sum(row["denominator"] for row in measured) if measured else None
    ratio = numerator / denominator if denominator and len(measured) == len(rows) else None
    return {"planned_units": len(rows), "measured_units": len(measured), "unscored_units": len(rows) - len(measured),
            "observed_numerator": numerator, "observed_denominator": denominator, "micro": ratio,
            "status": "MEASURED" if ratio is not None else "NOT_EVALUATED"}


def _summarize(rows):
    docs, companies = defaultdict(list), defaultdict(list)
    for row in rows:
        docs[row["document_id"]].append(row)
        companies[row["company_id"]].append(row)
    total = _group(rows)
    doc_summary = {key: _group(value) for key, value in docs.items()}
    measured = [value["micro"] for value in doc_summary.values() if value["micro"] is not None]
    return {**total, "macro_by_document": sum(measured) / len(measured) if measured and total["micro"] is not None else None,
            "scored_documents": len(measured), "by_document": doc_summary,
            "by_company": {key: _group(value) for key, value in companies.items() if key != "unknown"},
            "unknown_company_units": len(companies.get("unknown", []))}


def _rows(records, metric, stratum):
    if stratum == "overall":
        return records.get(metric, [])
    key = "formula_detection_recall_by_placement" if metric == "formula_detection_recall" else metric
    return [row for row in records.get(key, []) if row["placement"] in (None, stratum)] + (
        [row for row in records.get(metric, []) if row["status"] == "NOT_EVALUATED" and row["region_id"] == "page"]
        if key != metric else [])


def _paired(left, right, metric, settings):
    for reason, condition in (("INCOMPLETE_OR_EMPTY_PAIRED_SAMPLE", not left or not right or any(
            row["status"] != "MEASURED" for row in (*left, *right))),
                              ("UNKNOWN_COMPANY_ID", any(row["company_id"] == "unknown" for row in (*left, *right)))):
        if condition:
            return {"status": "NOT_EVALUATED", "reason": reason}
    return company_cluster_bootstrap(left, right, metric=metric, retain_zero_denominators=True, **settings)


def _detection_summary(pages):
    known = [row for row in pages.values() if row is not None]
    counts = {key: sum(row[key] for row in known) for key in ("tp", "fp", "fn")} if known else None
    precision = recall = f1 = None
    if counts is not None and len(known) == len(pages):
        tp, fp, fn = (counts[key] for key in ("tp", "fp", "fn"))
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None
    return {"pages": len(pages), "annotated_pages": len(known), "observed_counts": counts,
            "precision": precision, "recall": recall, "f1": f1}


def _run_summary(run, localization, plan):
    by_doc, by_company = defaultdict(dict), defaultdict(dict)
    coverage = {fmt: {"reference_pairs": 0, "missing_predictions": 0, "comparable_pairs": 0}
                for fmt in formula_content.FORMATS}
    for key, counts in localization.items():
        doc_id, number = key
        by_doc[doc_id][key] = counts
        if plan[key] != "unknown":
            by_company[plan[key]][key] = counts
        for ref in run["pages"][doc_id][number].get("references", []):
            pair_id, fmt = ref["pair_id"], ref["format"]
            row = coverage[fmt]
            row["reference_pairs"] += 1
            row["missing_predictions"] += int(run["pairs"][pair_id]["prediction"] is None)
            if fmt == "TEXT":
                row["comparable_pairs"] += int(run["content"][pair_id]["text"]["status"] == "MEASURED")
            elif fmt == "LATEX":
                row["comparable_pairs"] += int(pair_id in run["cdm"])
    return {"evidence": run["evidence"], "localization": _detection_summary(localization),
            "localization_by_document": {key: _detection_summary(value) for key, value in by_doc.items()},
            "localization_by_company": {key: _detection_summary(value) for key, value in by_company.items()},
            "content_coverage_by_reference_format": coverage}


def evaluate(args):
    _require(type(args.seed) is int and args.seed >= 0 and type(args.resamples) is int and args.resamples >= 100
             and math.isfinite(args.confidence) and 0 < args.confidence < 1 and args.min_companies >= 2,
             "Invalid paired bootstrap settings")
    source_hash = sha256_file(args.sources)
    sources = read_sources(args.sources)
    _require(sha256_file(args.sources) == source_hash, "Source catalog changed while reading")
    sample, sample_hash = _read(args.sample, "ocr-formula-scorecard-sample-v1") if args.sample else (None, None)
    candidate = _load_run(args.candidate_alignment, args.candidate_pairs, args.candidate_critical, args.candidate_cdm,
                          sample, sample_hash)
    baseline = None
    if args.baseline_alignment is not None:
        baseline = _load_run(args.baseline_alignment, args.baseline_pairs, args.baseline_critical, args.baseline_cdm,
                             sample, sample_hash)
    else:
        _require(not any((args.baseline_pairs, args.baseline_critical, args.baseline_cdm)), "Baseline evidence needs an alignment")
    plan = _plan(candidate, sources, sample)
    right, right_detection = _project(candidate, plan)
    left, left_detection = None, None
    if baseline is not None:
        _paired_pages(baseline, candidate, plan)
        left, left_detection = _project(baseline, plan)
    settings = {name: getattr(args, name) for name in ("seed", "resamples", "confidence", "min_companies")}
    comparisons = {}
    for metric in METRICS:
        strata = ("overall",) if metric == "formula_detection_errors_per_gt" else ("overall", *formula_alignment.PLACEMENTS)
        for stratum in strata:
            new = _rows(right, metric, stratum)
            old = _rows(left, metric, stratum) if left is not None else None
            comparisons[f"{metric}:{stratum}"] = {"candidate": _summarize(new),
                "baseline": _summarize(old) if old is not None else None,
                "paired_bootstrap": _paired(old, new, metric, settings) if old is not None else None}
    return {"schema_version": SCHEMA, "acceptance_status": "NOT_EVALUATED", "eligible_for_quality_acceptance": False,
            "sources_sha256": source_hash, "sample_sha256": sample_hash, "settings": settings,
            "planned_pages": len(plan), "unknown_company_documents": sorted({key[0] for key, owner in plan.items() if owner == "unknown"}),
            "candidate": _run_summary(candidate, right_detection, plan),
            "baseline": _run_summary(baseline, left_detection, plan) if baseline else None,
            "comparisons": comparisons}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("sources", "candidate-alignment", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("sample", "candidate-pairs", "candidate-critical", "candidate-cdm", "baseline-alignment",
                 "baseline-pairs", "baseline-critical", "baseline-cdm"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--confidence", type=float, default=.95)
    parser.add_argument("--min-companies", type=int, default=2)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists() or any((parent / marker).is_file() for parent in output.parents
                              for marker in ("COMPLETED.json", "batch_input_manifest.json")):
        parser.error("Use a new output outside canonical publications")
    try:
        report = evaluate(args)
        atomic_write_json(output, report)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        parser.error(str(error))
    print(f"Formula scorecard: {report['planned_pages']} pages, acceptance {report['acceptance_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
