"""Read-only diagnosis of the selected runtime, paths and resources (P12).

`python -m ocr_runtime.diagnose [--json] [--verify-models]` shows the code
layout, the project root and why it was chosen, every resolved path with the
source of its value, the declared pipeline of each profile file, bundled
resources, the worker runtimes and which optional libraries are installed.
It writes nothing, repairs nothing and imports no model library; model files
are hashed only with --verify-models.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

from ocr_runtime import paths

OPTIONAL_MODULES = ("pydantic", "yaml", "psutil", "openpyxl", "pymupdf", "numpy", "cv2", "PIL", "torch",
                    "vietocr", "onnxruntime", "rapidocr_onnxruntime", "docling")


def _entry(name, path, source):
    path = Path(path)
    return {"name": name, "path": str(path), "source": source, "exists": path.exists()}


def _env_or(name, default):
    value = os.getenv(name)
    return (Path(value).expanduser(), name) if value else (Path(default), "default")


def _project_root_source():
    if os.getenv("OCR_PROJECT_ROOT"):
        return "OCR_PROJECT_ROOT"
    return "checkout" if paths.is_checkout() else "working directory"


def _declaration(path):
    try:
        from ocr_runtime.config import read_declaration
        return read_declaration(path)
    except ImportError as exc:  # PyYAML is part of the app extra
        return {"error": f"cannot read: {exc.name} not installed"}
    except Exception as exc:  # report, never repair
        return {"error": f"{type(exc).__name__}: {exc}"}


def _registry(verify):
    path = paths.PROJECT_ROOT / "models/v62/runtime-models.json"
    report = {"path": str(path), "exists": path.is_file()}
    if not report["exists"]:
        return report
    files = json.loads(path.read_text(encoding="utf-8")).get("files", {})
    selected = {name: paths.registry_model_path(name).resolve() for name in files}
    present = {name: path.is_file() for name, path in selected.items()}
    report.update(files_listed=len(files), files_present=sum(present.values()),
                  missing=sorted(name for name, ok in present.items() if not ok)[:20])
    if verify:
        from ocr_artifacts.hashing import sha256_file
        report["hash_mismatch"] = sorted(name for name, digest in files.items()
                                         if present[name] and sha256_file(selected[name]) != digest)
    report["selected_files"] = {name: str(path) for name, path in selected.items()}
    return report


def collect(verify_models=False):
    root = paths.PROJECT_ROOT
    models, models_source = _env_or("OCR_MODELS_DIR", root / "models")
    lease, lease_source = _env_or("OCR_GPU_LEASE_DIR", root / ".cache/gpu-leases")
    v63_cache_source = "OCR_CACHE_DIR" if os.getenv("OCR_CACHE_DIR") else "default"
    profile_files = [(paths.default_profile_path(), "canonical unified profile"),
                     (root / "config/profiles-v62.yaml" if paths.is_checkout() else None, "retired path alias"),
                     (root / "config/profiles-v63.yaml" if paths.is_checkout()
                      else paths.runtime_resource("profiles-v63.yaml"), "canonical path alias")]
    if os.getenv("OCR_CONFIG_PATH"):
        profile_files.insert(0, (Path(os.environ["OCR_CONFIG_PATH"]).expanduser(), "OCR_CONFIG_PATH"))
    suffix = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return {
        "layout": {"source_tree": paths.source_tree(), "package_root": str(paths.PACKAGE_ROOT),
                   "legacy_root": str(paths.LEGACY_ROOT), "project_root": str(root),
                   "project_root_source": _project_root_source(), "is_checkout": paths.is_checkout(),
                   "code_roots": [str(p) for p in paths.code_roots()], "python": sys.executable},
        "paths": [
            _entry("data", paths.data_dir(), "OCR_DATA_DIR" if os.getenv("OCR_DATA_DIR") else "default, working directory"),
            _entry("output", paths.output_dir(), "OCR_OUTPUT_DIR" if os.getenv("OCR_OUTPUT_DIR") else "default, working directory"),
            _entry("V6.3 job and stage cache", paths.v63_cache_root(), v63_cache_source),
            _entry("models", models, models_source),
            _entry("VietOCR weights", Path(os.getenv("VIETOCR_MODEL_DIR") or models / "vietocr"),
                   "VIETOCR_MODEL_DIR" if os.getenv("VIETOCR_MODEL_DIR") else "models/vietocr"),
            _entry("GPU leases", lease, lease_source),
        ],
        "profile_files": [{"file": str(path), "role": role, "exists": path.is_file(),
                           "declaration": _declaration(path) if path.is_file() else None}
                          for path, role in profile_files if path is not None],
        "resources": [_entry("keyword dictionary", paths.default_keywords_path(),
                             "checkout" if paths.is_checkout() else "bundled"),
                      _entry("Docling worker entry", paths.docling_worker_path(),
                             "checkout" if paths.is_checkout() else "bundled")],
        "worker_runtimes": [_entry(f"V6.3 {role}", root / ".venv-v62" / role / suffix, "default --env-root")
                            for role in ("text", "docling")],
        "model_registry": _registry(verify_models),
        "installed": {name: importlib.util.find_spec(name) is not None for name in OPTIONAL_MODULES},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verify-models", action="store_true", help="hash every registry model file (slow)")
    args = parser.parse_args(argv)
    report = collect(args.verify_models)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    for section, value in report.items():
        print(f"[{section}]")
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            print("  " + ", ".join(f"{k}={v}" for k, v in row.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
