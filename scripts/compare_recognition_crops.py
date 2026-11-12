#!/usr/bin/env python3
"""Paired fix/harm of two recognizers on a fixed crop set (V8-065).

CPU only. Both prediction files are canonical ``recognition_crop`` JSONL (one record per crop,
``MISSING_OUTPUT`` allowed and counted as wrong). The crop PNGs are re-hashed and must match
``crop_set.json``. ``--candidate-acronym`` instead derives the candidate from the baseline with
the V8-030 post-processing challenger (``acronym_diacritics.restore``), which isolates its effect
on the same crops.

  python scripts/compare_recognition_crops.py --crop-set scratch/v8/recognition_crops/<set> \
      --baseline <set>/baseline.jsonl (--candidate <file>.jsonl | --candidate-acronym) --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.challengers import acronym_diacritics  # noqa: E402
from benchmark.challengers.recognition_crops import compare, predictions_by_crop  # noqa: E402


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(crop_set_dir: Path, baseline_path: Path, candidate_path: Path = None, acronym: bool = False) -> dict:
    crop_set = json.loads((crop_set_dir / "crop_set.json").read_bytes())
    on_disk = {crop["crop_id"]: hashlib.sha256((crop_set_dir / "crops" / f"{crop['crop_id']}.png").read_bytes()).hexdigest()
               for crop in crop_set["crops"]}
    baseline_records = _jsonl(baseline_path)
    baseline = predictions_by_crop(baseline_records)
    if acronym:
        candidate = {cid: None if text is None else acronym_diacritics.restore(text)[0] for cid, text in baseline.items()}
        candidate_name = f"{acronym_diacritics.METHOD} applied to the baseline"
    else:
        candidate = predictions_by_crop(_jsonl(candidate_path))
        candidate_name = candidate_path.as_posix()
    report = compare(crop_set["crops"], baseline, candidate, crop_sha256=on_disk)
    report.update(crop_set=crop_set_dir.as_posix(), crop_set_seed=crop_set["seed"],
                  reference_kind=crop_set["reference_kind"], baseline=baseline_path.as_posix(), candidate=candidate_name)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--crop-set", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidate", type=Path)
    group.add_argument("--candidate-acronym", action="store_true")
    parser.add_argument("--report", type=Path, required=True, help="New JSON report (never overwritten)")
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    report = run(args.crop_set, args.baseline, args.candidate, args.candidate_acronym)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"crops": report["crops"], "effects": report["effects"], "totals": report["totals"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
