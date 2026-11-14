"""Build and reconcile blind rechecks of sealed diacritic adjudication."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.adjudicate_text_layer_diacritics import (  # noqa: E402
    SEAL_SCHEMA, check_measurement_lock, check_records,
)
from scripts.screen_text_layer import dumps, recheck_sample, sha256_bytes  # noqa: E402

BANGKOK = timezone(timedelta(hours=7))


def _timestamp(value):
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() != BANGKOK.utcoffset(None):
        raise ValueError("Review timestamps must use Asia/Bangkok (+07:00)")
    return timestamp


def _local_file(root, name):
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"Review file escapes its directory: {name}")
    return target


def _sealed_jsonl(path, expected_sha256=None):
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Adjudication decisions changed after sealing")
    return [json.loads(line) for line in raw.splitlines() if line.strip()], digest


def _locked_sample(sheet_dir, seal_path):
    sheet_bytes = (sheet_dir / "sheet.json").read_bytes()
    seal_bytes = seal_path.read_bytes()
    sheet, seal = map(json.loads, (sheet_bytes, seal_bytes))
    if (seal["schema_version"] != SEAL_SCHEMA or seal["sheet_id"] != sheet["sheet_id"]
            or seal["sheet_sha256"] != sha256_bytes(sheet_bytes)
            or seal["measurement"] != sheet["measurement"]):
        raise ValueError("Adjudication seal differs from the source sheet")
    sealed_path = _local_file(seal_path.parent, seal["sealed_file"])
    records, _ = _sealed_jsonl(sealed_path, seal["sealed_sha256"])
    problems = check_records(sheet, records, allow_missing=True)
    ids = {record["decision_id"] for record in records}
    if (problems or len(records) != seal["items"] or not ids or len(ids) != len(records)
            or any(not key for key in ids) or any(r["sheet_id"] != sheet["sheet_id"] for r in records)):
        raise ValueError("Sealed decisions must be unique and bound to the source sheet")
    measurement_path = Path(sheet["measurement"]["path"])
    measurement_bytes = measurement_path.read_bytes()
    if sha256_bytes(measurement_bytes) != sheet["measurement"]["sha256"]:
        raise ValueError("Measurement changed after adjudication")
    measurement = json.loads(measurement_bytes)
    check_measurement_lock(measurement)
    procedure = ROOT / measurement["lock"]["path"]
    locked = procedure.read_bytes()
    if sha256_bytes(locked) != measurement["lock"]["sha256"]:
        raise ValueError("The source procedure lock changed")
    seed = json.loads(locked)["parameters"]["seed"]
    chosen = set(recheck_sample(ids, seed))
    previous = {record["item_id"]: record for record in records}
    selected = [item for item in sheet["items"] if previous.get(item["item_id"], {}).get("decision_id") in chosen]
    if len(selected) != len(chosen):
        raise ValueError("Recheck sample differs from the original decisions")
    return sheet, seal, selected, previous, sha256_bytes(seal_bytes)


def _review_manifest(sheet, seal_hash, selected, stage):
    item_keys = {item["image"] for item in selected}
    return {**sheet, "mode": "adjudication_recheck", "review_round": stage,
            "sheet_id": sha256_bytes(dumps([seal_hash, stage, [item["item_id"] for item in selected]]))[:16],
            "pages": {key: info for key, info in sheet["pages"].items() if key in item_keys},
            "items": selected}


def _build_sheet(sheet_dir, out, manifest):
    public = {key: manifest[key] for key in ("sheet_id", "reviewer", "choices", "pages", "items", "tool_commit")}
    template = (ROOT / "benchmark/ground_truth_tools/adjudication_sheet.html").read_text(encoding="utf-8")
    html = template.replace("/*__SHEET__*/null", json.dumps(public, ensure_ascii=False).replace("</", "<\\/"))
    images = {}
    for page in manifest["pages"].values():
        file = _local_file(sheet_dir, page["image"])
        if sha256_bytes(file.read_bytes()) != page["image_sha256"]:
            raise ValueError(f"Source image changed: {file}")
        images[page["image"]] = (file, page["image_sha256"])
    out.mkdir(parents=True, exist_ok=False)
    for name, (file, digest) in images.items():
        content = file.read_bytes()
        if sha256_bytes(content) != digest:
            raise ValueError(f"Source image changed: {file}")
        path = _local_file(out, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (out / "sheet.json").write_bytes(dumps(manifest))
    (out / "index.html").write_text(html, encoding="utf-8", newline="\n")


def build_recheck(sheet_dir, seal_path, out):
    sheet, seal, selected, previous, seal_hash = _locked_sample(sheet_dir, seal_path)
    manifest = _review_manifest(sheet, seal_hash, selected, 2)
    manifest["review_not_before"] = _recheck_earliest(seal, previous).isoformat()
    _build_sheet(sheet_dir, out, manifest)
    return manifest


def _check_answers(manifest, path, earliest):
    records, digest = _sealed_jsonl(path)
    problems = check_records(manifest, records)
    if problems or any(record.get("sheet_id") != manifest["sheet_id"]
                       or not record.get("decision_id") for record in records):
        raise ValueError("Decisions do not match this blind review round")
    if any(_timestamp(record["decided_at"]) < earliest for record in records):
        raise ValueError("Recheck decisions must follow the seven-day interval or the preceding review")
    return {record["item_id"]: record for record in records}, digest


def _recheck_earliest(seal, previous):
    return max(_timestamp(seal["sealed_at"]),
               max(_timestamp(record["decided_at"]) for record in previous.values())) + timedelta(days=7)


def _verdict(record):
    if record["choice"] == "BOTH_WRONG":
        return record["choice"], unicodedata.normalize("NFC", record["corrected_text"].strip())
    return record["choice"], ""


def resolve_recheck(sheet_dir, seal_path, recheck_path, out, *, third_path=None):
    sheet, seal, selected, first, seal_hash = _locked_sample(sheet_dir, seal_path)
    review = _review_manifest(sheet, seal_hash, selected, 2)
    earliest = _recheck_earliest(seal, first)
    second, second_hash = _check_answers(review, recheck_path, earliest)
    differences = [item for item in selected if _verdict(first[item["item_id"]]) != _verdict(second[item["item_id"]])]
    report = {"schema_version": "ocr-v8-diacritic-adjudication-recheck-v1", "parent_seal_sha256": seal_hash,
              "review_tool_sha256": sha256_bytes(Path(__file__).read_bytes()),
              "recheck_sha256": second_hash, "rechecked": len(selected),
              "quality_acceptance": "NOT_EVALUATED", "review_not_before": earliest.isoformat(),
              "agreements": len(selected) - len(differences), "agreement": 1 - len(differences) / len(selected),
              "needs_third_review": [item["item_id"] for item in differences]}
    third = {}
    if differences:
        followup = _review_manifest(sheet, seal_hash + report["recheck_sha256"], differences, 3)
        if third_path is None:
            _build_sheet(sheet_dir, out, followup)
            report["status"] = "THIRD_REVIEW_REQUIRED"
            (out / "agreement.json").write_bytes(dumps(report))
            return report
        third, report["third_sha256"] = _check_answers(
            followup, third_path, max(_timestamp(r["decided_at"]) for r in second.values()),
        )
    elif third_path is not None:
        raise ValueError("The second round has no disagreements to review")
    final = dict(first)
    unresolved = []
    for key, record in third.items():
        agreed = _verdict(record) in (_verdict(first[key]), _verdict(second[key]))
        if not agreed:
            unresolved.append(key)
        final[key] = {**record, "sheet_id": sheet["sheet_id"], "decision_id": f"{key}#recheck3",
                      "choice": record["choice"] if agreed else "UNRESOLVED",
                      "corrected_text": record.get("corrected_text") if agreed else None,
                      "recheck_decision_ids": [first[key]["decision_id"], second[key]["decision_id"], record["decision_id"]]}
    out.mkdir(parents=True, exist_ok=False)
    raw = "".join(json.dumps(final[key], ensure_ascii=False) + "\n" for key in sorted(final)).encode("utf-8")
    (out / "decisions-reconciled.jsonl").write_bytes(raw)
    report.update(status="RECONCILED", unresolved_after_third=unresolved, reconciled_sha256=sha256_bytes(raw))
    (out / "agreement.json").write_bytes(dumps(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "resolve"))
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--sealed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--recheck-decisions", type=Path)
    parser.add_argument("--third-decisions", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            if args.recheck_decisions or args.third_decisions:
                parser.error("Build uses the sealed first round only")
            report = build_recheck(args.sheet, args.sealed, args.out)
            print(f"{len(report['items'])} blind recheck items, review from {report['review_not_before']} -> {args.out}")
        else:
            if args.recheck_decisions is None:
                parser.error("Resolve requires --recheck-decisions")
            report = resolve_recheck(args.sheet, args.sealed, args.recheck_decisions, args.out,
                                     third_path=args.third_decisions)
            print(f"{report['status']} -> {args.out}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
