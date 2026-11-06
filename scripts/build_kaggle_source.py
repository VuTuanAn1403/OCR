"""Package this checkout's runtime for Kaggle without Git publishing or model weights."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("Use a new source archive path")
    paths = set()
    for folder in ("src", "scripts", "config", "requirements/v62", "requirements/v63", "requirements/v70"):
        paths.update(p for p in (ROOT / folder).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and not p.name.endswith((".pyc", ".pyo"))
                     and ".egg-info" not in str(p.parent))
    paths.update(ROOT / n for n in ("pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "run_batch.py", "run_ocr.py",
                                    "models/v62/runtime-models.json", "assets/fonts/NotoSans-Regular.ttf", "assets/fonts/OFL.txt"))
    paths = sorted(p for p in paths if p.is_file())
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    manifest = {"schema_version": "kaggle-source-v1", "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
                "files": hashes, "excludes": ["model weights", "PDF inputs", "outputs", "credentials", "virtual environments"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr("kaggle-source-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != checksum for name, checksum in hashes.items()):
        raise RuntimeError("Source changed during packaging; discard this archive and use a new path")
    return {"archive": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "files": len(hashes)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(build(parser.parse_args().output)))
