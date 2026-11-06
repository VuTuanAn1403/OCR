"""Bind review observations to existing canonical extraction, without running OCR."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact
from ocr_pipeline.analysis_run import verify_extraction_source

from .canonical_predictions import collect_predictions
from .spatial_matching import _box


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _read(path):
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8-sig"))
    _require(isinstance(value, dict), f"Expected a JSON object: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def _index(rows, key):
    _require(isinstance(rows, list), "Review records must be an array")
    result = {}
    for row in rows:
        value = row[key]
        _require(isinstance(value, str) and value.strip() and value not in result, f"Invalid or duplicate {key}")
        result[value] = row
    return result


def _open_extraction(publication):
    directory = Path(publication["source_dir"]).resolve()
    _require(directory.name == publication["id"] and publication["kind"] == "extraction",
             "Review prediction must use an original extraction directory")
    proof = verify_extraction_source(directory)
    fields = ("ocr_identity", "completion_sha256", "ocr_receipt_sha256", "total_pages")
    _require(all(publication[field] == proof[field] for field in fields), "Review prediction changed since inventory")
    receipt, receipt_hash = _read(directory / "ocr_receipt.json")
    completion, completion_hash = _read(directory / "COMPLETED.json")
    extraction, extraction_hash = _read(directory / "extraction.json")
    _require(receipt_hash == publication["ocr_receipt_sha256"] and completion_hash == publication["completion_sha256"]
             and receipt["files"]["extraction.json"] == completion["files"]["extraction.json"] == extraction_hash
             and extraction["doc_id"] == publication["id"] and extraction["doc_sha16"] == publication["pdf_sha256"][:16],
             "Review extraction bytes or document identity differ from the verified publication")
    pages = {page["page"]: page for page in extraction["pages"]}
    _require(len(pages) == len(extraction["pages"]) == proof["total_pages"]
             and pages.keys() == set(range(1, proof["total_pages"] + 1)), "Review extraction lacks full-page coverage")
    return pages, extraction_hash


def _localized_unit(page, unit, match, unit_kind, score_field):
    source_bbox = _box(unit)
    _require(source_bbox is not None and unit.get("bbox_format", "xyxy") == "xyxy"
             and all(type(value) in (int, float) for value in unit["bbox"])
             and (unit["coordinate_space"], unit["transforms"])
             == (page["coordinate_space"], page["transforms"]), "Review unit requires a source bbox in the page coordinate space")
    reason = match.get("reason")
    _require(isinstance(reason, str) and reason.strip(), "Review alignment requires a source disposition reason")
    locator = match.get("locator")
    if match["status"] == "MISSING_OUTPUT":
        _require(locator is None, "A missing review prediction cannot have an output locator")
        return {"text": None, "score": None, "mandatory_review": True, "source_evidence": None}
    _require(match["status"] == "MATCHED" and isinstance(locator, dict), "Invalid review alignment disposition")
    item_id = locator["item_id"]
    item = next((row for row in page["items"] if row["id"] == item_id and row.get("visibility") != "suppressed"), None)
    _require(item is not None, "Review locator must refer to a visible extraction item on its physical page")
    cell_mode = unit_kind == "cell"
    _require(item["kind"] == ("t" if cell_mode else "b"), "Review locator targets the wrong extraction item kind")
    value = item
    if cell_mode:
        row, col = locator["row"], locator["col"]
        _require(locator.keys() == {"item_id", "row", "col"} and type(row) is int and type(col) is int
                 and min(row, col) >= 0, "Cell locator requires an exact table/row/column anchor")
        cells = [cell for cell in item["cells"] if (cell["row"], cell["col"]) == (row, col)]
        _require(len(cells) == 1, "Cell locator does not identify one extraction cell")
        value = cells[0]
    else:
        text = value["text_corrected"]
        _require(locator.keys() == {"item_id"} and (not text or text.splitlines() == [text]),
                 "A line requires a single-line extraction block")
    box = _box(value)
    _require(box is not None and min(box[2], source_bbox[2]) > max(box[0], source_bbox[0])
             and min(box[3], source_bbox[3]) > max(box[1], source_bbox[1]),
             "Review prediction geometry must intersect the source bbox")
    score = value.get(score_field)
    _require(score is None or (type(score) in (float, int) and 0 <= score <= 1), "Extraction review score is out of range")
    mandatory = (item.get("needs_review") is not False or value.get("needs_review") is not False or score is None
                 or (cell_mode and value.get("bbox_source") != "cell"))
    return {"text": value["text_corrected"], "score": score, "mandatory_review": mandatory,
            "source_evidence": {"locator": locator, "bbox": value["bbox"], "score_field": score_field,
                                "source": value["source"], "confidence_source": value["confidence_source"],
                                "bbox_source": value.get("bbox_source")}}


def project(sample, sample_hash, score_protocol, score_hash, alignment, inventory):
    unit_kind = sample["unit"]
    score_field = {"line": "quality_score", "cell": "confidence"}.get(unit_kind)
    _require(score_field is not None and sample["schema_version"] == "review-calibration-sample-v1"
             and sample["partition"] in ("calibration", "holdout")
             and sample["score_semantics"] == score_protocol.get("score_semantics") == "rank"
             and sample["score_protocol_sha256"] == score_hash
             and score_protocol.get("schema_version") == "review-canonical-score-protocol-v1"
             and score_protocol.get("unit") == unit_kind and score_protocol.get("source_field") == score_field,
             "Canonical review requires the exact frozen rank score protocol for the sampled unit")
    manifest_hash = sha256_json_compact(inventory)
    reviewer = alignment.get("reviewed_by")
    _require(alignment.get("schema_version") == "review-canonical-alignment-v1"
             and alignment.get("sample_sha256") == sample_hash
             and alignment.get("prediction_manifest_sha256") == manifest_hash
             and isinstance(reviewer, str) and reviewer.strip()
             and isinstance(alignment.get("reviewed_at"), str)
             and datetime.fromisoformat(alignment["reviewed_at"]).utcoffset() is not None
             and alignment.get("reviewed_against_source") is True,
             "Review alignment requires the exact sample and prediction manifest and a source review declaration")
    matches = _index(alignment["units"], "unit_id")
    planned = _index(sample["units"], "unit_id")
    _require(planned and matches.keys() == planned.keys(), "Review alignment must dispose every frozen sample unit")
    publications = _index(inventory["documents"], "id")
    by_document = defaultdict(list)
    for key, unit in planned.items():
        by_document[unit["document_id"]].append((key, unit))
    results, extraction_hashes = {}, {}
    for document_id, rows in by_document.items():
        publication = publications.get(document_id, {})
        _require(publication and all(unit["pdf_sha256"] == publication["pdf_sha256"] for _, unit in rows),
                 "Review sample is outside the canonical prediction inventory")
        pages, extraction_hash = _open_extraction(publication)
        extraction_hashes[document_id] = extraction_hash
        used, source_locations = set(), set()
        for key, unit in rows:
            match = matches[key]
            page = unit["page"]
            source_id = unit["source_id"]
            _require(type(page) is int and page in pages and isinstance(source_id, str) and source_id.strip()
                     and match["source_id"] == source_id,
                     "Review alignment source ID or physical page does not match the frozen sample")
            _require((page, source_id) not in source_locations, "Duplicate frozen review source location")
            source_locations.add((page, source_id))
            observed = _localized_unit(pages[page], unit, match, unit_kind, score_field)
            if observed["source_evidence"] is not None:
                location = (page, sha256_json_compact(match["locator"]))
                _require(location not in used, "An extraction item or cell cannot be reused across review units")
                used.add(location)
            results[key] = {"unit_id": key, **observed}
    return {"schema_version": "review-calibration-predictions-v1", "sample_sha256": sample_hash,
            "score_protocol_sha256": score_hash, "canonical_alignment": alignment,
            "canonical_source": {"prediction_manifest_sha256": manifest_hash, "extraction_sha256": extraction_hashes,
                                 "alignment_sha256": sha256_json_compact(alignment)},
            "units": [results[key] for key in planned]}


def verify_projection(sample, sample_hash, predictions, score_protocol_path, inventory):
    protocol, score_hash = _read(score_protocol_path)
    expected = project(sample, sample_hash, protocol, score_hash, predictions["canonical_alignment"], inventory)
    observations = _index(predictions["units"], "unit_id")
    _require(predictions.get("canonical_source") == expected["canonical_source"]
             and observations.keys() == {row["unit_id"] for row in expected["units"]}
             and all({key: value for key, value in observations[row["unit_id"]].items() if key != "review"} == row
                     for row in expected["units"]), "Review observations differ from canonical extraction projection")
    return expected["canonical_source"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sample", "score-protocol", "alignment", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--canonical-batch", type=Path, action="append", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(root.resolve()) for root in args.canonical_batch):
        parser.error("Predictions must use a new path outside canonical batches")
    try:
        inventory = collect_predictions(args.canonical_batch)
        sample, sample_hash = _read(args.sample)
        protocol, score_hash = _read(args.score_protocol)
        alignment, _ = _read(args.alignment)
        predictions = project(sample, sample_hash, protocol, score_hash, alignment, inventory)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, sqlite3.Error) as error:
        parser.error(str(error))
    atomic_write_json(output, predictions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
