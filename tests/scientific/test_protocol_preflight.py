import csv
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from benchmark.scientific_evaluation.protocol_preflight import REQUIRED_ARTIFACTS, preflight
from src.ocr.collect.catalog import ACCEPTANCE_SPLITS, FIELDS, file_sha256, lock_company_splits


TEMPLATE = Path(__file__).resolve().parents[2] / "docs/quality_assurance/templates/benchmark_acceptance_protocol.example.yaml"


@pytest.fixture
def bundle(tmp_path):
    protocol = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    protocol.update(status="LOCKED", approved_by="fixture", locked_at="2026-01-01T00:00:00+07:00")
    protocol["scope"].update(document_population="fixture", formula_scope_decision={
        "decision": "EXCLUDED", "reason": "Formula scoring is outside this controlled protocol fixture."})
    protocol["scope"]["declared_modalities"].remove("formulas")
    protocol["data"].update(holdout_custodian="fixture-custodian", contamination_disclosure="fixture")
    protocol["thresholds"].update(status="APPROVED", micro_wer_ws_maximum=0.1, micro_der_vn_maximum=0.1)
    protocol["statistics"]["minimum_independent_clusters"] = 2
    protocol["review"]["calibration_unit_and_label_definition"] = "fixture"
    index = {}
    for key in REQUIRED_ARTIFACTS:
        artifact = tmp_path / f"{key}.txt"
        artifact.write_text(f"test fixture for {key}", encoding="utf-8")
        index[key] = artifact.name
    sources = tmp_path / index["data.input_manifest_sha256"]
    with sources.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, FIELDS)
        writer.writeheader()
        for index_number, company in enumerate("abcd", 1):
            writer.writerow(dict(document_id=company, relative_path=f"{company}.pdf", company_id=company,
                                 sha256=f"{index_number:064x}", pages=1, status="OK"))
    audit = tmp_path / index["data.near_duplicate_audit_sha256"]
    groups = {company: company for company in "abcd"}
    audit.write_text(json.dumps(dict(schema_version="split-leakage-audit-v2", sources_sha256=file_sha256(sources),
                                     reviewed_by="fixture", holdout_custodian="fixture-custodian",
                                     template_groups=groups, near_duplicate_groups=groups,
                                     status="REVIEWED", reviewed_at="2026-01-01T00:00:00+07:00",
                                     source_dispositions={
                                         key: {"status": "development_only" if key == "b" else "eligible_for_assignment",
                                               "exposure_evidence": "fixture", "rights_evidence": "fixture"}
                                         for key in groups},
                                     partition_access={"calibration": "fixture-calibration", "holdout": "fixture-holdout"})),
                     encoding="utf-8")
    split = tmp_path / "splits.locked.json"
    lock_company_splits(sources, dict(zip(ACCEPTANCE_SPLITS, ([company] for company in "abcd"))), split, audit=audit)
    index["data.split_manifest_sha256"] = split.name
    for key, filename in index.items():
        section, field = key.split(".")
        protocol[section][field] = file_sha256(tmp_path / filename)
    index_path, protocol_path = tmp_path / "index.yaml", tmp_path / "protocol.yaml"
    index_path.write_text(yaml.safe_dump(index), encoding="utf-8")
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    return protocol_path, index_path, protocol, index


