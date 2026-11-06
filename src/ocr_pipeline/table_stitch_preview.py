"""Render one proposed logical table from an integrity-checked publication."""
import hashlib
import json
from pathlib import Path

from ocr_artifacts.atomic_io import atomic_write_json, atomic_write_text
from ocr_artifacts.hashing import sha256_file
from ocr_document.table_stitch import SCHEMA, project_table, render_preview_html
from ocr_pipeline.analysis_run import verify_extraction_source

PLAN_SCHEMA = "ocr-table-stitch-plan-v1"


def _load(path):
    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError(f"Duplicate JSON keys in {path.name}")
        return result

    data = path.read_bytes()
    return json.loads(data, object_pairs_hook=unique), hashlib.sha256(data).hexdigest()


def run_preview(source, plan_path, output):
    source, plan_path, output = (Path(path).resolve() for path in (source, plan_path, output))
    if (output.exists() or output.is_relative_to(source) or plan_path.is_relative_to(output)
            or any((parent / name).is_file() for parent in output.parents for name in
                   ("batch_input_manifest.json", "COMPLETED.json"))):
        raise ValueError("Table preview output must be new and outside the source publication")
    plan, plan_sha = _load(plan_path)
    fields = {"schema_version", "status", "document_id", "publication", "table_ids", "boundaries"}
    if not isinstance(plan, dict) or set(plan) != fields or plan["schema_version"] != PLAN_SCHEMA or plan["status"] != "DRAFT":
        raise ValueError("Expected a DRAFT table stitch plan with exact source pins")
    if (source / "source.json").is_file():
        raise ValueError("Table preview requires the original extraction publication")
    verified = verify_extraction_source(source)
    complete, completion_sha = _load(source / "COMPLETED.json")
    extraction, extract_sha = _load(source / "extraction.json")
    document, doc_sha = _load(source / "document.json")
    pins = {"completion_sha256": completion_sha, "extraction_sha256": extract_sha, "document_sha256": doc_sha}
    if (pins != plan["publication"] or verified["completion_sha256"] != completion_sha
            or complete["files"].get("extraction.json") != extract_sha or complete["files"].get("document.json") != doc_sha
            or extraction["doc_id"] != plan["document_id"] or document["doc_id"] != plan["document_id"]):
        raise ValueError("Table stitch plan does not match the verified document and source hashes")
    table = project_table(extraction, document, plan["table_ids"], plan["boundaries"])
    html = render_preview_html(table)
    for path, expected in ((plan_path, plan_sha), (source / "extraction.json", extract_sha),
                           (source / "document.json", doc_sha), (source / "COMPLETED.json", completion_sha),
                           (source / "ocr_receipt.json", verified["ocr_receipt_sha256"])):
        if sha256_file(path) != expected:
            raise ValueError(f"Table preview input changed: {path.name}")
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_text(output / "table.html", '<!doctype html>\n<html lang="vi">\n<head><meta charset="utf-8">'
                      '<title>Bản ghép bảng chờ rà</title></head>\n<body>\n<p>Bản ghép bảng chờ rà</p>\n'
                      + html + "</body>\n</html>\n")
    atomic_write_text(output / "table.md", html)
    result = {"schema_version": SCHEMA, "status": "DRAFT_PREVIEW", "quality_acceptance_status": "NOT_EVALUATED",
              "document_id": document["doc_id"], "doc_sha16": document["doc_sha16"], "source_directory": str(source),
              "source_artifact_hashes": {**pins, "ocr_receipt_sha256": verified["ocr_receipt_sha256"]},
              "plan_sha256": plan_sha, "table": table,
              "files": {name: sha256_file(output / name) for name in ("table.html", "table.md")}}
    atomic_write_json(output / "table-preview.json", result)
    return result
