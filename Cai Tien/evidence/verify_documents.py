"""Verify this document synthesis without changing OCR artifacts or running models."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BANGKOK = timezone(timedelta(hours=7))
BASE = "Test case/antigravity_review_20261103/observation_20261103_170326_cc7dda/observation.json"
REPORT06 = "Test case/06_DOI_CHIEU_PADDLE_VA_CHUAN_KEYWORD_20261103.md"
UPSTREAM = "Test case/doi_chieu_paddle_20261103/"
QA = "Test case/antigravity_review_20261103/"


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(relative):
    path = ROOT / relative
    return {"path": relative, "bytes": path.stat().st_size, "sha256": sha(path)}


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def code_state():
    namespace = runpy.run_path(str(ROOT / QA / "capture_observation.py"))
    return namespace["code_state"]()


def snapshot():
    sources = {p.relative_to(ROOT).as_posix() for p in (ROOT / "Test case").glob("*.md")}
    sources.update([
        "AGENTS.md", "CLAUDE.md", "scripts/build_dev_context.py",
        "Test case/scientific_benchmark_harness.py", "Test case/sample_test_suite.py",
        "Test case/replay_gpu_diagnostic.py", "Test case/ket_qua_20261030/verification.json",
        "Test case/ket_qua_20261030/delivered_file_hashes.json",
        "Test case/ket_qua_20261030/diagnostic_summary.json",
        "Test case/ket_qua_20261030/dataset_inventory.json", BASE,
        QA + "findings.json", QA + "test_adversarial_review.py",
        QA + "production_guard_probe.json", QA + "counterexample_run/run.json",
        QA + "counterexample_run/case_results.json", QA + "counterexample_run/evidence/junit.xml",
        QA + "audit_final_20261103_1655.json", QA + "final_verification_20261103_1655.json",
        QA + "automation_deleted.json", QA + "monitor_state.json",
        UPSTREAM + "verification.json", UPSTREAM + "source_manifest.json",
        UPSTREAM + "keyword_comparison.csv", UPSTREAM + "keyword_differences_reviewed.csv",
        UPSTREAM + "keyword_summary.json", UPSTREAM + "review_summary.json",
        UPSTREAM + "review_annotations.json", UPSTREAM + "source_block_traces.json",
        UPSTREAM + "keyword_evidence.json", UPSTREAM + "markdown_alignment_summary.json",
        UPSTREAM + "pdf_input_inventory.json", UPSTREAM + "long_repetition_runs.json",
        UPSTREAM + "verification_tests/run.json", UPSTREAM + "visual_evidence/visual_review_log.json",
        UPSTREAM + "visual_evidence/contact_o2o.png",
        UPSTREAM + "visual_evidence/contact_chuyen_doi_so.png",
        UPSTREAM + "visual_evidence/full_AAA_p100.png",
        UPSTREAM + "visual_evidence/full_VIC_p065.png",
        UPSTREAM + "visual_evidence/full_VIC_p037.png",
        UPSTREAM + "visual_evidence/full_VIC_p137.png",
        UPSTREAM + "visual_evidence/full_AGR_p040.png",
    ])
    protected_tests = [p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("*.py")
                       if p.name in {
                           "test_numeric_metric_counterexamples.py", "test_testcase_harness.py",
                           "test_rotated_line_crops.py", "test_build_dev_context.py",
                           "test_document_review_gate_exports.py", "test_ocr_review_propagation.py",
                           "test_table_evidence_occurrences.py"}]
    sources.update(protected_tests)
    current = code_state()
    baseline = load(BASE)["code_state"]
    changed = [p for p in sorted(set(current["files"]) | set(baseline["files"]))
               if current["files"].get(p) != baseline["files"].get(p)]
    legacy = load("Test case/ket_qua_20261030/delivered_file_hashes.json")
    legacy_changed = [name for name, value in legacy.items()
                      if sha(ROOT / "Test case" / name) != value]
    value = {
        "schema": "ocr-improvement-synthesis-sources-v1",
        "created_at_bangkok": datetime.now(BANGKOK).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_status_at_snapshot": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "code_scope": {"sha256": current["sha256"], "files_count": len(current["files"]),
                       "definition": current["scope"], "baseline_observation": BASE,
                       "changed_since_monitoring": changed},
        "legacy_delivery_check": {"files_checked": len(legacy), "changed": legacy_changed},
        "report06_matches_recorded_hash": sha(ROOT / REPORT06) == load(UPSTREAM + "verification.json")["report_sha256"],
        "selected_sources": [record(p) for p in sorted(sources)],
        "source_interpretation": {
            "primary": "Reports 00-05 and report06 sections1-8, findings and selected evidence; local byte identity checked again.",
            "historical_originals": "Indexed and checked through report01 corrections plus relevant excerpts; not accepted as measurements by default.",
            "large_data": "No full log/hash-map/PDF text loaded into conversation; no new OCR/GT evaluation or full image re-review.",
            "identity_limits": "No current rehash of PDF/model weights/interpreters. Original batch/input identity is historical receipt/manifest evidence.",
            "test_limits": "Reuses original test logs; no production pytest rerun or new numerical performance claims.",
        },
        "planned_document_edits": ["docs/development/README.md", "docs/development/PROJECT_MAP.md", "docs/development/HANDOFF.md"],
        "session_start_snapshot": "scratch/dev_sessions/20261103-cai-tien/start.json",
    }
    write_new(HERE / "source_snapshot.json", value)
    print(json.dumps({"selected_sources": len(sources), "code_files": len(current["files"]),
                      "code_changed": changed, "legacy_changed": legacy_changed,
                      "report06_unchanged": value["report06_matches_recorded_hash"]}, ensure_ascii=False))


def verify():
    baseline = json.loads((HERE / "source_snapshot.json").read_text(encoding="utf-8"))
    issues = []
    unchanged = []
    for item in baseline["selected_sources"]:
        ok = (ROOT / item["path"]).is_file() and sha(ROOT / item["path"]) == item["sha256"]
        if not ok:
            issues.append("Source changed/missing: " + item["path"])
        unchanged.append({"path": item["path"], "unchanged": ok})
    current = code_state()
    if current["sha256"] != baseline["code_scope"]["sha256"]:
        issues.append("Product source/config/lock scope changed")

    with (ROOT / UPSTREAM / "keyword_comparison.csv").open(encoding="utf-8-sig", newline="") as stream:
        cells = list(csv.DictReader(stream))
    values = [(int(row["expected"]), int(row["actual"])) for row in cells]
    stats = {
        "cells": len(values), "matching": sum(a == b for a, b in values),
        "mismatching": sum(a != b for a, b in values),
        "both_zero": sum(a == b == 0 for a, b in values),
        "positive_either": sum(a > 0 or b > 0 for a, b in values),
        "positive_either_matching": sum(a == b and a > 0 for a, b in values),
        "expected_total": sum(a for a, _ in values), "actual_total": sum(b for _, b in values),
        "deficit": sum(max(a - b, 0) for a, b in values),
        "excess": sum(max(b - a, 0) for a, b in values),
    }
    expected = dict(zip(stats, [352, 338, 14, 316, 36, 22, 166, 131, 37, 2]))
    if stats != expected:
        issues.append("Keyword arithmetic differs from supported synthesis")
    with (ROOT / UPSTREAM / "keyword_differences_reviewed.csv").open(encoding="utf-8-sig", newline="") as stream:
        differences = list(csv.DictReader(stream))
    statuses = dict(Counter(row["cause_status"] for row in differences))
    if len(differences) != 14 or sorted(statuses.values()) != [1, 3, 3, 7]:
        issues.append("Review classifications differ")
    per_document = []
    for row in load(UPSTREAM + "keyword_summary.json"):
        group = [(int(r["expected"]), int(r["actual"])) for r in cells if r["document"] == row["document"]]
        totals = {"cells": len(group), "mismatching_cells": sum(a != b for a, b in group),
                  "expected_total_display": sum(a for a, _ in group),
                  "actual_total_display": sum(b for _, b in group)}
        if any(totals[k] != row[k] for k in totals):
            issues.append("Per-document arithmetic: " + row["document"])
        per_document.append({"document": row["document"], **totals})

    with (ROOT / "Cai Tien/03_BACKLOG_CAI_TIEN.csv").open(encoding="utf-8-sig", newline="") as stream:
        backlog = list(csv.DictReader(stream))
    ids = [row["id"] for row in backlog]
    expected_ids = {*(f"AG-QA-{i:03}" for i in range(1, 7)),
                    *(f"DC-{i:02}" for i in range(1, 7)),
                    *(f"GAP-{i:02}" for i in range(1, 9)),
                    *(f"WF-{i:02}" for i in range(1, 4))}
    if len(ids) != 23 or set(ids) != expected_ids:
        issues.append("Backlog identity/count issue")
    dependencies = {}
    for row in backlog:
        for field in ("title", "evidence_status", "remediation_status", "acceptance_criteria", "evidence_refs"):
            if not row[field].strip():
                issues.append("Empty backlog field: " + row["id"] + ":" + field)
        dependencies[row["id"]] = [p.strip() for p in row["dependencies"].split(" | ") if p.strip()]
        for dependency in dependencies[row["id"]]:
            if dependency not in expected_ids:
                issues.append("Unknown dependency: " + dependency)
        for relative in row["evidence_refs"].split(" | "):
            if not (ROOT / relative).exists():
                issues.append("Missing backlog evidence: " + relative)
    visiting, visited = set(), set()

    def walk(identifier):
        if identifier in visiting:
            issues.append("Backlog dependency cycle: " + identifier)
            return
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in dependencies.get(identifier, []):
            walk(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in ids:
        walk(identifier)
    recorded_ids = {row["id"]: row["priority"] for row in load(QA + "findings.json")["findings"]}
    if any(row["priority"] != recorded_ids[row["id"]] for row in backlog if row["id"] in recorded_ids):
        issues.append("Original finding priority changed")

    docs = list((ROOT / "Cai Tien").glob("*.md")) + [
        ROOT / "docs/development/README.md", ROOT / "docs/development/PROJECT_MAP.md",
        ROOT / "docs/development/HANDOFF.md"]
    link_count, future_self_links = 0, []
    self_output = (HERE / "verification.json").resolve()
    for path in docs:
        text = path.read_text(encoding="utf-8-sig")
        if "\ufffd" in text:
            issues.append("Invalid Unicode replacement character: " + str(path))
        for destination in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
            destination = destination.strip().strip("<>")
            parts = urlsplit(destination)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            target = (path.parent / unquote(parts.path)).resolve()
            if target == self_output and not target.exists():
                future_self_links.append(path.relative_to(ROOT).as_posix())
                continue
            link_count += 1
            if not target.exists():
                issues.append(f"Broken link in {path.relative_to(ROOT)}: {destination}")
    end = load("scratch/dev_sessions/20261103-cai-tien/end.json")
    budget = end.get("documentation", {}).get("budget_pass")
    if budget is not True:
        issues.append("Documentation budget result not verified")
    results = {
        "schema": "ocr-improvement-synthesis-verification-v1",
        "verified_at_bangkok": datetime.now(BANGKOK).isoformat(),
        "status": "PASS" if not issues else "FAIL",
        "scope": "Documentation/source identity/arithmetic/links/register consistency; not OCR accuracy or a software fix verification",
        "protected_sources": unchanged, "code_scope_sha256": current["sha256"],
        "code_scope_unchanged": current["sha256"] == baseline["code_scope"]["sha256"],
        "legacy_13_files_unchanged": not baseline["legacy_delivery_check"]["changed"],
        "comparison_report_hash_matches_original": baseline["report06_matches_recorded_hash"],
        "keyword_recalculation": stats, "per_document": per_document,
        "review_status_counts": statuses, "backlog_items": len(ids),
        "backlog_categories": dict(Counter(row["category"] for row in backlog)),
        "dependencies_acyclic": not any("cycle" in issue for issue in issues),
        "local_links_checked": link_count, "verification_self_links_written_on_success": len(future_self_links),
        "documentation_budget_pass": budget,
        "artifact_hashes": [record(p.relative_to(ROOT).as_posix()) for p in sorted(docs)] + [
            record("Cai Tien/03_BACKLOG_CAI_TIEN.csv"),
            record("Cai Tien/evidence/verify_documents.py"),
            record("Cai Tien/evidence/source_snapshot.json"),
        ],
        "not_run": ["product pytest", "GPU inference", "batch audit rerun", "full image re-review", "independent GT evaluation"],
        "independent_accuracy_acceptance": "NOT_EVALUATED",
        "token_savings": "NOT_MEASURED", "productivity_improvement": "NOT_MEASURED",
        "issues": issues,
    }
    if issues:
        print(json.dumps({"status": "FAIL", "issues": issues}, ensure_ascii=False))
        raise SystemExit(1)
    write_new(HERE / "verification.json", results)
    print(json.dumps({"status": "PASS", "source_files_unchanged": len(unchanged),
                      "code_files": len(current["files"]), "keyword_cells": stats["cells"],
                      "backlog_items": len(ids), "links_checked": link_count + len(future_self_links),
                      "documentation_budget_pass": budget}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["snapshot", "verify"])
    args = parser.parse_args()
    snapshot() if args.mode == "snapshot" else verify()
