#!/usr/bin/env python3
"""Performance run on the product pipeline (proposal V6 section 6.5, V8-042); writes perf.json.

Every document runs through `ocr_pipeline.cli.main` in a child process
(`benchmark/product_run.py`): CUDA, every page, the unified profile, a fresh
output root per repeat and no `--resume`, so no stage or page is reused (H24).

Keeps the four quantities of section 6.1 apart:
- page latency: `quality.json` page reports, never from cache; p50 / mean / p95 per page category;
- document latency: product process start to exit (OCR, Docling, export, keywords, Excel);
- throughput: pages / wall time of the whole repeat;
- start-up: model loading before the first page, as the product records it.

Also reports PERF-02 (tail), PERF-05 (start-up), PERF-06 (peak RSS of the
product process tree; peak device VRAM from the scheduler samples), PERF-08
(stage and phase breakdown, run manifest) and PERF-09 (output size per page).
The CPU limits REQ-01..03 stay NOT_EVALUATED: product OCR runs only on CUDA.
With --ground-truth, quality is measured on the same outputs.

Example:
  python benchmark/perf/run_perf.py --pdf inputs/ACL_Baocaothuongnien_2022.pdf --repeat 3 --output output/<new>/perf
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import product_run  # noqa: E402  (puts src/ on sys.path)
from ocr_artifacts.atomic_io import atomic_write_json  # noqa: E402
from ocr_runtime.config import ConfigError, config_hash  # noqa: E402
from ocr_runtime.pipeline_policy import PROFILE  # noqa: E402
from ocr_runtime.structured_logging import LOG_FORMATS, configure_logging  # noqa: E402

PERF_SCHEMA = "perf-v2"
# Agreed CPU requirements (REQ-01..03), applied to p50 as proposed in ADJ-05.
CPU_P50_LIMITS = {"native": 0.15, "mixed": 1.80, "scan": 2.50}
# Low-quality native pages are processed like scans (H13 table); the two
# product-showcase pages of the sample were counted as scans in section 6.1.
_CATEGORY = {"NATIVE_TEXT": "native", "MIXED": "mixed"}
REGRESSION_TOLERANCE = 0.10  # section 6.5: >10% slower on the same hardware
_NO_DOCLING = (None, "DISABLED", "SKIPPED_NO_STRUCTURE_CANDIDATE")


def page_category(page_type: str) -> str:
    return _CATEGORY.get(page_type, "scan")


def percentile(values: List[float], q: float) -> Optional[float]:
    """Linear-interpolated percentile, q in [0, 100]."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100.0
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _stats(values: List[float]) -> Dict[str, Optional[float]]:
    return {
        "n": len(values),
        "p50": _round(percentile(values, 50)),
        "mean": _round(statistics.fmean(values) if values else None),
        "p95": _round(percentile(values, 95)),
        "max": _round(max(values) if values else None),
    }


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 4)


