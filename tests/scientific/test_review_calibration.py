import csv
import json

import pytest

from benchmark.scientific_evaluation.review_calibration import evaluate
from ocr_artifacts.hashing import sha256_file
from src.ocr.collect.catalog import ACCEPTANCE_SPLITS, FIELDS, lock_company_splits


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def inputs(tmp_path):
    sources = tmp_path / "sources.csv"
    names = dict(zip(ACCEPTANCE_SPLITS, "abcd"))
    hashes = {name: name * 64 for name in names.values()}
    with sources.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, FIELDS)
        writer.writeheader()
        for name in names.values():
            writer.writerow(dict(document_id=name, relative_path=f"{name}.pdf", company_id=name,
                                 sha256=hashes[name], pages=1, status="OK"))
    groups = {name: name for name in names.values()}
    audit = _write(tmp_path / "audit.json", dict(schema_version="split-leakage-audit-v1",
                   sources_sha256=sha256_file(sources), reviewed_by="fixture", holdout_custodian="fixture",
                   template_groups=groups, near_duplicate_groups=groups))
    splits = tmp_path / "split.json"
    lock_company_splits(sources, {partition: [name] for partition, name in names.items()}, splits, audit=audit)
    provenance = {key: _write(tmp_path / f"{key}.json", {"fixture": key})
                  for key in ("score_protocol", "label_definition", "adjudication")}

    def create(partition, *, incomplete=False, foreign=False, rank=False, page=1):
        document = names["development" if foreign else partition]
        units = [dict(unit_id=str(index), document_id=document, pdf_sha256=hashes[document],
                      page=page, source_id=f"region-{index}") for index in range(5)]
        sample = _write(tmp_path / f"{partition}-sample.json",
                        dict(schema_version="review-calibration-sample-v1", partition=partition, units=units,
                             split_sha256=sha256_file(splits), unit="cell", normalization="visible_strict_v1",
                             score_semantics="rank" if rank else "probability_of_exact_match", currency="VND",
                             score_protocol_sha256=sha256_file(provenance["score_protocol"]),
                             label_definition_sha256=sha256_file(provenance["label_definition"])))
        refs = [dict(unit_id=str(i), text=text, critical=i in (1, 2))
                for i, text in enumerate(("ắ", "020", "01", "", "Tăng"))]
        labels = _write(tmp_path / f"{partition}-labels.json",
                        dict(schema_version="review-calibration-labels-v1", sample_sha256=sha256_file(sample),
                             units=refs[:-1] if incomplete else refs, independent_reviewer="fixture",
                             adjudication_sha256=sha256_file(provenance["adjudication"])))
        pred = _write(tmp_path / f"{partition}-pred.json",
                      dict(schema_version="review-calibration-predictions-v1", sample_sha256=sha256_file(sample),
                           score_protocol_sha256=sha256_file(provenance["score_protocol"]), units=[
                               dict(unit_id="0", text="a\u0306\u0301", score=.9, mandatory_review=False),
                               dict(unit_id="1", text="O2O", score=.9, mandatory_review=False),
                               dict(unit_id="2", text="1", score=1.0, mandatory_review=True,
                                    review={"text": "01", "seconds": 5, "cost": 1200}),
                               dict(unit_id="4", text="Tăng", score=None, mandatory_review=False,
                                    review={"text": "Tang", "seconds": 2}),
                           ]))
        return (sample, labels, pred, sources, splits, audit), provenance

    return create


def test_routing_reliability_and_real_review_have_separate_denominators(inputs):
    args, provenance = inputs("calibration")
    result = evaluate(*args, **provenance, threshold=.9)
    assert result["status"] == "MEASURED" and result["acceptance_status"] == "NOT_EVALUATED"
    assert result["before_review_exact_accuracy"] == .4
    route = result["routing"]
    assert (route["accepted"], route["review_required"], route["false_rejects"]) == (2, 3, 1)
    assert route["critical_review_misses"] == 1 and route["miss_unit_ids"] == ["1"]
    assert route["review_recall"] == pytest.approx(2 / 3)
    assert route["auto_accept_risk"] == .5
    assert result["risk_coverage"][-1]["accepted"] == 2  # Ties stay together, hard-review units never enter.
    assert result["reliability"]["brier"] == pytest.approx((.1 ** 2 + .9 ** 2 + 1) / 3)
    actual = result["actual_review"]
    assert (actual["paired_units"], actual["fixed"], actual["introduced"]) == (2, 1, 1)
    assert actual["total_seconds"] == 7 and actual["total_cost"] is None
    assert result["missing_output_units"] == 1  # A missing prediction is an error even for an empty label.


def test_incomplete_labels_and_rank_scores_never_imply_calibration(inputs):
    args, provenance = inputs("calibration", incomplete=True, rank=True)
    report = evaluate(*args, **provenance, threshold=.9)
    assert report["status"] == "NOT_EVALUATED" and report["annotation_coverage"] == .8
    assert report["units"][-1]["correct"] is None
    assert report["reliability"]["ece"] is None and report["reliability"]["brier"] is None


def test_holdout_uses_only_the_measured_locked_threshold(inputs, tmp_path):
    calibration_args, provenance = inputs("calibration")
    calibration = _write(tmp_path / "calibration.json", evaluate(*calibration_args, **provenance, threshold=.9))
    lock = dict(schema_version="review-threshold-lock-v1", status="LOCKED", approved_by="fixture",
                locked_at="2026-11-04T00:00:00+07:00", threshold=.9, calibration_report_sha256=sha256_file(calibration))
    policy = _write(tmp_path / "policy.json", lock)
    holdout, _ = inputs("holdout")
    report = evaluate(*holdout, **provenance, policy=policy, calibration_report=calibration)
    assert report["risk_coverage"] is None and report["routing"]["threshold"] == .9
    with pytest.raises(ValueError, match="no threshold override"):
        evaluate(*holdout, **provenance, policy=policy, calibration_report=calibration, threshold=.8)
    lock["threshold"] = .8
    _write(policy, lock)
    with pytest.raises(ValueError, match="Threshold was not measured"):
        evaluate(*holdout, **provenance, policy=policy, calibration_report=calibration)


def test_rejects_foreign_partition_and_changed_adjudication(inputs):
    args, provenance = inputs("calibration", foreign=True)
    with pytest.raises(ValueError, match="locked partition"):
        evaluate(*args, **provenance, threshold=.9)
    args, provenance = inputs("calibration", page=2)
    with pytest.raises(ValueError, match="locked partition and source identity"):
        evaluate(*args, **provenance, threshold=.9)
    args, provenance = inputs("calibration")
    _write(provenance["adjudication"], {"changed": True})
    with pytest.raises(ValueError, match="adjudication provenance"):
        evaluate(*args, **provenance, threshold=.9)