def test_real_draft_cannot_be_used_for_holdout():
    result = preflight(TEMPLATE)
    assert result["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"
    assert result["verified_artifact_hashes"] == {}


def test_pinned_bundle_checks_inputs_without_granting_acceptance(bundle):
    protocol, index, _, _ = bundle
    result = preflight(protocol, index)
    assert result["status"] == "INPUTS_VERIFIED" and not result["issues"]
    assert set(result["verified_artifact_hashes"]) == set(REQUIRED_ARTIFACTS)
    assert result["quality_acceptance_status"] == "NOT_EVALUATED"
    assert not result["eligible_for_quality_acceptance"]


def test_keyword_scope_is_optional_for_components_and_required_for_v70_release(bundle):
    protocol_path, index_path, protocol, _ = bundle
    protocol["scope"]["declared_modalities"].remove("keywords")
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    assert preflight(protocol_path, index_path)["status"] == "INPUTS_VERIFIED"
    missing = preflight(protocol_path, index_path, for_release=True)
    assert "scope.declared_modalities: v7.0 release requires keyword occurrence correctness" in missing["issues"]
    protocol["scope"]["declared_modalities"].append("keywords")
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    assert preflight(protocol_path, index_path)["status"] == "INPUTS_VERIFIED"
    protocol["scope"]["declared_modalities"].append("keywords")
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    assert preflight(protocol_path, index_path)["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"
    protocol["scope"]["declared_modalities"][-1] = "unknown"
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    assert preflight(protocol_path, index_path)["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"


def test_changed_gt_artifact_is_rejected(bundle):
    protocol, index_path, _, index = bundle
    (index_path.parent / index["data.gt_manifest_sha256"]).write_text("changed", encoding="utf-8")
    result = preflight(protocol, index_path)
    assert result["issues"] == ["data.gt_manifest_sha256: SHA-256 mismatch"]
    assert result["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"


@pytest.mark.parametrize("decision", ["Include all formulas", "Scope still pending", None, {},
                                      {"decision": "EXCLUDED", "reason": " "}])
def test_legacy_ambiguous_or_unreasoned_formula_scope_cannot_open_holdout(bundle, decision):
    protocol_path, index_path, protocol, _ = bundle
    protocol["scope"]["formula_scope_decision"] = decision
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    result = preflight(protocol_path, index_path)
    assert result["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"
    assert any("formula_scope_decision" in issue for issue in result["issues"])


def test_in_scope_formulas_are_mandatory_and_cannot_pass_without_a_verified_evaluator(bundle):
    protocol_path, index_path, protocol, _ = bundle
    protocol["scope"]["formula_scope_decision"] = {"decision": "IN_SCOPE", "reason": "Required by the fixture owner."}
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    result = preflight(protocol_path, index_path)
    assert any("formulas are mandatory" in issue for issue in result["issues"])
    protocol["scope"]["declared_modalities"].append("formulas")
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    result = preflight(protocol_path, index_path)
    assert result["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"
    assert "evaluation.formula_policy_sha256: missing from the artifact index" in result["issues"]
    assert result["formula_evidence"]["status"] == "NOT_EVALUATED"
    assert result["quality_acceptance_status"] == "NOT_EVALUATED"


def _formula_fixture(bundle, *, d_pages=1):
    from benchmark.scientific_evaluation import formula_cdm, formula_policy, formula_scorecard

    protocol_path, index_path, protocol, index = bundle
    root = index_path.parent
    source = root / index["data.input_manifest_sha256"]
    if d_pages != 1:
        with source.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        next(row for row in rows if row["document_id"] == "d")["pages"] = d_pages
        with source.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    with source.open("a", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, FIELDS).writerow(dict(document_id="e", relative_path="e.pdf", company_id="e",
                                                    sha256=f"{5:064x}", pages=1, status="OK"))
    audit_path = root / index["data.near_duplicate_audit_sha256"]
    audit = json.loads(audit_path.read_bytes())
    audit["sources_sha256"] = file_sha256(source)
    audit["template_groups"]["e"] = audit["near_duplicate_groups"]["e"] = "e"
    audit["source_dispositions"]["e"] = audit["source_dispositions"]["d"]
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    split = root / "splits.formula.locked.json"
    assignment = dict(zip(ACCEPTANCE_SPLITS, ([company] for company in "abcd")))
    assignment["holdout"].append("e")
    lock_company_splits(source, assignment, split, audit=audit_path)
    index["data.split_manifest_sha256"] = split.name
    protocol["scope"]["formula_scope_decision"] = {"decision": "IN_SCOPE", "reason": "Controlled fixture"}
    protocol["scope"]["declared_modalities"].append("formulas")

    def write(key, value):
        path = root / index.setdefault(key, key + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        return file_sha256(path)

    tests = {f"{metric}:{stratum}": {"metric": metric, "stratum": stratum}
             for metric in formula_scorecard.METRICS for stratum in
             (("overall",) if metric == "formula_detection_errors_per_gt" else ("overall", "inline", "display"))}
    precision = dict(minimum_companies=2, minimum_documents=2, minimum_denominator=2, maximum_ci_width=.25,
                     power=dict(target=.8, pilot_company_influence_sd=.01, detectable_gap=.1, pilot_sha256="1"*64))
    family_key, thresholds_key, margins_key, plan_key = formula_policy.STATS_KEYS
    write(family_key, dict(schema_version="ocr-comparison-family-v1", tests=tests))
    write(thresholds_key, dict(schema_version="ocr-absolute-thresholds-v1",
                               comparisons={key: dict(threshold=.1, basis="confidence_bound") for key in tests}))
    write(margins_key, dict(schema_version="ocr-noninferiority-margins-v1", comparisons=dict.fromkeys(tests, .01)))
    write(plan_key, dict(schema_version="ocr-sample-precision-plan-v1", comparisons=dict.fromkeys(tests, precision)))
    sample = {"schema_version": formula_policy.SAMPLE_SCHEMA, "documents": [
        {"document_id": key, "pdf_sha256": f"{n:064x}", "pages": [1]} for key, n in (("d", 4), ("e", 5))]}
    write(formula_policy.SAMPLE_KEY, sample)
    runtime = {"method": formula_cdm.METHOD, "vendor": {"revision": formula_policy.VENDOR_REVISION,
                "manifest_sha256": formula_cdm.VENDOR_MANIFEST_SHA256}, "dpi": 200, "antialias_bits": 0, "color_tolerance_rgb": 1,
               "adapter_sha256": "2"*64, "python": {"sha256": "3"*64}, "packages": dict.fromkeys(formula_cdm.PACKAGES, "fixture"),
               "tools": {name: {"sha256": "4"*64} for name in ("node", "lualatex")},
               "unicode_fonts": {name: {"sha256": "6"*64} for name in formula_cdm.UNICODE_FONTS}}
    runtime_hash = write(formula_policy.RUNTIME_KEY, runtime)
    def renderer_file(name, value):
        path = root / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return {f"{name}_path": path.name, f"{name}_sha256": file_sha256(path)}

    reference_runtime = renderer_file("reference_runtime", {"revision": formula_policy.VENDOR_REVISION,
        "tex_engine": "lualatex", "comparison_scope": "INDEPENDENT_RAW_INPUT_TOKENIZE_COLOR_COMPILE_RASTER_MATCH",
        "shared_candidate_pdf_or_tex": False,
        "renderer": "ImageMagick/Ghostscript", "tools": {name: {"sha256": "5"*64, "version": "fixture"}
        for name in ("imagemagick", "ghostscript", "lualatex", "node")}})
    reference_report = renderer_file("reference_comparison", {"details": {kind: {"F1_score": .8} for kind in ("inline", "display")}})
    candidate_report = renderer_file("candidate_comparison", {"schema_version": formula_cdm.SCHEMA,
        "method": formula_cdm.METHOD, "runtime_sha256": runtime_hash, "details": [
            {"id": kind, "cdm_f1": .8, "status": "MEASURED", "reference_characters": 5, "prediction_characters": 5}
            for kind in ("inline", "display")]})
    pair_rows = [{"id": kind, "placement": kind, "reference": "x=020", "prediction": "x=02O"} for kind in ("inline", "display")]
    pair_inputs = renderer_file("pair_inputs", {"schema_version": "ocr-formula-renderer-inputs-v1", "pairs": pair_rows})
    pair_hashes = {row["id"]: hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode()).hexdigest() for row in pair_rows}
    coverage = renderer_file("reference_coverage", {"schema_version": "ocr-formula-renderer-coverage-v1",
        "pair_inputs_sha256": pair_inputs["pair_inputs_sha256"], "cases": [{"id": kind, "pair_sha256": pair_hashes[kind],
            "reference_tokens": 5, "localized_reference_tokens": 5, "prediction_tokens": 5, "localized_prediction_tokens": 5}
            for kind in ("inline", "display")]})
    parity = {"schema_version": formula_policy.PARITY_SCHEMA, "status": "REVIEWED", "partition": "development",
              "reviewed_by": "fixture", "reviewed_at": protocol["locked_at"], "candidate_method": formula_cdm.METHOD,
              "reference_revision": formula_policy.VENDOR_REVISION, "runtime_sha256": runtime_hash,
              **reference_runtime, **reference_report, **candidate_report, **pair_inputs, **coverage,
              "planned_case_ids": ["inline", "display"], "cases": [{"id": kind, "placement": kind, "pair_sha256": pair_hashes[kind],
                  "reference_cdm_f1": .8, "candidate_cdm_f1": .8} for kind in ("inline", "display")]}
    write(formula_policy.PARITY_KEY, parity)
    template = TEMPLATE.with_name("formula_acceptance_policy.example.json")
    policy = json.loads(template.read_bytes())
    policy.update(status="LOCKED", approved_by=protocol["approved_by"], locked_at=protocol["locked_at"],
                  iou_threshold=.5, maximum_cdm_pair_absolute_delta=.01)

    def freeze():
        policy["artifact_hashes"] = {key: file_sha256(root / index[key]) for key in policy["artifact_hashes"]}
        write(formula_policy.POLICY_KEY, policy)
        for key, name in index.items():
            section, field = key.split(".")
            protocol[section][field] = file_sha256(root / name)
        protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
        index_path.write_text(yaml.safe_dump(index), encoding="utf-8")

    freeze()
    return protocol_path, index_path, write, freeze, policy, sample, parity, tests


def test_declared_formula_policy_verifies_inputs_without_granting_release(bundle):
    protocol, index, *_ = _formula_fixture(bundle)
    verified = preflight(protocol, index, for_release=True)
    assert verified["status"] == "INPUTS_VERIFIED" and verified["scope_context"] == "V70_RELEASE"
    evidence = verified["formula_evidence"]
    assert evidence["status"] == "DECLARED_FORMULA_POLICY_VERIFIED"
    assert evidence["holdout_sample"] == {"documents": 2, "companies": 2, "pages": 2}
    assert evidence["locked_comparisons"] == 16 and evidence["reviewed_development_renderer_cases"] == 2
    assert not evidence["eligible_for_quality_acceptance"]
    assert not verified["issues"] and verified["quality_acceptance_status"] == "NOT_EVALUATED"
    replay = preflight(protocol, index, for_formula_replay=True)
    assert replay["status"] == "INPUTS_VERIFIED" and replay["scope_context"] == "FORMULA_HOLDOUT_REPLAY"
    assert not replay["eligible_for_quality_acceptance"]


def test_formula_replay_recomputes_sampled_pairs_and_keeps_negative_pages(bundle, monkeypatch):
    from types import SimpleNamespace
    from benchmark.scientific_evaluation import formula_holdout_replay as replay, formula_policy

    protocol, index, write, freeze, _policy, sample, parity, _tests = _formula_fixture(bundle, d_pages=3)
    sample["documents"][0]["pages"] = [1, 2]
    write(formula_policy.SAMPLE_KEY, sample)
    freeze()
    root = index.parent
    pdf_root = root / "inputs"
    frame = {"coordinate_space": "pdf_points_top_left", "transforms": [], "width": 100, "height": 100}
    bbox = [10, 10, 30, 20]
    label = {"id": "ref", "bbox": bbox, "content_raw": "x−1", "format": "TEXT", "placement": "inline", "equation_label": None}
    refs = {"documents": [], "custody": {"status": "DECLARED_CUSTODY_COMPLETE_FOR_HOLDOUT",
                                         "independent_ground_truth_verified": False}}
    publications = {side: {"batches": [], "documents": []} for side in replay.SIDES}

    def item(raw):
        return {"id": "visible", "bbox": bbox, "kind": "b", "block_type": "formula", "text_raw": raw, "source": "fixture"}

    def payload(path, data):
        path.write_text(json.dumps(data), encoding="utf-8")
        return file_sha256(path)

    for doc in sample["documents"]:
        key, pdf_hash = doc["document_id"], doc["pdf_sha256"]
        total = 3 if key == "d" else 1
        refs["documents"].append({"document_id": key, "pdf_sha256": pdf_hash, "total_pages": total,
            "pages": [{**frame, "page": page, "formulas": [label] if page == 1 else []} for page in doc["pages"]]})
        for side, publication in publications.items():
            directory = root / side / key
            directory.mkdir(parents=True)
            matched = (side, key) in (("baseline", "e"), ("candidate", "d"))
            pages = [{**frame, "page": 1, "items": [item("x−1")] if matched else []}]
            if key == "d":
                pages.extend([{**frame, "page": 2, "items": [item("false positive")] if side == "baseline" else []},
                              {**frame, "page": 3, "items": [item("outside locked sample")]}])
            extraction = payload(directory / "extraction.json", {"doc_id": key, "doc_sha16": pdf_hash[:16],
                                                                 "total_pages": total, "pages": pages})
            files = {"extraction.json": extraction}
            publication["documents"].append({"id": key, "source_dir": str(directory), "pdf_sha256": pdf_hash,
                "total_pages": total, "ocr_receipt_sha256": payload(directory / "ocr_receipt.json", {"files": files}),
                "completion_sha256": payload(directory / "COMPLETED.json", {"files": files, "side": side})})
    monkeypatch.setattr(replay, "replay_holdout_references", lambda *_: refs)
    monkeypatch.setattr(replay, "collect_predictions", lambda roots: publications[roots[0].name])
    global_sample = root / "global-sample.json"
    global_units = []
    for doc in sample["documents"]:
        for page in doc["pages"]:
            global_units.append({"unit_id": f"{doc['document_id']}/{page}/page", "document_id": doc["document_id"],
                "pdf_sha256": doc["pdf_sha256"], "page": page, "region_id": "page", "strata": [],
                "metrics": ["formula_detection_errors_per_gt"] + (["formula_detection_recall"] if page != 1 else [])})
        global_units.append({"unit_id": doc["document_id"] + "/1/formula:ref", "document_id": doc["document_id"],
            "pdf_sha256": doc["pdf_sha256"], "page": 1, "region_id": "formula:ref", "strata": ["inline"],
            "metrics": ["formula_detection_recall", "formula_text_cer", "formula_text_exact", "formula_critical_error_rate"]})
    global_hash = payload(global_sample, {"schema_version": "ocr-holdout-scorecard-sample-v1", "units": global_units})
    current_index = yaml.safe_load(index.read_text(encoding="utf-8"))
    plan_key = "statistics.sample_size_and_precision_plan_sha256"
    plan = json.loads((root / current_index[plan_key]).read_bytes())
    plan["sample_sha256"] = global_hash
    write(plan_key, plan)
    freeze()
    args = SimpleNamespace(protocol=protocol, artifact_index=index, pdf_root=pdf_root, output=root / "replay-output",
                           baseline_batch=[root / "baseline"], candidate_batch=[root / "candidate"], scorecard_sample=global_sample)
    assert replay.main(["--protocol", str(protocol), "--artifact-index", str(index), "--pdf-root", str(pdf_root),
                        "--baseline-batch", str(args.baseline_batch[0]), "--candidate-batch", str(args.candidate_batch[0]),
                        "--output", str(args.output), "--scorecard-sample", str(global_sample)]) == 0
    result = json.loads((args.output / "replay.json").read_bytes())
    assert result["status"] == "SOURCE_REPLAY_COMPLETED" and result["acceptance_status"] == "NOT_EVALUATED"
    assert not result["eligible_for_quality_acceptance"]
    assert result["sides"]["baseline"]["detection_counts"] == {"tp": 1, "fp": 1, "fn": 1}
    assert result["sides"]["candidate"]["detection_counts"] == {"tp": 1, "fp": 0, "fn": 1}
    baseline_alignment = args.output / "baseline/alignment.json"
    assert "outside locked sample" not in baseline_alignment.read_text(encoding="utf-8")
    scorecard_path = args.output / "scorecard.json"
    comparisons = json.loads(scorecard_path.read_bytes())["comparisons"]
    assert comparisons["formula_detection_errors_per_gt:overall"]["baseline"]["micro"] == 1
    assert comparisons["formula_text_cer:overall"]["candidate"]["micro"] == .5
    assert comparisons["formula_cdm_mean:overall"]["candidate"]["micro"] is None
    assert result["scorecard_sha256"] == file_sha256(scorecard_path)
    exported = json.loads((args.output / result["global_counts"]["candidate"]["path"]).read_bytes())
    assert exported["sample_sha256"] == global_hash and exported["acceptance_status"] == "NOT_EVALUATED"
    assert len(exported["records_by_metric"]["formula_detection_recall"]) == 3

    for side in replay.SIDES:
        review = json.loads((args.output / side / "critical-template.json").read_bytes())
        assert review["status"] == "BLANK" and review["reviewer"] is None
        review.update(status="SUBMITTED", actor_type="HUMAN", source_images_checked=True,
                      reviewer="fixture reviewer", reviewed_at="2026-11-04T12:00:00+07:00")
        for pair in review["pairs"]:
            for category in pair["categories"].values():
                category.update(status="ERROR", reason="Controlled formula discrepancy")
        review_path = root / f"{side}-critical.json"
        payload(review_path, review)
        setattr(args, f"{side}_critical", review_path)
    args.output = root / "reviewed-replay"
    reviewed = replay.run_replay(args)
    assert reviewed["critical_status"] == "MEASURED_DECLARED_REVIEWS" and reviewed["cdm_status"] == "NOT_EVALUATED"
    assert reviewed["sides"]["candidate"]["critical_review_sha256"] == file_sha256(args.candidate_critical)
    comparison = json.loads((args.output / "scorecard.json").read_bytes())["comparisons"]["formula_critical_error_rate:overall"]
    assert comparison["candidate"]["micro"] == 1.0

    # Only the subprocess boundary is simulated. Both runs bind the same
    # source replay, verify actual render artifacts and produce equal digests.
    from benchmark.scientific_evaluation import formula_cdm

    runtime_key = formula_policy.RUNTIME_KEY
    runtime_path = root / current_index[runtime_key]
    runtime = json.loads(runtime_path.read_bytes())
    executable = root / "controlled-tool.exe"
    executable.write_bytes(b"controlled identity, never executed")
    runtime.update(adapter_sha256=file_sha256(Path(formula_cdm.__file__)), vendor=formula_cdm.verify_vendor(),
                   limits={}, python={"version": "fixture", "sha256": "3" * 64})
    runtime["tools"] = {name: {"path": str(executable), "sha256": file_sha256(executable), "version": "fixture",
                               "adjacent_dlls": []} for name in ("node", "lualatex")}
    runtime_hash = write(runtime_key, runtime)
    parity["runtime_sha256"] = runtime_hash
    candidate_report = root / parity["candidate_comparison_path"]
    candidate_comparison = json.loads(candidate_report.read_bytes())
    candidate_comparison["runtime_sha256"] = runtime_hash
    parity["candidate_comparison_sha256"] = payload(candidate_report, candidate_comparison)
    write(formula_policy.PARITY_KEY, parity)
    freeze()
    monkeypatch.setattr(formula_cdm, "runtime_identity", lambda *_: runtime)

    def render_controls(options, pairs_path, output, locked_path, locked_hash):
        directory = output / "cdm"
        formula_cdm.evaluate_pair_file(pairs_path, directory, node=executable, lualatex=executable,
                                       expected_runtime_path=locked_path, expected_runtime_sha256=locked_hash)
        process = {"returncode": 1, "timed_out": False, "output_limit_exceeded": False}
        for name in ("stdout", "stderr"):
            log = output / name
            log.write_bytes(b"Controlled completed process")
            process.update({name: log.name, f"{name}_sha256": file_sha256(log)})
        payload(output / "cdm-process.json", process)
        _, checked = formula_cdm.verify_comparison(directory, pairs_path, expected_runtime_path=locked_path,
                                                    expected_runtime_sha256=locked_hash)
        return directory, checked

    monkeypatch.setattr(replay, "_render_pairs", render_controls)
    args.formula_python = args.node = args.lualatex = executable
    args.output = root / "first-render-replay"
    original = replay.run_replay(args)
    original_path = args.output
    args.formula_python = args.node = args.lualatex = None
    args.baseline_cdm, args.candidate_cdm = (original_path / side / "cdm" for side in replay.SIDES)
    args.output = root / "cached-render-replay"
    repeated = replay.run_replay(args)
    assert original == repeated
    assert file_sha256(original_path / "replay.json") == file_sha256(args.output / "replay.json")

    args.output = root / "tampered-replay"
    original_doc = publications["candidate"]["documents"].pop()
    with pytest.raises(ValueError, match="lacks a frozen formula sample document"):
        replay.run_replay(args)
    publications["candidate"]["documents"].append(original_doc)
    baseline_doc = publications["baseline"]["documents"][-1]
    publications["candidate"]["documents"][-1] = {**original_doc, "completion_sha256": baseline_doc["completion_sha256"]}
    with pytest.raises(ValueError, match="distinct completion receipts"):
        replay.run_replay(args)
    publications["candidate"]["documents"][-1] = original_doc
    (root / "candidate/d/COMPLETED.json").write_bytes(b"changed after collection")
    with pytest.raises(ValueError, match="differs from verified publication"):
        replay.run_replay(args)
    assert not args.output.exists()


def test_formula_replay_refuses_draft_before_custody_or_predictions(bundle, monkeypatch):
    from types import SimpleNamespace
    from benchmark.scientific_evaluation import formula_holdout_replay as replay

    excluded, index, *_ = bundle
    monkeypatch.setattr(replay, "replay_holdout_references", lambda *_: pytest.fail("opened custody before preflight"))
    monkeypatch.setattr(replay, "collect_predictions", lambda *_: pytest.fail("opened predictions before preflight"))
    root = index.parent
    args = SimpleNamespace(protocol=TEMPLATE, artifact_index=index, pdf_root=root / "inputs", output=root / "replay-output",
                           baseline_batch=[root / "baseline"], candidate_batch=[root / "candidate"])
    with pytest.raises(ValueError, match="must be LOCKED"):
        replay.run_replay(args)
    args.protocol = excluded
    with pytest.raises(ValueError, match="formula holdout replay requires IN_SCOPE"):
        replay.run_replay(args)
    assert not args.output.exists()


def test_formula_policy_rejects_changed_hash_and_non_holdout_sample(bundle):
    from benchmark.scientific_evaluation import formula_policy

    protocol, index, write, freeze, _, sample, *_ = _formula_fixture(bundle)
    sample["documents"][0].update(document_id="b", pdf_sha256=f"{2:064x}")
    write(formula_policy.SAMPLE_KEY, sample)
    assert f"{formula_policy.SAMPLE_KEY}: SHA-256 mismatch" in preflight(protocol, index)["issues"]
    freeze()
    result = preflight(protocol, index)
    assert any("outside holdout" in issue for issue in result["issues"])
    assert result["formula_evidence"]["status"] == "NOT_EVALUATED"


def test_formula_policy_rejects_unjustified_skips_and_renderer_mismatch(bundle):
    from benchmark.scientific_evaluation import formula_policy

    protocol, index, write, freeze, policy, _, parity, _ = _formula_fixture(bundle)
    policy["not_applicable"] = [{"metric": "formula_critical_error_rate", "stratum": "display", "reason": "fixture",
                                "calibration_evidence_sha256": "9"*64}]
    freeze()
    assert any("nonmandatory stratum" in issue for issue in preflight(protocol, index)["issues"])
    policy["not_applicable"] = []
    parity["cases"][0]["candidate_cdm_f1"] = .9
    candidate = index.parent / parity["candidate_comparison_path"]
    raw = json.loads(candidate.read_bytes())
    raw["details"][0]["cdm_f1"] = .9
    candidate.write_text(json.dumps(raw), encoding="utf-8")
    parity["candidate_comparison_sha256"] = file_sha256(candidate)
    write(formula_policy.PARITY_KEY, parity)
    freeze()
    assert any("parity tolerance" in issue for issue in preflight(protocol, index)["issues"])


def test_formula_policy_rejects_rewritten_renderer_report_and_requires_calibration_artifact(bundle):
    from benchmark.scientific_evaluation import formula_policy

    protocol, index, _, freeze, policy, _, parity, _ = _formula_fixture(bundle)
    policy["not_applicable"] = [{"metric": "formula_text_exact", "stratum": "display", "reason": "fixture",
                                "calibration_evidence_path": "missing-calibration.json", "calibration_evidence_sha256": "9"*64}]
    freeze()
    assert any("missing-calibration.json" in issue for issue in preflight(protocol, index)["issues"])
    policy["not_applicable"] = []
    freeze()
    (index.parent / parity["reference_comparison_path"]).write_text("{}", encoding="utf-8")
    assert any("reference_comparison" in issue and "changed" in issue for issue in preflight(protocol, index)["issues"])


@pytest.mark.parametrize("scope", ["shared_pdf", "no_compiler", "missing_compiler_identity"])
def test_formula_policy_requires_full_reference_compilation(bundle, scope):
    from benchmark.scientific_evaluation import formula_policy

    protocol, index, write, freeze, _, _, parity, _ = _formula_fixture(bundle)
    path = index.parent / parity["reference_runtime_path"]
    runtime = json.loads(path.read_bytes())
    if scope == "shared_pdf":
        runtime["shared_candidate_pdf_or_tex"] = True
    elif scope == "no_compiler":
        runtime.pop("tex_engine")
    else:
        runtime["tools"].pop("lualatex")
    path.write_text(json.dumps(runtime), encoding="utf-8")
    parity["reference_runtime_sha256"] = file_sha256(path)
    write(formula_policy.PARITY_KEY, parity)
    freeze()
    result = preflight(protocol, index, for_release=True)
    assert result["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"
    expected = "independent raw-input compilation" if scope != "missing_compiler_identity" else "Reference runtime identity"
    assert any(expected in issue for issue in result["issues"])


def test_formula_policy_rejects_perfect_scores_that_dropped_reference_glyphs(bundle):
    from benchmark.scientific_evaluation import formula_policy

    protocol, index, write, freeze, _, _, parity, _ = _formula_fixture(bundle)
    root = index.parent

    def update(name, mutate):
        path = root / parity[f"{name}_path"]
        value = json.loads(path.read_bytes())
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")
        parity[f"{name}_sha256"] = file_sha256(path)
        return value

    inputs = update("pair_inputs", lambda data: data["pairs"][0].update(reference="α+β", prediction="α+β"))
    pair_hash = hashlib.sha256(json.dumps(inputs["pairs"][0], sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest()
    update("reference_coverage", lambda data: (data.update(pair_inputs_sha256=parity["pair_inputs_sha256"]),
        data["cases"][0].update(pair_sha256=pair_hash, reference_tokens=3, localized_reference_tokens=1,
                                 prediction_tokens=3, localized_prediction_tokens=1)))
    update("reference_comparison", lambda data: data["details"]["inline"].update(F1_score=1.0))
    update("candidate_comparison", lambda data: data["details"][0].update(cdm_f1=1.0, reference_characters=1, prediction_characters=1))
    parity["cases"][0].update(pair_sha256=pair_hash, reference_cdm_f1=1.0, candidate_cdm_f1=1.0)
    write(formula_policy.PARITY_KEY, parity)
    freeze()
    result = preflight(protocol, index, for_release=True)
    assert result["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"
    assert any("reference glyph coverage is incomplete" in issue for issue in result["issues"])
    assert result["formula_evidence"]["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("prediction", [None, r"\frac{a}"])
def test_formula_renderer_keeps_missing_and_broken_predictions_with_zero_score(bundle, prediction):
    from benchmark.scientific_evaluation import formula_policy

    protocol, index, write, freeze, _, _, parity, _ = _formula_fixture(bundle)

    def update(name, mutate):
        path = index.parent / parity[f"{name}_path"]
        value = json.loads(path.read_bytes())
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")
        parity[f"{name}_sha256"] = file_sha256(path)
        return value

    inputs = update("pair_inputs", lambda data: data["pairs"][0].update(prediction=prediction))
    pair_hash = hashlib.sha256(json.dumps(inputs["pairs"][0], sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest()
    # Upstream can retain a partial glyph from malformed TeX. Its F1 must still be zero.
    partial = int(prediction is not None)
    update("reference_coverage", lambda data: (data.update(pair_inputs_sha256=parity["pair_inputs_sha256"]),
        data["cases"][0].update(pair_sha256=pair_hash, prediction_tokens=partial, localized_prediction_tokens=partial)))
    update("reference_comparison", lambda data: data["details"]["inline"].update(F1_score=0.0))
    update("candidate_comparison", lambda data: data["details"][0].update(cdm_f1=0.0,
        prediction_characters=None if partial else 0,
        reason="PREDICTION_RENDER_FAILED" if partial else "MISSING_PREDICTION",
        prediction_error_kind="CONTENT_RENDER_FAILURE" if partial else None))
    parity["cases"][0].update(pair_sha256=pair_hash, reference_cdm_f1=0.0, candidate_cdm_f1=0.0)
    write(formula_policy.PARITY_KEY, parity)
    freeze()
    assert preflight(protocol, index, for_release=True)["status"] == "INPUTS_VERIFIED"
    # A wide scalar tolerance cannot excuse upstream awarding partial credit here.
    update("reference_comparison", lambda data: data["details"]["inline"].update(F1_score=.001))
    parity["cases"][0]["reference_cdm_f1"] = .001
    write(formula_policy.PARITY_KEY, parity)
    freeze()
    assert any("must penalize" in issue for issue in preflight(protocol, index)["issues"])


def test_formula_policy_requires_coverage_and_exact_pair_identity(bundle):
    from benchmark.scientific_evaluation import formula_policy

    protocol, index, write, freeze, _, _, parity, _ = _formula_fixture(bundle)
    parity["cases"][0]["pair_sha256"] = "8" * 64
    write(formula_policy.PARITY_KEY, parity)
    freeze()
    assert any("case is missing, invalid" in issue for issue in preflight(protocol, index)["issues"])
    del parity["reference_coverage_path"]
    write(formula_policy.PARITY_KEY, parity)
    freeze()
    assert any("reference_coverage requires" in issue for issue in preflight(protocol, index)["issues"])


def test_excluded_formula_decision_cannot_conflict_with_the_modality_list(bundle):
    protocol_path, index_path, protocol, _ = bundle
    protocol["scope"]["declared_modalities"].append("formulas")
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    assert preflight(protocol_path, index_path)["issues"] == [
        "scope.formula_scope_decision: EXCLUDED conflicts with declared modality formulas"]


def test_excluded_component_bundle_cannot_open_a_v70_release_or_its_holdout(bundle):
    from types import SimpleNamespace
    from benchmark.scientific_evaluation.release_gate import run_gate

    protocol_path, index_path, _, _ = bundle
    assert preflight(protocol_path, index_path)["scope_context"] == "COMPONENT_MEASUREMENT"
    release = preflight(protocol_path, index_path, for_release=True)
    assert release["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"
    assert release["scope_context"] == "V70_RELEASE"
    assert release["issues"] == ["scope.formula_scope_decision: v7.0 release requires IN_SCOPE formula correctness"]
    # No sample or prediction arguments are supplied: the gate must stop
    # before trying to open holdout artifacts for an incomplete release scope.
    gate = run_gate(SimpleNamespace(protocol=protocol_path, artifact_index=index_path))
    assert gate["release_status"] == "NOT_EVALUATED"
    assert gate["preflight"] == release


def test_legacy_source_audit_can_be_read_but_does_not_open_acceptance(bundle):
    protocol_path, index_path, protocol, index = bundle
    root = index_path.parent
    audit_path = root / index["data.near_duplicate_audit_sha256"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["schema_version"] = "split-leakage-audit-v1"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    prior = json.loads((root / index["data.split_manifest_sha256"]).read_text(encoding="utf-8"))
    split_path = root / "legacy-split.json"
    lock_company_splits(root / index["data.input_manifest_sha256"], prior["companies"], split_path, audit=audit_path)
    index["data.split_manifest_sha256"] = split_path.name
    protocol["data"]["split_manifest_sha256"] = file_sha256(split_path)
    protocol["data"]["near_duplicate_audit_sha256"] = file_sha256(audit_path)
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    index_path.write_text(yaml.safe_dump(index), encoding="utf-8")
    result = preflight(protocol_path, index_path)
    assert result["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"
    assert result["issues"] == [
        "data.near_duplicate_audit_sha256: acceptance requires split-leakage-audit-v2 source-use evidence"]


def test_rehashing_tampered_split_does_not_make_it_valid(bundle):
    protocol_path, index_path, protocol, index = bundle
    split_path = index_path.parent / index["data.split_manifest_sha256"]
    split = json.loads(split_path.read_text(encoding="utf-8"))
    split["documents"][0]["split"] = "holdout"
    split_path.write_text(json.dumps(split), encoding="utf-8")
    protocol["data"]["split_manifest_sha256"] = file_sha256(split_path)
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    assert preflight(protocol_path, index_path)["issues"] == ["splits-v2: Split inventory changed"]


def test_incomplete_or_approved_decision_is_rejected(bundle):
    protocol_path, index_path, protocol, _ = bundle
    protocol["thresholds"]["micro_der_vn_maximum"] = None
    protocol["decision"]["release_approval"] = "pretend approval"
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    result = preflight(protocol_path, index_path)
    assert result["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"
    assert len(result["issues"]) == 2


def test_duplicate_yaml_keys_are_rejected(bundle):
    protocol_path, _, _, _ = bundle
    with protocol_path.open("a", encoding="utf-8") as stream:
        stream.write("status: DRAFT\n")
    with pytest.raises(ValueError, match="Duplicate YAML"):
        preflight(protocol_path)


def test_scorecard_cli_binds_the_locked_bundle_and_prediction_inventory(bundle, monkeypatch):
    import sys

    from benchmark.scientific_evaluation import scorecard_counts
    from benchmark.scientific_evaluation.canonical_predictions import pair_predictions
    from benchmark.scientific_evaluation.stratified_scorecard import main
    from ocr_artifacts.digest import sha256_json_compact

    protocol_path, index_path, protocol, index = bundle
    root = protocol_path.parent

    def write(name, schema, **fields):
        path = root / name
        path.write_text(json.dumps({"schema_version": schema, **fields}), encoding="utf-8")
        return path

    sha = f"{4:064x}"
    sample = write("sample.json", "ocr-holdout-scorecard-sample-v1",
                   units=[dict(unit_id="u", document_id="d", page=1, region_id="body", pdf_sha256=sha,
                               strata=[], metrics=["cer"])])
    method = dict(minimum_companies=2, minimum_documents=1, minimum_denominator=1, maximum_ci_width=.1,
                  power=dict(target=.8, pilot_company_influence_sd=.005, detectable_gap=.03, pilot_sha256="a" * 64))
    for section, field, schema, fields in (
        ("data", "gt_manifest_sha256", "ocr-scorecard-gt-v1", {"documents": {"d": {"pdf_sha256": sha}}}),
        ("statistics", "sample_size_and_precision_plan_sha256", "ocr-sample-precision-plan-v1",
         {"sample_sha256": file_sha256(sample), "comparisons": {"cer": method}}),
        ("statistics", "multiple_comparison_family_sha256", "ocr-comparison-family-v1",
         {"tests": {"cer": {"metric": "cer", "stratum": "overall"}}}),
        ("thresholds", "subgroup_thresholds_sha256", "ocr-absolute-thresholds-v1",
         {"comparisons": {"cer": {"threshold": protocol["thresholds"]["micro_cer_maximum"], "basis": "point"}}}),
        ("thresholds", "baseline_noninferiority_margins_sha256", "ocr-noninferiority-margins-v1",
         {"comparisons": {"cer": .001}}),
    ):
        path = write(index[f"{section}.{field}"], schema, **fields)
        protocol[section][field] = file_sha256(path)
    protocol_path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    paired = {side: {"documents": [dict(id="d", pdf_sha256=sha, total_pages=1, source_dir=side,
                                      completion_sha256=checksum * 64)]}
              for side, checksum in (("baseline", "a"), ("candidate", "b"))}
    predictions = write("predictions.json", "canonical-benchmark-predictions-v1", **paired,
                        pairs=pair_predictions(paired["baseline"], paired["candidate"]),
                        status="PREDICTIONS_VERIFIED", profile="unified_gpu_full_ocr", source_policy="gpu_ocr_only_v1")
    run_paths = {}
    for side in paired:
        run_paths[side] = write(f"{side}.json", "ocr-paired-counts-v1", run_id=side,
                                sample_sha256=file_sha256(sample), gt_sha256=protocol["data"]["gt_manifest_sha256"],
                                normalization="visible_strict_v1", prediction_inventory_sha256=file_sha256(predictions),
                                prediction_manifest_sha256=sha256_json_compact(paired[side]),
                                records_by_metric={"cer": [dict(unit_id="u", status="MEASURED",
                                                               numerator=1, denominator=100)]})
    def fake_document_counts(units, publication, evidence, *args, reading_order_alignment):
        assert publication["pdf_sha256"] == evidence["pdf_sha256"] == sha
        assert reading_order_alignment is None
        yield "cer", {"unit_id": units[0]["unit_id"], "status": "MEASURED", "numerator": 1, "denominator": 100}

    monkeypatch.setattr(scorecard_counts, "_document_counts", fake_document_counts)
    exported = root / "candidate-exported.json"
    export_paths = {"protocol": protocol_path, "artifact-index": index_path, "sample": sample,
                    "prediction-inventory": predictions, "output": exported}
    export_args = [value for key, path in export_paths.items() for value in (f"--{key}", str(path))]
    monkeypatch.setattr(sys, "argv", ["scorecard-counts", "--side", "candidate", *export_args])
    assert scorecard_counts.main() == 0
    run_paths["candidate"] = exported
    report = root / "report.json"
    paths = {"protocol": protocol_path, "artifact-index": index_path, "sample": sample,
             "prediction-inventory": predictions, "report": report, **run_paths}
    args = [value for key, path in paths.items() for value in (f"--{key}", str(path))]
    monkeypatch.setattr(sys, "argv", ["scorecard", *args])
    assert main() == 1
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["acceptance_status"] == "NOT_EVALUATED"
    assert result["comparisons"]["cer"]["scores"]["company_count"] == 1
    assert result["comparisons"]["cer"]["absolute"]["status"] == "NOT_EVALUATED"
    assert result["runs"][1]["producer"] == "canonical-scorecard-counts-v1"
    # A different prediction inventory cannot reuse the count reports.
    predictions.write_text(predictions.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    args[args.index("--report") + 1] = str(root / "second-report.json")
    monkeypatch.setattr(sys, "argv", ["scorecard", *args])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
