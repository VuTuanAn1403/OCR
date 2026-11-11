"""benchmark/challengers: experiment identity and canonical predictions (V8-040, spec 05)."""
import copy

import pytest

from benchmark.challengers import canonical, experiment

SHA = "a" * 64


def _manifest(role="baseline", run_id="run-b"):
    return {
        "schema_version": experiment.SCHEMA, "experiment_id": "EXP-V8-REC-20261120-001", "role": role,
        "run_id": run_id,
        "code": {"commit": "08f7602", "dirty_diff_sha256": SHA,
                 "code_fingerprints": {"extraction": "20e15efae22917bd", "analysis": "3c33830f271e1c29",
                                       "publication": "ef784a0f529f0f19"}},
        "config": {"profiles_sha256": SHA, "model_registry_sha256": SHA, "lock_sha256": SHA},
        "candidate": {"repository": "production", "revision": "v62", "weights_sha256": SHA,
                      "code_licence": "Apache-2.0", "weights_licence": "Apache-2.0", "tokenizer": "vietocr-vocab"},
        "data": {"pdf_manifest_sha256": SHA, "page_selection": [1, 2], "dpi": 300,
                 "image_manifest_sha256": SHA, "split": "development"},
        "protocol": {"protocol_sha256": SHA, "metric_versions": {"dser": "DSER_strict"}, "alpha": .05,
                     "thresholds": {"dser_upper": .0001}, "margin": 0},
        "environment": {"gpu": "RTX 2050", "vram_mb": 4096, "driver": "560", "cuda": "12.4", "backend": "cuda",
                        "seed": 7, "command": ["run_ocr.py"], "exit_code": 0, "process_tree_exited": True},
    }


@pytest.mark.parametrize("value", ["EXP-V8-REC-20261120-001", "EXP-V8-DET-20261231-120"])
def test_experiment_ids_follow_the_spec(value):
    assert experiment.parse_experiment_id(value)["serial"] >= 1


@pytest.mark.parametrize("value", ["EXP-V7-REC-20261120-001", "EXP-V8-rec-20261120-001", "EXP-V8-REC-20261340-001",
                                   "EXP-V8-REC-20261120-000", "EXP-V8-REC-20261120-1", None])
def test_malformed_experiment_ids_are_refused(value):
    with pytest.raises(ValueError):
        experiment.parse_experiment_id(value)


def test_complete_manifest_and_pair():
    assert experiment.validate_manifest(_manifest()) == {"status": "COMPLETE", "problems": []}
    pair = experiment.validate_pair(_manifest(), _manifest("candidate", "run-c"))
    assert pair["status"] == "COMPLETE"
    assert experiment.decision_options(pair, protocol_locked=True, independent_gt=True)[0] == "PROMOTE"


@pytest.mark.parametrize("group,field,value", [
    ("code", "dirty_diff_sha256", None), ("code", "code_fingerprints", {"extraction": "x"}),
    ("candidate", "weights_licence", ""), ("data", "split", "train"), ("protocol", "alpha", float("nan")),
    ("environment", "process_tree_exited", False), ("environment", "exit_code", 3),
])
def test_any_missing_identity_field_makes_the_run_inconclusive(group, field, value):
    manifest = _manifest()
    manifest[group][field] = value
    report = experiment.validate_manifest(manifest)
    assert report["status"] == "INCONCLUSIVE"
    assert any(problem.startswith(f"{group}.{field}") for problem in report["problems"])


def test_pair_requires_the_same_data_and_protocol_and_distinct_runs():
    candidate = _manifest("candidate", "run-b")
    candidate["data"] = {**candidate["data"], "dpi": 400}
    pair = experiment.validate_pair(_manifest(), candidate)
    assert pair["status"] == "INCONCLUSIVE"
    assert "data differs between runs" in pair["problems"] and "baseline and candidate need distinct run_id" in pair["problems"]
    assert experiment.decision_options(pair, protocol_locked=True, independent_gt=True) == ("INCONCLUSIVE",)


@pytest.mark.parametrize("locked,gt", [(False, True), (True, False)])
def test_without_locked_protocol_or_independent_gt_only_inconclusive_is_allowed(locked, gt):
    pair = experiment.validate_pair(_manifest(), _manifest("candidate", "run-c"))
    assert experiment.decision_options(pair, protocol_locked=locked, independent_gt=gt) == ("INCONCLUSIVE",)


def test_experiment_directories_are_created_once(tmp_path):
    base = experiment.create_experiment_dirs(tmp_path, "EXP-V8-REC-20261120-001")
    assert sorted(p.name for p in base.iterdir()) == sorted(experiment.SUBDIRECTORIES)
    with pytest.raises(FileExistsError):
        experiment.create_experiment_dirs(tmp_path, "EXP-V8-REC-20261120-001")


