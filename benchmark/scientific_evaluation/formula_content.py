"""Measure literal TEXT formulas and account for declared critical reviews."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ocr_artifacts.atomic_io import atomic_write_json

from .ocr_metric import levenshtein_align, normalize_text_policy

METHOD = "formula-text-visible-strict-v1"
REPORT_SCHEMA = "ocr-formula-content-v1"
REVIEW_SCHEMA = "ocr-formula-critical-review-v1"
FORMATS = ("TEXT", "LATEX", "MATHML")
CRITICAL_CATEGORIES = ("SIGN", "RELATION", "FRACTION", "INDEX_OR_EXPONENT", "NUMBER", "UNIT", "EQUATION_LABEL")
REVIEW_STATUSES = ("MATCH", "ERROR", "NOT_APPLICABLE", "UNRESOLVED")
MAX_CODEPOINTS = 2048
MAX_INPUT_BYTES = 32 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _read(path):
    def unique_fields(items):
        value = dict(items)
        _require(len(value) == len(items), f"Duplicate JSON keys in {path}")
        return value

    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    _require(len(raw) <= MAX_INPUT_BYTES, f"Formula input exceeds the byte limit: {path}")
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_fields), hashlib.sha256(raw).hexdigest()


def _index(rows, name):
    _require(isinstance(rows, list), f"{name} requires a list")
    result = {}
    for row in rows:
        key = row.get("id") if isinstance(row, dict) else None
        _require(isinstance(key, str) and key.strip() and key not in result, f"Invalid or duplicate ID in {name}")
        result[key] = row
    return result


def _surface(pair):
    ref, pred = pair["reference"], pair["prediction"]
    ref_format = pair.get("reference_format", "LATEX")
    pred_format = pair.get("prediction_format", "LATEX") if pred is not None else None
    result = {"status": "NOT_EVALUATED", "reason": None, "exact": None, "counts": None, "cer": None,
              "reference_format": ref_format, "prediction_format": pred_format, "edits": None}
    if ref is None or not ref.strip():
        return {**result, "reason": "NO_FORMULA_REFERENCE"}
    if ref_format != "TEXT" or (pred is not None and pred_format != "TEXT"):
        return {**result, "reason": "TEXT_METRIC_REQUIRES_COMPARABLE_REPRESENTATIONS"}
    ref = normalize_text_policy(ref)
    actual = normalize_text_policy(pred)
    if max(len(ref), len(actual)) > MAX_CODEPOINTS:
        return {**result, "reason": "FORMULA_TEXT_CODEPOINT_LIMIT"}
    substitutions, deletions, insertions, hits, aligned = levenshtein_align(list(ref), list(actual))
    edits, ref_offset, pred_offset = [], 0, 0
    for expected, observed in aligned:
        if expected != observed:
            edits.append({"reference_offset": ref_offset, "prediction_offset": pred_offset,
                          "reference": expected, "prediction": observed})
        ref_offset += expected is not None
        pred_offset += observed is not None
    counts = {"reference_codepoints": len(ref), "prediction_codepoints": len(actual), "hits": hits,
              "substitutions": substitutions, "deletions": deletions, "insertions": insertions}
    return {**result, "status": "MEASURED", "reason": "MISSING_PREDICTION" if pred is None else None,
            "exact": ref == actual, "counts": counts, "edits": edits,
            "cer": (substitutions + deletions + insertions) / len(ref)}


def _review_index(review, pairs, pairs_hash, alignment_hash, sources, *, for_holdout=False):
    _require(isinstance(review, dict) and review.get("schema_version") == REVIEW_SCHEMA
             and review.get("pairs_sha256") == pairs_hash and "alignment_sha256" in review
             and review["alignment_sha256"] == alignment_hash, "Critical review identity does not match formula inputs")
    reviewer, reviewed_at = review.get("reviewer"), review.get("reviewed_at")
    _require(isinstance(reviewer, str) and reviewer.strip() and isinstance(reviewed_at, str)
             and datetime.fromisoformat(reviewed_at).utcoffset() is not None,
             "Critical review requires a reviewer and a timezone-aware timestamp")
    if for_holdout:
        _require(review.get("status") == "SUBMITTED" and review.get("actor_type") == "HUMAN"
                 and review.get("source_images_checked") is True and datetime.fromisoformat(reviewed_at) <= datetime.now(timezone.utc),
                 "Holdout critical review requires a submitted human source-image declaration")
    reviews = _index(review.get("pairs"), "critical reviews")
    _require(reviews.keys() <= pairs.keys(), "Critical review contains an unknown formula pair")
    for identifier, row in reviews.items():
        pair = pairs[identifier]
        ref, pred = pair["reference"], pair["prediction"]
        _require(ref is not None and ref.strip(), "Critical review requires a nonempty reference")
        categories = row.get("categories")
        _require(isinstance(categories, dict) and categories.keys() == set(CRITICAL_CATEGORIES),
                 "Critical review must explicitly account for every category")
        for detail in categories.values():
            _require(isinstance(detail, dict) and detail.keys() == {"status", "reason"}
                     and detail["status"] in REVIEW_STATUSES and isinstance(detail["reason"], str)
                     and detail["reason"].strip(), "Critical category requires a status and reason")
            _require((pred is not None and pred.strip()) or detail["status"] != "MATCH",
                     "Missing formula output cannot match a critical category")
        label = sources.get(identifier, pair).get("reference_equation_label")
        _require(label is None or categories["EQUATION_LABEL"]["status"] != "NOT_APPLICABLE",
                 "A labelled reference equation requires explicit label assessment")
    return reviews


def _source_index(alignment, pairs, pairs_hash):
    _require(isinstance(alignment, dict) and alignment.get("schema_version") == "ocr-formula-source-alignment-v1"
             and alignment.get("cdm_pairs_sha256") == pairs_hash and alignment.get("cdm_pair_count") == len(pairs),
             "Formula pair file does not match its alignment report")
    result = {}
    for doc in alignment["documents"]:
        for page in doc["pages"]:
            candidates = {row["id"]: row for row in page.get("candidates", [])}
            embedded = {row["id"]: row for row in page.get("embedded_spans", [])}
            matches = {row["reference_id"]: row["prediction_id"] for row in page.get("matches", [])}
            for ref in page.get("references", []):
                key = ref["pair_id"]
                _require(key in pairs and key not in result, "Invalid or duplicate alignment pair ID")
                pair = pairs[key]
                label = ref["equation_label"]
                _require((ref["content_raw"], ref["format"], label) ==
                         (pair["reference"], pair["reference_format"], pair.get("reference_equation_label", label)),
                         "Formula reference differs from its aligned source")
                match_id, span_id = matches.get(ref["id"]), ref.get("embedded_content_span_id")
                _require(match_id is None or span_id is None, "Formula pair cannot have two prediction sources")
                prediction = candidates[match_id] if match_id is not None else embedded[span_id] if span_id is not None else None
                if prediction is None:
                    _require(pair["prediction"] is None, "Unmatched formula pair must have no prediction")
                else:
                    _require((prediction["content_raw"], prediction["format"]) ==
                             (pair["prediction"], pair.get("prediction_format", "LATEX")),
                             "Formula prediction differs from its aligned source")
                result[key] = {"document_id": doc["document_id"], "pdf_sha256": doc["pdf_sha256"], "page": page["page"],
                               "reference_id": ref["id"], "reference_bbox": ref["bbox"], "placement": ref["placement"],
                               "reference_equation_label": label, "prediction_id": match_id, "embedded_content_span_id": span_id}
    _require(result.keys() == pairs.keys(), "Alignment must account for every formula pair")
    return result


def _text_totals(rows):
    text_rows = [row["text"] for row in rows if row["text"]["reference_format"] == "TEXT"]
    measured = [row for row in text_rows if row["status"] == "MEASURED"]
    totals = None
    if measured:
        totals = {name: sum(row["counts"][name] for row in measured) for name in measured[0]["counts"]}
    complete = bool(text_rows) and len(measured) == len(text_rows)
    errors = sum(totals[key] for key in ("substitutions", "deletions", "insertions")) if totals is not None else None
    return {"status": "MEASURED" if complete else "NOT_EVALUATED", "text_reference_pairs": len(text_rows),
            "measured_pairs": len(measured), "unscorable_pairs": len(text_rows) - len(measured),
            "measured_subset_counts": totals, "exact_rate": sum(row["exact"] for row in measured) / len(text_rows) if complete else None,
            "micro_cer": errors / totals["reference_codepoints"] if complete else None}


def _critical_totals(rows):
    categories = {}
    for category in CRITICAL_CATEGORIES:
        counts = Counter(row["critical"].get(category, {}).get("status", "UNRESOLVED") for row in rows)
        assessed = counts["MATCH"] + counts["ERROR"]
        categories[category] = {"matched_pairs": counts["MATCH"], "observed_error_pairs": counts["ERROR"] if assessed else None,
                                "not_applicable_pairs": counts["NOT_APPLICABLE"], "unresolved_pairs": counts["UNRESOLVED"],
                                "error_rate": counts["ERROR"] / assessed if assessed and not counts["UNRESOLVED"] else None}
    complete = bool(rows) and all(value["unresolved_pairs"] == 0 for value in categories.values())
    return {"status": "MEASURED_DECLARED_REVIEWS" if complete else "NOT_EVALUATED", "categories": categories,
            "pairs_with_observed_error": (sum(any(item["status"] == "ERROR" for item in row["critical"].values()) for row in rows)
                                          if any(value["observed_error_pairs"] is not None for value in categories.values()) else None)}


def evaluate(pairs_path, *, alignment_path=None, critical_review_path=None):
    """Recompute content metrics from exact pair bytes and optional source/review records."""
    raw_pairs, pairs_hash = _read(pairs_path)
    pairs = _index(raw_pairs, "formula pairs")
    for pair in pairs.values():
        _require(all(side in pair and (pair[side] is None or isinstance(pair[side], str))
                     and pair.get(f"{side}_format", "LATEX") in FORMATS for side in ("reference", "prediction")),
                 "Formula pair requires explicit string or null content and supported format")
        label = pair.get("reference_equation_label")
        _require(label is None or isinstance(label, str) and label.strip(), "Invalid formula equation label")
    alignment_hash, review_hash, reviewer = None, None, None
    sources, reviews = {}, {}
    for_holdout = False
    if alignment_path is not None:
        alignment, alignment_hash = _read(alignment_path)
        sources = _source_index(alignment, pairs, pairs_hash)
        for_holdout = "holdout_sample_sha256" in alignment
    if critical_review_path is not None:
        review, review_hash = _read(critical_review_path)
        reviews = _review_index(review, pairs, pairs_hash, alignment_hash, sources, for_holdout=for_holdout)
        reviewer = {key: review[key] for key in ("reviewer", "reviewed_at")}
    rows = [{"id": key, "source": sources.get(key), "text": _surface(pair),
             "critical": reviews[key]["categories"] if key in reviews else {}} for key, pair in pairs.items()]
    return {"schema_version": REPORT_SCHEMA, "text_method": METHOD, "acceptance_status": "NOT_EVALUATED",
            "independent_ground_truth_verified": False, "pair_count": len(rows), "pairs_sha256": pairs_hash,
            "alignment_sha256": alignment_hash, "critical_review_sha256": review_hash, "declared_reviewer": reviewer,
            "text": _text_totals(rows), "critical": _critical_totals(rows), "details": rows}


def critical_template(pairs_path, alignment_path):
    """Prepare explicit unresolved decisions without filling a reviewer's declaration."""
    report = evaluate(pairs_path, alignment_path=alignment_path)
    return {"schema_version": REVIEW_SCHEMA, "status": "BLANK", "actor_type": None, "source_images_checked": None,
            "reviewer": None, "reviewed_at": None, "pairs_sha256": report["pairs_sha256"],
            "alignment_sha256": report["alignment_sha256"], "pairs": [{"id": row["id"], "source": row["source"],
                "categories": {name: {"status": "UNRESOLVED", "reason": ""} for name in CRITICAL_CATEGORIES}}
                for row in report["details"]]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--alignment", type=Path)
    parser.add_argument("--critical-review", type=Path)
    parser.add_argument("--critical-template", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists() or any((parent / marker).is_file() for parent in output.parents
                              for marker in ("COMPLETED.json", "batch_input_manifest.json")):
        parser.error("Formula content output must be new and outside canonical publications")
    try:
        if args.critical_template:
            _require(args.alignment is not None and args.critical_review is None,
                     "Critical template requires its alignment and a new reviewer submission")
            template = critical_template(args.pairs, args.alignment)
            output.mkdir(parents=True, exist_ok=False)
            atomic_write_json(output / "critical-template.json", template)
            print(json.dumps({"status": "BLANK", "pair_count": len(template["pairs"])}))
            return 0
        report = evaluate(args.pairs, alignment_path=args.alignment, critical_review_path=args.critical_review)
        output.mkdir(parents=True, exist_ok=False)
        atomic_write_json(output / "formula-content.json", report)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps({"pair_count": report["pair_count"], "text_status": report["text"]["status"],
                      "critical_status": report["critical"]["status"], "acceptance_status": report["acceptance_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
