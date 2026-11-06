"""Diagnostic scores for independently annotated extraction structure."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from graphlib import TopologicalSorter
from pathlib import Path

from bs4 import BeautifulSoup

from ocr_contracts.table import TableCell, TableStructure
from ocr_document.contract_schema import validate_extraction

from . import canonical_layout, text_detection_metric
from .numeric_metric import compute_numeric_metrics
from .reading_order_v6_2 import PROTOCOL, REVIEWED_PROTOCOL, evaluate_reading_order
from .spatial_matching import _box, match_tables
from .teds_metric import evaluate_table_collection


def _load(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return payload, hashlib.sha256(raw).hexdigest()


def _records(value, label: str) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _check_bbox(record: dict) -> None:
    box = record.get("bbox")
    if (not isinstance(box, list) or any(type(value) not in (int, float) for value in box)
            or record.get("bbox_format", "xyxy") != "xyxy" or _box(record) is None):
        raise ValueError("GT requires a finite, positive-area xyxy bbox")


def _check_ids(records: list[dict]) -> set[str]:
    ids = [record.get("id") for record in records]
    if any(not isinstance(value, str) or not value.strip() for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("GT records require nonempty unique IDs within their page and modality")
    return set(ids)


def _gt_tables(value, scope: dict) -> list[dict]:
    records = _records(value, "tables")
    _check_ids(records)
    for record in records:
        _check_bbox(record)
        html = record.get("html")
        if not isinstance(html, str) or len(BeautifulSoup(html, "html.parser").find_all("table")) != 1:
            raise ValueError("Each GT table requires a single HTML table")
    return [{**record, **scope, "table_id": record["id"]} for record in records]


def _pred_tables(items: list[dict], scope: dict) -> list[dict]:
    tables = []
    for item in items:
        if item["kind"] != "t":
            continue
        cells = [TableCell(row_idx=cell["row"], col_idx=cell["col"], row_span=cell["row_span"],
                           col_span=cell["col_span"], text=cell["text_corrected"]) for cell in item.get("cells", [])]
        table = TableStructure(table_id=item["id"], page=scope["page"], cells=cells)
        tables.append({**scope, "id": item["id"], "bbox": item["bbox"],
                       "html": table.to_html(), "cells": item.get("cells", [])})
    return tables


def _numeric_cells(table: dict, cells: list[dict], *, table_id: str, value_key: str) -> list[dict]:
    result, locations = [], set()
    for cell in cells:
        row, col, value = cell.get("row"), cell.get("col"), cell.get(value_key)
        if (type(row) is not int or type(col) is not int or min(row, col) < 0
                or not isinstance(value, str) or not any(char.isdecimal() for char in value)):
            raise ValueError("Numeric cells require zero-based row/col and a digit-bearing string")
        location = f"{row}:{col}"
        if location in locations:
            raise ValueError("Duplicate numeric cell coordinates")
        locations.add(location)
        result.append({**{key: table[key] for key in ("document_id", "page", "coordinate_space")},
                       "value": value, "cell_id": location, "table_id": table_id})
    return result


def _numeric_page(gt: list[dict], pred: list[dict]) -> tuple[list[dict], list[dict]]:
    # Align the owning table by geometry before matching its cell coordinates.
    aligned = {col: f"gt:{gt[row]['id']}" for row, col in match_tables(gt, pred)}
    references, predictions = [], []
    for table in gt:
        references.extend(_numeric_cells(table, _records(table.get("numeric_cells"), "numeric_cells"),
                                         table_id=f"gt:{table['id']}", value_key="value"))
    for index, table in enumerate(pred):
        cells = [cell for cell in table["cells"] if any(char.isdecimal() for char in cell["text_corrected"])]
        predictions.extend(_numeric_cells(table, cells, table_id=aligned.get(index, f"pred:{table['id']}"),
                                          value_key="text_corrected"))
    return references, predictions


def _precedence_pairs(value, ids: set[str]) -> list[tuple[str, str]]:
    if not isinstance(value, list) or any(
        not isinstance(pair, list) or len(pair) != 2
        or any(not isinstance(node, str) or node not in ids for node in pair) for pair in value
    ):
        raise ValueError("Reading order requires explicit pairs between annotated nodes")
    return [tuple(pair) for pair in value]


def _reading_order(label: dict, items: list[dict], reviewed_spans=None, *, has_prediction=True) -> dict:
    if not isinstance(label, dict):
        raise ValueError("reading_order must be an object")
    nodes = _records(label.get("nodes"), "reading_order.nodes")
    ids = _check_ids(nodes)
    for node in nodes:
        _check_bbox(node)
        if not isinstance(node.get("text"), str):
            raise ValueError("Reading order nodes require text")
    pairs = _precedence_pairs(label.get("before_pairs"), ids)
    adjacent = _precedence_pairs(label["adjacent_pairs"], ids) if "adjacent_pairs" in label else None
    mode = label.get("alignment_mode", "automatic")
    if mode not in ("automatic", "reviewed_spans") or (reviewed_spans is not None and mode != "reviewed_spans"):
        raise ValueError("Reading order alignment must follow the mode declared in the GT page")
    review_missing = mode == "reviewed_spans" and reviewed_spans is None and has_prediction
    graph = TopologicalSorter()
    for before, after in pairs:
        graph.add(after, before)
    tuple(graph.static_order())  # Reject contradictory GT before measuring it.
    visible = [item for item in items if item.get("visibility") != "suppressed" and item["kind"] == "b"]
    prediction = [{"id": item["id"], "bbox": item["bbox"], "text": item["text_corrected"]} for item in visible]
    result = evaluate_reading_order(nodes, prediction, before_pairs=pairs, adjacent_pairs=adjacent,
                                    reviewed_spans=([] if reviewed_spans is None else reviewed_spans)
                                    if mode == "reviewed_spans" else None)
    result["spurious_nodes"] = result["predicted_nodes"] - result["matched_prediction_nodes"]
    result["penalized_precedence"] = (
        result["correct_pairs"] / result["gt_pairs"] if result["gt_pairs"] else None
    )
    if review_missing:
        result = {"protocol": REVIEWED_PROTOCOL, "status": "NOT_EVALUATED", "reason": "MISSING_REVIEWED_ALIGNMENT",
                  "reference_nodes": len(nodes), "predicted_nodes": len(prediction), "gt_pairs": len(pairs),
                  "gt_adjacent_pairs": len(adjacent or ()), "penalized_precedence": None}
    return result


def _reviewed_pages(path, gt, gt_hash, extraction_hash, expected_hash, partition):
    payload, digest = _load(path)
    if (payload.get("schema_version") != "ocr-reading-order-alignment-v1"
            or payload.get("document_id") != gt["document_id"] or payload.get("pdf_sha256") != gt["pdf_sha256"]
            or payload.get("ground_truth_sha256") != gt_hash or extraction_hash is None
            or payload.get("extraction_sha256") != extraction_hash or (expected_hash is not None and digest != expected_hash)):
        raise ValueError("Reading order alignment must pin the exact document, GT and extraction")
    intended = payload.get("intended_partition")
    if intended not in ("development", "calibration", "holdout") or (partition is not None and intended != partition):
        raise ValueError("Reading order alignment belongs to a different partition")
    reviewer, timestamp = payload.get("reviewed_by"), payload.get("reviewed_at")
    if (not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(timestamp, str)
            or datetime.fromisoformat(timestamp).utcoffset() is None or payload.get("reviewed_against_source") is not True):
        raise ValueError("Reading order alignment requires a reviewer, timezone and source review declaration")
    rows = _records(payload.get("pages"), "alignment.pages")
    pages = {}
    if not rows:
        raise ValueError("Reading order alignment requires at least one reviewed page")
    for row in rows:
        number = row.get("page")
        if type(number) is not int or number < 1 or number in pages:
            raise ValueError("Reading order alignment requires unique positive physical pages")
        pages[number] = _records(row.get("mappings"), "alignment.mappings")
    return pages, digest


def evaluate_structure(prediction_dir: Path, gt_path: Path, *, expected_pdf_sha256: str | None = None,
                       reading_order_alignment: Path | None = None, expected_alignment_sha256: str | None = None,
                       alignment_partition: str | None = None, include_layout_ap: bool = True) -> dict:
    """Evaluate explicitly labelled pages, with no prediction fallback for missing output."""
    gt, gt_hash = _load(gt_path)
    pdf_hash = gt.get("pdf_sha256")
    if (gt.get("schema_version") != "structured-page-gt-v1" or gt.get("document_id") != prediction_dir.name
            or not isinstance(pdf_hash, str) or not re.fullmatch("[0-9a-f]{64}", pdf_hash)):
        raise ValueError("Structured GT schema, document ID or PDF hash is invalid")
    if expected_pdf_sha256 is not None and pdf_hash != expected_pdf_sha256:
        raise ValueError("Structured GT PDF SHA-256 differs from the verified canonical input")
    extraction_path = prediction_dir / "extraction.json"
    extraction, extraction_hash = _load(extraction_path) if extraction_path.is_file() else ({}, None)
    if extraction_hash is not None:
        errors = validate_extraction(extraction)
        if errors:
            raise ValueError("; ".join(errors[:5]))
        if extraction["doc_id"] != gt["document_id"] or extraction["doc_sha16"] != pdf_hash[:16]:
            raise ValueError("Structured GT and extraction document identities differ")
    predicted_pages = {page["page"]: page for page in extraction.get("pages", [])}
    total_pages = gt.get("total_pages")
    if type(total_pages) is not int or total_pages < 1 or extraction.get("total_pages", total_pages) != total_pages:
        raise ValueError("Structured GT page universe is missing or differs from extraction")
    reviewed, alignment_hash = ({}, None) if reading_order_alignment is None else _reviewed_pages(
        reading_order_alignment, gt, gt_hash, extraction_hash, expected_alignment_sha256, alignment_partition)

    gt_tables, pred_tables, gt_numbers, pred_numbers = [], [], [], []
    gt_layout, pred_layout = [], []
    seen, records, detection_sources = set(), [], {}
    for page in _records(gt.get("pages"), "pages"):
        number, space = page.get("page"), page.get("coordinate_space")
        if type(number) is not int or not 1 <= number <= total_pages or number in seen:
            raise ValueError("Structured GT requires unique page numbers in the document universe")
        seen.add(number)
        predicted = predicted_pages.get(number)
        if (space not in ("pdf_points_top_left", "pdf_points_top_left_rotated")
                or not isinstance(page.get("transforms"), list)
                or (predicted and (space, page["transforms"]) != (predicted["coordinate_space"], predicted["transforms"]))):
            raise ValueError(f"GT and extraction coordinate spaces/transforms differ on page {number}")
        scope = {"page": number, "document_id": gt["document_id"], "coordinate_space": space}
        items = predicted["items"] if predicted else []
        record = {"page": number, "prediction_status": "PRESENT" if predicted else "MISSING_OUTPUT"}
        if "numeric_cells_complete" in page and type(page["numeric_cells_complete"]) is not bool:
            raise ValueError("numeric_cells_complete must be boolean when provided")
        if page.get("tables") is not None:
            ref, pred = _gt_tables(page["tables"], scope), _pred_tables(items, scope)
            record["tables"] = _table_scores(ref, pred)
            gt_tables.extend(ref)
            pred_tables.extend(pred)
            if page.get("numeric_cells_complete") is True:
                ref_numbers, pred_values = _numeric_page(ref, pred)
                record["numeric_cells"] = compute_numeric_metrics(ref_numbers, pred_values)
                gt_numbers.extend(ref_numbers)
                pred_numbers.extend(pred_values)
        elif page.get("numeric_cells_complete") is True:
            raise ValueError("Complete numeric annotations require complete table annotations")
        if page.get("reading_order") is not None:
            if number in reviewed and predicted is None:
                raise ValueError("Reading order alignment cannot cover a missing extraction page")
            record["reading_order"] = _reading_order(page["reading_order"], items, reviewed.get(number),
                                                      has_prediction=predicted is not None)
            if number in reviewed:
                record["reading_order"]["alignment_sha256"] = alignment_hash
        if page.get("layout") is not None:
            image_id = f"{gt['document_id']}:p{number}"
            ref, (pred, excluded) = (canonical_layout.reference_regions(page["layout"], image_id),
                                     canonical_layout.prediction_regions(items, image_id))
            record["layout"] = canonical_layout.evaluate_page(ref, pred, excluded)
            if include_layout_ap:
                gt_layout.extend(ref)
                pred_layout.extend(pred)
        if page.get("text_detection") is not None:
            source_path = prediction_dir / "pages" / f"page-{number:04d}.json"
            source_page, source_hash = text_detection_metric.read_page(source_path)
            record["text_detection"] = text_detection_metric.evaluate_page(
                page["text_detection"], source_page, predicted,
                gt.get("text_detection_matching"))
            record["text_detection"]["page_artifact_sha256"] = source_hash
            if source_hash is not None:
                detection_sources[source_path] = source_hash
        records.append(record)

    for path, digest in detection_sources.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Detector source page artifact changed during evaluation")
    if detection_sources and (hashlib.sha256(gt_path.read_bytes()).hexdigest() != gt_hash
                             or extraction_hash is not None
                             and hashlib.sha256(extraction_path.read_bytes()).hexdigest() != extraction_hash):
        raise ValueError("Text detection GT or extraction changed during evaluation")
    if reviewed.keys() - {record["page"] for record in records if "reading_order" in record}:
        raise ValueError("Reading order alignment references pages without reading order GT")
    order = [record["reading_order"] for record in records if "reading_order" in record]
    scorable = [row for row in order if row["status"] != "NOT_EVALUATED"]
    unscorable = sorted(record["page"] for record in records
                        if record.get("reading_order", {}).get("status") == "NOT_EVALUATED")
    order_counts = {key: sum(page[key] for page in scorable) for key in (
        "reference_nodes", "predicted_nodes", "matched_nodes", "matched_prediction_nodes", "missing_nodes",
        "duplicate_predictions", "spurious_nodes", "gt_pairs", "matched_pairs", "correct_pairs",
        "gt_adjacent_pairs", "matched_adjacent_pairs", "correct_adjacent_pairs",
    )}
    protocols = sorted({row["protocol"] for row in order})
    orders = {**order_counts, "status": "MEASURED" if order_counts["gt_pairs"] and not unscorable else "NOT_EVALUATED",
              "declared_gt_pairs": sum(row["gt_pairs"] for row in order),
              "protocol": protocols[0] if len(protocols) == 1 else "mixed_declared_by_page" if protocols else PROTOCOL,
              "protocols": protocols, "missing_alignment_pages": unscorable,
              "reviewed_alignment_pages": sorted(reviewed), "alignment_sha256": alignment_hash,
              "penalized_precedence": (order_counts["correct_pairs"] / order_counts["gt_pairs"]
                                       if order_counts["gt_pairs"] and not unscorable else None)}
    coverage = {}
    for metric in ("tables", "numeric_cells", "reading_order", "layout"):
        annotated = [record for record in records if metric in record]
        coverage[metric] = {"annotated_pages": sorted(record["page"] for record in annotated),
                            "missing_prediction_pages": sorted(record["page"] for record in annotated
                                                               if record["prediction_status"] == "MISSING_OUTPUT"),
                            "total_pages": total_pages}
    detector_pages = [row for row in records if "text_detection" in row]
    coverage["text_detection"] = {
        "declared_pages": [row["page"] for row in detector_pages],
        "annotated_pages": [row["page"] for row in detector_pages
                            if row["text_detection"]["annotation_state"] != "unannotated"],
        "measured_pages": [row["page"] for row in detector_pages if row["text_detection"]["counts"] is not None],
        "unscorable_pages": [row["page"] for row in detector_pages if row["text_detection"]["counts"] is None],
        "total_pages": total_pages}
    return {
        "protocol": "extraction-structure-diagnostic-v1", "eligible_for_quality_acceptance": False,
        "ground_truth_sha256": gt_hash, "extraction_sha256": extraction_hash,
        "pdf_sha256": pdf_hash, "identity_check": "EXTRACTION_PDF_SHA16" if extraction_hash else "MISSING_OUTPUT",
        "coverage": coverage, "pages": sorted(records, key=lambda record: record["page"]),
        "tables": (_table_scores(gt_tables, pred_tables) if coverage["tables"]["annotated_pages"]
                   else {"status": "NOT_EVALUATED"}),
        "numeric_cells": (compute_numeric_metrics(gt_numbers, pred_numbers)
                          if coverage["numeric_cells"]["annotated_pages"] else {"status": "NOT_EVALUATED"}),
        "reading_order": orders,
        "text_detection": text_detection_metric.summarize(
            [record["text_detection"] for record in records if "text_detection" in record]),
        "layout": canonical_layout.summarize([row["layout"] for row in records if "layout" in row],
                                             gt_layout, pred_layout, include_ap=include_layout_ap),
    }


def _table_scores(reference: list[dict], prediction: list[dict]) -> dict:
    result = evaluate_table_collection(reference, prediction)
    if result["status"] == "NO_TABLES":
        # Keep the historical metric API intact. An empty annotation only
        # measures the absence of spurious tables, not recognition quality.
        result.update(table_precision=None, table_recall=None, table_f1=None)
    return result
