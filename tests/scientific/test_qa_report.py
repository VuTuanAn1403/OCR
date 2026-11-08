"""Verify scope, custody and source replay across the offline report adapters."""
from copy import deepcopy
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from benchmark.qa.__main__ import main
from benchmark.qa.evidence import EvidenceStore, write_new_json
from benchmark.qa.error_registry import snapshot
from benchmark.qa.paired_effects import run
from benchmark.qa.report import build_report
from benchmark.qa.report_view import render
from benchmark.scientific_evaluation.structured_scoreboard import evaluate_structure
from tests.scientific.test_error_registry import imported, packet, write
from tests.scientific.test_qa_paired_effects import DRAFT, comparison, controlled_backend
from tests.scientific.test_text_detection_metric import structured_fixture


def options(root, **changes):
    return SimpleNamespace(**{"evidence_root": root, "registry": None, "paired": None, "detector_report": None,
                              "detector_gt": None, "detector_extraction": None, "include_development_details": False, **changes})


def browser_payload(html):
    return json.loads(re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S)[1])


def test_real_draft_and_registry_do_not_create_measured_metrics_or_corpus_counts(packet):
    _, root, _ = packet
    registry = root / "registry.json"
    write_new_json(registry, imported(packet, historical=True))
    protocol, paired = root / "draft.yaml", root / "paired.json"
    protocol.write_bytes(DRAFT.read_bytes())
    write_new_json(paired, run(SimpleNamespace(protocol=protocol, artifact_index=None, evidence_root=root)))
    report = build_report(options(root, registry=registry, paired=paired))
    assert report["quality_status"] == "NOT_EVALUATED" and not report["quality_acceptance"]
    assert report["registry"]["finding_kinds"] == {"HISTORICAL_FINDING": 3}
    assert report["registry"]["source_pages_with_findings"] == 1 and report["registry"]["findings"] == []
    assert report["population"]["documents_evaluated_overall"] is report["population"]["pages_evaluated_overall"] is None
    assert report["paired"]["status"] == "NOT_READY"
    assert all(row["status"] == "NOT_EVALUATED" and row["values"] is None for row in report["metrics"].values())


def test_development_detail_preserves_raw_and_crop_without_script_injection(packet):
    directory, root, rows = packet
    attack = '</script><img src=x onerror="globalThis.OCR_PWNED=1">'
    rows[0]["text_raw"] = attack
    manifest = json.loads((directory / "packet.json").read_text(encoding="utf-8"))
    manifest["files"]["review.json"] = write(directory / "review.json", {"schema_version": "operator-review-items-v1", "items": rows})
    write(directory / "packet.json", manifest)
    registry = root / "registry.json"
    write_new_json(registry, imported(packet))
    report = build_report(options(root, registry=registry, include_development_details=True))
    html = render(report, root / "reports" / "dashboard.html", root)
    assert attack not in html and "<img src=x" not in html
    finding = browser_payload(html)["registry"]["findings"][0]
    assert finding["actual"]["text_raw"] == attack
    assert finding["source"]["source_id"] == rows[0]["source_id"]
    assert finding["crop"]["assets"]["target"]["href"] == "../packet/images/crop.png"


def test_opt_in_still_excludes_independent_gt_detail(packet):
    _, root, _ = packet
    initial = imported(packet)
    records = deepcopy(initial["records"])
    oracle = root / "independent-fixture.json"
    write(oracle, {"label": "private annotation"})
    records[0]["expected"] = {"kind": "INDEPENDENT_GT", "value": "private annotation", "evidence": [EvidenceStore(root).ref(oracle)]}
    path = root / "registry.json"
    write_new_json(path, snapshot(records, created_at=initial["created_at"], creator="fixture", evidence=initial["evidence"]))
    result = build_report(options(root, registry=path, include_development_details=True))
    assert result["registry"]["distinct_findings"] == 3
    assert result["registry"]["development_details_included"] == 2
    assert "private annotation" not in json.dumps(result)


