#!/usr/bin/env python3
"""Measurement lock of the V8-011 text-layer procedure: the choices of GROUND_TRUTH_PROTOCOL 7.6.

Lock v1 (`lock_text_layer_procedure.py`) fixed the inventory, the partitions, the bound and
the screening order. The tools written after it make seven more choices: visible glyphs,
the screening unit, bbox matching, the measured stream, the gate count, rho_U and the
adjudication rules. This lock binds those choices to lock v1 by sha256 and pins the bytes
of every tool that implements them, so a measurement can show that it ran under rules
fixed before anyone saw a result. `measure_text_layer_diacritics.py` refuses to run
without a valid lock of the current schema.

Version 3 (10/11/2026) adds two things. The matching rule is now a choice (`--matching`,
one of `measure_text_layer_diacritics.MATCHING_METHODS`): lock v2 joined the text layer
with extraction items of kind b only, so text inside tables counted as deleted. And the
sealed screenings are written into the lock by sha256 (section 7.4 E); a measurement
must then use exactly those seals. `--supersedes` records the lock this one replaces.

Version 4 (10/11/2026) adds the adjudication sample (`--adjudication-sample N`): only N
items, ranked by sha256 of `seed:adjudication-sample:<item_id>`, go on the sheet, and every
item left out counts as UNRESOLVED. Without the option every item is adjudicated.

  --draft   Write the proposal for the reviewer: status DRAFT_NOT_LOCKED, no decision; the
            stream and the matching rule may stay open. A draft never unlocks a measurement.
  default   Write the lock once the reviewer has approved it; --reviewer, --decided-on,
            --stream and --matching are required. The operator runs this only on the
            reviewer's decision.
  --verify  Rebuild a lock and list every difference, including tools or seals whose bytes changed.

  python scripts/lock_text_layer_measurement.py --base-lock docs/quality_assurance/locks/v8_011_text_layer_procedure_lock_v1.json \
      --draft --report scratch/v8/<new>.json
  python scripts/lock_text_layer_measurement.py --base-lock <v1>.json --stream text_corrected \
      --matching bbox-connected-groups-phase-a-v1 --screening-seal <seal.json>... \
      --supersedes <old lock>.json --supersede-reason "<why>" \
      --reviewer <name> --decided-on YYYY-MM-DD --report docs/quality_assurance/locks/<new>.json
  python scripts/lock_text_layer_measurement.py --verify <lock>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

SCHEMA = "ocr-v8-text-layer-measurement-lock-v4"
PROCEDURE_VERSION = 4
BASE_SCHEMA = "ocr-v8-text-layer-procedure-lock-v1"
PROTOCOL = "docs/quality_assurance/GROUND_TRUTH_PROTOCOL.md#7.6"
LOCKED, DRAFT = "LOCKED_PROCEDURE", "DRAFT_NOT_LOCKED"
STREAMS = ("text_corrected", "text_raw")
# Every file whose behaviour section 7.6 describes. A byte change in any of them voids the lock.
TOOLS = (
    "benchmark/ground_truth_tools/text_layer_reference.py",
    "benchmark/ground_truth_tools/screening_sheet.html",
    "scripts/screen_text_layer.py",
    "scripts/measure_text_layer_diacritics.py",
    "benchmark/scientific_evaluation/ocr_metric.py",
    "benchmark/scientific_evaluation/diacritic_acceptance.py",  # uncomposed-mark eligibility of a unit
    "benchmark/scientific_evaluation/exact_bounds.py",
    "benchmark/scientific_evaluation/cluster_correlation.py",
    "scripts/adjudicate_text_layer_diacritics.py",
    "benchmark/ground_truth_tools/adjudication_sheet.html",
)


class LockError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tool_sha256(path: Path) -> str:
    """sha256 of the file with CRLF read as LF, so a Windows and a Linux checkout agree."""
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def current_choices(base_parameters: Dict, stream: Optional[str], matching: Optional[str],
                    adjudication_sample: Optional[int] = None) -> Dict:
    """The seven choices as the tools implement them now (values are read from the code)."""
    from benchmark.ground_truth_tools import text_layer_reference as tlr
    from benchmark.scientific_evaluation import cluster_correlation
    from scripts import adjudicate_text_layer_diacritics as adjudicate
    from scripts import measure_text_layer_diacritics as measure
    from scripts import screen_text_layer as screen

    if matching is not None and matching not in measure.MATCHING_METHODS:
        raise LockError(f"matching must be one of {sorted(measure.MATCHING_METHODS)}")
    if adjudication_sample is not None and (type(adjudication_sample) is not int or adjudication_sample < 1):
        raise LockError("the adjudication sample must be a positive whole number of items")
    return {
        "visible_glyphs": {
            "method": tlr.VISIBILITY_METHOD, "render_dpi": round(72 * tlr.VISIBILITY_ZOOM),
            "min_changed_pixels": tlr.MIN_CHANGED_PIXELS,
            "zero_width_part": "takes the verdict of the preceding base character",
            "partially_visible_word": "left out of the sample and reported apart",
            "implemented_by": "benchmark/ground_truth_tools/text_layer_reference.py::mark_visibility"},
        "screening_unit": {
            "unit": "one text-layer word with at least one diacritic slot",
            "bulk_match": "the undecided words of one line in one action, recorded as bulk: line",
            "counted_match_slots": "only on pages decided in full, in the lock order",
            "recheck_share": screen.RECHECK_SHARE, "recheck_minimum": screen.RECHECK_MINIMUM,
            "implemented_by": "scripts/screen_text_layer.py::verdict"},
        "matching": {
            "method": matching, "ocr_side": measure.MATCHING_METHODS.get(matching),
            "min_vertical_overlap": measure.MIN_VERTICAL_OVERLAP,
            "table_share": measure.TABLE_SHARE if matching == "bbox-connected-groups-no-tables-v1" else None,
            "join": "an OCR line and a visible text-layer line join when they intersect horizontally and "
                    "overlap vertically by at least min_vertical_overlap of the smaller height",
            "unit": "one connected group, ordered by rows then left to right",
            "text_layer_line_without_ocr": "every slot counts as deleted_slots",
            "ocr_line_without_text_layer": "reported apart as unmatched_ocr_lines",
            "allowed": sorted(measure.MATCHING_METHODS),
            "implemented_by": "scripts/measure_text_layer_diacritics.py::ocr_lines, match_units"},
        "stream": {"value": stream, "allowed": list(STREAMS)},
        "gate": {
            "metric": base_parameters["metric"], "errors": "dser_errors", "denominator": "ref_slots",
            "reported_beside": "DER_VN_v1 (never the gate count)",
            "implemented_by": "scripts/measure_text_layer_diacritics.py::build"},
        "rho_upper": {
            "method": cluster_correlation.METHOD, "confidence": base_parameters["confidence"], "sides": "one",
            "implemented_by": "benchmark/scientific_evaluation/cluster_correlation.py::page_icc"},
        "adjudication": {
            "choices": list(adjudicate.CHOICES),
            "item": "one differing token segment that holds a diacritic slot or mark",
            "BOTH_WRONG": "the reviewer must type the correct text read from the image",
            "UNRESOLVED": "every slot of the segment that differs from the text layer counts as an error",
            "sample_size": adjudication_sample,
            "sample_rank": adjudicate.SAMPLE_RANK if adjudication_sample else None,
            "unsampled_items": "count as UNRESOLVED" if adjudication_sample else None,
            "implemented_by": "scripts/adjudicate_text_layer_diacritics.py::build_sheet, seal"},
    }


def read_base(base_path: str) -> tuple[Dict, str]:
    data = resolve(base_path).read_bytes()
    base = json.loads(data)
    if base.get("schema_version") != BASE_SCHEMA or base.get("status") != LOCKED:
        raise LockError(f"{base_path}: base must be a {LOCKED} lock of schema {BASE_SCHEMA}")
    if base.get("parameters", {}).get("metric") != "DSER_strict":
        raise LockError(f"{base_path}: base lock metric must be DSER_strict")
    return base, sha256_bytes(data)


def screening_seals(paths: Sequence[str], base_sha: str) -> List[Dict]:
    """Section 7.4 E: each sealed screening is written into the next lock version by sha256."""
    seals = []
    for path in sorted(paths):
        data = resolve(path).read_bytes()
        seal = json.loads(data)
        if (seal.get("lock") or {}).get("sha256") != base_sha:
            raise LockError(f"{path}: the screening was sealed under another base lock")
        seals.append({"pdf": seal["pdf"], "pdf_sha256": seal["pdf_sha256"], "producer": seal.get("producer"),
                      "path": path, "sha256": sha256_bytes(data), "sealed_sha256": seal["sealed_sha256"],
                      "verdict": seal["verdict"]["status"]})
    return seals


def superseded(path: Optional[str], reason: Optional[str]) -> Optional[Dict]:
    if path is None:
        return None
    if not (reason or "").strip():
        raise LockError("a superseded lock needs a reason (--supersede-reason)")
    return {"path": path, "sha256": sha256_bytes(resolve(path).read_bytes()), "reason": reason}


def build_lock(base_path: str, *, draft: bool, stream: Optional[str] = None, matching: Optional[str] = None,
               reviewer: Optional[str] = None, decided_on: Optional[str] = None, seals: Sequence[str] = (),
               supersedes: Optional[str] = None, supersede_reason: Optional[str] = None,
               adjudication_sample: Optional[int] = None) -> Dict:
    base, base_sha = read_base(base_path)
    if stream is not None and stream not in STREAMS:
        raise LockError(f"stream must be one of {STREAMS}")
    if draft:
        if reviewer or decided_on:
            raise LockError("a draft carries no decision; drop --reviewer and --decided-on")
        decision = None
    else:
        if not (reviewer or "").strip() or not decided_on or stream is None or matching is None:
            raise LockError("a lock needs the reviewer's decision: --reviewer, --decided-on, --stream and --matching")
        decision = {"decided_on": decided_on, "timezone": "Asia/Bangkok", "reviewer": reviewer}
    choices = current_choices(base["parameters"], stream, matching, adjudication_sample)
    return {
        "schema_version": SCHEMA, "procedure_version": PROCEDURE_VERSION, "status": DRAFT if draft else LOCKED,
        "gt_status": "NOT_VERIFIED", "quality_acceptance": "NOT_EVALUATED", "protocol": PROTOCOL,
        "base_lock": {"path": base_path, "sha256": base_sha, "schema_version": BASE_SCHEMA,
                      "procedure_version": base.get("procedure_version")},
        "supersedes": superseded(supersedes, supersede_reason),
        "decision": decision,
        "open_choices": [name for name, value in (("matching", matching), ("stream", stream)) if value is None],
        "choices": choices,
        "screening_seals": screening_seals(seals, base_sha),
        "tools": {path: tool_sha256(ROOT / path) for path in TOOLS},
    }


def dump(lock: Dict) -> str:
    return json.dumps(lock, ensure_ascii=False, indent=2) + "\n"


def verify(lock_path: Path) -> List[str]:
    """Rebuild the lock from its own base, decision, choices and seals; return the differences."""
    lock = json.loads(lock_path.read_bytes())
    if lock.get("schema_version") != SCHEMA:
        return [f"schema must be {SCHEMA} (an older lock version cannot authorise a measurement)"]
    problems = []
    for path, digest in lock.get("tools", {}).items():
        current = ROOT / path
        if not current.is_file():
            problems.append(f"tool missing: {path}")
        elif tool_sha256(current) != digest:
            problems.append(f"tool bytes changed since the lock: {path}")
    for seal in lock.get("screening_seals", []):
        current = resolve(seal["path"])
        if not current.is_file() or sha256_bytes(current.read_bytes()) != seal["sha256"]:
            problems.append(f"screening seal missing or changed since the lock: {seal['path']}")
    if problems:
        return problems
    decision = lock.get("decision") or {}
    old = lock.get("supersedes") or {}
    try:
        rebuilt = build_lock(lock["base_lock"]["path"], draft=lock.get("status") == DRAFT,
                             stream=lock["choices"]["stream"]["value"], matching=lock["choices"]["matching"]["method"],
                             reviewer=decision.get("reviewer"), decided_on=decision.get("decided_on"),
                             seals=[seal["path"] for seal in lock.get("screening_seals", [])],
                             supersedes=old.get("path"), supersede_reason=old.get("reason"),
                             adjudication_sample=lock["choices"]["adjudication"].get("sample_size"))
    except (LockError, OSError, KeyError) as error:
        return [f"cannot rebuild: {error}"]
    if rebuilt["base_lock"]["sha256"] != lock["base_lock"]["sha256"]:
        return ["base lock bytes differ from the lock"]
    if dump(rebuilt) != dump(lock):
        return ["lock content differs from a rebuild with the current tools"]
    return []


def require_locked(lock_path: Path, base_lock_sha256: str, stream: str, seal_paths: Sequence[Path] = ()) -> Dict:
    """Gate for a measurement: a verified lock on this base lock and stream and, when it lists seals, these seals."""
    data = lock_path.read_bytes()
    lock = json.loads(data)
    if lock.get("status") != LOCKED:
        raise LockError(f"{lock_path}: status {lock.get('status')}; only a {LOCKED} lock allows a measurement")
    if lock.get("schema_version") != SCHEMA:
        raise LockError(f"{lock_path}: schema must be {SCHEMA}")
    if lock["base_lock"]["sha256"] != base_lock_sha256:
        raise LockError(f"{lock_path}: bound to another base lock")
    if lock["choices"]["stream"]["value"] != stream:
        raise LockError(f"{lock_path}: locked stream is {lock['choices']['stream']['value']}, not {stream}")
    locked_seals = {seal["sha256"] for seal in lock.get("screening_seals", [])}
    given = {sha256_bytes(Path(path).read_bytes()) for path in seal_paths}
    if locked_seals and given != locked_seals:
        raise LockError(f"{lock_path}: the screening seals differ from the {len(locked_seals)} seals in the lock")
    problems = verify(lock_path)
    if problems:
        raise LockError(f"{lock_path}: " + "; ".join(problems))
    return {"path": relative(lock_path), "sha256": sha256_bytes(data), "status": LOCKED,
            "procedure_version": lock["procedure_version"], "matching": lock["choices"]["matching"]["method"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-lock", type=Path, help="Lock v1 (ocr-v8-text-layer-procedure-lock-v1)")
    parser.add_argument("--report", type=Path, help="New lock or draft path (never overwritten)")
    parser.add_argument("--draft", action="store_true", help="Write a proposal without a decision")
    parser.add_argument("--stream", choices=STREAMS)
    parser.add_argument("--matching", help="Matching rule, one of measure_text_layer_diacritics.MATCHING_METHODS")
    parser.add_argument("--screening-seal", type=Path, nargs="*", default=[], help="seal.json of each sealed screening")
    parser.add_argument("--supersedes", type=Path, help="The lock this one replaces")
    parser.add_argument("--supersede-reason")
    parser.add_argument("--adjudication-sample", type=int, help="Adjudicate only this many seeded-ranked items")
    parser.add_argument("--reviewer")
    parser.add_argument("--decided-on", help="Decision date, YYYY-MM-DD (Asia/Bangkok)")
    parser.add_argument("--verify", type=Path, help="Rebuild this lock and compare")
    args = parser.parse_args(argv)
    if args.verify:
        problems = verify(args.verify)
        for problem in problems:
            print(f"MISMATCH {problem}")
        print("OK lock reproduces" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if args.base_lock is None or args.report is None:
        parser.error("--base-lock and --report are required")
    if args.report.exists():
        parser.error(f"{args.report} exists")
    try:
        lock = build_lock(relative(args.base_lock), draft=args.draft, stream=args.stream, matching=args.matching,
                          reviewer=args.reviewer, decided_on=args.decided_on,
                          seals=[relative(path) for path in args.screening_seal],
                          supersedes=relative(args.supersedes) if args.supersedes else None,
                          supersede_reason=args.supersede_reason, adjudication_sample=args.adjudication_sample)
    except LockError as error:
        parser.error(str(error))
    text = dump(lock).encode("utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(text)  # LF only, so the printed sha256 matches the file
    open_choices = ", ".join(lock["open_choices"]) or "none"
    print(f"{lock['status']} v{PROCEDURE_VERSION}: {len(lock['tools'])} tools, {len(lock['screening_seals'])} seals pinned, "
          f"open choices: {open_choices} -> {args.report} sha256 {sha256_bytes(text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