def _prediction(**changes):
    record = {"schema_version": canonical.SCHEMA, "status": "PREDICTED", "document_id": "doc", "physical_page": 1,
              "region_id": "r1", "engine": "vietocr", "model_version": "vgg_seq2seq", "run_id": "run-b",
              "text_raw": "Báo cáo", "bbox": [1, 2, 30, 12], "coordinate_space": "image_pixels",
              "source_image_sha256": SHA, "confidence": .93, "crop_id": "c1", "crop_sha256": SHA}
    record.update(changes)
    return record


def test_canonical_record_passes_and_keeps_raw_text():
    assert canonical.validate_prediction(_prediction(), "recognition_crop") == []
    no_score = _prediction(confidence=None, confidence_reason="engine exposes no score")
    assert canonical.validate_prediction(no_score, "recognition_crop") == []


@pytest.mark.parametrize("changes,problem", [
    ({"confidence": None}, "confidence is null without confidence_reason"),
    ({"confidence": 1.2}, "confidence must be within [0, 1] or null"),
    ({"bbox": [5, 5, 1, 9]}, "bbox must be [x0, y0, x1, y1] with x0 <= x1 and y0 <= y1"),
    ({"coordinate_space": "unknown"}, "coordinate_space"),
    ({"physical_page": 0}, "physical_page must be a 1-based integer"),
    ({"crop_sha256": "x"}, "crop_sha256"),
])
def test_noncanonical_records_are_reported(changes, problem):
    assert problem in canonical.validate_prediction(_prediction(**changes), "recognition_crop")


def test_missing_output_stays_in_the_file_without_invented_text():
    missing = _prediction(status="MISSING_OUTPUT", text_raw=None)
    assert canonical.validate_prediction(missing, "recognition_crop") == []
    assert "MISSING_OUTPUT must not carry text_raw" in canonical.validate_prediction(
        _prediction(status="MISSING_OUTPUT"), "recognition_crop")


def test_prediction_file_must_cover_the_frozen_units_exactly_once():
    units = {("doc", 1, "r1"), ("doc", 1, "r2")}
    records = [_prediction(), _prediction(region_id="r2", status="MISSING_OUTPUT", text_raw=None, crop_id="c2")]
    report = canonical.validate_predictions(records, "recognition_crop", units)
    assert report["status"] == "COMPLETE" and report["missing_output_records"] == 1
    dropped = canonical.validate_predictions(records[:1], "recognition_crop", units)
    assert dropped["status"] == "INCOMPLETE" and dropped["missing_units"] == [("doc", 1, "r2")]
    duplicate = canonical.validate_predictions([records[0], copy.deepcopy(records[0])], "recognition_crop", {("doc", 1, "r1")})
    assert duplicate["status"] == "INCOMPLETE" and "record 1: duplicates record 0" in duplicate["problems"]


def test_model_catalog_is_well_formed_and_only_the_pinned_candidate_is_downloadable():
    from benchmark.challengers import catalog

    data = catalog.load_catalog()
    assert catalog.validate_catalog(data) == []
    status = catalog.catalog_status(data)
    # 10/11/2026: the user asked to pin Vintern-1B-v3.5 (revision and weights sha256 from the Hub); nothing else.
    assert [name for name, row in status.items() if row["download_allowed"]] == ["vintern-1b-v3.5"]
    assert "restrictive or conditional licence needs licence_review" in status["doclayout-yolo"]["blockers"]


def test_download_gate_opens_only_with_verified_licence_pinned_revision_and_sha():
    from benchmark.challengers import catalog

    entry = {"licence_label": "VERIFIED", "revision": "abc123", "weights_sha256": SHA,
             "code_licence": "MIT", "weights_licence": "Apache-2.0"}
    assert catalog.download_allowed(entry)
    assert not catalog.download_allowed({**entry, "weights_licence": "AGPL-3.0"})
    assert catalog.download_allowed({**entry, "weights_licence": "AGPL-3.0", "licence_review": "benchmark-only, approved"})
    for change in ({"licence_label": "HYPOTHESIS"}, {"revision": None}, {"weights_sha256": None}):
        assert not catalog.download_allowed({**entry, **change})


@pytest.mark.parametrize("licence,restricted", [("CC-BY-NC-SA-4.0", True), ("Qwen Research License", True),
                                                ("Apache-2.0 licence", False), ("MIT", False), ("GPL-3.0", True)])
def test_restrictive_licence_detection_matches_tokens_not_substrings(licence, restricted):
    from benchmark.challengers import catalog

    entry = {"licence_label": "VERIFIED", "revision": "r", "weights_sha256": SHA, "code_licence": "MIT",
             "weights_licence": licence}
    assert catalog.download_allowed(entry) is not restricted
