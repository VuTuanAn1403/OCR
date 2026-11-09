"""Local VLM backends, gated by the model catalog (V8-043) before anything is loaded.

A backend may load weights only from a local directory, only for a catalog candidate
whose ``download_allowed`` holds (licences VERIFIED, revision pinned, weights sha256
recorded), and only when the files on disk hash to that sha256. Nothing is downloaded
here. Until a candidate is pinned, ``open_backend`` refuses with the catalog's reasons,
so no VLM run can happen by accident.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict

from benchmark.challengers import catalog

CATALOG = Path(__file__).resolve().parents[1] / "model_catalog.json"


class BackendUnavailable(RuntimeError):
    pass


def candidate(candidate_id: str, catalog_path: Path = CATALOG) -> Dict:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    for entry in data["candidates"]:
        if entry["id"] == candidate_id:
            if entry.get("experiment_layer") != "VLM":
                raise BackendUnavailable(f"{candidate_id} is not a VLM candidate")
            return entry
    raise BackendUnavailable(f"{candidate_id} is not in the catalog")


def weights_sha256(directory: Path) -> str:
    """sha256 over the sorted relative paths and bytes of every file under the weights directory."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def open_backend(candidate_id: str, weights_dir: Path, catalog_path: Path = CATALOG):
    entry = candidate(candidate_id, catalog_path)
    if not catalog.download_allowed(entry):
        raise BackendUnavailable(f"{candidate_id}: catalog does not allow use: {catalog.download_blockers(entry)}")
    if not weights_dir.is_dir():
        raise BackendUnavailable(f"{weights_dir} does not exist; weights are never downloaded by the adapter")
    found = weights_sha256(weights_dir)
    if found != entry["weights_sha256"]:
        raise BackendUnavailable(f"{candidate_id}: weights sha256 {found} differs from the catalog")
    raise BackendUnavailable(f"{candidate_id}: no inference code is written for this model yet; "
                             "add it in its own venv (.venv-v8-<candidate>) after the pin (benchmark/challengers/README.md)")
