"""Freeze a source-only annotation worklist for periodic OCR drift review."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file

from .canonical_predictions import collect_predictions
from .degradation_metric import _unique_object
from .stratified_scorecard import _hash, _require

PLAN_SCHEMA = "ocr-drift-sampling-plan-v1"
FRAME_SCHEMA = "ocr-drift-sampling-frame-v1"
METHOD = "sha256-stratified-source-pages-v1"


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def validate_drift_plan(plan):
    strata = plan.get("strata")
    _require(plan.get("schema_version") == PLAN_SCHEMA and _text(plan.get("owner"))
             and type(plan.get("interval_days")) is int and plan["interval_days"] > 0
             and type(plan.get("minimum_documents")) is int and plan["minimum_documents"] > 0
             and isinstance(strata, list) and strata and all(_text(value) for value in strata)
             and len(strata) == len({value.casefold() for value in strata})
             and _text(plan.get("escalation_trigger")) and plan.get("independent_annotation_required") is True,
             "Drift plan requires a scheduled sample, distinct strata, independent labels and escalation")


def _time(value):
    when = datetime.fromisoformat(value)
    _require(when.utcoffset() is not None, "Drift dates must include a timezone")
    return when.astimezone(timezone.utc)


def _read_pinned(path, digest, schema):
    raw = path.read_bytes()
    _require(_hash(digest) and hashlib.sha256(raw).hexdigest() == digest, f"Frozen SHA-256 mismatch: {path}")
    data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    _require(isinstance(data, dict) and data.get("schema_version") == schema, f"Expected {schema}: {path}")
    return data


def select_worklist(plan, plan_hash, frame, inventory):
    """Rank PDF identities and physical pages, with no prediction-derived signals."""
    validate_drift_plan(plan)
    _require(frame["plan_sha256"] == plan_hash and _hash(plan_hash), "Sampling frame belongs to a different plan")
    start = _time(frame["period_start"])
    end = start + timedelta(days=plan["interval_days"])
    purpose, curator = frame["purpose"], frame["curator"]
    _require(purpose in ("DEVELOPMENT_DRY_RUN", "MONITORING") and _text(curator), "Invalid drift frame purpose or curator")
    if purpose == "MONITORING":
        _require(plan.get("status") == "LOCKED" and _text(plan.get("approved_by"))
                 and _time(plan["locked_at"]) <= start, "Monitoring requires a plan locked before the period")

    pages_per_doc, min_new = frame["pages_per_document"], frame["minimum_new_documents"]
    _require(type(pages_per_doc) is int and pages_per_doc > 0 and type(min_new) is int and min_new >= 0,
             "Drift frame requires explicit page and new-document sample sizes")
    previous = frame["previous_pdf_sha256"]
    _require(isinstance(previous, list) and all(_hash(value) for value in previous)
             and len(set(previous)) == len(previous), "Previous PDF inventory must carry distinct SHA-256 values")
    previous = set(previous)
    by_id = {row["id"]: row for row in inventory["documents"]}
    dispositions = frame["documents"]
    _require(isinstance(dispositions, dict) and dispositions.keys() == by_id.keys(),
             "Frame must account for every verified publication PDF")

    strata = {name: [] for name in plan["strata"]}
    eligible, excluded = [], []
    for key, row in dispositions.items():
        pdf = by_id[key]
        _require(row["pdf_sha256"] == pdf["pdf_sha256"], f"Frame PDF hash differs: {key}")
        tag, reason = row["stratum"], row["exclusion_reason"]
        if tag is None:
            _require(_text(reason), f"Exclusion requires a reason: {key}")
            excluded.append({"document_id": key, "pdf_sha256": pdf["pdf_sha256"], "reason": reason})
            continue
        _require(isinstance(tag, str) and tag in strata and reason is None, f"Invalid stratum: {key}")
        item = {"document_id": key, "pdf_sha256": pdf["pdf_sha256"], "pdf_path": pdf["pdf_path"],
                "total_pages": pdf["total_pages"], "stratum": tag, "new_to_supplied_history": pdf["pdf_sha256"] not in previous}
        strata[tag].append(item)
        eligible.append(item)

    period = start.isoformat()

    def rank(pdf_sha256, page):
        return sha256_json_compact([METHOD, plan_hash, period, pdf_sha256, page])

    ordered = sorted(eligible, key=lambda item: rank(item["pdf_sha256"], None))
    picked = {}
    for tag in plan["strata"]:
        first = next((item for item in ordered if item["stratum"] == tag), None)
        if first is not None:
            picked[first["document_id"]] = first
    new_picked = sum(item["new_to_supplied_history"] for item in picked.values())
    for item in ordered:
        if new_picked >= min_new:
            break
        if item["new_to_supplied_history"] and item["document_id"] not in picked:
            picked[item["document_id"]] = item
            new_picked += 1
    for item in ordered:
        if len(picked) >= plan["minimum_documents"]:
            break
        picked[item["document_id"]] = item

    shortfall = {"documents": max(0, plan["minimum_documents"] - len(picked)),
                 "new_documents": max(0, min_new - sum(item["new_to_supplied_history"] for item in picked.values())),
                 "unrepresented_strata": [tag for tag, members in strata.items() if not members]}
    chosen = []
    for item in picked.values():
        pages = sorted(range(1, item["total_pages"] + 1), key=lambda page: rank(item["pdf_sha256"], page))
        chosen.append({**item, "pages": sorted(pages[:pages_per_doc])})
    return {"schema_version": "ocr-drift-sampling-worklist-v1", "method": METHOD, "purpose": purpose,
            "status": "INSUFFICIENT_FRAME" if any(shortfall.values()) else "SAMPLE_PREPARED",
            "quality_acceptance_status": "NOT_EVALUATED", "independent_annotations": "PENDING",
            "plan_sha256": plan_hash, "period_start_utc": period, "period_end_utc": end.isoformat(),
            "minimum_documents": plan["minimum_documents"], "minimum_new_documents": min_new,
            "pages_per_document": pages_per_doc, "eligible_by_stratum": {tag: len(rows) for tag, rows in strata.items()},
            "excluded": sorted(excluded, key=lambda item: item["document_id"]), "shortfall": shortfall, "selected": chosen}


def prepare_sample(plan_path, plan_hash, frame_path, frame_hash, batches, output):
    batches = [Path(path).resolve() for path in batches]
    output = Path(output).resolve()
    _require(not output.exists() and not any(output.is_relative_to(root) for root in batches)
             and not any((parent / name).is_file() for parent in output.parents
                         for name in ("batch_input_manifest.json", "COMPLETED.json")),
             "Use a new worklist directory outside published batches")
    plan = _read_pinned(plan_path, plan_hash, PLAN_SCHEMA)
    frame = _read_pinned(frame_path, frame_hash, FRAME_SCHEMA)
    inventory = collect_predictions(batches)
    report = select_worklist(plan, plan_hash, frame, inventory)
    _require(sha256_file(plan_path) == plan_hash and sha256_file(frame_path) == frame_hash,
             "Sampling inputs changed during preparation")
    report.update(frame_sha256=frame_hash, publication_inventory_sha256=sha256_json_compact(inventory),
                  batch_publications=inventory["batches"], sampler_sha256=sha256_file(Path(__file__)))
    output.mkdir(parents=True, exist_ok=False)
    packets = {}
    if report["status"] == "SAMPLE_PREPARED":
        units = [{"document_id": row["document_id"], "pdf_sha256": row["pdf_sha256"], "pdf_path": row["pdf_path"],
                  "page": page, "transcript": None, "critical_observations": None}
                 for row in report["selected"] for page in row["pages"]]
        selection = sha256_json_compact(report["selected"])
        for role in ("A", "B"):
            path = output / f"annotation_{role}.blank.json"
            atomic_write_json(path, {"schema_version": "ocr-drift-annotation-template-v1", "status": "BLANK", "role": role,
                                     "frame_sha256": frame_hash, "selection_sha256": selection, "annotator": None,
                                     "completed_at": None, "independent_from_other_annotator": None, "units": units})
            packets[role] = {"path": path.name, "sha256": sha256_file(path)}
    report["blank_annotation_packets"] = packets
    atomic_write_json(output / "worklist.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("plan", "frame", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ("plan-sha256", "frame-sha256"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--batch", type=Path, nargs="+", required=True)
    args = parser.parse_args(argv)
    try:
        report = prepare_sample(args.plan, args.plan_sha256, args.frame, args.frame_sha256, args.batch, args.output)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(report["status"])
    return int(report["status"] != "SAMPLE_PREPARED")


if __name__ == "__main__":
    raise SystemExit(main())
