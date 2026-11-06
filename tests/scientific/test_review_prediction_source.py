import json

import pytest

from benchmark.scientific_evaluation import review_prediction_source as source
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return sha256_file(path)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    directory = tmp_path / "DOC"
    directory.mkdir()
    scope = {"coordinate_space": "pdf_points_top_left", "transforms": []}
    bbox = [10, 20, 30, 40]
    observed = {"text_corrected": "020", "source": "fixture", "bbox": bbox,
                "confidence_source": "fixture", "needs_review": False}
    item = {"id": "line", "kind": "b", "quality_score": .75, **observed}
    table = {"id": "table", "kind": "t", "needs_review": True, "cells": [
        {**observed, "row": 0, "col": 1, "bbox_source": "cell", "confidence": .9}]}
    extraction = {"doc_id": "DOC", "doc_sha16": "a" * 16,
                  "pages": [{"page": 1, **scope, "items": [item, table]}]}
    document = {"id": "DOC", "kind": "extraction", "source_dir": str(directory), "pdf_sha256": "a" * 64,
                "ocr_identity": "identity", "total_pages": 1}

    def publish():
        digest = _write(directory / "extraction.json", extraction)
        document["ocr_receipt_sha256"] = _write(directory / "ocr_receipt.json", {"files": {"extraction.json": digest}})
        document["completion_sha256"] = _write(directory / "COMPLETED.json", {"files": {"extraction.json": digest}})

    publish()
    monkeypatch.setattr(source, "verify_extraction_source", lambda path: document.copy())
    inventory = {"documents": [document], "batches": []}
    sample = {"schema_version": "review-calibration-sample-v1", "partition": "holdout", "score_semantics": "rank",
              "units": [{"unit_id": str(n), "source_id": f"s{n}", "document_id": "DOC", "page": 1, "bbox": bbox,
                         "pdf_sha256": document["pdf_sha256"], **scope} for n in range(2)]}
    protocol_path = tmp_path / "protocol.json"
    sample_path = tmp_path / "sample.json"

    def prepare(kind="line"):
        protocol = {"schema_version": "review-canonical-score-protocol-v1", "unit": kind, "score_semantics": "rank",
                    "source_field": "quality_score" if kind == "line" else "confidence"}
        sample.update(unit=kind, score_protocol_sha256=_write(protocol_path, protocol))
        sample_hash = _write(sample_path, sample)
        locator = {"item_id": "line"} if kind == "line" else {"item_id": "table", "row": 0, "col": 1}
        alignment = {"schema_version": "review-canonical-alignment-v1", "sample_sha256": sample_hash,
                     "prediction_manifest_sha256": sha256_json_compact(inventory),
                     "reviewed_by": "fixture", "reviewed_at": "2020-01-01T00:00:00+07:00",
                     "reviewed_against_source": True, "units": [
                         {"unit_id": "0", "source_id": "s0", "status": "MATCHED", "reason": "Fixture",
                          "locator": locator},
                         {"unit_id": "1", "source_id": "s1", "status": "MISSING_OUTPUT", "reason": "Fixture missing"},
                     ]}
        return sample, sample_hash, protocol, sample["score_protocol_sha256"], alignment, inventory

    return directory, prepare, protocol_path, item, table, publish


@pytest.mark.parametrize(("kind", "score", "mandatory"), [("line", .75, False), ("cell", .9, True)])
def test_projection_preserves_raw_observation_and_missing_unit(inputs, kind, score, mandatory):
    _, prepare, protocol_path, *_ = inputs
    args = prepare(kind)
    projected = source.project(*args)
    found, missing = projected["units"]
    assert found["text"] == "020" and found["score"] == score and found["mandatory_review"] is mandatory
    assert found["source_evidence"]["score_field"] == ("quality_score" if kind == "line" else "confidence")
    assert missing == {"unit_id": "1", "text": None, "score": None, "mandatory_review": True, "source_evidence": None}
    found["review"] = {"text": "O2O", "seconds": 2}
    assert source.verify_projection(*args[:2], projected, protocol_path, args[-1]) == projected["canonical_source"]
    found["text"] = "O2O"
    with pytest.raises(ValueError, match="differ from canonical"):
        source.verify_projection(*args[:2], projected, protocol_path, args[-1])


@pytest.mark.parametrize(("change", "error"), [
    (lambda sample, protocol, alignment: protocol.update(score_semantics="probability_of_exact_match"), "rank score"),
    (lambda sample, protocol, alignment: alignment["units"].pop(), "every frozen sample"),
    (lambda sample, protocol, alignment: alignment["units"][0].update(source_id="another"), "source ID"),
    (lambda sample, protocol, alignment: alignment["units"][1].update(
        status="MATCHED", locator={"item_id": "line"}), "cannot be reused"),
    (lambda sample, protocol, alignment: sample["units"][0].update(bbox=[31, 40, 50, 60]), "must intersect"),
])
def test_invalid_bindings_fail_closed(inputs, change, error):
    _, prepare, *_ = inputs
    args = prepare()
    change(args[0], args[2], args[4])
    with pytest.raises(ValueError, match=error):
        source.project(*args)


def test_projection_requires_receipt_pinned_bytes_and_never_upgrades_coarse_cells(inputs):
    directory, prepare, _, _, table, publish = inputs
    table["needs_review"] = False
    table["cells"][0]["bbox_source"] = "table_fallback"
    publish()
    args = prepare("cell")
    assert source.project(*args)["units"][0]["mandatory_review"] is True
    with (directory / "extraction.json").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="extraction bytes"):
        source.project(*args)


def test_cli_exports_a_new_bound_prediction_file(inputs, tmp_path, monkeypatch):
    import sys

    directory, prepare, protocol_path, *_ = inputs
    args = prepare()
    alignment = tmp_path / "alignment.json"
    _write(alignment, args[4])
    output = tmp_path / "predictions.json"
    monkeypatch.setattr(source, "collect_predictions", lambda roots: args[-1] if roots == [directory] else None)
    command = ["review-prediction-source", "--sample", str(tmp_path / "sample.json"), "--score-protocol",
               str(protocol_path), "--alignment", str(alignment), "--canonical-batch", str(directory)]
    monkeypatch.setattr(sys, "argv", [*command, "--output", str(output)])
    assert source.main() == 0
    assert json.loads(output.read_text(encoding="utf-8")) == source.project(*args)
    monkeypatch.setattr(sys, "argv", [*command, "--output", str(directory / "new.json")])
    with pytest.raises(SystemExit) as error:
        source.main()
    assert error.value.code == 2 and not (directory / "new.json").exists()
