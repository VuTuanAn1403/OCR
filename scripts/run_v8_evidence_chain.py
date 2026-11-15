#!/usr/bin/env python3
"""Run the deterministic V8 evidence chain after the reviewer's work (reviewer decision 13/11/2026).

The reviewer's steps stay human (GROUND_TRUTH_PROTOCOL 7.1): screening decisions, blind A/B
adjudication, structured-GT labels, the export thresholds and every lock decision. Everything
after them is mechanical, and this script chains it so nothing is forgotten or run out of order:

1. ``status`` (default): for every review sheet, the number of decisions the autosave server has
   written (``serve_review_sheets.py``) against the number of units, and which exported GT files
   exist. Read-only.
2. ``--run``: in a new folder ``<out>/<stamp>/`` it runs only the steps whose input is complete:
   * ``screen_text_layer.py seal`` for each holdout screening sheet with decisions (the verdict
     ACCEPTED / REJECTED / INCOMPLETE comes from the tool, not from this script);
   * ``adjudicate_text_layer_diacritics.py seal`` for the lock v8 adjudication sheet (partial
     adjudication is allowed by lock v8; undecided items count as UNRESOLVED);
   * ``run_scientific_benchmark.py`` on baseline and candidate outputs for every exported
     ``*.structure.json`` (files named ``SYNTHETIC_NOT_GT*`` are skipped), and
     ``compare_layout_candidate.py`` for the layout candidate on all of them.
   Steps that need a reviewer decision are not run; their command is printed in the report:
   exporting labels (``--iou-threshold``/``--ignore-overlap``), writing the holdout measurement
   lock, and measuring holdout outputs under it.

Every child command, its exit code and its output path are written to ``chain.json`` and
``chain.md``. Nothing is overwritten. Quality stays NOT_EVALUATED until independent GT is scored.

  python scripts/run_v8_evidence_chain.py                 # status only
  python scripts/run_v8_evidence_chain.py --run --out scratch/v8/evidence_chain
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ocr-v8-evidence-chain-v1"
BANGKOK = timezone(timedelta(hours=7), "Asia/Bangkok")  # no tzdata on Windows
DEFAULTS = {
    "holdout_screening": "scratch/v8/holdout/screening",
    "adjudication_sheet": "scratch/v8/adjudication/v8_011_dev_006_v8_20261113",
    "structured_gt": "scratch/gt",
    "structured_sheets": "scratch/gt/structured_dev_004_20261112",
    "baseline": "output/v8_006_arena1536_20261112",
    "candidate": "output/v8_007_arena1536_upscale2_20261112",
    "candidate_rec": "output/v8_065_vgg_transformer_dev_20261114",
    "layout_candidate": "scratch/v8/v8_070_doclayout_gt44_20261112.jsonl",
}


def _jsonl_rows(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def sheet_status(folder: Path, prefix: str) -> Dict:
    """Decisions saved by the autosave server for one sheet folder, against its units."""
    sheet = json.loads((folder / "sheet.json").read_bytes())
    units = sheet.get("items") or sheet.get("units") or []
    saved = sorted((folder / "autosave").glob(f"{prefix}_*.decisions.jsonl")) if (folder / "autosave").is_dir() else []
    migrated = sorted(folder.glob("migrated-*.jsonl"))
    decided = _jsonl_rows(saved[-1]) if saved else 0
    return {"sheet": folder.as_posix(), "sheet_id": sheet.get("sheet_id"), "units": len(units),
            "decided": decided, "autosave": saved[-1].as_posix() if saved else None,
            "migrated": [p.as_posix() for p in migrated]}


def structured_gt_files(folder: Path) -> List[Path]:
    return sorted(p for p in folder.rglob("*.structure.json") if not p.name.startswith("SYNTHETIC_NOT_GT"))


def collect_status(paths: Dict[str, Path]) -> Dict:
    screening = [sheet_status(p, "screening") for p in sorted(paths["holdout_screening"].iterdir())
                 if (p / "sheet.json").is_file()] if paths["holdout_screening"].is_dir() else []
    adjudication = (sheet_status(paths["adjudication_sheet"], "adjudication")
                    if (paths["adjudication_sheet"] / "sheet.json").is_file() else None)
    labels = []
    if paths["structured_sheets"].is_dir():
        for folder in sorted(p for p in paths["structured_sheets"].iterdir() if (p / "sheet.json").is_file()):
            saved = sorted((folder / "autosave").glob("structured-gt_*.json")) if (folder / "autosave").is_dir() else []
            labels.append({"sheet": folder.as_posix(), "autosave": saved[-1].as_posix() if saved else None})
    return {"holdout_screening": screening, "adjudication": adjudication, "structured_label_sheets": labels,
            "structured_gt_exports": [p.as_posix() for p in structured_gt_files(paths["structured_gt"])]}


def plan(status: Dict, paths: Dict[str, Path], out: Path) -> List[Dict]:
    """Commands for the steps whose input exists; each step names why it runs or waits."""
    py, steps = [sys.executable, "-B"], []
    for row in status["holdout_screening"]:
        name = Path(row["sheet"]).name
        if row["autosave"]:
            steps.append({"step": f"seal screening {name}", "run": True, "out": (out / "screening" / name).as_posix(),
                          "command": [*py, "scripts/screen_text_layer.py", "seal", "--sheet", row["sheet"],
                                      "--decisions", row["autosave"], "--out", (out / "screening" / name).as_posix()]})
        else:
            steps.append({"step": f"seal screening {name}", "run": False, "reason": "no reviewer decision saved yet"})
    adj = status["adjudication"]
    if adj and adj["autosave"]:
        # The autosave holds what the reviewer loaded (the migrated decisions) plus new clicks.
        steps.append({"step": "seal adjudication v8", "run": True, "out": (out / "adjudication").as_posix(),
                      "command": [*py, "scripts/adjudicate_text_layer_diacritics.py", "seal", "--sheet", adj["sheet"],
                                  "--decisions", adj["autosave"], "--out", (out / "adjudication").as_posix()]})
    elif adj:
        steps.append({"step": "seal adjudication v8", "run": False,
                      "reason": "the reviewer has not opened the sheet yet; migrated decisions alone are not sealed"})
    gts = status["structured_gt_exports"]
    for gt in gts:
        doc = Path(gt).name.split(".structure.json")[0]
        for side in ("baseline", "candidate", "candidate_rec"):
            prediction = paths[side] / doc
            target = out / "structured" / f"{side}_{doc}"
            steps.append({"step": f"score {doc} on {side}", "run": prediction.is_dir(), "out": target.as_posix(),
                          **({} if prediction.is_dir() else {"reason": f"{prediction.as_posix()} missing"}),
                          "command": [*py, "scripts/run_scientific_benchmark.py", "--prediction", prediction.as_posix(),
                                      "--structured-gt", gt, "--output-dir", target.as_posix()]})
    if gts:
        steps.append({"step": "layout candidate on exported GT", "run": paths["layout_candidate"].is_file(),
                      "out": (out / "layout_candidate.json").as_posix(),
                      "command": [*py, "scripts/compare_layout_candidate.py", "--candidate", paths["layout_candidate"].as_posix(),
                                  "--output", paths["baseline"].as_posix(), "--gt", *gts,
                                  "--report", (out / "layout_candidate.json").as_posix()]})
    steps.append({"step": "export structured labels", "run": False,
                  "reason": "the reviewer chooses --iou-threshold and --ignore-overlap",
                  "command_template": "scripts/label_structured_gt.py export --sheet <sheet> --labels <download.json> "
                                      "--out scratch/gt/<DOC>.structure.json --iou-threshold <t> --ignore-overlap <o>"})
    steps.append({"step": "holdout measurement lock and measurement", "run": False,
                  "reason": "needs every holdout screening ACCEPTED and the reviewer's lock decision",
                  "command_template": "scripts/lock_text_layer_measurement.py --draft ... then measure_text_layer_diacritics.py "
                                      "and compare_text_layer_runs.py on the holdout outputs"})
    return steps


def run_steps(steps: List[Dict]) -> None:
    for step in steps:
        if not step.get("run"):
            continue
        Path(step["out"]).parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(step["command"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        step.update(exit_code=done.returncode, stdout_tail=done.stdout[-1500:], stderr_tail=done.stderr[-1500:])


def markdown(report: Dict) -> str:
    lines = [f"# Chuỗi bằng chứng V8 ({report['created_at']})", "", "Chất lượng: NOT_EVALUATED.", "",
             "| Bước | Chạy | Exit | Ghi chú |", "| --- | --- | --- | --- |"]
    for step in report["steps"]:
        lines.append(f"| {step['step']} | {'có' if step.get('run') else 'không'} | {step.get('exit_code', '')} | "
                     f"{step.get('reason') or step.get('out', '')} |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for key, value in DEFAULTS.items():
        parser.add_argument("--" + key.replace("_", "-"), default=value)
    parser.add_argument("--run", action="store_true", help="Run the ready steps into a new folder")
    parser.add_argument("--out", default="scratch/v8/evidence_chain")
    args = parser.parse_args(argv)
    paths = {key: ROOT / getattr(args, key) for key in DEFAULTS}
    status = collect_status(paths)
    stamp = datetime.now(BANGKOK)
    out = ROOT / args.out / stamp.strftime("%Y%m%d-%H%M%S")
    steps = plan(status, paths, out.relative_to(ROOT))
    report = {"schema_version": SCHEMA, "created_at": stamp.isoformat(timespec="seconds"), "mode": "run" if args.run else "status",
              "quality_acceptance": "NOT_EVALUATED", "status": status, "steps": steps}
    if not args.run:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    if out.exists():
        parser.error(f"{out} exists; runs are never overwritten")
    out.mkdir(parents=True)
    run_steps(steps)
    (out / "chain.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "chain.md").write_text(markdown(report), encoding="utf-8")
    failed = [s["step"] for s in steps if s.get("run") and s.get("exit_code")]
    print(f"{out.relative_to(ROOT).as_posix()}: {sum(1 for s in steps if s.get('run'))} steps run, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
