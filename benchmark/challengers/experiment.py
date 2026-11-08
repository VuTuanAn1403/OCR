"""Experiment IDs, identity manifests and the directory layout (spec 05 sections 2-3).

A manifest that lacks any required identity field is INCONCLUSIVE: its scorecards
may be computed for diagnosis but cannot support a PROMOTE proposal.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

SCHEMA = "ocr-v8-experiment-manifest-v1"
EXPERIMENT_ID = re.compile(r"^EXP-V8-(?P<layer>[A-Z][A-Z0-9]{1,7})-(?P<date>\d{8})-(?P<serial>\d{3})$")
RUN_ROLES = ("baseline", "candidate")
SPLITS = ("development", "calibration", "holdout")
SUBDIRECTORIES = ("manifests", "predictions", "scorecards", "errors", "logs")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{16}$")

# Spec 05 section 3; value kinds: "text", "sha256", "number", "bool", "fingerprints", "list", "map".
REQUIRED_FIELDS = {
    "code": {"commit": "text", "dirty_diff_sha256": "sha256", "code_fingerprints": "fingerprints"},
    "config": {"profiles_sha256": "sha256", "model_registry_sha256": "sha256", "lock_sha256": "sha256"},
    "candidate": {"repository": "text", "revision": "text", "weights_sha256": "sha256",
                  "code_licence": "text", "weights_licence": "text", "tokenizer": "text"},
    "data": {"pdf_manifest_sha256": "sha256", "page_selection": "list", "dpi": "number",
             "image_manifest_sha256": "sha256", "split": "split"},
    "protocol": {"protocol_sha256": "sha256", "metric_versions": "map", "alpha": "number",
                 "thresholds": "map", "margin": "number"},
    "environment": {"gpu": "text", "vram_mb": "number", "driver": "text", "cuda": "text", "backend": "text",
                    "seed": "number", "command": "list", "exit_code": "number", "process_tree_exited": "bool"},
}


def parse_experiment_id(value: str) -> dict:
    """Return the layer, date and serial of ``EXP-V8-<LAYER>-<YYYYMMDD>-<NNN>``."""
    match = EXPERIMENT_ID.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(f"Experiment ID must look like EXP-V8-REC-20261120-001: {value!r}")
    date = datetime.strptime(match["date"], "%Y%m%d").date()
    if match["serial"] == "000":
        raise ValueError("Experiment serial starts at 001")
    return {"layer": match["layer"], "date": date.isoformat(), "serial": int(match["serial"])}


def _valid(kind: str, value) -> bool:
    if kind == "text":
        return isinstance(value, str) and bool(value.strip())
    if kind == "sha256":
        return isinstance(value, str) and bool(_SHA256.fullmatch(value))
    if kind == "number":
        return type(value) in (int, float) and value == value and value not in (float("inf"), float("-inf"))
    if kind == "bool":
        return type(value) is bool
    if kind == "fingerprints":
        return (isinstance(value, dict) and set(value) == {"extraction", "analysis", "publication"}
                and all(isinstance(v, str) and _FINGERPRINT.fullmatch(v) for v in value.values()))
    if kind == "list":
        return isinstance(value, list) and bool(value)
    if kind == "map":
        return isinstance(value, dict) and bool(value)
    if kind == "split":
        return value in SPLITS
    raise ValueError(f"Unknown field kind: {kind}")


def validate_manifest(manifest: dict) -> dict:
    """Check one run manifest; any missing or malformed field makes it INCONCLUSIVE."""
    problems = []
    try:
        parse_experiment_id(manifest.get("experiment_id"))
    except ValueError as exc:
        problems.append(f"experiment_id: {exc}")
    if manifest.get("schema_version") != SCHEMA:
        problems.append("schema_version")
    if manifest.get("role") not in RUN_ROLES:
        problems.append("role")
    if not _valid("text", manifest.get("run_id")):
        problems.append("run_id")
    for group, fields in REQUIRED_FIELDS.items():
        section = manifest.get(group)
        if not isinstance(section, dict):
            problems.append(group)
            continue
        problems.extend(f"{group}.{name}" for name, kind in fields.items() if not _valid(kind, section.get(name)))
    environment = manifest.get("environment") or {}
    if environment.get("process_tree_exited") is False:
        problems.append("environment.process_tree_exited: the run's process tree did not exit")
    if environment.get("exit_code") not in (None, 0) and "environment.exit_code" not in problems:
        problems.append("environment.exit_code: nonzero")
    return {"status": "INCONCLUSIVE" if problems else "COMPLETE", "problems": problems}


def validate_pair(baseline: dict, candidate: dict) -> dict:
    """A paired comparison needs both manifests complete and the same data and protocol."""
    reports = {"baseline": validate_manifest(baseline), "candidate": validate_manifest(candidate)}
    problems = [f"{role}: {problem}" for role, report in reports.items() for problem in report["problems"]]
    if baseline.get("role") != "baseline" or candidate.get("role") != "candidate":
        problems.append("roles must be baseline and candidate")
    if baseline.get("experiment_id") != candidate.get("experiment_id"):
        problems.append("experiment_id differs")
    if baseline.get("run_id") == candidate.get("run_id"):
        problems.append("baseline and candidate need distinct run_id")
    for group in ("data", "protocol"):
        if baseline.get(group) != candidate.get(group):
            problems.append(f"{group} differs between runs")
    return {"status": "INCONCLUSIVE" if problems else "COMPLETE", "problems": problems, "runs": reports}


def decision_options(pair_report: dict, *, protocol_locked: bool, independent_gt: bool) -> tuple[str, ...]:
    """Decisions a reviewer may record (spec 05 section 5); the choice is always manual."""
    if pair_report.get("status") != "COMPLETE" or not protocol_locked or not independent_gt:
        return ("INCONCLUSIVE",)
    return ("PROMOTE", "KEEP_BASELINE", "REJECT", "INCONCLUSIVE")


def create_experiment_dirs(root: Path, experiment_id: str) -> Path:
    """Create ``<root>/<experiment_id>/{manifests,...}``; an existing experiment is never reused."""
    parse_experiment_id(experiment_id)
    base = Path(root) / experiment_id
    base.mkdir(parents=True, exist_ok=False)
    for name in SUBDIRECTORIES:
        (base / name).mkdir()
    return base