def test_paired_partial_denominators_and_holdout_unit_redaction(controlled_backend, tmp_path):
    args, runs, _ = controlled_backend
    runs["candidate"]["records_by_metric"]["cer"][3] = {"unit_id": "3", "status": "NOT_EVALUATED", "reason": "NO_SCORABLE_REFERENCE"}
    path = tmp_path / "holdout-private-paired.json"
    write_new_json(path, run(args))
    report = build_report(options(tmp_path, paired=path, include_development_details=True))
    row = report["metrics"]["cer"]
    assert row["status"] == "PARTIAL" and row["values"]["baseline"]["denominator"] == 40
    candidate = row["values"]["candidate"]
    assert candidate["value"] is None and candidate["denominator"] == 30 and candidate["scored_units"] == 3
    assert row["paired_effects"]["harm_rate"] is row["paired_effects"]["fix_rate"] is None
    assert report["metrics"]["text_detection_recall"]["values"] is None
    html = render(report, tmp_path / "dashboard.html", tmp_path)
    payload = browser_payload(html)
    assert "holdout-private-paired.json" not in html and "path" not in payload["sources"]["paired"]
    assert "unit_id" not in json.dumps(payload) and "count_inputs" not in json.dumps(payload)


def test_report_rejects_changed_source_and_recomputed_arithmetic_mismatch(controlled_backend, tmp_path):
    args, _, _ = controlled_backend
    path = tmp_path / "paired.json"
    valid = run(args)
    changed = deepcopy(valid)
    changed["comparisons"]["cer"]["overall"]["fixed"] += 10
    write_new_json(path, changed)
    with pytest.raises(ValueError, match="does not replay"):
        build_report(options(tmp_path, paired=path))
    original = tmp_path / "paired-original.json"
    write_new_json(original, valid)
    (tmp_path / "gt.json").write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_report(options(tmp_path, paired=original))


def test_report_replays_primary_detector_and_does_not_borrow_layout_recall(tmp_path):
    directory, gt, second = structured_fixture(tmp_path)
    first = tmp_path / "detector-partial.json"
    write_new_json(first, evaluate_structure(directory, gt))
    config = options(tmp_path, detector_report=first, detector_gt=gt, detector_extraction=directory / "extraction.json")
    partial = build_report(config)["metrics"]["text_detection_recall"]
    assert partial["status"] == "NOT_EVALUATED" and partial["values"]["diagnostic"]["value"] is None
    assert partial["values"]["diagnostic"]["observed_counts"] == {"tp": 1, "fp": 0, "fn": 0}
    second_path = directory / "pages/page-0002.json"
    write(second_path, second)
    with pytest.raises(ValueError, match="do not replay"):
        build_report(config)
    config.detector_report = tmp_path / "detector-complete.json"
    write_new_json(config.detector_report, evaluate_structure(directory, gt))
    result = build_report(config)
    measured = result["metrics"]["text_detection_recall"]["values"]["diagnostic"]
    assert (measured["numerator"], measured["denominator"], measured["value"]) == (1, 2, .5)
    assert result["metrics"]["layout_recall"]["status"] == "NOT_EVALUATED"
    assert result["quality_status"] == "NOT_EVALUATED"
    second_path.write_bytes(second_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="do not replay"):
        build_report(config)


def test_report_cli_writes_new_html_and_json_without_writing_into_packet(packet):
    directory, root, _ = packet
    registry, output, html = (root / name for name in ("registry.json", "report.json", "dashboard.html"))
    write_new_json(registry, imported(packet))
    argv = ["report", "--registry", str(registry), "--evidence-root", str(root), "--output", str(output), "--html", str(html)]
    assert main(argv) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "REPORT_READY"
    assert browser_payload(html.read_text(encoding="utf-8"))["registry"]["findings"] == []
    assert main(argv) == 2
    argv[argv.index(str(output))] = str(root / "next.json")
    argv[argv.index(str(html))] = str(directory / "not-allowed.html")
    assert main(argv) == 2 and not (root / "next.json").exists() and not (directory / "not-allowed.html").exists()
