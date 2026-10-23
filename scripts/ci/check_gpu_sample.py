"""Opt-in real V6.3 GPU sample fresh/resume acceptance on prepared runtimes.

No dependency/model setup or cleanup is performed. Requires new output/cache
paths and preserves the shared machine GPU lease. This is not a quality test.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True, help="User-provided single-page PDF; never bundled")
    parser.add_argument("--env-root", type=Path, required=True, help="Prepared text/docling environments")
    parser.add_argument("--output-dir", type=Path, required=True, help="New batch output directory")
    parser.add_argument("--cache-dir", type=Path, required=True, help="New cache directory, excluding GPU leases")
    parser.add_argument("--report", type=Path, required=True, help="JSON evidence file")
    parser.add_argument("--baseline", type=Path, help="Existing verified sample document directory (read only)")
    args = parser.parse_args(argv)
    root = Path(__file__).absolute().parents[2]
    output, cache, report = args.output_dir.absolute(), args.cache_dir.absolute(), args.report.absolute()
    stage_output = output.with_name(output.name + "-stage-resume")
    if output.exists() or cache.exists() or stage_output.exists():
        parser.error("output/cache paths must be new; nothing will be overwritten or deleted")
    if output == cache or output.is_relative_to(cache) or cache.is_relative_to(output):
        parser.error("output and cache must be disjoint")
    if not args.env_root.is_dir():
        parser.error("--env-root must point to prepared runtimes; this script will not create them")
    sample = args.sample.absolute()
    if not sample.is_file():
        parser.error("--sample must point to an existing single-page PDF")
    import pymupdf
    with pymupdf.open(sample) as pdf:
        if len(pdf) != 1:
            parser.error("--sample must contain exactly one page for this bounded GPU check")
    report.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": os.pathsep.join([str(root / "src"), str(root)]), "OCR_CACHE_DIR": str(cache)}
    # OCR_GPU_LEASE_DIR is intentionally inherited, never replaced with this run's cache.
    evidence = {"schema_version": "gpu-sample-check-v1", "status": "RUNNING", "fixture": str(sample),
                "scope": "V6.3 sample fresh/resume; no long batch or ground-truth acceptance",
                "accuracy": "NOT_EVALUATED", "gpu_inference": "NOT_RUN"}
    try:
        sys.path[:0] = [str(root / "src"), str(root)]
        from ocr_runtime.fingerprint import code_fingerprints
        code = code_fingerprints()
        command = [sys.executable, "-B", str(root / "run_ocr.py"), str(sample),
                   "--output", str(output), "--env-root", str(args.env_root.absolute()), "--assets", "png"]
        subprocess.run(command, cwd=root, env=env, check=True, timeout=1200)
        from ocr_pipeline.analysis_run import verify_extraction_source
        from ocr_artifacts.hashing import sha256_file
        directory = output / sample.stem
        fresh = verify_extraction_source(directory)
        audit = json.loads((directory / "gpu_scheduler.json").read_text(encoding="utf-8"))
        runtime = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["gpu_runtime"]
        placement = {name: runtime["phase_a_placement"][name]["status"]
                     for name in ("detector", "recognizer", "layout")}
        placement["docling"] = [entry["status"] for entry in runtime["phase_b_placement"]]
        assert all(placement[name] == "VERIFIED_INFERENCE" for name in ("detector", "recognizer", "layout"))
        assert placement["docling"] and set(placement["docling"]) == {"VERIFIED_INFERENCE"}
        assert audit["status"] == "COMPLETED"
        assert not any(audit["phases"][phase].get("resumed") for phase in ("text", "structure"))
        assert all(audit["phases"][phase]["tree_exited"] for phase in ("text", "structure", "export"))
        assert code_fingerprints() == code, "source changed during GPU verification"
        stable = ("result.md", "document.md", "document.json", "extraction.json", "structure.json")
        before = {name: sha256_file(directory / name) for name in stable}
        evidence.update(fresh=fresh, gpu_inference="VERIFIED_BY_EXTRACTION_GATE", placement=placement)
        subprocess.run(command + ["--resume"], cwd=root, env=env, check=True, timeout=300)
        resumed = verify_extraction_source(directory)
        assert before == {name: sha256_file(directory / name) for name in stable}
        assert fresh["ocr_identity"] == resumed["ocr_identity"]
        # Batch resume can retain the original audit without invoking the scheduler.
        # Its original START/TREE_EXITED events then remain historical, not new inference.
        after = json.loads((directory / "gpu_scheduler.json").read_text(encoding="utf-8"))
        assert after == audit, "unchanged batch resume unexpectedly scheduled extraction"
        stage_command = list(command)
        stage_command[stage_command.index("--output") + 1] = str(stage_output)
        subprocess.run(stage_command + ["--resume"], cwd=root, env=env, check=True, timeout=300)
        stage_directory = stage_output / sample.stem
        stage_source = verify_extraction_source(stage_directory)
        stage_audit = json.loads((stage_directory / "gpu_scheduler.json").read_text(encoding="utf-8"))
        assert stage_audit["status"] == "COMPLETED"
        assert all(stage_audit["phases"][phase]["resumed"] for phase in ("text", "structure"))
        assert stage_audit["phases"]["export"]["tree_exited"]
        assert [event["phase"] for event in stage_audit["events"]] == ["export", "export"]
        assert before == {name: sha256_file(stage_directory / name) for name in stable}
        assert code_fingerprints() == code, "source changed during GPU verification"
        baseline_result = None
        if args.baseline:
            baseline = args.baseline.absolute()
            verify_extraction_source(baseline)
            compared = (*stable, *(p.relative_to(directory).as_posix() for p in (directory / "pages").glob("*.md")))
            differing = [name for name in compared if sha256_file(baseline / name) != sha256_file(directory / name)]
            assert not differing, f"baseline artifact regression: {differing}"
            old_counts = json.loads((baseline / "keyword_counts.json").read_text(encoding="utf-8"))
            new_counts = json.loads((directory / "keyword_counts.json").read_text(encoding="utf-8"))
            assert all(old_counts[key] == new_counts[key] for key in ("canonical_counts", "display_counts"))
            baseline_result = {"directory": str(baseline), "stable_files_compared": len(compared),
                               "differing": differing, "keyword_vectors_equal": True}
        evidence.update(status="PASS", resumed=resumed, stable_files=before, code_fingerprints=code,
                        baseline=baseline_result, stage_resumed=stage_source,
                        resume_execution="BATCH_REUSE_NO_NEW_EXTRACTION",
                        stage_resume_execution="STAGES_A_B_REUSED_EXPORT_RAN")
        return 0
    except Exception as exc:
        evidence.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
        print(evidence["error"], file=sys.stderr)
        return 1
    finally:
        report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
