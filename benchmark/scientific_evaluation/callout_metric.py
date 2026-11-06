"""Diagnose quote ownership and CER from published document chunks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ocr_artifacts.hashing import sha256_file
from ocr_document.source_identity import valid_bbox

from .degradation_metric import _unique_object
from .ocr_metric import compute_cer_detailed

SCHEMA = "ocr-callout-development-plan-v1"
METHOD = "source-window-callout-ownership-v1"
FRAME_FIELDS = ("coordinate_space", "transforms", "width", "height")
FURNITURE = {"page_number", "header", "footer", "running_header", "running_footer"}
MAX_CER_CELLS = 10_000_000


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def _intersection(a, b):
    return (max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1])))


def _contains(outer, inner):
    return all(outer[i] <= inner[i] for i in (0, 1)) and all(outer[i] >= inner[i] for i in (2, 3))


def _quote_boxes(rows, window):
    if rows is None:
        return None
    _require(isinstance(rows, list), "Quote annotations must be a list or null")
    boxes = {}
    for row in rows:
        key, box = row["id"], row["bbox"]
        _require(isinstance(key, str) and key and key not in boxes and valid_bbox(box) and _contains(window, box),
                 "Quote region requires a unique ID and an in-window bbox")
        _require(not any(_intersection(box, prior) > 0 for prior in boxes.values()), "Quote annotation regions overlap")
        boxes[key] = box
    return boxes


def _project(page, document, window):
    ids, partial, unplaced = set(), [], set()
    bboxes = {}
    for item in page["items"]:
        if item["kind"] != "b" or item.get("block_type") in FURNITURE:
            continue
        box, key = item["bbox"], item["id"]
        if not valid_bbox(box):
            unplaced.add(key)
            continue
        if _contains(window, box):
            _require(key not in ids, "Duplicate source ID in callout window")
            ids.add(key)
            bboxes[key] = box
        elif _intersection(box, window) > 0:
            partial.append(key)
    selected, crossing, ambiguous, ownership = [], [], [], {}
    for chunk in document["chunks"]:
        if chunk["type"] not in ("paragraph", "list_item") and not chunk.get("callout_id"):
            continue
        all_refs = [(span["page"], key) for span in chunk["spans"] for key in span["block_ids"]]
        if any(n == page["page"] and key in unplaced for n, key in all_refs):
            ambiguous.append(chunk["chunk_id"])
        inside = [key for n, key in all_refs if n == page["page"] and key in ids]
        if not inside:
            continue
        if len(inside) != len(all_refs):
            crossing.append(chunk["chunk_id"])
            continue
        for key in inside:
            _require(key not in ownership, "A source line is projected by more than one chunk")
            ownership[key] = chunk
        selected.append((chunk, inside))
    return selected, ownership, bboxes, {"crossing_chunk_ids": crossing, "partial_source_ids": partial,
                                        "unplaced_chunk_ids": ambiguous}


def _quote_metrics(quote_boxes, selected, ownership, bboxes):
    alignment, ambiguous = {}, []
    for key, box in bboxes.items():
        overlaps = {region: _intersection(box, qbox) / _area(box) for region, qbox in quote_boxes.items()}
        touched = [region for region, fraction in overlaps.items() if fraction > 0]
        if len(touched) == 1 and overlaps[touched[0]] >= .8:
            alignment[key] = touched[0]
        elif touched:
            ambiguous.append(key)
    if ambiguous:
        return {"status": "NOT_EVALUATED", "reason": "AMBIGUOUS_QUOTE_SOURCE_OVERLAP", "ambiguous_source_ids": ambiguous,
                "reference_quote_regions": len(quote_boxes), "inserted_quote_regions": None, "false_detached_chunks": None,
                "regions": []}
    regions, claimed, false_detached = [], set(), []
    for chunk, ids in selected:
        if not chunk.get("callout_id"):
            continue
        targets = {alignment.get(key) for key in ids}
        if len(targets) != 1 or None in targets or targets & claimed:
            false_detached.append(chunk["chunk_id"])
        else:
            claimed.update(targets)
    for region in quote_boxes:
        observed = sorted(key for key, target in alignment.items() if target == region)
        body = [key for key in observed if key in ownership and not ownership[key].get("callout_id")]
        detached = [key for key in observed if key in ownership and ownership[key].get("callout_id")]
        missing = sorted(set(observed) - ownership.keys())
        detached_chunks = {ownership[key]["chunk_id"] for key in detached}
        status = ("INSERTED_IN_BODY" if body else "MISSING_OUTPUT" if not observed or missing else
                  "SEPARATED_OBSERVED_SOURCE" if len(detached_chunks) == 1 and not detached_chunks.intersection(false_detached)
                  else "INCONSISTENT_DETACHMENT")
        regions.append({"id": region, "status": status, "observed_source_ids": observed, "body_source_ids": body,
                        "detached_source_ids": detached, "unprojected_source_ids": missing})
    inserted = sum(row["status"] == "INSERTED_IN_BODY" for row in regions)
    return {"status": "EVALUATED_DEVELOPMENT_GEOMETRY", "reference_quote_regions": len(regions),
            "inserted_quote_regions": inserted, "insertion_rate_per_reference_region": inserted / len(regions) if regions else None,
            "separated_observed_regions": sum(row["status"] == "SEPARATED_OBSERVED_SOURCE" for row in regions),
            "missing_quote_regions": sum(row["status"] == "MISSING_OUTPUT" for row in regions),
            "false_detached_chunks": len(false_detached), "false_detached_chunk_ids": false_detached, "regions": regions}


def evaluate_window(page, document, record, body_reference):
    _require(all(page[key] == record[key] for key in FRAME_FIELDS), "Callout annotation coordinate frame differs from extraction")
    window = record["window_bbox"]
    _require(valid_bbox(window) and _contains([0, 0, page["width"], page["height"]], window),
             "Callout window is outside the source page")
    boxes = _quote_boxes(record["quote_regions"], window)
    selected, ownership, bboxes, gaps = _project(page, document, window)
    body = [chunk for chunk, _ in selected if not chunk.get("callout_id")]
    text = "\n\n".join(chunk["text_corrected"] for chunk in body)
    reason = ("OUTPUT_LOCATION_UNKNOWN" if gaps["unplaced_chunk_ids"] else
              "OUTPUT_CROSSES_WINDOW" if any(gaps.values()) else None)
    quote_reason = reason or ("MISSING_QUOTE_LABELS" if boxes is None else None)
    quote = ({"status": "NOT_EVALUATED", "reason": quote_reason, "inserted_quote_regions": None, "false_detached_chunks": None}
             if quote_reason else _quote_metrics(boxes, selected, ownership, bboxes))
    cer_reason = reason or ("MISSING_BODY_REFERENCE" if body_reference is None else None)
    if cer_reason is None and (len(body_reference) + 1) * (len(text) + 1) > MAX_CER_CELLS:
        cer_reason = "CER_WINDOW_SIZE_LIMIT"
    cer = ({"status": "NOT_EVALUATED", "reason": cer_reason, "cer": None} if cer_reason else
           compute_cer_detailed(body_reference, text, normalization_policy="visible_strict_v1"))
    return {"quote_ownership": quote, "body_text_score": cer, "body_chunk_ids": [chunk["chunk_id"] for chunk in body],
            "body_projection_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), **gaps}


def _read(path):
    data = path.read_bytes()
    return json.loads(data, object_pairs_hook=_unique_object), hashlib.sha256(data).hexdigest()


def evaluate_publication(plan_path, batch):
    from .canonical_predictions import collect_predictions

    plan, plan_hash = _read(plan_path)
    _require(plan.get("schema_version") == SCHEMA and plan.get("partition") == "development"
             and plan.get("reference_origin") in ("DEVELOPMENT_OBSERVATION", "DECLARED_HUMAN_ADJUDICATED"),
             "Expected a development callout plan with declared reference origin")
    records = plan["windows"]
    ids = [record["id"] for record in records]
    _require(ids and all(isinstance(key, str) and key for key in ids) and len(set(ids)) == len(ids),
             "Callout windows require unique IDs")
    publication = collect_predictions([batch])
    inventory = {row["id"]: row for row in publication["documents"]}
    cache, result, paths = {}, [], {plan_path: plan_hash}
    for record in records:
        identity = inventory[record["document_id"]]
        _require(record["pdf_sha256"] == identity["pdf_sha256"], "Callout reference PDF differs from prediction")
        if record["document_id"] not in cache:
            directory = Path(identity["source_dir"])
            complete, complete_hash = _read(directory / "COMPLETED.json")
            _require(complete_hash == identity["completion_sha256"], "Callout publication changed during evaluation")
            paths[directory / "COMPLETED.json"] = complete_hash
            documents = []
            for filename in ("extraction.json", "document.json"):
                path = directory / filename
                value, digest = _read(path)
                _require(digest == complete["files"][filename], "Callout source artifacts differ from completion receipt")
                paths[path] = digest
                documents.append(value)
            cache[record["document_id"]] = ({page["page"]: page for page in documents[0]["pages"]}, documents[1])
        pages, document = cache[record["document_id"]]
        artifact, text = record["body_reference"], None
        if artifact is not None:
            _require(plan["reference_origin"] == "DECLARED_HUMAN_ADJUDICATED", "Body CER requires a declared adjudicated human reference")
            relative = Path(artifact["path"])
            target = (plan_path.parent / relative).resolve()
            _require(not relative.anchor and target.is_relative_to(plan_path.parent), "Body reference escapes the plan directory")
            data = target.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            _require(digest == artifact["sha256"] and paths.get(target, digest) == digest, "Body reference SHA-256 differs")
            paths[target] = digest
            text = data.decode("utf-8")
        result.append({"id": record["id"], "document_id": record["document_id"], "page": record["page"],
                       "completion_sha256": identity["completion_sha256"], **evaluate_window(pages[record["page"]], document, record, text)})
    _require(all(sha256_file(path) == digest for path, digest in paths.items()), "Callout inputs changed during evaluation")
    return {"method": METHOD, "partition": "development", "quality_acceptance_status": "NOT_EVALUATED",
            "reference_origin": plan["reference_origin"], "plan_sha256": plan_hash,
            "evaluator_sha256": sha256_file(Path(__file__)), "publication": publication["batches"], "windows": result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("plan", "batch", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        output, batch = args.output.resolve(), args.batch.resolve()
        _require(not output.exists() and not output.is_relative_to(batch), "Use a new report path outside the source batch")
        report = evaluate_publication(args.plan.resolve(), batch)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Callout diagnostics: {len(report['windows'])} windows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
