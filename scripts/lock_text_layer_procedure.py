#!/usr/bin/env python3
"""Lock the V8-011 text-layer verification procedure for the 99.99% diacritic gate.

Reads a text-layer inventory (`scripts/inventory_text_layers.py`), binds it by
sha256 and writes a lock manifest: the partition of every PDF, the locked
statistical parameters, the page-cluster summary of the candidate slots and a
seeded screening order per PDF that the human reviewer works through before any
measurement (docs/quality_assurance/GROUND_TRUTH_PROTOCOL.md section 7).

The lock fixes the procedure only. Every candidate stays `NOT_VERIFIED` until the
reviewer has screened it. No AI, model or pipeline output is ever a label.
The output is deterministic, so `--verify` rebuilds it and compares.

  python scripts/lock_text_layer_procedure.py --inventory <inventory>.json --report <new>.json \
      --partition development --reviewer <name> --custodian <name> --decided-on 2026-11-09
  python scripts/lock_text_layer_procedure.py --verify <lock>.json [--pdf-root inputs]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.scientific_evaluation.exact_bounds import minimum_trials  # noqa: E402

SCHEMA = "ocr-v8-text-layer-procedure-lock-v1"
INVENTORY_SCHEMA = "ocr-v8-text-layer-inventory-v1"
PROCEDURE_VERSION = 1
PROTOCOL = "docs/quality_assurance/GROUND_TRUTH_PROTOCOL.md#7"
SEED = "V8-011-LOCK-20261109"
CONFIDENCE = 0.95
GATE_MAX_ERROR_RATE = 1e-4
PLANNED_ERRORS = 0
# Screening must bound the text-layer slot error rate at 1e-3 (ten times looser than the gate).
SCREEN_MAX_ERROR_RATE = 1e-3
PARTITIONS = ("development", "holdout")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def order_key(pdf_sha256: str, page: int, seed: str = SEED) -> str:
    """Hash rank of a page: reproducible without any language-specific random generator."""
    return sha256_bytes(f"{seed}:{pdf_sha256}:{page}".encode("ascii"))


def candidate_pages(document: Dict) -> List[Dict]:
    return [{"page": record["page"], "slots": record["diacritic_slots"]}
            for record in document["page_records"]
            if record["status"] == "CANDIDATE" and record["diacritic_slots"] > 0]


def screening_order(document: Dict, seed: str = SEED) -> List[Dict]:
    return sorted(candidate_pages(document), key=lambda item: order_key(document["sha256"], item["page"], seed))


def worklist(order: List[Dict], minimum_slots: int) -> List[Dict]:
    """Shortest prefix of the order whose slots reach the screening minimum (whole pages)."""
    pages, total = [], 0
    for item in order:
        if total >= minimum_slots:
            break
        total += item["slots"]
        pages.append({**item, "cumulative_slots": total})
    return pages


def cluster_summary(slots: Iterable[int], required: int) -> Dict:
    """Page clusters: N, mean size and the size-weighted mean sum(m^2)/sum(m) used in DEFF.

    Kish's design effect for unequal clusters is 1 + ((1 + CV^2) * m_mean - 1) * rho, and
    (1 + CV^2) * m_mean equals sum(m^2)/sum(m). `rho_max` is the largest intra-page correlation
    that still leaves floor(N / DEFF) >= required.
    """
    sizes = [size for size in slots if size > 0]
    total = sum(sizes)
    report = {"slots": total, "clusters": len(sizes), "mean_cluster_size": None,
              "weighted_cluster_size": None, "rho_max_for_required": None}
    if not sizes:
        return report
    weighted = sum(size * size for size in sizes) / total
    report.update(mean_cluster_size=round(total / len(sizes), 2), weighted_cluster_size=round(weighted, 2))
    if total >= required:
        report["rho_max_for_required"] = 1.0 if weighted <= 1 else round((total / required - 1) / (weighted - 1), 6)
    return report


def eligibility(slots: int, screening_slots: int) -> str:
    if slots == 0:
        return "EXCLUDED_NO_CANDIDATE_SLOTS"
    if slots < screening_slots:
        return "EXCLUDED_BELOW_SCREENING_SLOTS"
    return "SCREENING_REQUIRED"


def build_lock(inventory: Dict, inventory_path: str, inventory_sha256: str, *, partition: str,
               reviewer: str, custodian: str, decided_on: str,
               excluded_sha256: Optional[set] = None) -> Dict:
    if inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise ValueError(f"inventory schema must be {INVENTORY_SCHEMA}")
    if partition not in PARTITIONS:
        raise ValueError(f"partition must be one of {PARTITIONS}")
    if not reviewer.strip() or not custodian.strip():
        raise ValueError("a named human reviewer and custodian are required")
    gate_slots = minimum_trials(PLANNED_ERRORS, GATE_MAX_ERROR_RATE, CONFIDENCE)
    screening_slots = minimum_trials(0, SCREEN_MAX_ERROR_RATE, CONFIDENCE)
    overlap = sorted(doc["pdf"] for doc in inventory["documents"] if doc["sha256"] in (excluded_sha256 or set()))
    if overlap:
        raise ValueError(f"PDF bytes already locked in another partition: {', '.join(overlap)}")
    documents, eligible_slots = [], []
    for doc in sorted(inventory["documents"], key=lambda item: item["pdf"]):
        order = screening_order(doc)
        slots = sum(item["slots"] for item in order)
        status = eligibility(slots, screening_slots)
        record = {"pdf": doc["pdf"], "sha256": doc["sha256"], "producer": doc.get("producer"),
                  "creator": doc.get("creator"), "partition": partition, "pages": doc["pages"],
                  "candidate_pages": len(order), "candidate_slots": slots, "eligibility": status,
                  "gt_status": "NOT_VERIFIED", "screening": None}
        if status == "SCREENING_REQUIRED":
            pages = worklist(order, screening_slots)
            record["screening"] = {"status": "PENDING_REVIEW", "minimum_slots": screening_slots,
                                   "worklist": pages, "worklist_slots": pages[-1]["cumulative_slots"],
                                   "order": [item["page"] for item in order]}
            eligible_slots += [item["slots"] for item in order]
        documents.append(record)
    return {
        "schema_version": SCHEMA, "procedure_version": PROCEDURE_VERSION, "status": "LOCKED_PROCEDURE",
        "gt_status": "NOT_VERIFIED", "quality_acceptance": "NOT_EVALUATED", "protocol": PROTOCOL,
        "inventory": {"path": inventory_path, "sha256": inventory_sha256, "schema_version": INVENTORY_SCHEMA},
        "decision": {"decided_on": decided_on, "timezone": "Asia/Bangkok", "reviewer": reviewer,
                     "custodian": custodian, "partition": partition},
        "parameters": {"bound_method": "clopper_pearson_one_sided_v1", "confidence": CONFIDENCE,
                       "maximum_error_rate": GATE_MAX_ERROR_RATE, "planned_errors": PLANNED_ERRORS,
                       "required_effective_slots": gate_slots, "metric": "DSER_strict",
                       "cluster_unit": "page", "design_effect": "1 + (sum(m^2)/sum(m) - 1) * rho_upper",
                       "seed": SEED, "order_key": "sha256(seed:pdf_sha256:page)",
                       "screening_max_error_rate": SCREEN_MAX_ERROR_RATE,
                       "screening_minimum_slots": screening_slots,
                       "screening_rule": "0 confirmed mismatches over the minimum slots, else the PDF is rejected"},
        "documents": documents,
        "eligible_before_screening": cluster_summary(eligible_slots, gate_slots),
    }


def dump(lock: Dict) -> str:
    return json.dumps(lock, ensure_ascii=False, indent=2) + "\n"


def read_inventory(path: Path) -> tuple[Dict, str]:
    data = path.read_bytes()
    return json.loads(data.decode("utf-8")), sha256_bytes(data)


def verify(lock_path: Path, pdf_root: Optional[Path], excluded: Optional[set]) -> List[str]:
    """Rebuild the lock from its own inventory and decision; return the discrepancies."""
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    problems = []
    inventory_path = ROOT / lock["inventory"]["path"]
    if not inventory_path.is_file():
        return [f"inventory missing: {lock['inventory']['path']}"]
    inventory, digest = read_inventory(inventory_path)
    if digest != lock["inventory"]["sha256"]:
        problems.append("inventory sha256 differs from the lock")
    decision = lock["decision"]
    rebuilt = build_lock(inventory, lock["inventory"]["path"], digest, partition=decision["partition"],
                         reviewer=decision["reviewer"], custodian=decision["custodian"],
                         decided_on=decision["decided_on"], excluded_sha256=excluded)
    if dump(rebuilt) != dump(lock):
        problems.append("lock content differs from a rebuild with the locked parameters")
    if pdf_root is not None:
        for doc in lock["documents"]:
            pdf = pdf_root / doc["pdf"]
            if not pdf.is_file():
                problems.append(f"PDF missing under {pdf_root}: {doc['pdf']}")
            elif sha256_bytes(pdf.read_bytes()) != doc["sha256"]:
                problems.append(f"PDF bytes differ from the lock: {doc['pdf']}")
    return problems


def locked_sha256(paths: Iterable[Path]) -> set:
    return {doc["sha256"] for path in paths for doc in json.loads(path.read_text(encoding="utf-8"))["documents"]}


def relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inventory", type=Path, help="Text-layer inventory JSON")
    parser.add_argument("--report", type=Path, help="New lock path (never overwritten)")
    parser.add_argument("--partition", choices=PARTITIONS)
    parser.add_argument("--reviewer", help="Named human reviewer")
    parser.add_argument("--custodian", help="Named holdout custodian")
    parser.add_argument("--decided-on", help="Decision date, YYYY-MM-DD (Asia/Bangkok)")
    parser.add_argument("--exclude-locked", type=Path, action="append", default=[],
                        help="Lock of another partition; identical PDF bytes are refused")
    parser.add_argument("--verify", type=Path, help="Rebuild this lock and compare")
    parser.add_argument("--pdf-root", type=Path, help="With --verify: folder holding the locked PDFs")
    args = parser.parse_args(argv)
    excluded = locked_sha256(args.exclude_locked) if args.exclude_locked else None
    if args.verify:
        problems = verify(args.verify, args.pdf_root, excluded)
        for problem in problems:
            print(f"MISMATCH {problem}")
        print("OK lock reproduces" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    missing = [name for name in ("inventory", "report", "partition", "reviewer", "custodian", "decided_on")
               if getattr(args, name) is None]
    if missing:
        parser.error("missing: " + ", ".join("--" + name.replace("_", "-") for name in missing))
    if args.report.exists():
        parser.error(f"{args.report} exists")
    inventory, digest = read_inventory(args.inventory)
    lock = build_lock(inventory, relative(args.inventory), digest, partition=args.partition,
                      reviewer=args.reviewer, custodian=args.custodian, decided_on=args.decided_on,
                      excluded_sha256=excluded)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(dump(lock).encode("utf-8"))  # LF only, so the printed sha256 matches the file
    for doc in lock["documents"]:
        screening = doc["screening"]
        work = f"worklist {len(screening['worklist'])} pages / {screening['worklist_slots']} slots" if screening else "-"
        print(f"{doc['pdf']}: {doc['eligibility']} {doc['candidate_slots']} slots, {work}")
    summary = lock["eligible_before_screening"]
    print(f"eligible before screening: {summary['slots']} slots in {summary['clusters']} pages, "
          f"m_w {summary['weighted_cluster_size']} -> {args.report} sha256 {sha256_bytes(dump(lock).encode('utf-8'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
