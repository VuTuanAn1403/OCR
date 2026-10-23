"""Private phase worker: `python -m ocr_workers.phases --request R --phase P`.

Only this child imports the model/pipeline modules. Each phase lives in its
own module (`phase_text`, `phase_structure`, `phase_export`), so its code
identity is its own stage closure (P11b). This entry imports none of them
statically: it loads the requested one by name and, when the phase is done,
refuses any project module loaded outside that phase's fingerprinted closure.
"""
from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from ocr_artifacts.hashing import sha256_file as sha256
from ocr_workers.stage_io import read

PHASE_MODULES = {"text": "ocr_workers.phase_text", "structure": "ocr_workers.phase_structure",
                 "export": "ocr_workers.phase_export"}
# Names defined here before P11b; still importable from this module and its
# legacy alias `src.ocr.runtime.gpu_phase_worker`.
_MOVED = {"run_text": "text", "run_structure": "structure", "phase_b_status_accepted": "structure",
          "run_export": "export"}


def __getattr__(name):
    if name in _MOVED:
        return getattr(importlib.import_module(PHASE_MODULES[_MOVED[name]]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--phase", choices=tuple(PHASE_MODULES), required=True)
    args = parser.parse_args()
    request = read(args.request)
    from ocr_runtime.dependency_lock import verify_installed_lock
    lock = next(path for path in request["lock_hashes"] if path.endswith("text-gpu.lock"))
    verify_installed_lock(lock)
    # No mutable weights, locks or source may be reused after phase A starts.
    from ocr_runtime.fingerprint import extraction_fingerprint, legacy_stage, stage_fingerprint
    if request["identity"]["source"] != extraction_fingerprint():
        raise RuntimeError("Source changed during document phases; restart with a new generation")
    legacy = legacy_stage(args.phase, request["config"], request.get("finalize_document", True))
    stages = request.get("stages")
    if stages and stages[args.phase]["code"] != stage_fingerprint(args.phase, legacy=legacy):
        raise RuntimeError(f"Phase {args.phase} code differs from its stage key; restart with a new generation")
    for path, digest in {**request["model_hashes"], **request["lock_hashes"]}.items():
        if sha256(path) != digest:
            raise RuntimeError(f"Runtime input changed during document phases: {path}")
    # The files this process would load must be the pinned ones (F06).
    from ocr_runtime.paths import registry_model_path
    for name, path in (request.get("model_selection") or {}).items():
        if str(registry_model_path(name).resolve()) != path:
            raise RuntimeError(f"MODEL_SELECTION_CHANGED: this worker would load {name} from "
                               f"{registry_model_path(name).resolve()}, not the pinned {path}")
    if request.get("model_registry_path"):
        from ocr_runtime.model_registry import validate_registry
        validate_registry(read(Path(request["model_registry_path"])))
    getattr(importlib.import_module(PHASE_MODULES[args.phase]), f"run_{args.phase}")(request)
    # Everything the phase imported must be inside the fingerprinted files and
    # inside this phase's own closure, or its stage key could miss a change.
    from ocr_runtime.fingerprint import assert_loaded_code_fingerprinted, assert_loaded_code_in_stage
    assert_loaded_code_fingerprinted()
    assert_loaded_code_in_stage(args.phase, legacy=legacy)


if __name__ == "__main__":
    main()
