#!/usr/bin/env python3
"""Screening sheets for the text-layer reference (GROUND_TRUTH_PROTOCOL section 7.4 B, D, E).

The operator builds the sheet; only the reviewer decides. Nothing here reads OCR
output, and no decision is pre-filled.

  build    Render the pages of one PDF in the locked order and write an offline HTML
           sheet. Every visible text-layer word that carries a diacritic slot is a
           unit. Words that are not fully visible (section 7.3 condition 3) are listed
           apart and leave the denominator.
  seal     Check the reviewer's JSONL export against the sheet, copy it to a sealed
           file named by its sha256 and give the verdict for the PDF: ACCEPTED when
           0 MISMATCH over at least the locked minimum of MATCH slots, REJECTED on any
           confirmed MISMATCH, otherwise INCOMPLETE.
  recheck  Build a blind re-check sheet: 10% of sealed decisions, at least 50, chosen
           by ascending sha256(seed:recheck:<decision_id>). Old decisions are not shown.

  python scripts/screen_text_layer.py build --lock <lock.json> --pdf-root inputs --pdf AAA.pdf --out scratch/v8/screening/<new>
  python scripts/screen_text_layer.py seal --sheet scratch/v8/screening/<sheet> --decisions <export.jsonl> --out scratch/v8/screening/<sealed>
  python scripts/screen_text_layer.py recheck --sheet <sheet> --sealed <sealed>/seal.json --out scratch/v8/screening/<recheck>
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.ground_truth_tools import text_layer_reference as tlr  # noqa: E402

SHEET_SCHEMA = "ocr-v8-text-layer-screening-sheet-v1"
RECORD_SCHEMA = "ocr-v8-text-layer-screening-decision-v1"
SEAL_SCHEMA = "ocr-v8-text-layer-screening-seal-v1"
SHEET_ZOOM = 3.0  # 216 DPI, enough to read a tone mark at body size
CROP_PAD_POINTS = 2.0
DECISIONS = ("MATCH", "MISMATCH", "UNRESOLVED")
CAUSES = ("TO_UNICODE", "EMBEDDED_FONT", "SUBSTITUTED_CHAR", "MISSING_MARK", "EXTRA_MARK", "HIDDEN_TEXT")
RECHECK_SHARE = 0.10
RECHECK_MINIMUM = 50
TIMEZONE = "+07:00"  # Asia/Bangkok (section 7.4 E)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_new(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"{path} exists; screening files are never overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def dumps(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")


def tool_commit() -> Dict:
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    status = git("status", "--porcelain", "--", "scripts/screen_text_layer.py", "benchmark/ground_truth_tools")
    return {"head": git("rev-parse", "HEAD"), "tool_files_dirty": bool(status) if status is not None else None}


def lock_document(lock: Dict, pdf_name: str) -> Dict:
    for document in lock["documents"]:
        if document["pdf"] == pdf_name:
            return document
    raise ValueError(f"{pdf_name} is not in the lock")


def page_order(document: Dict, pages: Optional[int], skip: int) -> List[int]:
    screening = document.get("screening") or {}
    if document.get("eligibility") != "SCREENING_REQUIRED" or not screening.get("order"):
        raise ValueError(f"{document['pdf']} needs no screening under this lock ({document.get('eligibility')})")
    count = len(screening["worklist"]) if pages is None else pages
    selected = screening["order"][skip:skip + count]
    if not selected:
        raise ValueError("the requested range of the locked order is empty")
    return selected


def crop_box(bbox: Sequence[float], page, zoom: float, width: int, height: int):
    padded = (bbox[0] - CROP_PAD_POINTS, bbox[1] - CROP_PAD_POINTS, bbox[2] + CROP_PAD_POINTS, bbox[3] + CROP_PAD_POINTS)
    return tlr.pixel_box(page, padded, zoom, width, height)


def build_sheet(lock_path: Path, pdf_root: Path, pdf_name: str, out: Path, reviewer: str,
                pages: Optional[int] = None, skip: int = 0) -> Dict:
    import numpy
    import pymupdf

    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    document = lock_document(lock, pdf_name)
    pdf_bytes = (pdf_root / pdf_name).read_bytes()
    pdf_sha = sha256_bytes(pdf_bytes)
    if pdf_sha != document["sha256"]:
        raise ValueError(f"{pdf_name}: sha256 {pdf_sha} differs from the lock")
    order = page_order(document, pages, skip)
    if out.exists():
        raise FileExistsError(f"{out} exists; build a new sheet directory")
    (out / "pages").mkdir(parents=True)
    sheet_pages, units, excluded = [], [], []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        for rank, number in enumerate(order, start=skip + 1):
            data = tlr.page_units(pdf_bytes, number)
            page = pdf[number - 1]
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(SHEET_ZOOM, SHEET_ZOOM), alpha=False, colorspace=pymupdf.csRGB)
            pixels = numpy.frombuffer(pixmap.samples, dtype=numpy.uint8).reshape(pixmap.height, pixmap.width, 3)
            image_name = f"pages/p{number:04d}.png"
            png = pixmap.tobytes("png")
            write_new(out / image_name, png)
            page_units = 0
            for line in data["lines"]:
                for word in line.words:
                    if not word.slots:
                        continue
                    record = {"unit_id": f"{pdf_sha[:16]}:p{number:04d}:{word.word_id}", "page": number,
                              "line_id": word.line_id, "text_layer": word.text, "slots": word.slots,
                              "bbox": list(word.bbox), "char_start": word.char_start, "char_end": word.char_end,
                              "visibility": word.visibility}
                    if word.visibility != "VISIBLE":
                        excluded.append(record)
                        continue
                    box = crop_box(word.bbox, page, SHEET_ZOOM, pixmap.width, pixmap.height)
                    crop = numpy.ascontiguousarray(pixels[box[1]:box[3], box[0]:box[2]])
                    record.update({"crop_px": list(box), "crop_sha256": sha256_bytes(crop.tobytes()),
                                   "line_text": line.text, "line_bbox": list(line.bbox)})
                    units.append(record)
                    page_units += 1
            sheet_pages.append({"page": number, "order_rank": rank, "image": image_name, "image_sha256": sha256_bytes(png),
                                "image_size": [pixmap.width, pixmap.height], "zoom": SHEET_ZOOM,
                                "rotation_matrix": list(page.rotation_matrix), "canonical_text_sha256": data["canonical_text_sha256"],
                                "slots": data["slots"], "visible_slots": data["visible_slots"], "units": page_units})
    sheet_id = sha256_bytes(f"{pdf_sha}:{','.join(map(str, order))}:{tlr.VISIBILITY_METHOD}".encode())[:16]
    manifest = {
        "schema_version": SHEET_SCHEMA, "mode": "screening", "sheet_id": sheet_id,
        "protocol": "docs/quality_assurance/GROUND_TRUTH_PROTOCOL.md#7.4",
        "lock": {"path": lock_path.as_posix(), "sha256": sha256_bytes(lock_bytes), "seed": lock["parameters"]["seed"],
                 "minimum_slots": document["screening"]["minimum_slots"]},
        "pdf": pdf_name, "pdf_sha256": pdf_sha, "producer": document.get("producer"),
        "order_range": [skip, skip + len(order)], "reviewer": reviewer, "tool_commit": tool_commit(),
        "created_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds"),
        "visibility_method": tlr.VISIBILITY_METHOD, "decisions": list(DECISIONS), "causes": list(CAUSES),
        "pages": sheet_pages, "units": units, "excluded_not_visible": excluded,
        "totals": {"units": len(units), "slots": sum(u["slots"] for u in units),
                   "excluded_units": len(excluded), "excluded_slots": sum(u["slots"] for u in excluded)},
        "gt_status": "NOT_VERIFIED", "quality_acceptance": "NOT_EVALUATED",
    }
    write_new(out / "sheet.json", dumps(manifest))
    write_new(out / "index.html", render_html(manifest).encode("utf-8"))
    return manifest


def render_html(manifest: Dict) -> str:
    template = (ROOT / "benchmark" / "ground_truth_tools" / "screening_sheet.html").read_text(encoding="utf-8")
    public = {key: manifest[key] for key in ("sheet_id", "mode", "pdf", "pdf_sha256", "reviewer", "decisions", "causes",
                                             "pages", "units", "totals", "tool_commit")}
    public["lock"] = {"sha256": manifest["lock"]["sha256"], "minimum_slots": manifest["lock"]["minimum_slots"]}
    payload = json.dumps(public, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("/*__SHEET__*/null", payload)


def read_jsonl(paths: Iterable[Path]) -> List[Dict]:
    records = []
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{number}: not JSON ({error})") from None
    return records


def check_records(manifest: Dict, records: List[Dict]) -> List[str]:
    units = {unit["unit_id"]: unit for unit in manifest["units"]}
    problems, seen = [], {}
    for index, record in enumerate(records, start=1):
        where = f"record {index}"
        if record.get("schema_version") != RECORD_SCHEMA:
            problems.append(f"{where}: schema_version {record.get('schema_version')!r}")
        unit = units.get(record.get("unit_id"))
        if unit is None:
            problems.append(f"{where}: unit {record.get('unit_id')!r} is not on the sheet")
            continue
        for key in ("pdf_sha256",):
            if record.get(key) != manifest[key]:
                problems.append(f"{where}: {key} differs from the sheet")
        for key in ("page", "crop_sha256", "char_start", "char_end", "text_layer", "slots"):
            if record.get(key) != unit[key]:
                problems.append(f"{where}: {key} differs from the sheet unit")
        if record.get("decision") not in DECISIONS:
            problems.append(f"{where}: decision {record.get('decision')!r}")
        if record.get("decision") == "MISMATCH" and record.get("cause") not in CAUSES:
            problems.append(f"{where}: MISMATCH needs a cause from {CAUSES}")
        if record.get("decision") != "MISMATCH" and record.get("cause") is not None:
            problems.append(f"{where}: cause is only for MISMATCH")
        if not record.get("reviewer"):
            problems.append(f"{where}: reviewer missing")
        stamp = record.get("decided_at") or ""
        if not stamp.endswith(TIMEZONE):
            problems.append(f"{where}: decided_at {stamp!r} is not Asia/Bangkok ({TIMEZONE})")
        if not record.get("decision_id"):
            problems.append(f"{where}: decision_id missing")
        previous = seen.get(record.get("unit_id"))
        if previous is not None:
            problems.append(f"{where}: unit {record['unit_id']} decided twice (records {previous} and {index})")
        seen[record.get("unit_id")] = index
    return problems


def verdict(manifest: Dict, records: List[Dict]) -> Dict:
    """Section 7.4 B: walk the pages in locked order; MATCH slots count, UNRESOLVED do not."""
    by_unit = {record["unit_id"]: record for record in records}
    minimum = manifest["lock"]["minimum_slots"]
    pages, match_slots, mismatches, unresolved_slots = [], 0, [], 0
    complete_prefix = True
    for page in manifest["pages"]:
        units = [unit for unit in manifest["units"] if unit["page"] == page["page"]]
        decided = [by_unit[u["unit_id"]] for u in units if u["unit_id"] in by_unit]
        page_match = sum(r["slots"] for r in decided if r["decision"] == "MATCH")
        page_unresolved = sum(r["slots"] for r in decided if r["decision"] == "UNRESOLVED")
        page_mismatch = [r for r in decided if r["decision"] == "MISMATCH"]
        complete = len(decided) == len(units)
        pages.append({"page": page["page"], "units": len(units), "decided": len(decided), "complete": complete,
                      "match_slots": page_match, "unresolved_slots": page_unresolved, "mismatch_units": len(page_mismatch)})
        mismatches.extend(page_mismatch)
        if complete_prefix and complete:
            match_slots += page_match
            unresolved_slots += page_unresolved
        else:
            complete_prefix = False
    causes: Dict[str, int] = {}
    for record in mismatches:
        causes[record["cause"]] = causes.get(record["cause"], 0) + 1
    if mismatches:
        status = "REJECTED"
    elif match_slots >= minimum:
        status = "ACCEPTED"
    else:
        status = "INCOMPLETE"
    return {"status": status, "minimum_slots": minimum, "match_slots_complete_pages": match_slots,
            "unresolved_slots_complete_pages": unresolved_slots, "mismatch_units": len(mismatches),
            "mismatch_causes": causes, "pages": pages,
            "text_layer_error_upper_bound_95": round(1 - 0.05 ** (1 / match_slots), 6) if status == "ACCEPTED" else None}


def seal(sheet_dir: Path, decision_paths: List[Path], out: Path) -> Dict:
    manifest_bytes = (sheet_dir / "sheet.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("mode") != "screening":
        raise ValueError("seal takes a screening sheet; use the re-check report for a re-check sheet")
    records = read_jsonl(decision_paths)
    problems = check_records(manifest, records)
    if problems:
        raise ValueError("decisions do not match the sheet:\n  " + "\n  ".join(problems[:40]))
    records.sort(key=lambda record: (record["page"], record["unit_id"]))
    sealed_bytes = b"".join(json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n" for record in records)
    sealed_sha = sha256_bytes(sealed_bytes)
    if out.exists():
        raise FileExistsError(f"{out} exists; a sealed record is never rewritten")
    write_new(out / f"decisions-{sealed_sha[:16]}.jsonl", sealed_bytes)
    stamps = sorted(record["decided_at"] for record in records)
    report = {
        "schema_version": SEAL_SCHEMA, "sheet_id": manifest["sheet_id"], "sheet_sha256": sha256_bytes(manifest_bytes),
        "lock": manifest["lock"], "pdf": manifest["pdf"], "pdf_sha256": manifest["pdf_sha256"],
        "producer": manifest.get("producer"), "sources": [{"path": p.as_posix(), "sha256": sha256_bytes(p.read_bytes())}
                                                         for p in decision_paths],
        "sealed_file": f"decisions-{sealed_sha[:16]}.jsonl", "sealed_sha256": sealed_sha, "records": len(records),
        "reviewers": sorted({record["reviewer"] for record in records}), "decided_between": [stamps[0], stamps[-1]] if stamps else None,
        "tool_commits": sorted({json.dumps(record.get("tool_commit"), sort_keys=True) for record in records}),
        "excluded_not_visible": manifest["totals"]["excluded_units"], "verdict": verdict(manifest, records),
        "next_step": "record sealed_sha256 in the next lock version (section 7.4 E)",
        "sealed_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds"),
    }
    write_new(out / "seal.json", dumps(report))
    return report


def recheck_sample(decision_ids: Sequence[str], seed: str) -> List[str]:
    size = min(len(decision_ids), max(RECHECK_MINIMUM, math.ceil(RECHECK_SHARE * len(decision_ids))))
    return sorted(decision_ids, key=lambda value: hashlib.sha256(f"{seed}:recheck:{value}".encode()).hexdigest())[:size]


def build_recheck(sheet_dir: Path, sealed_report: Path, out: Path) -> Dict:
    manifest = json.loads((sheet_dir / "sheet.json").read_bytes())
    report = json.loads(sealed_report.read_bytes())
    if report["sheet_id"] != manifest["sheet_id"]:
        raise ValueError("the sealed report belongs to another sheet")
    sealed = read_jsonl([sealed_report.parent / report["sealed_file"]])
    if sha256_bytes((sealed_report.parent / report["sealed_file"]).read_bytes()) != report["sealed_sha256"]:
        raise ValueError("the sealed decisions file changed after sealing")
    chosen = set(recheck_sample([record["decision_id"] for record in sealed], manifest["lock"]["seed"]))
    unit_ids = {record["unit_id"] for record in sealed if record["decision_id"] in chosen}
    if out.exists():
        raise FileExistsError(f"{out} exists; build a new re-check directory")
    out.mkdir(parents=True)
    pages_used = sorted({unit["page"] for unit in manifest["units"] if unit["unit_id"] in unit_ids})
    for page in manifest["pages"]:
        if page["page"] in pages_used:
            write_new(out / page["image"], (sheet_dir / page["image"]).read_bytes())
    recheck = dict(manifest, mode="recheck", sheet_id=f"{manifest['sheet_id']}-recheck",
                   parent_sheet_id=manifest["sheet_id"], parent_sealed_sha256=report["sealed_sha256"],
                   pages=[page for page in manifest["pages"] if page["page"] in pages_used],
                   units=[unit for unit in manifest["units"] if unit["unit_id"] in unit_ids],
                   excluded_not_visible=[],
                   created_at=dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds"))
    recheck["totals"] = {"units": len(recheck["units"]), "slots": sum(u["slots"] for u in recheck["units"]),
                         "excluded_units": 0, "excluded_slots": 0}
    write_new(out / "sheet.json", dumps(recheck))
    write_new(out / "index.html", render_html(recheck).encode("utf-8"))
    return recheck


def compare_recheck(sealed_report: Path, recheck_dir: Path, decision_paths: List[Path]) -> Dict:
    """Agreement between the sealed decisions and a blind re-check (section 7.4 D)."""
    report = json.loads(sealed_report.read_bytes())
    sealed = {record["unit_id"]: record for record in read_jsonl([sealed_report.parent / report["sealed_file"]])}
    manifest = json.loads((recheck_dir / "sheet.json").read_bytes())
    records = read_jsonl(decision_paths)
    problems = check_records(manifest, records)
    if problems:
        raise ValueError("re-check decisions do not match the sheet:\n  " + "\n  ".join(problems[:40]))
    differing = [record["unit_id"] for record in records
                 if (record["decision"], record.get("cause")) != (sealed[record["unit_id"]]["decision"], sealed[record["unit_id"]].get("cause"))]
    missing = sorted({unit["unit_id"] for unit in manifest["units"]} - {record["unit_id"] for record in records})
    return {"schema_version": "ocr-v8-text-layer-recheck-agreement-v1", "parent_sealed_sha256": report["sealed_sha256"],
            "rechecked": len(records), "expected": len(manifest["units"]), "missing": missing,
            "agreement": round(1 - len(differing) / len(records), 6) if records else None,
            "needs_third_review": differing}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--lock", type=Path, required=True)
    build.add_argument("--pdf-root", type=Path, required=True)
    build.add_argument("--pdf", required=True, help="PDF file name as written in the lock")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--reviewer", default="VuTuanAn1403")
    build.add_argument("--pages", type=int, help="Pages of the locked order to include (default: the worklist)")
    build.add_argument("--skip", type=int, default=0, help="Skip this many pages of the locked order")
    sealer = commands.add_parser("seal")
    sealer.add_argument("--sheet", type=Path, required=True)
    sealer.add_argument("--decisions", type=Path, nargs="+", required=True)
    sealer.add_argument("--out", type=Path, required=True)
    again = commands.add_parser("recheck")
    again.add_argument("--sheet", type=Path, required=True)
    again.add_argument("--sealed", type=Path, required=True, help="seal.json of the sealed screening")
    again.add_argument("--out", type=Path, required=True)
    agree = commands.add_parser("agreement")
    agree.add_argument("--sealed", type=Path, required=True)
    agree.add_argument("--recheck", type=Path, required=True)
    agree.add_argument("--decisions", type=Path, nargs="+", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_sheet(args.lock, args.pdf_root, args.pdf, args.out, args.reviewer, args.pages, args.skip)
        totals = manifest["totals"]
        print(f"{manifest['pdf']}: {len(manifest['pages'])} pages, {totals['units']} units, {totals['slots']} slots; "
              f"{totals['excluded_units']} words not fully visible ({totals['excluded_slots']} slots) -> {args.out / 'index.html'}")
    elif args.command == "seal":
        report = seal(args.sheet, args.decisions, args.out)
        result = report["verdict"]
        print(f"{report['pdf']}: {result['status']}; MATCH slots {result['match_slots_complete_pages']}/{result['minimum_slots']}, "
              f"MISMATCH units {result['mismatch_units']}; sealed {report['sealed_sha256']}")
    elif args.command == "recheck":
        recheck = build_recheck(args.sheet, args.sealed, args.out)
        print(f"re-check sheet: {recheck['totals']['units']} units -> {args.out / 'index.html'}")
    else:
        result = compare_recheck(args.sealed, args.recheck, args.decisions)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
