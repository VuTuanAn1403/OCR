"""Record downloaded model files without redistributing their weights."""
from __future__ import annotations
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    model_root = ROOT / "models/docling"
    files = []
    for path in sorted(model_root.rglob("*")):
        if not path.is_file() or path.name == "model_manifest.json" or any(
            part in ("blobs", ".locks", ".cache", "xet") for part in path.relative_to(model_root).parts
        ):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        files.append({"path": path.relative_to(model_root).as_posix(), "size_bytes": path.stat().st_size,
                      "sha256": digest.hexdigest()})
    manifest = {"schema": "docling-model-artifacts-v1", "device": "cpu",
        "packages": {p: version(p) for p in ("docling-slim", "docling-core", "docling-ibm-models", "torch", "transformers", "easyocr")},
        "requirements_lock_sha256": hashlib.sha256((ROOT / "requirements-docling.lock.txt").read_bytes()).hexdigest(),
        "files": files}
    target = model_root / "model_manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence = ROOT / "docs/integrations/docling_20261011/model_artifacts.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(target.read_bytes())
    print(json.dumps({"file_count": len(files), "bytes": sum(f["size_bytes"] for f in files), "manifest": str(evidence)}))


if __name__ == "__main__":
    main()
