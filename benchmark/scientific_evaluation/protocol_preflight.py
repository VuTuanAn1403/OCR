"""Verify frozen benchmark inputs before holdout, without measuring quality."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

import yaml

from src.ocr.collect.catalog import ACCEPTANCE_SPLITS, SOURCE_USE_AUDIT, file_sha256, verify_company_splits
from . import formula_policy


SCHEMA = "ocr-benchmark-acceptance-proposal-v1"
REQUIRED_ARTIFACTS = (
    "scope.subgroup_manifest_sha256",
    "data.input_manifest_sha256",
    "data.split_manifest_sha256",
    "data.gt_manifest_sha256",
    "data.annotation_guideline_sha256",
    "data.adjudication_manifest_sha256",
    "data.near_duplicate_audit_sha256",
    "evaluation.projection_code_sha256",
    "evaluation.evaluator_commit_and_dirty_diff_sha256",
    "evaluation.matching_protocol_sha256",
    "thresholds.subgroup_thresholds_sha256",
    "thresholds.baseline_noninferiority_margins_sha256",
    "statistics.sample_size_and_precision_plan_sha256",
    "statistics.multiple_comparison_family_sha256",
    "review.calibrated_thresholds_sha256",
    "review.holdout_sample_sha256",
    "runtime.model_registry_sha256",
    "runtime.dependency_lock_manifest_sha256",
    "runtime.interpreter_and_hardware_manifest_sha256",
)
FIXED_FIELDS = {
    "scope.profile": "unified_gpu_full_ocr",
    "scope.ocr_source_policy": "gpu_ocr_only_v1",
    "scope.full_document_required": True,
    "data.partitions": list(ACCEPTANCE_SPLITS),
    "data.split_unit": "company_and_document",
    "evaluation.primary_artifact": "result.md",
    "evaluation.normalization": "visible_strict_v1",
    "evaluation.markdown_projection_symbol": (
        "benchmark.scientific_evaluation.markdown_evaluator._strip_markdown_for_text_evaluation"
    ),
    "evaluation.whitespace_wer_name": "WER_ws",
    "evaluation.missing_gt": "NOT_EVALUATED",
    "evaluation.missing_output": "KEEP_IN_DENOMINATOR_AND_PENALIZE",
    "evaluation.annotated_empty": "SCORE_SPURIOUS_OUTPUT_COUNTS",
    "evaluation.preserve_case_diacritics_numbers_units_and_multiplicity": True,
    "evaluation.keyword_contract": "literal_v1",
    "evaluation.source_occurrence_dispositions_required": True,
    "thresholds.status": "APPROVED",
    "statistics.cluster_unit": "company",
    "statistics.paired_comparison_required": True,
    "statistics.zero_error_population_risk_is_not_zero": True,
    "runtime.fresh_output_and_process_exit_receipts_required": True,
    "decision.acceptance_status": "NOT_EVALUATED",
}
RATIO_FIELDS = (
    "numeric_cell_exact_accuracy_minimum", "teds_content_minimum", "teds_structure_minimum",
    "penalized_reading_order_precedence_minimum", "declared_gt_evaluation_coverage_minimum",
    "automatic_acceptance_coverage_minimum", "noncritical_review_miss_rate_maximum",
)


class _UniqueKeysLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            raise ValueError("Duplicate YAML mapping keys")
        return mapping


def _field(data: dict, path: str):
    section, _, name = path.partition(".")
    fields = data.get(section)
    return fields.get(name) if isinstance(fields, dict) else None


def _number(value, *, minimum=0, maximum=None) -> bool:
    return (type(value) in (int, float) and (type(value) is int or math.isfinite(value))
            and value >= minimum and (maximum is None or value <= maximum))


def formula_scope_issues(protocol: dict, *, for_release: bool = False, for_formula_replay: bool = False) -> list[str]:
    """A free-form sentence cannot silently exclude a mandatory modality."""
    decision = _field(protocol, "scope.formula_scope_decision")
    if (not isinstance(decision, dict) or decision.keys() != {"decision", "reason"}
            or decision.get("decision") not in ("IN_SCOPE", "EXCLUDED")
            or not isinstance(decision.get("reason"), str) or not decision["reason"].strip()):
        return ["scope.formula_scope_decision: expected explicit IN_SCOPE or EXCLUDED with a nonempty reason; legacy free-form decisions require migration"]
    modalities = _field(protocol, "scope.declared_modalities")
    declared = isinstance(modalities, list) and "formulas" in modalities
    issues = []
    if decision["decision"] == "IN_SCOPE":
        if not declared:
            issues.append("scope.declared_modalities: formulas are mandatory when formula_scope_decision is IN_SCOPE")
    elif declared:
        issues.append("scope.formula_scope_decision: EXCLUDED conflicts with declared modality formulas")
    if for_release and decision["decision"] != "IN_SCOPE":
        issues.append("scope.formula_scope_decision: v7.0 release requires IN_SCOPE formula correctness")
    if for_formula_replay and decision["decision"] != "IN_SCOPE":
        issues.append("scope.formula_scope_decision: formula holdout replay requires IN_SCOPE")
    return issues


def _check_fields(protocol: dict, *, for_release: bool = False, for_formula_replay: bool = False) -> list[str]:
    issues = [f"{key}: expected {expected!r}" for key, expected in FIXED_FIELDS.items()
              if type(_field(protocol, key)) is not type(expected) or _field(protocol, key) != expected]
    for key in ("approved_by", "scope.document_population",
                "data.holdout_custodian", "data.contamination_disclosure",
                "review.calibration_unit_and_label_definition"):
        value = _field(protocol, key) if "." in key else protocol.get(key)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"{key}: required")
    try:
        locked_at = datetime.fromisoformat(protocol.get("locked_at"))
        if locked_at.utcoffset() is None:
            raise ValueError("missing timezone")
    except (TypeError, ValueError):
        issues.append("locked_at: expected a quoted ISO 8601 timestamp with timezone")
    modalities = _field(protocol, "scope.declared_modalities")
    expected_modalities = ["numeric_cells", "reading_order", "tables", "text"]
    if not isinstance(modalities, list) or any(not isinstance(item, str) for item in modalities):
        issues.append("scope.declared_modalities: expected a list of modality names")
    elif (len(set(modalities)) != len(modalities) or not set(expected_modalities) <= set(modalities)
          or set(modalities) - set(expected_modalities) - {"keywords", "layout", "formulas"}):
        issues.append(f"scope.declared_modalities: requires {expected_modalities}, optionally keywords, layout and explicitly scoped formulas")
    issues.extend(formula_scope_issues(protocol, for_release=for_release, for_formula_replay=for_formula_replay))
    if for_release and (not isinstance(modalities, list) or "keywords" not in modalities):
        issues.append("scope.declared_modalities: v7.0 release requires keyword occurrence correctness")
    for key in RATIO_FIELDS + ("micro_cer_maximum", "micro_wer_ws_maximum", "micro_der_vn_maximum"):
        # Error rates can exceed 1 due to insertions.
        ceiling = 1 if key in RATIO_FIELDS else None
        if not _number(_field(protocol, f"thresholds.{key}"), maximum=ceiling):
            issues.append(f"thresholds.{key}: missing or invalid threshold")
    for key, minimum in (("thresholds.observed_critical_numeric_errors_maximum", 0),
                         ("thresholds.critical_review_misses_maximum", 0),
                         ("statistics.minimum_independent_clusters", 2),
                         ("statistics.seed", 0), ("statistics.resamples", 1)):
        value = _field(protocol, key)
        if type(value) is not int or value < minimum:
            issues.append(f"{key}: expected an integer >= {minimum}")
    confidence = _field(protocol, "statistics.confidence_level")
    if not _number(confidence, maximum=1) or confidence in (0, 1):
        issues.append("statistics.confidence_level: expected a value strictly between 0 and 1")
    for key in ("decision.release_approval", "decision.mandatory_metric_report_sha256"):
        if _field(protocol, key) is not None:
            issues.append(f"{key}: a pre-holdout protocol cannot record a release decision or result")
    return issues


def _verify_artifacts(protocol: dict, index_path: Path, issues: list[str], extra=()) -> dict[str, Path]:
    raw = index_path.read_text(encoding="utf-8-sig")
    index = yaml.load(raw, Loader=_UniqueKeysLoader)
    required = (*REQUIRED_ARTIFACTS, *extra)
    if not isinstance(index, dict) or not set(REQUIRED_ARTIFACTS) <= index.keys() or index.keys() - set(required):
        raise ValueError("Artifact index must contain exactly the required dotted protocol keys")
    root = index_path.resolve().parent
    verified = {}
    for key in required:
        if key not in index:
            issues.append(f"{key}: missing from the artifact index")
            continue
        expected, name = _field(protocol, key), index[key]
        if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
            issues.append(f"{key}: expected a lowercase SHA-256")
            continue
        if not isinstance(name, str) or not name.strip() or Path(name).anchor:
            issues.append(f"{key}: expected a relative artifact path")
            continue
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            issues.append(f"{key}: file missing or outside the artifact index directory")
        elif file_sha256(path) != expected:
            issues.append(f"{key}: SHA-256 mismatch")
        else:
            verified[key] = path
    return verified


def preflight(protocol_path: Path, artifact_index: Path | None = None, *, for_release: bool = False,
              for_formula_replay: bool = False) -> dict:
    if for_release and for_formula_replay:
        raise ValueError("Formula replay and release preflight are separate scopes")
    raw = protocol_path.read_bytes()
    protocol = yaml.load(raw.decode("utf-8-sig"), Loader=_UniqueKeysLoader)
    if not isinstance(protocol, dict) or protocol.get("schema_version") != SCHEMA:
        raise ValueError(f"Expected schema {SCHEMA}")
    issues, verified = [], {}
    decision = _field(protocol, "scope.formula_scope_decision")
    formula_in_scope = isinstance(decision, dict) and decision.get("decision") == "IN_SCOPE"
    formula_evidence = None
    if formula_in_scope:
        formula_evidence = {"status": "NOT_EVALUATED", "required_artifacts": list(formula_policy.ARTIFACTS),
                            "missing_verified_artifacts": list(formula_policy.ARTIFACTS)}
    if protocol.get("status") != "LOCKED":
        issues.append("status: protocol must be LOCKED before holdout")
    elif artifact_index is None:
        issues.append("artifact index is required for a locked protocol")
    else:
        issues.extend(_check_fields(protocol, for_release=for_release, for_formula_replay=for_formula_replay))
        verified = _verify_artifacts(protocol, artifact_index, issues, formula_policy.ARTIFACTS if formula_in_scope else ())
        split_keys = ("data.input_manifest_sha256", "data.split_manifest_sha256", "data.near_duplicate_audit_sha256")
        locked = None
        if all(key in verified for key in split_keys):
            sources, split, audit = (verified[key] for key in split_keys)
            try:
                locked = verify_company_splits(sources, split, audit=audit)
                if locked.get("leakage_audit_schema") != SOURCE_USE_AUDIT:
                    issues.append("data.near_duplicate_audit_sha256: acceptance requires split-leakage-audit-v2 source-use evidence")
                if locked["holdout_custodian"] != _field(protocol, "data.holdout_custodian"):
                    issues.append("data.holdout_custodian: does not match splits-v2")
                for key in split_keys:
                    if file_sha256(verified[key]) != _field(protocol, key):
                        issues.append(f"{key}: changed during split verification")
                        del verified[key]
            except (OSError, ValueError, TypeError, KeyError) as exc:
                issues.append(f"splits-v2: {exc}")
        if formula_in_scope:
            evidence_keys = (*formula_policy.ARTIFACTS, *formula_policy.STATS_KEYS, *split_keys,
                             "data.adjudication_manifest_sha256")
            if (locked is not None and locked.get("leakage_audit_schema") == SOURCE_USE_AUDIT
                    and locked["holdout_custodian"] == _field(protocol, "data.holdout_custodian")
                    and all(key in verified for key in evidence_keys)):
                try:
                    checked = formula_policy.verify(protocol, verified, locked)
                    changed = [key for key in evidence_keys if file_sha256(verified[key]) != _field(protocol, key)]
                    if changed:
                        for key in changed:
                            del verified[key]
                        raise ValueError(f"Formula artifacts changed during verification: {changed}")
                    formula_evidence.update(checked)
                except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
                    issues.append(f"formula_policy: {exc}")
            formula_evidence["missing_verified_artifacts"] = [key for key in formula_policy.ARTIFACTS if key not in verified]
    return {
        "status": "INPUTS_VERIFIED" if not issues else "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT",
        "scope_context": "V70_RELEASE" if for_release else "FORMULA_HOLDOUT_REPLAY" if for_formula_replay else "COMPONENT_MEASUREMENT",
        "protocol_sha256": hashlib.sha256(raw).hexdigest(),
        "verified_artifact_hashes": {key: _field(protocol, key) for key in verified},
        "issues": issues, "quality_acceptance_status": "NOT_EVALUATED",
        "eligible_for_quality_acceptance": False,
        **({"formula_evidence": formula_evidence} if formula_evidence is not None else {}),
    }


def load_verified_protocol(protocol_path, artifact_index, verification):
    """Reopen the checked protocol and resolve artifacts by their verified bytes."""
    if verification["status"] != "INPUTS_VERIFIED":
        raise ValueError("; ".join(verification["issues"]))
    raw = protocol_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != verification["protocol_sha256"]:
        raise ValueError("Protocol changed during verification")
    protocol = yaml.load(raw.decode("utf-8-sig"), Loader=_UniqueKeysLoader)
    index = yaml.load(artifact_index.read_text(encoding="utf-8-sig"), Loader=_UniqueKeysLoader)
    root = artifact_index.resolve().parent
    hashes = verification["verified_artifact_hashes"]
    if not isinstance(index, dict) or index.keys() != hashes.keys():
        raise ValueError("Artifact index keys changed during verification")

    def path(key):
        name = index[key]
        if not isinstance(name, str) or not name.strip() or Path(name).anchor:
            raise ValueError(f"{key}: expected a relative artifact path")
        result = (root / name).resolve()
        if not result.is_relative_to(root) or file_sha256(result) != hashes[key]:
            raise ValueError(f"{key}: frozen artifact changed during verification")
        return result

    return protocol, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("--artifact-index", type=Path)
    args = parser.parse_args()
    try:
        report = preflight(args.protocol, args.artifact_index, for_release=True)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "INPUTS_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
