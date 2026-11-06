"""Compare reviewed source occurrences against literal_v1 matches in result.md."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from ocr_keywords.contract import validate_report
from ocr_keywords.counter import KeywordCounter


METHOD = "keyword-source-occurrences-v1"


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _rows(value, label: str) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _span(row: dict) -> tuple[str, int, int]:
    key = _text(row.get("keyword_id"), "keyword_id")
    start, end = row.get("start"), row.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError("Occurrence offsets must be a nonempty half-open range")
    return key, start, end


def _span_record(span: tuple[str, int, int]) -> dict:
    return dict(zip(("keyword_id", "start", "end"), span))


def _find(text: str, keyword_ids: dict[str, str]) -> set[tuple[str, int, int]]:
    return {(keyword_ids[phrase], start, end)
            for phrase, start, end in KeywordCounter.iter_occurrences(text, list(keyword_ids))}


def inventory(document: Path, snapshot: dict) -> dict:
    """Bind observed offsets to the published Markdown and its keyword report."""
    markdown = document / "result.md"
    report = _read_json(document / "keyword_counts.json")
    validate_report(report, snapshot, markdown, document.name)
    pdf_hash = _text(report.get("pdf_sha256"), "pdf_sha256")
    if len(pdf_hash) != 64 or any(char not in "0123456789abcdef" for char in pdf_hash):
        raise ValueError("Expected a full PDF SHA-256 in the keyword report")
    raw = markdown.read_bytes()
    if hashlib.sha256(raw).hexdigest() != report["identity"]["result_md_sha256"]:
        raise ValueError("Markdown changed while reading")
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    keyword_ids = {row["keyword"]: row["id"] for row in snapshot["canonical_keywords"]}
    if KeywordCounter.unique_keywords(list(keyword_ids)) != list(keyword_ids):
        raise ValueError("Dictionary canonical keywords must be NFC and unique under literal_v1")
    spans = _find(text, keyword_ids)
    counts = Counter(key for key, _, _ in spans)
    if any(counts[key] != count for key, count in report["canonical_counts"].items()):
        raise ValueError("Observed literal occurrences disagree with the published keyword counts")
    pages = report.get("selected_pages")
    if (not isinstance(pages, list) or not pages or any(type(page) is not int or page < 1 for page in pages)
            or len(set(pages)) != len(pages)):
        raise ValueError("Keyword report requires unique selected physical pages")
    return {
        "identity": {"document_id": document.name, "pdf_sha256": pdf_hash, **report["identity"]},
        "selected_pages": pages, "keywords": snapshot["canonical_keywords"],
        "occurrences": [_span_record(span) for span in sorted(spans, key=lambda span: (span[1], span[2], span[0]))],
    }


def _reference_units(ground_truth: dict, observed: dict) -> tuple[dict, dict, list[str]]:
    keyword_ids = {row["keyword"]: row["id"] for row in observed["keywords"]}
    pages = set(observed["selected_pages"])
    units, references, unannotated = {}, {}, []
    for unit in _rows(ground_truth.get("units"), "units"):
        unit_id = _text(unit.get("unit_id"), "unit_id")
        page, box = unit.get("physical_page"), unit.get("bbox")
        if unit_id in units or type(page) is not int or page not in pages:
            raise ValueError("GT units require unique IDs and selected physical pages")
        if (not isinstance(box, list) or len(box) != 4
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in box)
                or box[2] <= box[0] or box[3] <= box[1]):
            raise ValueError("GT units require a finite, positive-area bbox")
        _text(unit.get("coordinate_space"), "coordinate_space")
        units[unit_id] = unit
        annotation = unit.get("keyword_occurrences")
        if annotation is None:
            unannotated.append(unit_id)
            continue
        transcription = unit.get("transcription")
        if not isinstance(transcription, str):
            raise ValueError("Reviewed units require an adjudicated transcription")
        spans = set()
        for occurrence in _rows(annotation, "keyword_occurrences"):
            occurrence_id = _text(occurrence.get("id"), "occurrence id")
            span = _span(occurrence)
            if occurrence_id in references or span in spans:
                raise ValueError("Duplicate GT occurrence ID or span within a source unit")
            spans.add(span)
            references[occurrence_id] = {"id": occurrence_id, "unit_id": unit_id, **_span_record(span)}
        if spans != _find(transcription, keyword_ids):
            raise ValueError(f"GT occurrences disagree with the adjudicated transcription for {unit_id}")
    return units, references, sorted(unannotated)


def evaluate(observed: dict, ground_truth: dict, alignment: dict) -> dict:
    """Score explicit occurrence links, allowing unmatched and repeated predictions."""
    if alignment.get("schema_version") != METHOD or alignment.get("identity") != observed["identity"]:
        raise ValueError("Alignment schema or publication identity mismatch")
    gt_identity = {key: observed["identity"][key] for key in ("document_id", "pdf_sha256", "dictionary_sha256")}
    if ground_truth.get("schema_version") != "keyword-source-gt-v1" or ground_truth.get("identity") != gt_identity:
        raise ValueError("GT schema or PDF/dictionary identity mismatch")
    _text(alignment.get("reviewed_by"), "reviewed_by")
    units, references, unannotated = _reference_units(ground_truth, observed)
    spans = {_span(row) for row in observed["occurrences"]}
    attributions = {}
    for row in _rows(alignment.get("attributions"), "attributions"):
        span = _span(row)
        if span not in spans or span in attributions:
            raise ValueError("Attributions must identify distinct observed literal occurrences")
        unit_id, ref_id = row.get("unit_id"), row.get("reference_id")
        if unit_id is None:
            _text(row.get("outside_scope_reason"), "outside_scope_reason")
            if ref_id is not None:
                raise ValueError("An out-of-scope occurrence cannot link to a reference")
        else:
            if _text(unit_id, "unit_id") not in units:
                raise ValueError("Attribution names an unknown source unit")
            if ref_id is not None and _text(ref_id, "reference_id") not in references:
                raise ValueError("Attribution links to an unknown reference occurrence")
        attributions[span] = row

    matched, extra, excluded = {}, [], []
    unscored = []
    for span in sorted(attributions, key=lambda item: (item[1], item[2], item[0])):
        row = attributions[span]
        unit_id, ref_id = row.get("unit_id"), row.get("reference_id")
        ref = references.get(ref_id)
        prediction = {**_span_record(span), "unit_id": unit_id, "reference_id": ref_id}
        if unit_id is None:
            excluded.append({**prediction, "reason": row["outside_scope_reason"]})
        elif units[unit_id].get("keyword_occurrences") is None:
            unscored.append(prediction)
        elif ref and ref["unit_id"] == unit_id and ref["keyword_id"] == span[0] and ref_id not in matched:
            matched[ref_id] = prediction
        else:
            extra.append(prediction)
    missing = [references[key] for key in sorted(references.keys() - matched.keys())]
    unattributed = [_span_record(span) for span in sorted(spans - attributions.keys())]
    # Counts on a partially reviewed ledger describe the available evidence.
    # They cannot establish absence of errors in the declared scope.
    status = "NOT_EVALUATED"
    if units and not unannotated and not unattributed:
        status = "FAIL" if missing or extra else "PASS"
    correct_counts = Counter(row["keyword_id"] for row in matched.values())
    missing_counts = Counter(row["keyword_id"] for row in missing)
    extra_counts = Counter(row["keyword_id"] for row in extra)
    by_keyword = {}
    for row in observed["keywords"]:
        key = row["id"]
        by_keyword[key] = {"keyword": row["keyword"], "correct": correct_counts[key],
                           "missing": missing_counts[key], "extra": extra_counts[key],
                           "net_delta": extra_counts[key] - missing_counts[key] if status != "NOT_EVALUATED" else None}
    return {
        "method": METHOD, "status": status, "eligible_for_quality_acceptance": False,
        "identity": observed["identity"], "reviewed_by": alignment["reviewed_by"],
        "unit_locations": {key: {field: unit.get(field) for field in
                           ("physical_page", "coordinate_space", "bbox", "table_cell_id")}
                           for key, unit in units.items()},
        "by_keyword": by_keyword, "correct": [{"reference": references[key], "prediction": matched[key]}
                                             for key in sorted(matched)],
        "missing": missing, "extra": extra, "outside_scope": excluded, "unscored": unscored,
        "unannotated_unit_ids": unannotated, "unattributed": unattributed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="Document directory containing result.md and keyword_counts.json")
    parser.add_argument("dictionary", type=Path, help="Frozen keyword dictionary snapshot JSON")
    parser.add_argument("--ground-truth", type=Path, help="Frozen source units and adjudicated occurrences")
    parser.add_argument("--alignment", type=Path, help="Reviewed literal occurrence attributions")
    args = parser.parse_args()
    if (args.alignment is None) != (args.ground_truth is None):
        parser.error("--ground-truth and --alignment must be supplied together")
    try:
        observed = inventory(args.document.resolve(), _read_json(args.dictionary))
        if args.alignment is None:
            print(json.dumps(observed, ensure_ascii=True, indent=2))
            return 0
        gt_raw, alignment_raw = args.ground_truth.read_bytes(), args.alignment.read_bytes()
        ground_truth = json.loads(gt_raw.decode("utf-8-sig"))
        alignment = json.loads(alignment_raw.decode("utf-8-sig"))
        if not isinstance(ground_truth, dict) or not isinstance(alignment, dict):
            raise ValueError("Ground truth and alignment must be JSON objects")
        gt_hash = hashlib.sha256(gt_raw).hexdigest()
        if alignment.get("ground_truth_sha256") != gt_hash:
            raise ValueError("Alignment ground-truth checksum mismatch")
        report = evaluate(observed, ground_truth, alignment)
        report.update(ground_truth_sha256=gt_hash, alignment_sha256=hashlib.sha256(alignment_raw).hexdigest())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
    return {"PASS": 0, "FAIL": 1, "NOT_EVALUATED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
