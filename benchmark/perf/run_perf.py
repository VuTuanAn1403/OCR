#!/usr/bin/env python3
"""Performance run per proposal V6 section 6.5; writes perf.json.

Keeps the four quantities of section 6.1 apart:
- page latency: warm, never from cache; p50 / mean / p95 per page category;
- document latency: open to validation.json written, export included;
- throughput: pages / wall time of the whole repeat;
- start-up: model loading before the first page (Docling warmed up explicitly).

Every repeat uses a fresh, empty page cache with resume off, so no timing is
inherited from an earlier run (H24). Also reports PERF-02 (tail), PERF-05
(start-up), PERF-06 (peak RAM incl. the Docling worker), PERF-08 (stage
breakdown, run manifest) and PERF-09 (output size per page). With
--ground-truth, quality is measured on the same outputs.

Example:
  python benchmark/perf/run_perf.py --pdf inputs/ACC_Baocaothuongnien_2025.pdf \
      --pages 1-10 --repeat 3 --output benchmark/results/perf/b0
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ocr.application.convert_document import ConvertDocumentUseCase  # noqa: E402
from src.ocr.cli.run_ocr import parse_pages_arg  # noqa: E402
from src.ocr.infrastructure.export.markdown_exporter import ASSET_MODES  # noqa: E402
from src.ocr.runtime.atomic_io import atomic_write_json  # noqa: E402
from src.ocr.runtime.device import VALID_DEVICES  # noqa: E402
from src.ocr.runtime.run_manifest import RunRecorder, file_sha256  # noqa: E402

PERF_SCHEMA = "perf-v1"
# Agreed CPU requirements (REQ-01..03), applied to p50 as proposed in ADJ-05.
CPU_P50_LIMITS = {"native": 0.15, "mixed": 1.80, "scan": 2.50}
# Low-quality native pages are processed like scans (H13 table); the two
# product-showcase pages of the sample were counted as scans in section 6.1.
_CATEGORY = {"NATIVE_TEXT": "native", "MIXED": "mixed"}
REGRESSION_TOLERANCE = 0.10  # section 6.5: >10% slower on the same hardware


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
    for key in ("device", "assets_mode"):
        if (key in current or key in previous) and current.get(key) != previous.get(key):
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


class PeakMemorySampler:
    """Samples RSS of this process plus all children (the Docling worker), PERF-06."""

    def __init__(self, interval: float = 0.25):
        self.interval = interval
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        me = psutil.Process()
        while not self._stop.is_set():
            total = 0
            for proc in [me, *me.children(recursive=True)]:
                try:
                    total += proc.memory_info().rss
                except psutil.Error:
                    pass
            self.peak_bytes = max(self.peak_bytes, total)
            self._stop.wait(self.interval)

    def __enter__(self) -> "PeakMemorySampler":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()


def _dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _page_records(doc) -> List[Dict[str, Any]]:
    records = []
    for page in doc.pages:
        q = page.quality
        status = (page.metadata.get("docling_structure") or {}).get("status", "DISABLED")
        records.append({
            "document_id": doc.document_id, "page": page.page_num, "page_type": q.page_type,
            "category": page_category(q.page_type), "seconds": q.time_taken_seconds,
            "stages": dict(q.stage_seconds), "from_cache": q.from_cache,
            "docling_called": status not in ("DISABLED", "SKIPPED_NO_STRUCTURE_CANDIDATE"),
            "errors": q.errors,
            "content_status": q.content_status,
        })
    return records


def run(args: argparse.Namespace) -> Dict[str, Any]:
    document_ids = [Path(pdf).stem.casefold() for pdf in args.pdf]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("Performance inputs must have distinct document IDs (PDF filenames)")
    converter = ConvertDocumentUseCase(args.config)
    profile_config = converter.resolve_profile(args.profile, args.device)
    output = Path(args.output)
    pages = parse_pages_arg(args.pages)
    fresh_cache = Path(tempfile.mkdtemp(prefix="ocr-perf-cache-"))
    recorder = RunRecorder("perf", config_path=converter.config_path, profile=args.profile,
                           profile_config=profile_config, device=profile_config["device"],
                           cache_dir=fresh_cache, resume=False, assets_mode=args.assets)
    fresh_cache.rmdir()
    recorder.data["cache"]["dir"] = "fresh empty temporary directory per repeat"

    repeats, all_pages, documents = [], [], []
    for repeat in range(1, args.repeat + 1):
        cache_dir = Path(tempfile.mkdtemp(prefix="ocr-perf-cache-"))
        repeat_dir = output / f"repeat-{repeat}"
        if repeat_dir.exists() and any(repeat_dir.iterdir()):
            cache_dir.rmdir()
            raise ValueError(f"Performance output must be fresh: {repeat_dir}")
        _reset_peak_vram()
        started = time.perf_counter()
        repeat_pages = 0
        repeat_documents = []
        try:
            with PeakMemorySampler() as memory:
                for pdf in args.pdf:
                    doc = converter.execute(
                        file_path=pdf, profile_name=args.profile, pages=pages, output_dir=str(repeat_dir),
                        resume=False, benchmark=True, device=profile_config["device"],
                        assets_mode=args.assets, warmup=True, cache_dir=str(cache_dir),
                    )
                    recorder.add_document(doc)
                    doc_dir = repeat_dir / doc.document_id
                    records = _page_records(doc)
                    all_pages.extend({**r, "repeat": repeat} for r in records)
                    repeat_pages += len(records)
                    entry = {
                        "repeat": repeat, "document_id": doc.document_id, "pages": len(records),
                        "timing": doc.timing,
                        "output_bytes": None,
                        "output_kb_per_page": None,
                        "quality": None,
                    }
                    documents.append(entry)
                    repeat_documents.append((entry, doc_dir, Path(doc.file_path), records,
                                             recorder.data["documents"][-1]))
            wall = time.perf_counter() - started
        finally:
            shutil.rmtree(cache_dir, ignore_errors=True)
        repeats.append({
            "repeat": repeat, "pages": repeat_pages, "wall_seconds": round(wall, 3),
            # PERF-04, one worker (W = 1, eta = 1).
            "throughput_pages_per_hour": round(repeat_pages / wall * 3600, 1) if wall else None,
            "peak_rss_mb": round(memory.peak_bytes / 1024 ** 2, 1),
            "peak_vram_mb": _peak_vram_mb(),
            "peak_vram_scope": "current process only; external Docling worker excluded",
        })
        # Provenance hashing, size inventory and quality evaluation are outside
        # the extraction wall-clock interval.
        for entry, doc_dir, input_path, records, manifest_record in repeat_documents:
            output_bytes = _dir_bytes(doc_dir)
            entry.update(output_bytes=output_bytes,
                         output_kb_per_page=round(output_bytes / 1024 / max(1, len(records)), 1))
            page_artifacts = [{"page": record["page"],
                               "json_sha256": file_sha256(doc_dir / "pages" / f"page-{record['page']:04d}.json"),
                               "markdown_sha256": file_sha256(doc_dir / "pages" / f"page-{record['page']:04d}.md")}
                              for record in records]
            manifest_record.update(file_sha256=file_sha256(input_path), page_artifacts=page_artifacts)
            entry["quality"] = _evaluate(doc_dir, args.ground_truth)

    timeout = float(profile_config.get("page_timeout_seconds", 120))
    startup = [d["timing"]["startup_seconds"] for d in documents if "startup_seconds" in d["timing"]]
    latency = [d["timing"]["document_latency_seconds"] for d in documents if "document_latency_seconds" in d["timing"]]
    report = {
        "schema": PERF_SCHEMA,
        "profile": args.profile,
        "device": profile_config["device"],
        "assets_mode": args.assets,
        "repeats": repeats,
        "page_latency": summarize_pages(all_pages, timeout, device=profile_config["device"]),
        "document_latency_seconds": _stats(latency),
        "startup_seconds": _stats(startup),
        "output_kb_per_page": _stats([d["output_kb_per_page"] for d in documents]),
        "documents": documents,
        "pages": all_pages,
        "pages_with_errors": sum(bool(page["errors"]) for page in all_pages),
    }
    recorder.write(output / "run_manifest.json")
    report["run_manifest"] = recorder.data
    report["protocol_readiness"] = protocol_readiness(report)
    if args.compare:
        report["comparison"] = compare_with_previous(report, json.loads(Path(args.compare).read_text(encoding="utf-8")))
    atomic_write_json(output / "perf.json", report)
    return report


def protocol_readiness(report: Dict[str, Any]) -> Dict[str, Any]:
    """Report measured evidence and pending decisions without declaring acceptance."""
    manifest = report.get("run_manifest", {})
    cache = manifest.get("cache", {})
    models = manifest.get("models_at_finish", manifest.get("models", {}))
    measured_quality = [doc.get("quality") for doc in report.get("documents", [])]
    checks = {
        "cpu_device": report.get("device") == "cpu",
        "balanced_profile": report.get("profile") == "balanced",
        "three_repeats": len(report.get("repeats", [])) >= 3,
        "clean_commit": manifest.get("git", {}).get("dirty") is False and
                        bool(manifest.get("git", {}).get("commit")),
        "fresh_cache_without_resume": cache.get("empty_at_start") is True and
                                      cache.get("resume") is False and not cache.get("pages_from_cache"),
        "model_hashes_recorded": bool(models) and all(value is not None for value in models.values()),
        "startup_recorded_without_errors": bool(report.get("documents")) and all(
            "startup_seconds" in doc.get("timing", {}) and
            not any("error" in key for key in doc.get("timing", {}))
            for doc in report.get("documents", [])),
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
                                 "approved latency statistic (ADJ-05)"],
        "comparison_scope": "latency regression diagnostic; not a PERF-07 quality acceptance test",
    }


def _evaluate(doc_dir: Path, ground_truth: Optional[str]) -> Optional[Dict[str, Any]]:
    if not ground_truth:
        return None
    from scripts.run_scientific_benchmark import evaluate_document_scientific
    return evaluate_document_scientific(doc_dir, Path(ground_truth))


def _reset_peak_vram() -> None:
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()


def _peak_vram_mb() -> Optional[float]:
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    return round(torch.cuda.max_memory_allocated() / 1024 ** 2, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", nargs="+", required=True, help="PDF files of the (stratified) perf subset")
    parser.add_argument("--pages", default=None, help="Pages applied to every PDF, e.g. '1-10' (default: all)")
    parser.add_argument("--profile", default="balanced")
    parser.add_argument("--config", default=None, help="Profile config path (default: config/profiles.yaml)")
    parser.add_argument("--device", choices=VALID_DEVICES, default=None)
    parser.add_argument("--assets", choices=ASSET_MODES, default="png")
    parser.add_argument("--repeat", type=int, default=3, help="Repeats for stable p50/p95 (6.5 uses 3)")
    parser.add_argument("--ground-truth", default=None, help="Measure quality on the same outputs")
    parser.add_argument("--compare", default=None, help="Earlier perf.json; flags >10%% p50 regressions")
    parser.add_argument("--output", required=True, help="Directory for outputs and perf.json")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    report = run(args)
    print(json.dumps({"page_latency": report["page_latency"]["categories"],
                      "startup_seconds": report["startup_seconds"],
                      "repeats": report["repeats"]}, indent=2, ensure_ascii=False))
    print(f"perf.json written to {Path(args.output) / 'perf.json'}")


if __name__ == "__main__":
    main()