def summarize_pages(pages: Iterable[Dict[str, Any]], page_timeout: float, device: str = "cpu") -> Dict[str, Any]:
    """Aggregate page records ({category, page_type, seconds, stages, from_cache,
    docling_called}) into per-category latency, tail and stage statistics."""
    pages = list(pages)
    excluded = sum(1 for p in pages if p["from_cache"])
    measured = [p for p in pages if not p["from_cache"]]
    summary: Dict[str, Any] = {"pages_measured": len(measured), "pages_excluded_from_cache": excluded,
                               "categories": {}}
    for category in sorted({p["category"] for p in measured}):
        group = [p for p in measured if p["category"] == category]
        seconds = [p["seconds"] for p in group]
        stats = _stats(seconds)
        raw_p50, raw_p95 = percentile(seconds, 50), percentile(seconds, 95)
        stage_names = sorted({name for p in group for name in p["stages"]})
        limit = CPU_P50_LIMITS.get(category)
        entry: Dict[str, Any] = {
            "latency_seconds": stats,
            "page_types": dict(sorted(_count(p["page_type"] for p in group).items())),
            "stage_mean_seconds": {name: _round(statistics.fmean(p["stages"].get(name, 0.0) for p in group))
                                   for name in stage_names},
            # PERF-02: tail no worse than 3 x p50, and no page over the timeout.
            "perf02_tail_ok": _within_limit(raw_p95, 3 * raw_p50) if raw_p50 is not None else None,
            "pages_over_timeout": sum(1 for s in seconds if s > page_timeout),
            "cpu_p50_limit_seconds": limit,
            "meets_cpu_p50_limit": _within_limit(raw_p50, limit) if device == "cpu" and limit is not None else None,
            "cpu_comparison_status": "MEASURED" if device == "cpu" else "NOT_EVALUATED_NON_CPU_DEVICE",
            "limit_statistic_status": "PROPOSED_ADJ_05_PENDING_APPROVAL",
        }
        if category == "native":
            # Reported for ADJ-01 (pending approval); the agreed limit still applies.
            for label, called in (("with_docling", True), ("without_docling", False)):
                entry[f"latency_seconds_{label}"] = _stats([p["seconds"] for p in group if p["docling_called"] is called])
        summary["categories"][category] = entry
    return summary


def _within_limit(value: Optional[float], limit: float) -> Optional[bool]:
    if value is None:
        return None
    return value <= limit or math.isclose(value, limit, rel_tol=0, abs_tol=1e-12)


