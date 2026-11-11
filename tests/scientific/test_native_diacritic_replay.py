"""Native-copy checks use real PDF text and controlled, explicitly fake GT."""
from copy import deepcopy
import json

import pymupdf
import pytest

from benchmark.scientific_evaluation import native_diacritic_replay as native
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file


@pytest.fixture(scope="module")
def reader_hash():
    return sha256_json_compact(native.runtime_identity())


@pytest.fixture
def source(tmp_path, reader_hash):
    gt_path = tmp_path / "gt.json"
    reference = tmp_path / "reference.txt"
    reference.write_text("á", encoding="utf-8")
    units, publications, documents = [], [], {}
    for key, text in (("native", "á"), ("scan", None)):
        path = tmp_path / (key + ".pdf")
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            if text is not None:
                page.insert_text((30, 60), text, fontsize=12)
            pdf.save(path)
        digest = sha256_file(path)
        units.append({"unit_id": key, "document_id": key, "pdf_sha256": digest,
                      "page": 1, "region_id": "page", "metrics": ["der"]})
        publications.append({"id": key, "pdf_path": str(path), "pdf_sha256": digest, "total_pages": 1})
        documents[key] = {"pdf_sha256": digest, "text_pages": {
            "1": {"path": reference.name, "sha256": sha256_file(reference)}}}
    scope = {"schema_version": native.SCOPE_SCHEMA, "status": "LOCKED", "approved_by": "fixture owner",
             "locked_at": "2026-11-04T09:00:00+07:00", "runtime_sha256": reader_hash,
             "units": [{"unit_id": "native", "native_applicable": True, "reason": "Controlled native PDF"},
                       {"unit_id": "scan", "native_applicable": False, "reason": "Controlled image-only page"}]}
    gt = {"schema_version": "ocr-scorecard-gt-v1", "documents": documents, "native_diacritics": scope}
    inputs = {"protocol": {"approved_by": "fixture owner", "locked_at": "2026-11-04T10:00:00+07:00"},
              "sample": {"units": units}, "plan": {}, "verification": {"verified_artifact_hashes": {}},
              "predictions": {"candidate": {"documents": publications}},
              "split": {"documents": [{"document_id": key, "company_id": key, "split": "holdout"} for key in documents]},
              "artifact_path": lambda *_: gt_path, "artifact": lambda *_: deepcopy(gt)}

    def freeze():
        gt_path.write_text(json.dumps(gt, ensure_ascii=False), encoding="utf-8")
        inputs["verification"]["verified_artifact_hashes"]["data.gt_manifest_sha256"] = sha256_file(gt_path)

    freeze()
    return inputs, gt, freeze, reference


def test_real_pdf_copy_is_not_accepted_as_population_proof_without_a_locked_precision_plan(source):
    inputs, _, _, _ = source
    result = native.recompute_native_diacritics(inputs)
    assert result["native_raw"]["point_status"] == result["native_nfc"]["point_status"] == "PASS"
    # One slot is far from the 29,956 the exact bound needs; the stream claim stays open.
    assert result["native_nfc"]["status"] == "NOT_EVALUATED"
    assert result["native_nfc"]["bound"]["reason"] == "INSUFFICIENT_SLOTS_FOR_BOUND"
    assert result["excluded_scan_unit_ids"] == ["scan"]
    assert result["source_units"]["native"]["blocks"][0]["text_raw"] == "á"
    assert result["native_confidence"]["reason"] == "LOCKED_NATIVE_PRECISION_PLAN_REQUIRED"
    assert result["status"] == result["quality_acceptance"] == "NOT_EVALUATED"


def test_native_wrong_accent_fails_even_without_a_precision_plan(source):
    inputs, gt, freeze, reference = source
    reference.write_text("à", encoding="utf-8")
    for document in gt["documents"].values():
        document["text_pages"]["1"]["sha256"] = sha256_file(reference)
    freeze()
    result = native.recompute_native_diacritics(inputs)
    assert result["status"] == result["native_nfc"]["status"] == "FAIL"
    assert result["native_nfc"]["gate_errors"] == 1


