"""CPU alias analytics after the document worker has exited; extraction stays frozen."""
import json
from pathlib import Path

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.hashing import sha256_file
from ocr_pipeline.analysis_run import AnalysisProcessor


def selected_rules_path(path, disabled, keywords_path):
    from ocr_runtime.paths import PROJECT_ROOT, default_keywords_path, is_checkout, runtime_resource
    if disabled:
        return None
    if path is not None:
        return Path(path)
    if Path(keywords_path).resolve() != default_keywords_path().resolve():
        return None
    return PROJECT_ROOT / "config/alias_rules.json" if is_checkout() else runtime_resource("alias_rules.json")


def analytics_projection(companion, dictionary, checksum):
    if companion.get("schema_version") != "keyword-two-tier-v3":
        raise ValueError("Global alias analytics requires a v3 companion")
    return {"companion_sha256": checksum, "alias_rules_sha256": companion["alias_rules_sha256"],
            "alias_rules_snapshot_sha256": companion["alias_rules_snapshot_sha256"],
            "tier2_counts": [companion["tier2_reviewed_counts"][key] for key in dictionary["display_to_canonical"]],
            "pending_counts": [companion["pending_counts"][key] for key in dictionary["display_to_canonical"]],
            "total_tier2_canonical": companion["tier2_total_reviewed"], "total_pending_canonical": companion["total_pending"]}


def publication_material(records, dictionary, config, batch_id, revision):
    """Rebuild companion/readback evidence from the immutable prepared projection."""
    from ocr_keywords.alias_map import AliasDecision
    from ocr_keywords.tiered import build_tiered_report
    rendered, items, unknown = [], [], []
    snapshot = config.get("alias_decisions")
    decisions = None if snapshot is None else [AliasDecision.model_validate(d) for d in snapshot["decisions"]]
    for row in records:
        row = dict(row)
        rendered.append(row)
        if row.get("outcome") != "SUCCEEDED":
            unknown.append(row["id"])
            continue
        directory = Path(row["output"])
        path = directory / "keyword_two_tier.json"
        actual = json.loads(path.read_text(encoding="utf-8"))
        report = json.loads((directory / "keyword_counts.json").read_text(encoding="utf-8"))
        source = directory
        if (directory / "source.json").is_file():
            source = Path(json.loads((directory / "source.json").read_text(encoding="utf-8"))["extraction"]["source_dir"])
        expected = build_tiered_report(report, dictionary, (directory / "result.md").read_text(encoding="utf-8"),
                                      decisions=decisions, decision_snapshot=snapshot, rules=config["alias_rules"], source_dir=source)
        expected.pop("reconciled_at_utc")
        comparable = {k: v for k, v in actual.items() if k != "reconciled_at_utc"}
        if comparable != expected or analytics_projection(actual, dictionary, sha256_file(path)) != row.get("alias_analytics"):
            raise ValueError("Prepared alias analytics differ from source/rules/companion")
        row["alias_resolutions"] = actual["resolutions"]
        row["literal_citations"] = report.get("citations", [])
        items.extend(r for r in actual["resolutions"] if r["review_status"] == "NOT_EVALUATED")
    queue = {"schema_version": "new-suspicions-queue-v1", "batch_id": batch_id, "revision": revision,
             "alias_rules_sha256": config["alias_rules"]["source_sha256"], "dictionary_snapshot_hash": dictionary["snapshot_sha256"],
             "quality_acceptance": "NOT_EVALUATED", "documents_not_evaluated": unknown,
             "pending_total": None if unknown else len(items), "observed_pending_items": len(items), "items": items}
    from ocr_artifacts.digest import sha256_json_compact
    from ocr_keywords.global_rules import normalized
    variants = {}
    for item in items:
        key = item["keyword_id"], normalized(item["observed_text"])
        group = variants.setdefault(key, {"variant_id": "variant-" + sha256_json_compact(key)[:24],
            "keyword_id": key[0], "keyword": item["keyword"], "normalized_alias": key[1],
            "review_status": "NOT_EVALUATED", "occurrences": 0, "examples": []})
        group["occurrences"] += 1
        if len(group["examples"]) < 3:
            group["examples"].append({k: item[k] for k in ("document_id", "candidate_id", "page_numbers", "context")})
    queue["variants"] = [variants[key] for key in sorted(variants)]
    queue["observed_variant_count"] = len(variants)
    return rendered, queue


class AliasFinalizingProcessor:
    """Extend a CPU document finalization without another counter/model invocation."""
    def __init__(self, processor, policy):
        self.processor, self.policy = processor, policy

    def verify_existing(self, record, snapshot, output):
        self.policy.verify_decision_source()
        self.processor.verify_existing(record, snapshot, output)
        directory = Path(record["output"])
        report = json.loads((directory / "keyword_counts.json").read_text(encoding="utf-8"))
        expected = self.policy._two_tier(report, snapshot, (directory / "result.md").read_text(encoding="utf-8"), directory)
        actual = json.loads((directory / "keyword_two_tier.json").read_text(encoding="utf-8"))
        expected.pop("reconciled_at_utc")
        actual.pop("reconciled_at_utc", None)
        if actual != expected:
            raise ValueError("Two-tier companion differs from the frozen rules/source")

    def __call__(self, record, snapshot, output, **options):
        result = self.processor(record, snapshot, output, **options)
        if result.get("outcome") != "SUCCEEDED":
            return result
        self.policy.verify_decision_source()
        from ocr_pipeline.completion import clear_completed, mark_completed
        from ocr_pipeline.keyword_validation import GROUP_VALIDATORS
        directory = Path(result["output"])
        report = json.loads((directory / "keyword_counts.json").read_text(encoding="utf-8"))
        companion = self.policy._two_tier(report, snapshot, (directory / "result.md").read_text(encoding="utf-8"), directory)
        clear_completed(directory)
        atomic_write_json(directory / "keyword_two_tier.json", companion)
        mark_completed(directory, result["validation"], group_validators=GROUP_VALIDATORS)
        return {**result, "completion_sha256": sha256_file(directory / "COMPLETED.json")}