def _count(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def compare_with_previous(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """Flag categories whose p50 page latency regressed by more than 10%.
    Only meaningful on the same hardware, which is checked first."""
    hardware_now = current.get("run_manifest", {}).get("hardware", {})
    hardware_before = previous.get("run_manifest", {}).get("hardware", {})
    same_hw = bool(hardware_now.get("processor")) and hardware_now.get("processor") == hardware_before.get("processor")
    for key in ("cpu_count_physical", "cpu_count_logical", "total_ram_gb", "gpu_name", "gpu_total_vram_gb"):
        if key in hardware_now or key in hardware_before:
            same_hw = same_hw and hardware_now.get(key) == hardware_before.get(key)
    result: Dict[str, Any] = {"same_hardware": same_hw, "regressions": []}
    if not same_hw:
        return result
    mismatches = []
    for key in ("device", "assets_mode", "output_mode"):
        default = "legacy" if key == "output_mode" else None
        if (key in current or key in previous) and current.get(key, default) != previous.get(key, default):
            mismatches.append(key)
    def workload(report):
        return {(page.get("document_id"), page.get("page"), page.get("page_type"))
                for page in report.get("pages", [])}
    if ("pages" in current or "pages" in previous) and workload(current) != workload(previous):
        mismatches.append("page_workload")
    result["comparable"] = not mismatches
    result["mismatches"] = mismatches
    if mismatches:
        return result
    now = current.get("page_latency", {}).get("categories", {})
    before = previous.get("page_latency", {}).get("categories", {})
    for category, entry in now.items():
        old = before.get(category, {}).get("latency_seconds", {}).get("p50")
        new = entry["latency_seconds"]["p50"]
        if old and new and new > old * (1 + REGRESSION_TOLERANCE):
            result["regressions"].append({"category": category, "p50_before": old, "p50_now": new})
    return result


def _dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def hardware_record() -> Dict[str, Any]:
    """Processor, RAM and GPU of this machine; a missing tool leaves its fields out."""
    record: Dict[str, Any] = {"processor": platform.processor() or platform.machine() or None,
                              "platform": platform.platform()}
    try:
        import psutil
        record.update(cpu_count_physical=psutil.cpu_count(logical=False), cpu_count_logical=psutil.cpu_count(),
                      total_ram_gb=round(psutil.virtual_memory().total / 1024 ** 3, 1))
    except ImportError:
        pass
    try:
        query = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return record
    lines = query.stdout.strip().splitlines() if query.returncode == 0 else []
    if lines:
        name, _, memory = lines[0].rpartition(",")
        record["gpu_name"] = name.strip()
        try:
            record["gpu_total_vram_gb"] = round(float(memory) / 1024, 1)
        except ValueError:
            pass
    return record


def page_records(document_dir: Path) -> List[Dict[str, Any]]:
    """Per-page timing the product wrote to quality.json, with each page's Docling status."""
    quality = product_run.read_json(document_dir / "quality.json")
    if quality is None:
        raise ValueError(f"{document_dir} has no readable quality.json")
    document_id = quality.get("document_id") or document_dir.name
    records = []
    for report in quality.get("page_reports") or []:
        page = int(report["page"])
        seconds = report.get("time_taken_seconds")
        if not isinstance(seconds, (int, float)):
            raise ValueError(f"{document_dir} page {page} has no time_taken_seconds")
        page_json = product_run.read_json(document_dir / "pages" / f"page-{page:04d}.json") or {}
        status = ((page_json.get("metadata") or {}).get("docling_structure") or {}).get("status")
        records.append({
            "document_id": document_id, "page": page, "page_type": report.get("page_type"),
            "category": page_category(report.get("page_type") or ""), "seconds": float(seconds),
            "stages": dict(report.get("stage_seconds") or {}), "from_cache": bool(report.get("from_cache")),
            "docling_called": status not in _NO_DOCLING, "errors": report.get("errors"),
            "content_status": report.get("content_status"),
        })
    return records


def document_timing(document_dir: Path, run_record: Dict[str, Any]) -> Dict[str, Any]:
    manifest = product_run.read_json(document_dir / "manifest.json") or {}
    scheduler = product_run.read_json(document_dir / "gpu_scheduler.json")
    summary = manifest.get("summary") or {}
    timing: Dict[str, Any] = {"document_latency_seconds": run_record["wall_seconds"],
                              "document_latency_scope": "product process start to exit"}
    for key, name in (("startup_seconds", "startup_seconds"), ("total_time_seconds", "pipeline_seconds")):
        if isinstance(summary.get(key), (int, float)):
            timing[name] = summary[key]
    if scheduler:
        timing["phase_seconds"] = {name: phase.get("seconds") for name, phase in (scheduler.get("phases") or {}).items()}
    return {"timing": timing, "manifest": manifest, "scheduler": scheduler}


def run(args: argparse.Namespace, run_document: Callable[..., Dict[str, Any]] = product_run.run_product) -> Dict[str, Any]:
    document_ids = [Path(pdf).stem.casefold() for pdf in args.pdf]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("Performance inputs must have distinct document IDs (PDF filenames)")
    config_path, profile = product_run.base_profile(args.config)
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Performance output must be fresh: {output}")
    git = product_run.git_state()
    repeats: List[Dict[str, Any]] = []
    all_pages: List[Dict[str, Any]] = []
    documents: List[Dict[str, Any]] = []
    devices, models, pages_from_cache, reused_stages = set(), {}, [], []
    timeout = float(profile.get("page_timeout_seconds", 120))
    for repeat in range(1, args.repeat + 1):
        repeat_dir = output / f"repeat-{repeat}"
        started = time.perf_counter()
        runs = [run_document(pdf, repeat_dir / Path(pdf).stem, config=config_path, assets=args.assets,
                             output_mode=args.output_mode) for pdf in args.pdf]
        wall = time.perf_counter() - started
        # Reading artifacts, hashing and quality evaluation stay outside the wall-clock interval.
        repeat_pages, vram = 0, []
        for run_record in runs:
            document_dir = Path(run_record["output"])
            entry: Dict[str, Any] = {
                "repeat": repeat, "document_id": run_record["document_id"], "status": run_record["status"],
                "returncode": run_record["returncode"], "log": run_record["log"],
                "ocr_identity": run_record["ocr_identity"], "pdf_sha256": run_record["pdf_sha256"],
                "peak_rss_mb": run_record["peak_rss_mb"], "pages": 0, "timing": {},
                "output_bytes": None, "output_kb_per_page": None, "quality": None,
            }
            documents.append(entry)
            if run_record["status"] != "COMPLETED":
                continue
            records = page_records(document_dir)
            details = document_timing(document_dir, run_record)
            manifest, scheduler = details["manifest"], details["scheduler"]
            devices.add(manifest.get("device"))
            models = models or dict((manifest.get("gpu_runtime") or {}).get("model_locks") or {})
            pages_from_cache += [[entry["document_id"], page] for page in
                                 (manifest.get("cache") or {}).get("pages_from_cache") or []]
            reused_stages += [[entry["document_id"], name] for name, stage in
                              ((manifest.get("gpu_runtime") or {}).get("stages") or {}).items() if stage.get("reused")]
            vram.append(product_run.peak_device_vram_mib(scheduler))
            output_bytes = _dir_bytes(document_dir)
            entry.update(pages=len(records), timing=details["timing"], output_bytes=output_bytes,
                         output_kb_per_page=round(output_bytes / 1024 / max(1, len(records)), 1),
                         peak_device_vram_mib=vram[-1], quality=_evaluate(document_dir, args.ground_truth))
            all_pages.extend({**record, "repeat": repeat} for record in records)
            repeat_pages += len(records)
        known_vram = [value for value in vram if value is not None]
        repeats.append({
            "repeat": repeat, "pages": repeat_pages, "wall_seconds": round(wall, 3),
            # PERF-04, one worker (W = 1, eta = 1).
            "throughput_pages_per_hour": round(repeat_pages / wall * 3600, 1) if wall else None,
            "peak_rss_mb": max((r["peak_rss_mb"] for r in runs if r["peak_rss_mb"] is not None), default=None),
            "peak_rss_scope": "product process tree, including its GPU workers",
            "peak_device_vram_mib": max(known_vram) if known_vram else None,
            "peak_vram_scope": "device-wide used memory sampled by the product scheduler",
            "documents_failed": sum(r["status"] != "COMPLETED" for r in runs),
        })

    device = devices.pop() if len(devices) == 1 else (None if not devices else "MIXED")
    completed = [d for d in documents if d["status"] == "COMPLETED"]
    report = {
        "schema": PERF_SCHEMA,
        "entry_point": product_run.ENTRY_POINT,
        "profile": PROFILE,
        "device": device,
        "assets_mode": args.assets,
        "output_mode": args.output_mode,
        "repeats": repeats,
        "page_latency": summarize_pages(all_pages, timeout, device=device or "unknown"),
        "document_latency_seconds": _stats([d["timing"]["document_latency_seconds"] for d in completed]),
        "startup_seconds": _stats([d["timing"]["startup_seconds"] for d in completed
                                   if "startup_seconds" in d["timing"]]),
        "output_kb_per_page": _stats([d["output_kb_per_page"] for d in completed]),
        "documents": documents,
        "pages": all_pages,
        "pages_with_errors": sum(bool(page["errors"]) for page in all_pages),
        "run_manifest": {
            "schema": "perf-run-manifest-v2", "entry_point": product_run.ENTRY_POINT, "git": git,
            **product_run.code_identity(), "config_path": str(config_path),
            "config_file_sha256": product_run.file_sha256(config_path), "profile": PROFILE,
            "profile_config_sha256": config_hash(profile), "hardware": hardware_record(),
            "cache": {"resume": False, "empty_at_start": True, "pages_from_cache": pages_from_cache,
                      "reused_stages": reused_stages},
            "models": models,
            "inputs": [{"pdf": str(pdf), "sha256": product_run.file_sha256(Path(pdf))} for pdf in args.pdf],
        },
    }
    report["protocol_readiness"] = protocol_readiness(report)
    if args.compare:
        report["comparison"] = compare_with_previous(report, json.loads(Path(args.compare).read_text(encoding="utf-8")))
    atomic_write_json(output / "perf.json", report)
    return report


def protocol_readiness(report: Dict[str, Any]) -> Dict[str, Any]:
    """Report measured evidence and pending decisions without declaring acceptance."""
    manifest = report.get("run_manifest", {})
    cache = manifest.get("cache", {})
    models = manifest.get("models", {})
    documents = report.get("documents", [])
    measured_quality = [doc.get("quality") for doc in documents]
    checks = {
        "cuda_device": report.get("device") == product_run.PRODUCT_DEVICE,
        "unified_profile": report.get("profile") == PROFILE,
        "three_repeats": len(report.get("repeats", [])) >= 3,
        "clean_commit": manifest.get("git", {}).get("dirty") is False and
                        bool(manifest.get("git", {}).get("commit")),
        "fresh_output_without_resume": cache.get("empty_at_start") is True and cache.get("resume") is False
                                       and not cache.get("pages_from_cache") and not cache.get("reused_stages"),
        "model_hashes_recorded": bool(models) and all(value is not None for value in models.values()),
        "startup_recorded_without_errors": bool(documents) and all(
            doc.get("status", "COMPLETED") == "COMPLETED" and "startup_seconds" in doc.get("timing", {})
            for doc in documents),
        "no_page_errors": report.get("pages_with_errors", 0) == 0,
        "quality_on_same_outputs": bool(measured_quality) and all(
            quality is not None and quality.get("academic_metrics", {}).get("evaluated_pages", 0) > 0
            for quality in measured_quality),
    }
    return {
        "checks": checks,
        "run_classification": "RECORDED_CANDIDATE" if checks["clean_commit"] else
                              "EXPLORATORY_DIRTY_WORKTREE" if manifest.get("git", {}).get("dirty") is True else
                              "EXPLORATORY_UNVERIFIED_CODE_STATE",
        "acceptance_status": "NOT_EVALUATED",
        "pending_requirements": ["dev pilot and frozen test split (9.3)",
                                 "stakeholder-approved absolute thresholds (9.3)",
                                 "company-cluster non-inferiority comparison to B0 (PERF-07)",
                                 "approved latency statistic (ADJ-05)",
                                 "GPU latency limits: REQ-01..03 are CPU limits and product OCR runs only on CUDA"],
        "comparison_scope": "latency regression diagnostic; not a PERF-07 quality acceptance test",
    }


def _evaluate(doc_dir: Path, ground_truth: Optional[str]) -> Optional[Dict[str, Any]]:
    if not ground_truth:
        return None
    from scripts.run_scientific_benchmark import evaluate_document_scientific
    return evaluate_document_scientific(doc_dir, Path(ground_truth))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", nargs="+", required=True, help="PDF files of the (stratified) perf subset")
    parser.add_argument("--config", default=None,
                        help="Configuration file (default: OCR_CONFIG_PATH, then config/profiles.yaml)")
    parser.add_argument("--assets", choices=product_run.ASSET_MODES, default="png")
    parser.add_argument("--output-mode", choices=product_run.OUTPUT_MODES, default="compact")
    parser.add_argument("--repeat", type=int, default=3, help="Repeats for stable p50/p95 (6.5 uses 3)")
    parser.add_argument("--ground-truth", default=None, help="Measure quality on the same outputs")
    parser.add_argument("--compare", default=None, help="Earlier perf.json; flags >10%% p50 regressions")
    parser.add_argument("--output", required=True, help="Fresh directory for outputs and perf.json")
    parser.add_argument("--log-format", choices=LOG_FORMATS, default="text",
                        help="text keeps console progress; json writes JSON lines to stderr")
    args = parser.parse_args()
    configure_logging(args.log_format)
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    try:
        report = run(args)
    except (ConfigError, ValueError) as error:
        raise SystemExit(f"[ERROR] {error}")
    print(json.dumps({"page_latency": report["page_latency"]["categories"],
                      "startup_seconds": report["startup_seconds"],
                      "repeats": report["repeats"]}, indent=2, ensure_ascii=False))
    print(f"perf.json written to {Path(args.output) / 'perf.json'}")
    if any(repeat["documents_failed"] for repeat in report["repeats"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
