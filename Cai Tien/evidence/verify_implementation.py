"""Verify the improvement register, trace references and one completed pytest run.

This checks implementation evidence only. It never certifies OCR accuracy.
"""
import argparse
import ast
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
BACKLOG = ROOT / "Cai Tien/03_BACKLOG_CAI_TIEN.csv"
TRACE = ROOT / "Cai Tien/05_TRACE_KIEM_THU.csv"
MATRICES = [ROOT / "Test case/KE_HOACH_VA_DANH_SACH_TEST_CASE.md",
            ROOT / "Test case/BO_TEST_CASE_DANH_GIA_DO_CHINH_XAC_KHOA_HOC.md"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"Missing or non-local evidence: {relative}")
    return path


def read_csv(path):
    assert path.read_bytes().startswith(b"\xef\xbb\xbf"), f"Missing UTF-8 BOM: {path}"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--run", required=True, help="Repository-relative completed scratch run directory")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--update-trace", action="store_true", help="Record implementation-test evidence, never GT acceptance")
    args = parser.parse_args()
    assert not args.report.exists(), "Refusing to replace an existing verification report"
    assert sha(BACKLOG) == "0c3bddab08a77dc5db521daeb0abc1670766f119375a32b739d6e2dc960d551d"
    backlog = read_csv(BACKLOG)
    identifiers = {r["id"] for r in backlog}
    expected_ids = {*(f"AG-QA-{i:03}" for i in range(1, 7)), *(f"DC-{i:02}" for i in range(1, 7)),
                    *(f"GAP-{i:02}" for i in range(1, 9)), *(f"WF-{i:02}" for i in range(1, 4))}
    assert len(backlog) == 23 and identifiers == expected_ids
    graph = {r["id"]: [d for d in r["dependencies"].split(" | ") if d] for r in backlog}

    def visit(identifier, active):
        assert identifier in identifiers and identifier not in active, "Invalid dependency or cycle"
        for child in graph[identifier]:
            visit(child, active | {identifier})

    for row in backlog:
        visit(row["id"], set())
        for ref in row["evidence_refs"].split(" | "):
            local(ref)
    trace = read_csv(TRACE)
    expected_tcs = [identifier for matrix in MATRICES
                    for identifier in re.findall(r"\| \*\*(TC_[A-Z_]+_\d+)\*\* \|", matrix.read_text(encoding="utf-8"))]
    assert len(expected_tcs) == len(trace) == 65
    assert Counter(expected_tcs) == Counter(r["tc_id"] for r in trace)
    run_path = local(args.run + "/run.json")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run.get("exit_code") == 0, "A successful completed pytest run is required"
    junit = local(args.run + "/evidence/junit.xml")
    cases = list(ET.parse(junit).getroot().iter("testcase"))
    assert cases and not any(c.find("failure") is not None or c.find("error") is not None for c in cases)
    for row in trace:
        assert all(value.strip() for value in row.values()), row["tc_id"]
        assert set(row["backlog_ids"].split(" | ")) <= identifiers | {"REGRESSION"}
        assert row["acceptance_status"] == "NOT_EVALUATED", "This checker cannot grant TC/GT acceptance"
        matched = []
        if row["test_refs"] != "NOT_EVALUATED":
            for ref in row["test_refs"].split(" | "):
                file, _, symbol = ref.partition("::")
                module = ast.parse(local(file).read_text(encoding="utf-8-sig"))
                if symbol:
                    assert symbol in {n.name for n in ast.walk(module) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}, ref
                name = Path(file).with_suffix("").as_posix().replace("/", ".")
                selected = [c for c in cases if (c.get("classname") == name or c.get("classname", "").startswith(name + "."))
                            and (not symbol or c.get("name", "").split("[")[0] == symbol)]
                assert selected, f"No executed test evidence: {ref}"
                matched.extend(selected)
        if args.update_trace:
            row["test_status"] = ("VERIFIED_TEST_SUBSET" if matched and all(c.find("skipped") is None for c in matched)
                                  else "PARTIAL_SKIPPED" if matched else "NOT_EVALUATED")
            row["run_evidence"] = args.run + "/run.json" if matched else "NOT_EVALUATED"
    # Upstream diagnostic data and pre-existing test evidence are read-only.
    snapshot = json.loads(local("Cai Tien/evidence/source_snapshot.json").read_text(encoding="utf-8"))
    protected = [r for r in snapshot["selected_sources"] if r["path"].startswith(("Test case/", "tests/"))]
    assert all(sha(local(r["path"])) == r["sha256"] for r in protected), "Historical source evidence changed"
    if args.update_trace:
        with TRACE.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(trace[0]))
            writer.writeheader()
            writer.writerows(trace)
    code_files = ["src/ocr_text/numeric_guard.py", "src/ocr_text/vietnamese_diacritics.py",
                  "benchmark/scientific_evaluation/numeric_metric.py", "src/ocr_document/region_tree.py",
                  "src/ocr_document/resolve_document_layout.py", "src/ocr_document/section_tree.py",
                  "src/ocr_document/document_contracts.py", "src/ocr_document/export.py",
                  "src/ocr_recognition/vietnamese_seq2seq_engine.py"]
    report = {"schema": "ocr-improvement-implementation-verification-v1", "status": "VERIFIED_IMPLEMENTATION_SCOPE",
              "created_at_bangkok": datetime.now(timezone(timedelta(hours=7))).isoformat(),
              "accuracy_status": "NOT_EVALUATED", "gt_acceptance_granted": False,
              "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "git_status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
              "backlog": {"ids": len(backlog), "sha256": sha(BACKLOG), "historical_byte_match": True},
              "trace": {"cases": len(trace), "functional": sum(not r["tc_id"].startswith("TC_SCI_") for r in trace),
                        "scientific": sum(r["tc_id"].startswith("TC_SCI_") for r in trace),
                        "test_status_counts": dict(Counter(r["test_status"] for r in trace)), "sha256": sha(TRACE)},
              "pytest": {"run": args.run, "exit_code": run["exit_code"], "cases": len(cases),
                         "skipped": sum(c.find("skipped") is not None for c in cases), "junit_sha256": sha(junit)},
              "protected_historical_sources_unchanged": len(protected),
              "focus_code_hashes": {file: sha(local(file)) for file in code_files},
              "scope_limit": "Focused code hashes and fixture tests; not full model/runtime identity, new GPU OCR, soak or independent GT"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"status": report["status"], "trace": report["trace"], "pytest": report["pytest"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
