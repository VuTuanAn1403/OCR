"""Challenger model catalog and the download gate (V8-043, spec 05 section 1).

A candidate is downloadable only when both licences have been checked on the official
page (``licence_label = VERIFIED``), the revision is pinned and the SHA-256 of the
weights is recorded. Copyleft, non-commercial or conditional weights licences also
need an explicit ``licence_review`` entry before any download. Standard library only.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

SCHEMA = "ocr-v8-model-catalog-v1"
CATALOG = Path(__file__).with_name("model_catalog.json")
LABELS = ("VERIFIED", "HYPOTHESIS")
REQUIRED = ("id", "layer", "name", "url", "revision", "code_licence", "weights_licence", "licence_label",
            "weights_sha256", "vram_mb", "vietnamese", "experiment_layer", "note")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# "NC" only as a licence token (CC-BY-NC-SA), never inside a word such as "licence".
_RESTRICTIVE = re.compile(r"GPL|(?<![A-Za-z])NC(?![A-Za-z])|non-?commercial|Research License|RAIL|revenue",
                          re.IGNORECASE)


def load_catalog(path: Path = CATALOG) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_catalog(catalog: dict) -> list[str]:
    """Return structural problems; an empty list means the catalog is well formed."""
    problems = []
    if catalog.get("schema_version") != SCHEMA:
        problems.append("schema_version")
    candidates = catalog.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return [*problems, "candidates must be a nonempty list"]
    seen = set()
    for index, entry in enumerate(candidates):
        where = f"candidates[{index}]"
        missing = [key for key in REQUIRED if key not in entry]
        problems.extend(f"{where}: missing {key}" for key in missing)
        if entry.get("id") in seen:
            problems.append(f"{where}: duplicate id {entry.get('id')}")
        seen.add(entry.get("id"))
        if entry.get("licence_label") not in LABELS:
            problems.append(f"{where}: licence_label must be one of {LABELS}")
        sha = entry.get("weights_sha256")
        if sha is not None and not (isinstance(sha, str) and _SHA256.fullmatch(sha)):
            problems.append(f"{where}: weights_sha256 must be a lowercase SHA-256 or null")
        vram = entry.get("vram_mb")
        if vram is not None and not (type(vram) is int and vram > 0):
            problems.append(f"{where}: vram_mb must be a positive integer or null")
        if not str(entry.get("url", "")).startswith("https://"):
            problems.append(f"{where}: url must be https")
    return problems


def download_blockers(entry: dict) -> list[str]:
    """Why a candidate may not be downloaded yet; empty means the gate is open."""
    blockers = []
    if entry.get("licence_label") != "VERIFIED":
        blockers.append("licences not VERIFIED on the official page")
    if not entry.get("revision"):
        blockers.append("revision not pinned")
    if not (isinstance(entry.get("weights_sha256"), str) and _SHA256.fullmatch(entry["weights_sha256"])):
        blockers.append("weights SHA-256 not recorded")
    licences = f"{entry.get('code_licence', '')} {entry.get('weights_licence', '')}"
    if _RESTRICTIVE.search(licences) and not entry.get("licence_review"):
        blockers.append("restrictive or conditional licence needs licence_review")
    return blockers


def download_allowed(entry: dict) -> bool:
    return not download_blockers(entry)


def catalog_status(catalog: dict) -> dict:
    """Per-candidate gate state, for reports; it never downloads anything."""
    return {entry["id"]: {"download_allowed": download_allowed(entry), "blockers": download_blockers(entry)}
            for entry in catalog.get("candidates", [])}