def test_native_font_or_unicode_policy_cannot_be_used_to_exclude_existing_text(source):
    inputs, gt, freeze, _ = source
    gt["native_diacritics"]["units"][0]["native_applicable"] = False
    freeze()
    with pytest.raises(ValueError, match="applicability differs"):
        native.recompute_native_diacritics(inputs)


@pytest.mark.parametrize("change", ["missing_scope", "missing_reference", "uncomposed_reference"])
def test_unknown_native_coverage_never_becomes_zero_errors(source, change):
    inputs, gt, freeze, reference = source
    if change == "missing_scope":
        gt.pop("native_diacritics")
    elif change == "missing_reference":
        gt["documents"]["native"]["text_pages"].clear()
    else:
        reference.write_text("á\u0301", encoding="utf-8")
        gt["documents"]["native"]["text_pages"]["1"]["sha256"] = sha256_file(reference)
    freeze()
    assert native.recompute_native_diacritics(inputs)["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("change", ["runtime", "late_scope", "unit_membership", "pdf_hash"])
def test_changed_native_identity_or_post_holdout_applicability_is_rejected(source, change):
    inputs, gt, freeze, _ = source
    if change == "runtime":
        gt["native_diacritics"]["runtime_sha256"] = "0" * 64
    elif change == "late_scope":
        gt["native_diacritics"]["locked_at"] = "2026-11-04T11:00:00+07:00"
    elif change == "unit_membership":
        gt["native_diacritics"]["units"].pop()
    else:
        inputs["predictions"]["candidate"]["documents"][0]["pdf_sha256"] = "0" * 64
    freeze()
    with pytest.raises(ValueError):
        native.recompute_native_diacritics(inputs)


def test_native_extractor_must_keep_raw_and_apply_only_nfc(source, monkeypatch):
    from types import SimpleNamespace

    inputs, _, _, _ = source
    class AlteredReader:
        def __init__(self, pdf):
            pass

        def extract_blocks(self, page):
            return [SimpleNamespace(text_raw="á", text="a")]

    monkeypatch.setattr(native.native_text_extractor, "NativeTextExtractor", AlteredReader)
    with pytest.raises(ValueError, match="only NFC"):
        native.recompute_native_diacritics(inputs)


@pytest.mark.parametrize("applies", [True, False])
def test_pdf_parser_warnings_do_not_certify_native_text_or_scan_applicability(source, applies):
    inputs, gt, freeze, _ = source
    publication = inputs["predictions"]["candidate"]["documents"][0]
    from pathlib import Path

    path = Path(publication["pdf_path"])
    changed = path.with_suffix(".changed.pdf")
    with pymupdf.open(path) as pdf:
        content, = pdf[0].get_contents()
        pdf.update_stream(content, pdf.xref_stream(content) + b"\nunknown-native-test-operator\n")
        pdf.save(changed)
    path.write_bytes(changed.read_bytes())
    digest = sha256_file(path)
    publication["pdf_sha256"] = gt["documents"]["native"]["pdf_sha256"] = digest
    inputs["sample"]["units"][0]["pdf_sha256"] = digest
    gt["native_diacritics"]["units"][0]["native_applicable"] = applies
    freeze()
    result = native.recompute_native_diacritics(inputs)
    assert result["status"] == "NOT_EVALUATED"
    assert result["parser_warnings"]["native"]["messages"]
    assert result["unverified_applicability_unit_ids"] == ["native"]
    assert "native" not in result["excluded_scan_unit_ids"]


def _precision_case():
    inputs = {"plan": {"native_diacritics": {"minimum_companies": 2, "minimum_documents": 2,
        "minimum_denominator": 100, "maximum_ci_width": .0001,
        "power": {"target": .8, "pilot_company_influence_sd": .000002,
                  "detectable_gap": .00002, "pilot_sha256": "a" * 64}}},
        "protocol": {"statistics": {"confidence_level": .95, "seed": 7, "resamples": 500,
                                    "minimum_independent_clusters": 2}},
        "artifact": lambda *_: {"tests": {"overall": {}}}}
    records = [{"company_id": f"c{i//2}", "document_id": f"d{i}", "page": 1, "region_id": "page",
                "status": "MEASURED", "numerator": i+1, "denominator": 100000} for i in range(6)]
    return inputs, records


@pytest.mark.parametrize("change,expected", [("adequate", "PASS"), ("errors", "FAIL"),
    ("one_company", "NOT_EVALUATED"), ("zero_errors", "NOT_EVALUATED"), ("zero_errors_locked_deff", "PASS"),
    ("zero_errors_one_company", "NOT_EVALUATED"), ("small_denominator", "NOT_EVALUATED")])
def test_native_confidence_uses_company_clusters_and_locked_precision_requirements(change, expected):
    inputs, records = _precision_case()
    if change == "errors":
        for row in records:
            row["numerator"] += 50
    elif change == "one_company":
        for row in records:
            row["company_id"] = "same"
    elif change.startswith("zero_errors"):
        for row in records:
            row["numerator"] = 0
        if change == "zero_errors_locked_deff":
            # V8-021: zero events on 600k slots with a locked DEFF is bounded, not unscored.
            inputs["plan"]["native_diacritics"]["design_effect"] = 4.0
        elif change == "zero_errors_one_company":
            inputs["plan"]["native_diacritics"]["design_effect"] = 4.0
            for row in records:
                row["company_id"] = "same"
    elif change == "small_denominator":
        inputs["plan"]["native_diacritics"]["minimum_denominator"] = 1000000
    result = native._confidence(inputs, records)
    assert result["status"] == expected
    if change == "zero_errors":
        assert result["reason"] == "LOCKED_DESIGN_EFFECT_REQUIRED"
    if change == "zero_errors_locked_deff":
        interval = result["marginal_confidence"]["error_rate_ci_unadjusted"]
        assert interval["method"] == "clopper_pearson_zero_event" and interval["effective_trials"] == 150000


def test_native_confidence_uses_the_exact_bound_as_a_floor_for_few_clusters():
    inputs, records = _precision_case()
    marginal = native._confidence(inputs, records)["marginal_confidence"]
    assert marginal["error_rate_ci_unadjusted"]["upper"] >= marginal["exact_upper_bound"] > 0


def test_runtime_cli_records_identity_without_approving_quality_and_refuses_overwrite(tmp_path, reader_hash):
    report_path = tmp_path / "identity.json"
    assert native.main(["--runtime-report", str(report_path)]) == 0
    report = json.loads(report_path.read_bytes())
    assert report["runtime_sha256"] == reader_hash
    assert report["status"] == "SOURCE_IDENTITY_ONLY" and report["quality_acceptance"] == "NOT_EVALUATED"
    with pytest.raises(SystemExit) as exc:
        native.main(["--runtime-report", str(report_path)])
    assert exc.value.code == 2


def test_missing_native_plan_stops_quality_before_any_held_out_counts_or_transcriptions(source, monkeypatch):
    from types import SimpleNamespace
    from benchmark.scientific_evaluation import release_gate

    inputs, _, _, _ = source
    def forbid(*args, **kwargs):
        pytest.fail("Unready native metadata opened held-out measurement inputs")

    monkeypatch.setattr(release_gate, "count_verified_predictions", forbid)
    monkeypatch.setattr(release_gate, "recompute_for_gate", forbid)
    monkeypatch.setattr(native, "_source", forbid)
    result = release_gate._quality(inputs, SimpleNamespace())
    assert result["status"] == "NOT_EVALUATED"
    assert result["native_input_readiness"]["reason"] == "LOCKED_NATIVE_PRECISION_PLAN_REQUIRED"


def test_native_readiness_checks_metadata_without_opening_transcriptions(source, monkeypatch):
    inputs, gt, _, _ = source
    precision, _ = _precision_case()
    inputs["plan"] = precision["plan"]
    inputs["protocol"]["statistics"] = precision["protocol"]["statistics"]
    original_artifact = inputs["artifact"]
    inputs["artifact"] = lambda key, schema: original_artifact(key, schema) if key == "data.gt_manifest_sha256" else {"tests": {"overall": {}}}
    monkeypatch.setattr(native, "_source", lambda *args: pytest.fail("Readiness opened a transcription"))
    result = native.check_native_readiness(inputs)
    assert result["status"] == "DECLARED_NATIVE_INPUTS_READY" and result["native_units"] == 1
