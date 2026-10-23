"""Install a built wheel outside its checkout and verify its lightweight APIs.

Creates only a new work directory and the requested JSON report. Installs into
three disposable venvs; never installs into the invoking Python environment.
Use --offline --wheelhouse DIR for a prepared local wheelhouse.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import venv
import zipfile


PROBE = textwrap.dedent('''
    import importlib.util, json, pathlib, sys
    from importlib import metadata
    from ocr_keywords.counter import KeywordCounter
    from ocr_runtime import paths
    from ocr_runtime.fingerprint import assert_loaded_code_fingerprinted
    assert not paths.source_tree() and not paths.is_checkout()
    assert pathlib.Path(paths.__file__).is_relative_to(pathlib.Path(sys.prefix))
    for name in ("keywords.txt", "profiles.yaml", "profiles-v63.yaml", "docling_structure_worker.py",
                 "fonts/NotoSans-Regular.ttf", "fonts/OFL.txt"):
        assert paths.runtime_resource(name).is_file(), name
    assert list(paths.runtime_resource("hardware").glob("*.yaml"))
    assert paths.default_keywords_path() == paths.runtime_resource("keywords.txt")
    report = KeywordCounter.count_keywords("CHUYỂN ĐỔI SỐ; chuyển đổi số", ["chuyển đổi số"])
    assert report.total_matches == 2
    extra = sys.argv[1]
    if extra in ("reporting", "app"):
        from src.ocr.application.count_keywords import CountKeywordsUseCase
        doc = pathlib.Path("document"); doc.mkdir()
        (doc / "result.md").write_text("Chuyển đổi số", encoding="utf-8")
        report = CountKeywordsUseCase.execute(doc, "document")
        assert report.total_matches > 0 and (doc / "count_keywords.xlsx").is_file()
        explicit = pathlib.Path("explicit-keywords.txt")
        explicit.write_text("never present", encoding="utf-8")
        assert CountKeywordsUseCase.execute(doc, "document", explicit).total_matches == 0
    if extra == "app":
        import ocr_pipeline.analysis_run, ocr_pipeline.backend, ocr_pipeline.cli
        try:
            ocr_pipeline.backend.prepare_backend(paths.runtime_resource("profiles-v63.yaml"),
                "unified_gpu_full_ocr", pathlib.Path("missing-envs"))
        except ValueError as exc:
            assert str(exc).startswith("NOT_SUPPORTED"), str(exc)
        else:
            raise AssertionError("GPU wheel backend must be rejected explicitly")
    assert_loaded_code_fingerprinted()
    forbidden = ("torch", "vietocr", "onnxruntime", "docling", "cv2")
    assert all(importlib.util.find_spec(name) is None for name in forbidden)
    print(json.dumps({"extra": extra, "version": metadata.version("ocr-pdf"), "prefix": sys.prefix,
                      "site": str(paths.PACKAGE_ROOT), "resource": str(paths.default_keywords_path()),
                      "gpu_inference": "NOT_RUN", "accuracy": "NOT_EVALUATED"}))
''')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True, help="An already built ocr_pdf wheel")
    parser.add_argument("--work-dir", type=Path, required=True, help="New directory; existing paths are refused")
    parser.add_argument("--output", type=Path, required=True, help="JSON evidence file")
    parser.add_argument("--wheelhouse", type=Path, help="Optional directory of dependency wheels")
    parser.add_argument("--offline", action="store_true", help="Install with --no-index")
    parser.add_argument("--installer", choices=("pip", "uv"), default="pip",
                        help="uv can reuse an existing local cache with --offline; no runtime is installed")
    args = parser.parse_args(argv)
    wheel, work, output = args.wheel.absolute(), args.work_dir.absolute(), args.output.absolute()
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error("--wheel must name an existing wheel")
    root = Path(__file__).absolute().parents[2]
    if work.is_relative_to(root):
        parser.error("--work-dir must be outside the checkout")
    if args.offline and not args.wheelhouse and args.installer == "pip":
        parser.error("--offline requires --wheelhouse with the pinned dependencies")
    if args.installer == "uv" and not shutil.which("uv"):
        parser.error("uv is not installed; use pip or prepare uv separately")
    if work.exists():
        parser.error("--work-dir already exists; use a fresh path (nothing will be deleted)")
    work.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    probe = work / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("OCR_") and k not in (
        "PYTHONPATH", "PYTHONHOME", "VIETOCR_MODEL_DIR")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    evidence = {"schema_version": "installed-wheel-check-v1", "status": "RUNNING", "wheel": str(wheel),
                "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "environments": {},
                "gpu_inference": "NOT_RUN", "ground_truth_accuracy": "NOT_EVALUATED"}
    try:
        for extra in ("core", "reporting", "app"):
            evidence["active_environment"] = extra
            target = work / extra
            venv.EnvBuilder(with_pip=True).create(target)
            python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            cwd = work / (extra + "-unrelated-project")
            cwd.mkdir()
            (cwd / "pyproject.toml").write_text("[project]\nname='unrelated'\n", encoding="utf-8")
            (cwd / "config").mkdir()
            (cwd / "config/keywords.txt").write_text("wrong dictionary", encoding="utf-8")
            requirement = str(wheel) + (f"[{extra}]" if extra != "core" else "")
            command = (["uv", "pip", "install", "--python", str(python), requirement]
                       if args.installer == "uv" else [str(python), "-m", "pip", "install", requirement])
            if args.wheelhouse:
                command.extend(["--find-links", str(args.wheelhouse.absolute())])
            if args.offline:
                command.append("--offline" if args.installer == "uv" else "--no-index")
            subprocess.run(command, cwd=cwd, env=env, check=True, timeout=600)
            subprocess.run([str(python), "-m", "pip", "check"], cwd=cwd, env=env, check=True, timeout=60)
            result = subprocess.run([str(python), "-I", "-B", str(probe), extra], cwd=cwd, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=180)
            if result.returncode:
                raise RuntimeError(f"{extra} probe failed:\n{result.stdout}\n{result.stderr}")
            info = json.loads(result.stdout.strip().splitlines()[-1])
            site = Path(info["site"])
            checked = 0
            with zipfile.ZipFile(wheel) as archive:
                assert not any(name.startswith("src/ocr_") for name in archive.namelist())
                for name in archive.namelist():
                    if name.endswith("/") or ".dist-info/" in name or ".data/" in name:
                        continue
                    installed = site / name
                    assert installed.is_file() and installed.read_bytes() == archive.read(name), name
                    checked += 1
            evidence["environments"][extra] = {**info, "status": "PASS", "installed_files_verified": checked}
            if extra == "app":
                subprocess.run([str(python), "-I", "-B", "-c",
                                "from src.ocr.cli.unified import run_batch; run_batch()", "--help"],
                               cwd=cwd, env=env, check=True, timeout=60)
        evidence.update(status="PASS", active_environment=None)
        return 0
    except Exception as exc:
        evidence.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
        print(evidence["error"], file=sys.stderr)
        return 1
    finally:
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
