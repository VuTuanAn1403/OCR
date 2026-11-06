"""Bind formula annotations and CDM pairs to acknowledged OCR extraction bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from ocr_artifacts.atomic_io import atomic_write_bytes, atomic_write_json
from ocr_artifacts.digest import sha256_json_compact

from .canonical_predictions import collect_predictions
from .spatial_matching import bbox_iou, match_tables

ANNOTATION_SCHEMA = "ocr-formula-page-annotations-v1"
REPORT_SCHEMA = "ocr-formula-source-alignment-v1"
EMBEDDED_SCHEMA = "ocr-formula-embedded-spans-v1"
FRAMES = ("pdf_points_top_left", "pdf_points_top_left_rotated")
PLACEMENTS = ("inline", "display")
FORMATS = ("LATEX", "TEXT", "MATHML")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _box(value):
    return (isinstance(value, list) and len(value) == 4 and all(_number(n) for n in value)
            and value[0] < value[2] and value[1] < value[3])


def _index(rows, key, name):
    _require(isinstance(rows, list), f"{name} must be a list")
    result = {}
    for row in rows:
        _require(isinstance(row, dict) and key in row, f"{name} requires {key}")
        value = row[key]
        if key == "page":
            _require(type(value) is int and value > 0, f"{name} requires a positive physical page")
        else:
            _require(isinstance(value, str) and bool(value.strip()), f"{name} requires a nonempty {key}")
        _require(value not in result, f"Duplicate {key} in {name}: {value}")
        result[value] = row
    return result


def _read(path, expected=None):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    _require(expected is None or digest == expected, f"File changed or differs from verified publication: {path}")
    payload = json.loads(raw.decode("utf-8-sig"))
    _require(isinstance(payload, dict), f"Expected JSON object: {path}")
    return payload, digest


def _frame(page):
    space, transforms, width, height = (page.get(key) for key in ("coordinate_space", "transforms", "width", "height"))
    _require(space in FRAMES and isinstance(transforms, list) and _number(width) and _number(height)
             and width > 0 and height > 0, "Invalid formula annotation or extraction page frame")
    return space, transforms, width, height


def _inside(box, page):
    return _box(box) and 0 <= box[0] < box[2] <= page["width"] and 0 <= box[1] < box[3] <= page["height"]


def _formula_text(item):
    return item["kind"] == "b" and (item.get("role_final") or item.get("block_type")) == "formula"


def _predictions(page):
    rows = []
    for item in page["items"]:
        is_formula = item["kind"] == "f"
        if not (is_formula or _formula_text(item)):
            continue
        if is_formula:
            value = item.get("latex")
            _require(isinstance(value, str) and value == item.get("text_raw"),
                     f"Formula LaTeX differs from raw source: {item['id']}")
        else:
            value = item["text_raw"]
        rows.append({"id": item["id"], "source_id": item.get("source_id"), "bbox": item["bbox"],
                     "format": "LATEX" if is_formula else "TEXT", "content_raw": value,
                     "text_corrected": item.get("text_corrected"), "source": item.get("source"),
                     "engine": item.get("engine"), "device": item.get("device"), "status": item.get("status"),
                     "placement": "display" if is_formula else "unknown",
                     "visibility": item.get("visibility", "visible")})
    return _index(rows, "id", "formula predictions")


def _embedded_owner(items, locator):
    _require(isinstance(locator, dict) and locator.keys() in ({"item_id"}, {"item_id", "row", "col"})
             and isinstance(locator["item_id"], str), "Invalid formula span locator")
    item = items.get(locator["item_id"])
    _require(item is not None and item.get("visibility") != "suppressed",
             "Formula span must point to a visible extraction item on its physical page")
    if "row" not in locator:
        _require(item["kind"] == "b" and not _formula_text(item), "Embedded block must be ordinary text")
        return item, item, "block"
    row, col = locator["row"], locator["col"]
    _require(item["kind"] == "t" and all(type(n) is int and n >= 0 for n in (row, col)),
             "Embedded cell must identify a table and zero-based row and column")
    cells = [cell for cell in item["cells"] if (cell["row"], cell["col"]) == (row, col)]
    _require(len(cells) == 1, "Formula span must identify exactly one extraction cell")
    return item, cells[0], cells[0].get("bbox_source")


def _embedded_evidence(page, spans, references):
    """Resolve raw substrings. Owner geometry can constrain a link but cannot locate its glyphs."""
    if not spans:
        return [], {}
    items = _index(page["items"], "id", "extraction items")
    evidence, linked, intervals = [], {}, {}
    for identifier, span in _index(spans, "id", "embedded formula spans").items():
        fields = {"id", "locator", "start", "end", "reason", "reference_id"}
        _require(span.keys() <= fields, "Embedded formula spans cannot supply content or geometry overrides")
        locator, reason = span.get("locator"), span.get("reason")
        _require(isinstance(reason, str) and reason.strip(), "Embedded formula span requires a reason")
        item, owner, bbox_source = _embedded_owner(items, locator)
        raw = owner["text_raw"]
        start, end = span.get("start"), span.get("end")
        _require(isinstance(raw, str) and type(start) is int and type(end) is int
                 and 0 <= start < end <= len(raw) and raw[start:end].strip(),
                 "Formula span requires nonempty in-bounds raw text offsets")
        key = (item["id"], locator.get("row"), locator.get("col"))
        intervals.setdefault(key, []).append((start, end))
        record = {"id": identifier, "locator": locator, "start": start, "end": end, "reason": reason,
                  "format": "TEXT", "content_raw": raw[start:end],
                  "owner_raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                  "source_id": item.get("source_id"), "source": owner.get("source"), "device": owner.get("device"),
                  "container_bbox": owner.get("bbox"), "container_bbox_source": bbox_source,
                  "formula_bbox": None, "reference_id": span.get("reference_id")}
        reference_id = record["reference_id"]
        if reference_id is not None:
            _require(isinstance(reference_id, str) and reference_id in references and reference_id not in linked,
                     "Embedded span must link one unique formula reference on the same annotated page")
            _require(bbox_source in ("block", "cell") and _inside(record["container_bbox"], page)
                     and bbox_iou({"bbox": record["container_bbox"]}, references[reference_id]) > 0,
                     "Embedded link requires an in-frame block or cell intersecting the reference")
            linked[reference_id] = record
        evidence.append(record)
    for ranges in intervals.values():
        ranges.sort()
        _require(all(left[1] <= right[0] for left, right in zip(ranges, ranges[1:])),
                 "Embedded formula spans cannot reuse overlapping raw text")
    return evidence, linked


def _reference_regions(annotation, page):
    if annotation is None:
        return {}, {}, False
    _require(_frame(annotation) == _frame(page), f"Annotation frame differs on physical page {page['page']}")
    _require("formulas" in annotation, "Explicitly declare formulas as null, empty list or labelled list")
    if annotation["formulas"] is None:
        _require(not annotation.get("ignore_regions"), "Unannotated page cannot declare ignore regions")
        return {}, {}, False
    regions = _index(annotation["formulas"], "id", "formula references")
    ignores = _index(annotation.get("ignore_regions", []), "id", "formula ignore regions")
    for row in regions.values():
        _require(_inside(row.get("bbox"), page) and row.get("placement") in PLACEMENTS
                 and row.get("format") in FORMATS and isinstance(row.get("content_raw"), str)
                 and bool(row["content_raw"].strip()) and "equation_label" in row
                 and (row["equation_label"] is None or isinstance(row["equation_label"], str)
                      and bool(row["equation_label"].strip())),
                 f"Invalid formula reference on page {page['page']}: {row['id']}")
    for row in ignores.values():
        _require(_inside(row.get("bbox"), page) and isinstance(row.get("reason"), str) and bool(row["reason"].strip()),
                 f"Invalid formula ignore region on page {page['page']}: {row['id']}")
    return regions, ignores, True


def _align_page(document_id, page, annotation, threshold, embedded_spans=()):
    candidates = _predictions(page)
    predictions = [row for row in candidates.values() if row["visibility"] != "suppressed"]
    references, ignores, annotated = _reference_regions(annotation, page)
    evidence, linked = _embedded_evidence(page, embedded_spans, references)
    result = {"page": page["page"], "coordinate_space": page["coordinate_space"], "annotated": annotated,
              "prediction_count": len(predictions), "candidates": list(candidates.values()), "counts": None}
    if evidence:
        result["embedded_spans"] = evidence
    if not annotated:
        return result, []

    gt = [row.copy() for row in references.values()]
    placed = [row for row in predictions if _inside(row["bbox"], page)]
    pairs, matches, used_predictions, used_references = [], [], set(), set()
    # Matches are constrained to one physical page and its verified frame.
    for i, j in match_tables(gt, placed, iou_threshold=threshold):
        ref, pred = gt[i], placed[j]
        used_predictions.add(pred["id"])
        used_references.add(ref["id"])
        matches.append({"reference_id": ref["id"], "prediction_id": pred["id"], "iou": bbox_iou(ref, pred)})
    by_reference = {row["reference_id"]: candidates[row["prediction_id"]] for row in matches}
    _require(not (by_reference.keys() & linked.keys()), "Embedded link would replace a localized formula prediction")
    for ref in gt:
        pred = by_reference.get(ref["id"]) or linked.get(ref["id"])
        pair_id = sha256_json_compact([document_id, page["page"], ref["id"]])
        pairs.append({"id": pair_id, "reference": ref["content_raw"], "reference_format": ref["format"],
                      "reference_equation_label": ref["equation_label"],
                      "prediction": pred["content_raw"] if pred else None,
                      **({"prediction_format": pred["format"]} if pred else {})})
        ref["pair_id"] = pair_id
        if ref["id"] in linked:
            ref["embedded_content_span_id"] = linked[ref["id"]]["id"]

    extras, duplicates, ignored, unplaced = [], [], [], []
    for pred in predictions:
        if pred["id"] in used_predictions:
            continue
        if not _inside(pred["bbox"], page):
            extras.append(pred["id"])
            unplaced.append(pred["id"])
            continue
        overlap = [ref["id"] for ref in gt if bbox_iou(ref, pred) >= threshold]
        if overlap:
            duplicates.append({"prediction_id": pred["id"], "reference_ids": overlap})
            continue
        mask = [region["id"] for region in ignores.values() if bbox_iou(region, pred) >= threshold]
        if mask:
            ignored.append({"prediction_id": pred["id"], "ignore_region_ids": mask})
        else:
            extras.append(pred["id"])
    missing = [ref["id"] for ref in gt if ref["id"] not in used_references]
    result.update(references=gt, ignore_regions=list(ignores.values()), matches=matches, missing=missing,
                  spurious=extras, duplicates=duplicates, ignored=ignored, unplaced=unplaced,
                  counts={"tp": len(matches), "fp": len(extras) + len(duplicates), "fn": len(missing)},
                  reference_placement={placement: {
                      "matched": sum(ref["placement"] == placement and ref["id"] in used_references for ref in gt),
                      "total": sum(ref["placement"] == placement for ref in gt)} for placement in PLACEMENTS})
    return result, pairs


def _document(doc, annotation, threshold, embedded=None, *, sample_only=False):
    directory = Path(doc["source_dir"])
    receipt, _ = _read(directory / "ocr_receipt.json", doc["ocr_receipt_sha256"])
    extraction_hash = receipt["files"]["extraction.json"]
    completion, _ = _read(directory / "COMPLETED.json", doc["completion_sha256"])
    _require(completion["files"]["extraction.json"] == extraction_hash,
             "Formula extraction hash differs between receipt and completion")
    extraction, _ = _read(directory / "extraction.json", extraction_hash)
    _require(extraction["doc_id"] == doc["id"] and extraction["doc_sha16"] == doc["pdf_sha256"][:16]
             and extraction["total_pages"] == doc["total_pages"], "Extraction document identity differs")
    pages = _index(extraction["pages"], "page", "extraction pages")
    _require(pages.keys() == set(range(1, doc["total_pages"] + 1)), "Formula alignment requires full extraction pages")
    labels = {}
    if annotation is not None:
        _require(annotation.get("pdf_sha256") == doc["pdf_sha256"] and annotation.get("total_pages") == doc["total_pages"],
                 f"Formula annotation PDF identity differs: {doc['id']}")
        labels = _index(annotation.get("pages"), "page", "formula annotation pages")
        _require(labels.keys() <= pages.keys(), "Formula annotation page outside extraction universe")
    spans = {}
    if embedded is not None:
        for field, expected in (("pdf_sha256", doc["pdf_sha256"]), ("extraction_sha256", extraction_hash),
                                ("completion_sha256", doc["completion_sha256"])):
            _require(embedded.get(field) == expected, f"Embedded formula {field} differs for {doc['id']}")
        spans = _index(embedded.get("pages"), "page", "embedded formula pages")
        _require(spans.keys() <= pages.keys(), "Embedded formula page outside extraction universe")
    page_results, pairs = [], []
    selected = labels if sample_only else pages
    for number in sorted(selected):
        page = pages[number]
        _frame(page)
        rows = []
        if number in spans:
            _require(_frame(spans[number]) == _frame(page), f"Embedded formula frame differs on page {number}")
            rows = spans[number].get("spans")
            _require(isinstance(rows, list), "Embedded formula page requires a span list")
        result, page_pairs = _align_page(doc["id"], page, labels.get(number), threshold, rows)
        page_results.append(result)
        pairs.extend(page_pairs)
    return {"document_id": doc["id"], "pdf_sha256": doc["pdf_sha256"], "total_pages": doc["total_pages"],
            "completion_sha256": doc["completion_sha256"], "ocr_receipt_sha256": doc["ocr_receipt_sha256"],
            "extraction_sha256": extraction_hash, "pages": page_results}, pairs


def align_batches(batches, *, annotations_path=None, iou_threshold, embedded_spans_path=None):
    """Read canonical publications, return localization evidence and CDM inputs."""
    _require(_number(iou_threshold) and 0 < iou_threshold <= 1, "IoU threshold must be in (0, 1]")
    publication = collect_predictions(batches)
    annotations, annotations_hash = {}, None
    publication_ids = {doc["id"] for doc in publication["documents"]}
    if annotations_path is not None:
        value, annotations_hash = _read(annotations_path)
        _require(value.get("schema_version") == ANNOTATION_SCHEMA, "Unsupported formula annotation schema")
        annotations = _index(value.get("documents"), "document_id", "formula annotations")
        _require(annotations.keys() <= publication_ids,
                 "Formula annotations contain documents outside the verified publication")
    embedded, embedded_hash = {}, None
    if embedded_spans_path is not None:
        value, embedded_hash = _read(embedded_spans_path)
        _require(value.get("schema_version") == EMBEDDED_SCHEMA and "annotation_sha256" in value
                 and value["annotation_sha256"] == annotations_hash,
                 "Embedded span schema or annotation SHA256 mismatch")
        embedded = _index(value.get("documents"), "document_id", "embedded formula documents")
        _require(embedded.keys() <= publication_ids, "Embedded formula document outside the verified publication")
    return _align_publication(publication, annotations, annotations_hash, iou_threshold, embedded, embedded_hash)


def _align_publication(publication, annotations, annotations_hash, iou_threshold, embedded=None, embedded_hash=None,
                       *, sample_sha256=None):
    sample_only = sample_sha256 is not None
    embedded = embedded or {}
    documents, pairs = [], []
    for doc in publication["documents"]:
        result, doc_pairs = _document(doc, annotations.get(doc["id"]), iou_threshold, embedded.get(doc["id"]),
                                      sample_only=sample_only)
        documents.append(result)
        pairs.extend(doc_pairs)
    pages = [page for document in documents for page in document["pages"]]
    labelled = [page for page in pages if page["annotated"]]
    counts = {key: sum(page["counts"][key] for page in labelled) for key in ("tp", "fp", "fn")} if labelled else None
    report = {"schema_version": REPORT_SCHEMA, "status": "ALIGNMENT_PREPARED" if labelled else "NOT_EVALUATED",
              "localization_scope": "EXTRACTION_FORMULA_ITEMS_AND_FORMULA_TEXT_BLOCKS",
              "iou_threshold": iou_threshold, "annotation_sha256": annotations_hash,
              "independent_ground_truth_verified": False, "acceptance_status": "NOT_EVALUATED",
              "critical_symbol_status": "NOT_EVALUATED", "cdm_status": "NOT_EVALUATED",
              "batches": publication["batches"], "documents": documents,
              "coverage": {"documents": len(documents), "pages": len(pages), "annotated_pages": len(labelled),
                           "visible_predictions": sum(page["prediction_count"] for page in pages)},
              "annotated_page_counts": counts, "cdm_pair_count": len(pairs)}
    if sample_only:
        report["holdout_sample_sha256"] = sample_sha256
    if embedded_hash is not None:
        report["embedded_spans_sha256"] = embedded_hash
        report["embedded_span_count"] = sum(len(page.get("embedded_spans", ())) for page in pages)
        report["embedded_linked_content_pairs"] = sum(
            "embedded_content_span_id" in ref for page in labelled for ref in page["references"])
    return report, pairs


def write_alignment(output, report, pairs):
    """Write pair bytes first and bind their exact identity in the alignment."""
    output.mkdir(parents=True, exist_ok=False)
    pair_path = output / "cdm-pairs.json" if pairs else None
    pair_hash = None
    if pair_path is not None:
        data = json.dumps(pairs, ensure_ascii=False, indent=2).encode("utf-8")
        atomic_write_bytes(pair_path, data)
        pair_hash = hashlib.sha256(data).hexdigest()
    report_path = output / "alignment.json"
    atomic_write_json(report_path, {**report, "cdm_pairs_sha256": pair_hash})
    return report_path, pair_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--batch", type=Path, nargs="+", required=True)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--embedded-spans", type=Path)
    parser.add_argument("--iou-threshold", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(root.resolve()) for root in args.batch) or any(
            (parent / marker).is_file() for parent in output.parents for marker in ("batch_input_manifest.json", "COMPLETED.json")):
        parser.error("Output must be a new directory outside canonical publications")
    try:
        report, pairs = align_batches(args.batch, annotations_path=args.annotations, iou_threshold=args.iou_threshold,
                                      embedded_spans_path=args.embedded_spans)
        write_alignment(output, report, pairs)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps({key: report[key] for key in ("status", "coverage", "annotated_page_counts", "cdm_pair_count")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
