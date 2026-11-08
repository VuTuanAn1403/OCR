"""Assemble scope-labelled QA results without pooling unrelated evidence populations."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .error_registry import validate_registry
from .evidence import EvidenceStore, is_sha, require
from .paired_effects import METRICS, SCHEMA as PAIRED_SCHEMA, summarize as summarize_pairs

SCHEMA = "ocr-qa-report-v1"
DETECTOR_METRICS = ("text_detection_recall", "text_detection_precision", "text_detection_hmean")
OTHER_METRICS = ("review_precision", "review_recall", "review_miss_rate", "review_seconds", "review_cost",
                 "runtime_throughput", "runtime_latency_p95", "runtime_peak_rss", "runtime_peak_vram", "export_completeness")


def _unavailable(metric, reason):
    return {"metric": metric, "status": "NOT_EVALUATED", "reason": reason, "scope": None, "values": None,
            "paired_effects": None}


def _pair_artifact(store, reference):
    value = store.json(reference)
    require(value.get("schema_version") == PAIRED_SCHEMA and value.get("quality_status") == "NOT_EVALUATED"
            and value.get("partition") == "holdout" and value.get("access_policy") == "AGGREGATE_ONLY",
            "Invalid paired report schema or access scope")
    store.verify(value["protocol"])
    for ref in value["evidence"]:
        store.verify(ref)
    require(value["protocol"]["sha256"] == value["preflight"]["protocol_sha256"], "Paired report protocol hash differs")
    if value["status"] == "NOT_READY":
        require(value["evidence_level"] == "PREFLIGHT_ONLY" and not value["comparisons"]
                and value["preflight"]["status"] != "INPUTS_VERIFIED", "Not-ready report cannot contain scored comparisons")
        return value
    require(value["evidence_level"] == "RECOMPUTED_CANONICAL_COUNTS" and value["preflight"]["status"] == "INPUTS_VERIFIED",
            "Displayable paired report requires canonical counts and verified inputs")
    require(set(value["preflight"]["verified_artifact_hashes"].values()) <= {ref["sha256"] for ref in value["evidence"]},
            "Paired report lacks pinned preflight artifacts")
    sample = store.json(value["sample"])
    identities = value["identities"]
    require(value["sample"]["sha256"] == identities["sample_sha256"]
            and value["protocol"]["sha256"] == identities["protocol_sha256"]
            and value["preflight"]["verified_artifact_hashes"]["data.gt_manifest_sha256"] == identities["gt_sha256"],
            "Paired report does not bind the exact sample, GT and protocol")
    expected = summarize_pairs(sample, value["count_inputs"]["baseline"], value["count_inputs"]["candidate"])
    require(all(value.get(key) == item for key, item in expected.items() if key != "evidence_level"),
            "Paired report arithmetic, identity or coverage does not replay")
    return value


def _counter_value(rows, side):
    measured = [(row, row[side + "_count"]) for row in rows if row[side + "_count"]["status"] != "NOT_EVALUATED"]
    numerator = sum(value["numerator"] for _, value in measured) if measured else None
    denominator = sum(value["denominator"] for _, value in measured) if measured else None
    complete = bool(rows) and len(rows) == len(measured)
    status = "MEASURED" if complete and denominator else "PARTIAL" if measured and not complete else "NOT_EVALUATED"
    return {"status": status, "reason": None if status == "MEASURED" else "INCOMPLETE_SCOPE" if not complete else "ZERO_REFERENCE_DENOMINATOR",
            "numerator": numerator, "denominator": denominator, "value": numerator / denominator if status == "MEASURED" else None,
            "declared_units": len(rows), "scored_units": len(measured),
            "documents_with_scored_units": len({(row["document_id"], row["pdf_sha256"]) for row, _ in measured}) if measured else None,
            "pages_with_scored_units": len({(row["document_id"], row["pdf_sha256"], row["page"]) for row, _ in measured}) if measured else None,
            "missing_output_units": sum(row[side + "_missing"] for row in rows)}


def _paired_metrics(source, reference):
    result = {}
    for metric, comparison in source["comparisons"].items():
        sides = {side: _counter_value(comparison["units"], side) for side in ("baseline", "candidate")}
        statuses = {value["status"] for value in sides.values()}
        status = "MEASURED" if statuses == {"MEASURED"} else "PARTIAL" if statuses & {"MEASURED", "PARTIAL"} else "NOT_EVALUATED"
        result[metric] = {"metric": metric, "status": status, "reason": None if status == "MEASURED" else "PAIR_HAS_UNSCORED_OR_ZERO_REFERENCE_SCOPE",
                          "scope": {"partition": "holdout", "sample_sha256": source["identities"]["sample_sha256"],
                                    "definition": source["identities"]["normalization"], "kind": "paired_canonical_counts",
                                    "protocol_sha256": source["identities"]["protocol_sha256"], "gt_sha256": source["identities"]["gt_sha256"],
                                    "prediction_inventory_sha256": source["identities"]["prediction_inventory_sha256"],
                                    "runs": source["runs"]},
                          "source_sha256": reference["sha256"], "values": sides,
                          "paired_effects": {"rule": comparison["rule"], **comparison["overall"]}}
    return result


def _detector_metrics(store, args):
    from benchmark.scientific_evaluation import text_detection_metric as detector

    require(args.detector_gt is not None and args.detector_extraction is not None,
            "Detector report needs source GT and extraction paths")
    reference = store.ref(args.detector_report)
    source = store.json(reference)
    require(source.get("protocol") == "extraction-structure-diagnostic-v1"
            and source.get("eligible_for_quality_acceptance") is False and is_sha(source.get("ground_truth_sha256")),
            "Unsupported detector source report")
    gt_ref = store.ref(args.detector_gt, source["ground_truth_sha256"])
    gt = store.json(gt_ref)
    require(gt.get("schema_version") == "structured-page-gt-v1" and is_sha(gt.get("pdf_sha256"))
            and gt["pdf_sha256"] == source["pdf_sha256"], "Detector GT and report PDF identity differ")
    path = args.detector_extraction.resolve()
    require(path.is_relative_to(store.root) and path.name == "extraction.json" and path.parent.name == gt["document_id"],
            "Detector extraction is outside its evidence root or document identity")
    checksum = source["extraction_sha256"]
    if checksum is None:
        require(not path.exists(), "Detector report claims missing extraction but output exists")
        extraction = {"pages": []}
    else:
        extraction = store.json(store.ref(path, checksum))
        require(extraction["doc_id"] == gt["document_id"] and extraction["doc_sha16"] == gt["pdf_sha256"][:16],
                "Detector extraction and GT differ")
    pages = {page["page"]: page for page in extraction["pages"]}
    require(len(pages) == len(extraction["pages"]), "Duplicate detector extraction page")
    recorded = [row for row in source["pages"] if "text_detection" in row]
    expected = {row["page"]: row["text_detection"] for row in recorded}
    require(len(expected) == len(recorded), "Duplicate detector report page")
    replayed, seen = {}, set()
    for annotation in gt["pages"]:
        page = annotation["page"]
        require(type(page) is int and 1 <= page <= gt["total_pages"] and page not in seen, "Invalid detector page scope")
        seen.add(page)
        if annotation.get("text_detection") is None:
            continue
        predicted = pages.get(page)
        require(predicted is None or (annotation["coordinate_space"], annotation["transforms"]) ==
                (predicted["coordinate_space"], predicted["transforms"]), "Detector source frames differ")
        src_path = path.parent / "pages" / f"page-{page:04d}.json"
        artifact = store.ref(src_path) if src_path.is_file() else None
        record = detector.evaluate_page(annotation["text_detection"], store.json(artifact) if artifact else None,
                                        predicted, gt["text_detection_matching"])
        record["page_artifact_sha256"] = artifact["sha256"] if artifact else None
        replayed[page] = record
    aggregate = detector.summarize(list(replayed.values()))
    require(replayed == expected and aggregate == source["text_detection"], "Detector source counts or coverage do not replay")
    values = {}
    for metric, key in zip(DETECTOR_METRICS, ("recall", "precision", "hmean")):
        counts = aggregate["counts"]
        numerator = denominator = None
        if counts is not None:
            tp, fp, fn = (counts[k] for k in ("tp", "fp", "fn"))
            numerator, denominator = (tp, tp + fn) if key == "recall" else (tp, tp + fp) if key == "precision" else (2 * tp, 2 * tp + fp + fn)
        status = "MEASURED" if aggregate[key] is not None else "NOT_EVALUATED"
        reason = None if status == "MEASURED" else "ZERO_REFERENCE_DENOMINATOR" if denominator == 0 else aggregate["status"]
        values[metric] = {"metric": metric, "status": status, "reason": reason,
                          "scope": {"partition": gt.get("intended_partition"), "kind": "primary_detector_diagnostic",
                                    "definition": aggregate["protocol"], "gt_sha256": gt_ref["sha256"], "extraction_sha256": checksum},
                          "source_sha256": reference["sha256"], "paired_effects": None,
                          "values": {"diagnostic": {"status": status, "value": aggregate[key], "numerator": numerator,
                                                    "denominator": denominator, "declared_units": aggregate["declared_pages"],
                                                    "scored_units": aggregate["measured_pages"],
                                                    "observed_counts": aggregate["observed_counts"]}}}
    return reference, values


def _registry(store, reference, *, include_details):
    source = store.json(reference)
    validation = validate_registry(source, store)
    latest = {row["error_id"]: row for row in source["records"]}
    findings = []
    for record in latest.values():
        if not include_details or record["origin"]["kind"] != "operator_review" or record["expected"]["kind"] == "INDEPENDENT_GT":
            continue
        packet = store.json(record["evidence"]["review_packet"])
        if packet.get("usage") != "development_operator_review" or packet.get("contains_predictions") is not True:
            continue
        findings.append({"error_id": record["error_id"], "error_codes": record["error_codes"],
                         "finding_kind": record["finding_kind"], "historical": record["historical"],
                         "lifecycle": record["lifecycle"], "severity": record["severity"], "source": record["source"],
                         "actual": record["actual"], "crop": record["crop"], "review_reasons": record["observation"]["reasons"],
                         "root_cause_status": "DECLARED_WITH_EVIDENCE" if record["root_cause"] is not None else "UNVERIFIED"})
    documents = {(record["source"]["document_id"], record["source"]["pdf_sha256"]) for record in latest.values()
                 if record["source"]["document_id"] is not None}
    pages = {(record["source"]["document_id"], record["source"]["pdf_sha256"], record["source"]["page"]) for record in latest.values()
             if record["source"]["page"] is not None}
    return {"snapshot_sha256": validation["snapshot_sha256"], "record_revisions": validation["record_revisions"],
            "distinct_findings": validation["distinct_findings"], "finding_kinds": validation["finding_kinds"],
            "lifecycle_counts": validation["lifecycle_counts"], "source_documents_with_findings": len(documents),
            "source_pages_with_findings": len(pages), "development_details_included": len(findings), "findings": findings}


def build_report(args):
    store = EvidenceStore(args.evidence_root)
    sources, registry, paired = {}, None, None
    metrics = {metric: _unavailable(metric, "NO_PAIRED_REPORT") for metric in sorted(METRICS)}
    metrics.update({metric: _unavailable(metric, "NO_PRIMARY_DETECTOR_REPORT") for metric in DETECTOR_METRICS})
    metrics.update({metric: _unavailable(metric, "NO_VERIFIED_ADAPTER_INPUT") for metric in OTHER_METRICS})
    if args.registry is not None:
        sources["registry"] = store.ref(args.registry)
        registry = _registry(store, sources["registry"], include_details=args.include_development_details)
    if args.paired is not None:
        sources["paired"] = store.ref(args.paired)
        source = _pair_artifact(store, sources["paired"])
        paired = {"status": source["status"], "evidence_level": source["evidence_level"], "partition": "holdout",
                  "access_policy": "AGGREGATE_ONLY", "preflight_status": source["preflight"]["status"],
                  "protocol_sha256": source["protocol"]["sha256"], "readiness_issue_count": len(source["preflight"].get("issues", [])),
                  "verified_artifact_hashes": source["preflight"]["verified_artifact_hashes"]}
        metrics.update({metric: _unavailable(metric, "PREFLIGHT_NOT_READY" if source["status"] == "NOT_READY" else "METRIC_NOT_IN_FROZEN_SAMPLE")
                        for metric in METRICS})
        metrics.update(_paired_metrics(source, sources["paired"]))
    if args.detector_report is not None:
        sources["detector"], detector = _detector_metrics(store, args)
        metrics.update(detector)
    require(sources, "Supply at least one registry, paired or detector source")
    store.verify_all()
    return {"schema_version": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "REPORT_READY", "quality_status": "NOT_EVALUATED", "quality_acceptance": False,
            "source_verification": "EVIDENCE_HASHES_AND_ADAPTER_REPLAY", "sources": sources,
            "registry": registry, "paired": paired, "metrics": metrics,
            "metric_states": dict(Counter(metric["status"] for metric in metrics.values())),
            "population": {"documents_evaluated_overall": None, "pages_evaluated_overall": None,
                           "reason": "SEPARATE_METRIC_SCOPES_ARE_NOT_A_SINGLE_POPULATION"}}
