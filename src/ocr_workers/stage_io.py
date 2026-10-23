"""Stage directories and receipts shared by the phase workers (P11b).

Each phase writes its files and `done.json` into its own stage directory. A
request carries one directory per stage; requests from before P11b (a single
`job_dir`) still resolve to `<job_dir>` with `<phase>.done.json` names.
"""
from __future__ import annotations

import json
from pathlib import Path

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.hashing import sha256_file as sha256

PREDECESSOR = {"structure": "text", "export": "structure"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stage_dir(request, phase) -> Path:
    stages = request.get("stages")
    return Path(stages[phase]["dir"]) if stages else Path(request["job_dir"])


def receipt_path(request, phase) -> Path:
    if request.get("stages"):
        return stage_dir(request, phase) / "done.json"
    return Path(request["job_dir"]) / f"{phase}.done.json"


def write_receipt(request, phase, files, **extra):
    root = stage_dir(request, phase)
    data = {"generation": request["generation"], "phase": phase,
            "files": {str(Path(path).relative_to(root).as_posix()): sha256(path) for path in files}, **extra}
    if request.get("stages"):
        data["schema_version"] = "stage-receipt-v1"
        data["key"] = request["stages"][phase]["key"]
    predecessor = PREDECESSOR.get(phase)
    if predecessor:
        data["input_receipt_sha256"] = sha256(receipt_path(request, predecessor))
    atomic_write_json(receipt_path(request, phase), data)
