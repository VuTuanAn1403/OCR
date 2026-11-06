"""Validate formula policy and declared renderer evidence before holdout access."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

from src.ocr.collect.catalog import file_sha256, read_sources

POLICY_KEY = "evaluation.formula_policy_sha256"
SAMPLE_KEY = "data.formula_holdout_sample_sha256"
PARITY_KEY = "evaluation.formula_renderer_validation_sha256"
RUNTIME_KEY = "runtime.formula_renderer_manifest_sha256"
ARTIFACTS = (POLICY_KEY, SAMPLE_KEY, PARITY_KEY, RUNTIME_KEY)
POLICY_SCHEMA = "ocr-formula-acceptance-policy-v1"
PARITY_SCHEMA = "ocr-formula-renderer-validation-v1"
SAMPLE_SCHEMA = "ocr-formula-scorecard-sample-v1"
VENDOR_REVISION = "5a2c80d96b1d2dba447ff18d873e5fb73ba03c35"
STATS_KEYS = ("statistics.multiple_comparison_family_sha256", "thresholds.subgroup_thresholds_sha256",
              "thresholds.baseline_noninferiority_margins_sha256", "statistics.sample_size_and_precision_plan_sha256")
FIXED_RULES = {"missing_gt": "BLOCK_MEASUREMENT", "missing_prediction": "KEEP_AND_PENALIZE",
               "unsupported_representation": "BLOCK_ACCEPTANCE", "annotation_custody": "TWO_INDEPENDENT_HUMANS_AND_ADJUDICATOR",
               "localization_scope": "EXTRACTION_FORMULA_ITEMS_AND_FORMULA_TEXT_BLOCKS",
               "reviewed_span_credit": "CONTENT_ONLY", "critical_scope": "ALL_SEVEN_CATEGORIES_PER_FORMULA",
               "zero_denominator": "NOT_EVALUATED", "paired_bootstrap": "COMPANY_CLUSTER"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, limit=None):
    return (type(value) in (int, float) and math.isfinite(value) and value >= 0
            and (limit is None or value <= limit))


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _time(value):
    parsed = datetime.fromisoformat(value)
    _require(parsed.utcoffset() is not None, "Formula approval timestamps must include a timezone")
    return parsed


def _json(path, schema=None):
    def unique_fields(items):
        result = dict(items)
        _require(len(result) == len(items), f"Duplicate JSON keys in {path.name}")
        return result

    value = json.loads(path.read_bytes(), object_pairs_hook=unique_fields)
    _require(isinstance(value, dict) and (schema is None or value.get("schema_version") == schema),
             f"Expected {schema or 'a JSON object'} in {path.name}")
    return value


def _indexed_json(root, entry, name, schema=None):
    relative = entry.get(f"{name}_path")
    digest = entry.get(f"{name}_sha256")
    _require(_text(relative) and not Path(relative).is_absolute() and _hash(digest), f"{name} requires a relative path and SHA-256")
    path = (root / relative).resolve()
    _require(path.is_relative_to(root) and file_sha256(path) == digest, f"{name} is outside its evidence directory or has changed")
    value = _json(path, schema)
    _require(file_sha256(path) == digest, f"{name} changed during verification")
    return value


def _frozen_policy(protocol, policy):
    from .formula_cdm import METHOD as cdm_method
    from .formula_content import METHOD as text_method

    _require(policy.get("status") == "LOCKED" and _text(policy.get("approved_by"))
             and policy["approved_by"] == protocol["approved_by"], "Formula policy requires the protocol approver and LOCKED status")
    locked = _time(policy["locked_at"])
    _require(locked <= _time(protocol["locked_at"]), "Formula policy must be locked before or with the protocol")
    _require(policy.get("rules") == FIXED_RULES and policy.get("reference_placements") == ["inline", "display"],
             "Formula policy must cover inline and display and preserve mandatory rules")
    _require(policy.get("text_method") == text_method and policy.get("cdm_method") == cdm_method,
             "Formula policy uses a different TEXT or CDM implementation")
    _require(_number(policy.get("iou_threshold"), 1) and policy["iou_threshold"] > 0
             and _number(policy.get("maximum_cdm_pair_absolute_delta"), 1), "Formula IoU and CDM parity tolerances must be locked")
    hashes = policy.get("artifact_hashes")
    keys = (SAMPLE_KEY, PARITY_KEY, RUNTIME_KEY, "data.adjudication_manifest_sha256", *STATS_KEYS)
    expected = {key: protocol[section][field] for key in keys for section, field in (key.split("."),)}
    _require(hashes == expected and all(_hash(value) for value in expected.values()),
             "Formula policy must pin the same sample, adjudication, renderer and statistical artifacts as the protocol")
    return locked


def _sample(sample, split, sources):
    assigned = {row["document_id"]: row for row in split["documents"] if row["split"] == "holdout"}
    catalog = {row["document_id"]: row for row in sources if row["status"] == "OK"}
    requested = sample.get("documents")
    _require(isinstance(requested, list) and requested, "Formula holdout sample is empty")
    seen, companies, page_count = set(), set(), 0
    for record in requested:
        key, pages = record["document_id"], record["pages"]
        _require(key not in seen and key in assigned and key in catalog, "Formula sample document is duplicate or outside holdout")
        current, partition = catalog[key], assigned[key]
        _require(record["pdf_sha256"] == current["sha256"] == partition["sha256"]
                 and current["company_id"] == partition["company_id"] and current["company_id"] != "unknown",
                 "Formula sample PDF or company identity differs")
        _require(isinstance(pages, list) and pages and all(type(page) is int and 1 <= page <= int(current["pages"]) for page in pages)
                 and len(set(pages)) == len(pages), "Formula sample requires unique in-range physical pages")
        seen.add(key)
        companies.add(current["company_id"])
        page_count += len(pages)
    return {"documents": len(seen), "companies": len(companies), "pages": page_count}


def _family(policy, statistics, family, thresholds, margins, precision_plan, available, policy_root, locked_at):
    from .cluster_statistics import BOUNDED_RATIOS
    from .formula_scorecard import METRICS
    from .stratified_scorecard import _precision_plan

    _require(type(statistics["resamples"]) is int and statistics["resamples"] >= 100,
             "Formula company bootstrap requires at least 100 resamples")
    mandatory = {(metric, "overall") for metric in METRICS}
    mandatory.update((metric, stratum) for metric in ("formula_detection_recall", "formula_critical_error_rate")
                     for stratum in ("inline", "display"))
    optional = {(metric, stratum) for metric in ("formula_text_cer", "formula_text_exact", "formula_cdm_mean")
                for stratum in ("inline", "display")}
    not_applicable = policy.get("not_applicable")
    _require(isinstance(not_applicable, list), "Formula applicability must be explicit")
    skipped = set()
    for item in not_applicable:
        key = item["metric"], item["stratum"]
        _require(key in optional and key not in skipped and _text(item.get("reason")) and _hash(item.get("calibration_evidence_sha256")),
                 "Formula not-applicable claims require a nonmandatory stratum and calibration evidence")
        evidence = _indexed_json(policy_root, item, "calibration_evidence", "ocr-formula-applicability-evidence-v1")
        _require((evidence.get("metric"), evidence.get("stratum")) == key and evidence.get("partition") == "calibration"
                 and evidence.get("status") == "REVIEWED" and _text(evidence.get("reviewed_by"))
                 and _time(evidence["reviewed_at"]) <= locked_at and _text(evidence.get("reason")),
                 "Formula applicability evidence must be reviewed calibration for the exact stratum")
        skipped.add(key)
    tests = family["tests"]
    _require(tests.keys() == thresholds["comparisons"].keys() == margins["comparisons"].keys() == precision_plan["comparisons"].keys(),
             "Formula family must share the global thresholds, margins and precision-plan keys")
    pairs = set()
    for name, test in tests.items():
        metric, stratum = test["metric"], test["stratum"]
        if not metric.startswith("formula_"):
            continue
        key = metric, stratum
        _require(key not in pairs, "Duplicate formula metric and stratum")
        pairs.add(key)
        threshold, margin = thresholds["comparisons"][name], margins["comparisons"][name]
        limit = 1 if metric in BOUNDED_RATIOS else None
        _require(_number(threshold.get("threshold"), limit) and threshold.get("basis") in ("point", "confidence_bound")
                 and _number(margin, limit), f"Missing or invalid formula threshold or margin: {name}")
        precision = _precision_plan(precision_plan["comparisons"][name], statistics, len(tests))
        _require(precision["required_companies"] <= available["companies"] and precision["minimum_documents"] <= available["documents"],
                 f"Formula holdout sample is smaller than the approved precision plan: {name}")
    _require(pairs == (mandatory | optional) - skipped, "Formula comparison family is incomplete or conflicts with locked applicability")
    return len(pairs)


def _renderer_coverage(root, evidence, planned, candidate_cases):
    inputs = _indexed_json(root, evidence, "pair_inputs", "ocr-formula-renderer-inputs-v1")
    coverage = _indexed_json(root, evidence, "reference_coverage", "ocr-formula-renderer-coverage-v1")
    pairs, rows = inputs["pairs"], coverage["cases"]
    indexed_pairs, indexed_rows = ({row["id"]: row for row in group} for group in (pairs, rows))
    _require(len(indexed_pairs) == len(pairs) and len(indexed_rows) == len(rows)
             and indexed_pairs.keys() == indexed_rows.keys() == set(planned)
             and coverage.get("pair_inputs_sha256") == evidence["pair_inputs_sha256"],
             "Renderer coverage must bind every planned input pair exactly")
    digests = {}
    for key, pair in indexed_pairs.items():
        _require(pair.get("placement") in ("inline", "display") and _text(pair.get("reference"))
                 and (pair.get("prediction") is None or isinstance(pair["prediction"], str))
                 and pair.get("reference_format", "LATEX") == pair.get("prediction_format", "LATEX") == "LATEX",
                 "Renderer coverage requires explicit LaTeX source pairs")
        digest = hashlib.sha256(json.dumps(pair, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        row, candidate = indexed_rows[key], candidate_cases[key]
        gt, located = row["reference_tokens"], row["localized_reference_tokens"]
        _require(row.get("pair_sha256") == digest and type(gt) is int and gt > 0 and type(located) is int
                 and type(candidate.get("reference_characters")) is int
                 and located == gt == candidate["reference_characters"],
                 "Renderer reference glyph coverage is incomplete or differs between renderers")
        total, visible = row["prediction_tokens"], row["localized_prediction_tokens"]
        _require(type(total) is int and type(visible) is int and total >= visible >= 0,
                 "Invalid renderer prediction glyph counts")
        if pair.get("prediction") is None:
            _require(total == visible == 0 and type(candidate.get("prediction_characters")) is int
                     and candidate["prediction_characters"] == candidate.get("cdm_f1") == 0,
                     "Missing prediction must have no rendered glyphs and zero score")
        elif candidate.get("reason") == "PREDICTION_RENDER_FAILED":
            _require(candidate.get("prediction_error_kind") == "CONTENT_RENDER_FAILURE"
                     and candidate.get("cdm_f1") == 0,
                     "Prediction content render failure must stay in the cohort with zero score")
        else:
            _require(total > 0 and type(candidate.get("prediction_characters")) is int
                     and total == visible == candidate["prediction_characters"],
                     "Renderer prediction glyph coverage is incomplete or differs between renderers")
        digests[key] = digest
    return indexed_pairs, digests


def _renderer(policy, evidence, runtime, runtime_hash, locked_at, evidence_root):
    from .formula_cdm import PACKAGES, UNICODE_FONTS, VENDOR_MANIFEST_SHA256

    method = policy["cdm_method"]
    raster = (runtime.get("dpi"), runtime.get("antialias_bits"), runtime.get("color_tolerance_rgb"))
    fonts = runtime.get("unicode_fonts", {})
    _require(runtime.get("method") == method and runtime.get("vendor", {}).get("revision") == VENDOR_REVISION
             and runtime["vendor"].get("manifest_sha256") == VENDOR_MANIFEST_SHA256
             and all(type(value) is int for value in raster) and raster == (200, 0, 1)
             and _hash(runtime.get("adapter_sha256")) and _hash(runtime.get("python", {}).get("sha256"))
             and all(_text(runtime.get("packages", {}).get(name)) for name in PACKAGES)
             and all(_hash(runtime.get("tools", {}).get(name, {}).get("sha256"))
                     for name in ("node", "lualatex"))
             and fonts.keys() == set(UNICODE_FONTS) and all(_hash(entry.get("sha256")) for entry in fonts.values()),
             "Formula renderer runtime identity is incomplete or differs from the approved method")
    _require(evidence.get("status") == "REVIEWED" and evidence.get("partition") == "development"
             and _text(evidence.get("reviewed_by")) and _time(evidence["reviewed_at"]) <= locked_at
             and evidence.get("candidate_method") == method and evidence.get("reference_revision") == VENDOR_REVISION
             and evidence.get("runtime_sha256") == runtime_hash and _hash(evidence.get("reference_runtime_sha256"))
             and _hash(evidence.get("reference_comparison_sha256")) and _hash(evidence.get("candidate_comparison_sha256")),
             "Formula renderer validation requires reviewed development evidence for the exact runtime")
    planned, rows = evidence.get("planned_case_ids"), evidence.get("cases")
    _require(isinstance(planned, list) and planned and all(_text(key) for key in planned)
             and len(set(planned)) == len(planned) and isinstance(rows, list), "Formula renderer validation requires a frozen case list")
    original_runtime = _indexed_json(evidence_root, evidence, "reference_runtime")
    reference_engine = original_runtime.get("tex_engine")
    _require(reference_engine in ("pdflatex", "lualatex", "xelatex")
             and original_runtime.get("comparison_scope") == "INDEPENDENT_RAW_INPUT_TOKENIZE_COLOR_COMPILE_RASTER_MATCH"
             and original_runtime.get("shared_candidate_pdf_or_tex") is False,
             "Reference comparison requires an explicit compiler and independent raw-input compilation")
    _require(original_runtime.get("revision") == VENDOR_REVISION and original_runtime.get("renderer") == "ImageMagick/Ghostscript"
             and all(_hash(original_runtime.get("tools", {}).get(name, {}).get("sha256"))
                     and _text(original_runtime.get("tools", {}).get(name, {}).get("version"))
                     for name in ("imagemagick", "ghostscript", reference_engine, "node")),
             "Reference runtime identity differs from the pinned CDM revision")
    original_report = _indexed_json(evidence_root, evidence, "reference_comparison")
    from .formula_cdm import SCHEMA as cdm_schema
    candidate_report = _indexed_json(evidence_root, evidence, "candidate_comparison", cdm_schema)
    _require(candidate_report.get("method") == method and candidate_report.get("runtime_sha256") == runtime_hash,
             "Candidate comparison uses different renderer bytes")
    original_cases = original_report["details"]
    candidate_rows = candidate_report["details"]
    candidate_cases = {row["id"]: row for row in candidate_rows}
    _require(isinstance(original_cases, dict) and original_cases.keys() == candidate_cases.keys() == set(planned)
             and len(candidate_cases) == len(candidate_rows), "Both renderer reports must cover exactly the planned cases")
    input_pairs, pair_digests = _renderer_coverage(evidence_root, evidence, planned, candidate_cases)
    seen, placements = set(), set()
    for row in rows:
        key, placement = row["id"], row["placement"]
        original, candidate = row["reference_cdm_f1"], row["candidate_cdm_f1"]
        _require(key in planned and key not in seen and placement == input_pairs[key]["placement"]
                 and row.get("pair_sha256") == pair_digests[key]
                 and _number(original, 1) and _number(candidate, 1)
                 and original == original_cases[key]["F1_score"] and candidate == candidate_cases[key]["cdm_f1"]
                 and candidate_cases[key]["status"] == "MEASURED"
                 and abs(original - candidate) <= policy["maximum_cdm_pair_absolute_delta"],
                 "Formula renderer case is missing, invalid or exceeds the locked parity tolerance")
        _require(not (input_pairs[key].get("prediction") is None
                      or candidate_cases[key].get("reason") == "PREDICTION_RENDER_FAILED") or original == 0,
                 "Reference comparison must penalize a missing or failed prediction with zero score")
        seen.add(key)
        placements.add(placement)
    _require(seen == set(planned) and placements == {"inline", "display"},
             "Formula renderer validation must cover every planned case and both placements")
    return len(seen)


def verify(protocol, paths, split):
    """Check declared policy evidence without opening formula GT or predictions."""
    policy = _json(paths[POLICY_KEY], POLICY_SCHEMA)
    locked_at = _frozen_policy(protocol, policy)
    sample = _json(paths[SAMPLE_KEY], SAMPLE_SCHEMA)
    available = _sample(sample, split, read_sources(paths["data.input_manifest_sha256"]))
    schemas = ("ocr-comparison-family-v1", "ocr-absolute-thresholds-v1", "ocr-noninferiority-margins-v1", "ocr-sample-precision-plan-v1")
    statistics = [_json(paths[key], schema) for key, schema in zip(STATS_KEYS, schemas, strict=True)]
    tests = _family(policy, protocol["statistics"], *statistics, available, paths[POLICY_KEY].parent, locked_at)
    runtime_hash = protocol["runtime"]["formula_renderer_manifest_sha256"]
    cases = _renderer(policy, _json(paths[PARITY_KEY], PARITY_SCHEMA), _json(paths[RUNTIME_KEY]), runtime_hash, locked_at,
                      paths[PARITY_KEY].parent)
    return {"status": "DECLARED_FORMULA_POLICY_VERIFIED", "holdout_sample": available,
            "locked_comparisons": tests, "reviewed_development_renderer_cases": cases,
            "acceptance_status": "NOT_EVALUATED", "eligible_for_quality_acceptance": False}
