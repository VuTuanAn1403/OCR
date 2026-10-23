"""Analysis run: count keywords on verified extraction without running OCR (P11a).

Sources are V6.3 document outputs (a batch directory or single documents) or
documents of an earlier analysis run. Each source is verified read-only; its
`result.md` is copied byte for byte into a new output, counted with the run's
dictionary and published through the same prepare -> publish -> read back ->
acknowledge gate as an OCR batch. Sources are never written. The run records
where each document came from and never claims inference of its own.
"""
from __future__ import annotations

import json
from pathlib import Path
import unicodedata
from zipfile import BadZipFile

from ocr_artifacts.atomic_io import atomic_write_bytes, atomic_write_json
from ocr_artifacts.hashing import sha256_file as sha256
from ocr_contracts.processing import IdentityMismatch, PublicationError
from ocr_keywords.contract import count_report, validate_report
from ocr_reporting.workbooks import export_document, verify_document
from ocr_runtime import fingerprint

SOURCE_SCHEMA = "analysis-source-v1"
RUN_MODE = "analysis_run_v1"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


_DOCUMENT_MARKERS = ("result.md", "manifest.json", "source.json", "ocr_receipt.json", "COMPLETED.json")


def _looks_like_document(path: Path) -> bool:
    return any((path / name).is_file() for name in _DOCUMENT_MARKERS)


def _key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _expected_documents(source: Path):
    """(doc_id, directory, batch record) of every document the source must hold.

    A batch directory lists its documents in batch_input_manifest.json, so a
    document whose output is damaged or deleted still has a row. Without a
    manifest, a directory holding document outputs is a set of documents and
    any other directory is one standalone document (failing verification).
    """
    manifest = source / "batch_input_manifest.json"
    if manifest.is_file():
        return [(r["id"], source / r["id"], r) for r in read(manifest)["documents"]]
    parent_manifest = source.parent / "batch_input_manifest.json"
    if _looks_like_document(source):
        siblings = {r["id"]: r for r in read(parent_manifest)["documents"]} if parent_manifest.is_file() else {}
        return [(source.name, source, siblings.get(source.name, {}))]
    documents = sorted((p for p in source.iterdir() if p.is_dir() and _looks_like_document(p)),
                       key=lambda p: _key(p.name))
    return [(p.name, p, {}) for p in documents] or [(source.name, source, {})]


def discover_sources(paths) -> list[dict]:
    """Snapshot records, one per expected source document, in stable order.

    Missing outputs become records with `source_error`; they are published
    as FAILED_DOCUMENT with no counts, never dropped (P11a item 7).
    """
    records, seen = [], {}
    for source in paths:
        source = Path(source).resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Analysis source not found: {source}")
        for doc_id, directory, original in _expected_documents(source):
            if _key(doc_id) in seen:
                raise ValueError(f"Colliding document ID {doc_id} in {directory} and {seen[_key(doc_id)]}")
            seen[_key(doc_id)] = directory
            text = directory / "result.md"
            error = (f"Document output directory missing: {directory}" if not directory.is_dir()
                     else f"result.md missing in {directory}" if not text.is_file() else None)
            pdf_sha256 = original.get("pdf_sha256")
            if pdf_sha256 is None and error is None:
                for name in ("source.json", "keyword_counts.json"):
                    if (directory / name).is_file():
                        try:
                            pdf_sha256 = read(directory / name).get("pdf_sha256")
                        except (OSError, ValueError):
                            pass
                        break
            records.append({"id": doc_id, "name": original.get("name", f"{doc_id}.pdf"),
                            "path": original.get("path", str(directory)), "pdf_sha256": pdf_sha256,
                            "size": original.get("size"), "source_dir": str(directory),
                            "input_path": str(text), "input_sha256": None if error else sha256(text),
                            "source_error": error, "total_pages": original.get("total_pages"),
                            "source_review": original.get("source_review", "NOT_EVALUATED"),
                            "duplicate_of": original.get("duplicate_of"), "counts": None})
    if len(records) > 1048574:
        raise ValueError("Input snapshot exceeds XLSX row capacity")
    return records


def verify_extraction_source(directory: Path) -> dict:
    """Integrity and GPU-source checks of a V6.3 extraction output."""
    from ocr_pipeline.document import manifest_ocr_hash, ocr_files, validate_gpu_source
    from ocr_pipeline.completion import verify_completed
    from ocr_document.validation import validate_document
    if not verify_completed(directory):
        raise ValueError("Completion marker missing or artifacts changed")
    receipt = read(directory / "ocr_receipt.json")
    if receipt.get("files") != ocr_files(directory) or receipt.get("manifest_ocr_sha256") != manifest_ocr_hash(directory):
        raise ValueError("OCR receipt does not match the extraction artifacts")
    validate_gpu_source(directory)
    validation = validate_document(directory, skip_groups=True)
    if validation["status"] == "FAIL":
        raise ValueError(f"Document artifacts fail validation: {validation['errors'][:3]}")
    manifest = read(directory / "manifest.json")
    return {"kind": "extraction", "source_dir": str(directory), "ocr_identity": receipt.get("ocr_identity"),
            "pipeline_version": manifest.get("pipeline_version"), "selected_pages": manifest["selected_pages"],
            "total_pages": manifest["total_pages"], "validation": validation["status"],
            "result_md_sha256": sha256(directory / "result.md"),
            "manifest_ocr_sha256": receipt["manifest_ocr_sha256"],
            "ocr_receipt_sha256": sha256(directory / "ocr_receipt.json"),
            "completion_sha256": sha256(directory / "COMPLETED.json"),
            "inference_by_this_run": False}


def verify_source(directory: Path) -> dict:
    directory = Path(directory)
    if not (directory / "source.json").is_file():
        return verify_extraction_source(directory)
    from ocr_pipeline.completion import verify_completed
    if not verify_completed(directory):
        raise ValueError("Completion marker missing or artifacts changed")
    source = read(directory / "source.json")
    counted = sha256(directory / "result.md")
    if source.get("schema_version") != SOURCE_SCHEMA or source.get("result_md_sha256") != counted:
        raise ValueError("Analysis source record is invalid or does not match result.md")
    # Never trust the recorded provenance: verify the original extraction again
    # and bind it to the exact text counted here (review F01).
    claimed = source.get("extraction") or {}
    origin = Path(claimed["source_dir"]) if claimed.get("source_dir") else None
    if origin is None or not origin.is_dir():
        raise ValueError(f"Extraction evidence of this analysis source is unavailable: {claimed.get('source_dir')}")
    verified = verify_extraction_source(origin)
    if verified["result_md_sha256"] != counted:
        raise ValueError("Counted result.md is not the result.md of the verified extraction")
    for key in ("ocr_identity", "manifest_ocr_sha256", "ocr_receipt_sha256"):
        if claimed.get(key) != verified[key]:
            raise ValueError(f"Extraction changed since the earlier analysis run ({key})")
    return {**verified, "via_analysis_run": [*source.get("via_analysis_run", []), str(directory)]}


def _reusable_report(source_dir: Path, analysis: str, snapshot, text_path, doc_id, pdf_sha256):
    try:
        receipt = read(source_dir / "keyword_receipt.json")
        if receipt.get("analysis_fingerprint") != analysis or receipt["report_sha256"] != sha256(source_dir / "keyword_counts.json"):
            return None
        report = read(source_dir / "keyword_counts.json")
        validate_report(report, snapshot, text_path, doc_id, pdf_sha256)
        return report
    except (OSError, ValueError, KeyError, TypeError):
        return None


class AnalysisProcessor:
    """`process_batch` processor that imports instead of running OCR."""

    def __init__(self):
        self.counted, self.reused = [], []

    def __call__(self, record, snapshot, output, *, resume, force_ocr, max_attempts=2):
        from ocr_pipeline.completion import clear_completed, mark_completed
        source_dir, out = Path(record["source_dir"]), Path(output) / record["id"]
        try:
            provenance = verify_source(source_dir)
        except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
            # A damaged read-only source is a document failure, not infrastructure.
            raise ValueError(f"Analysis source rejected: {type(exc).__name__}: {exc}") from exc
        if provenance["result_md_sha256"] != record["input_sha256"]:
            raise IdentityMismatch(f"INPUT_CHANGED: {record['input_path']}")
        clear_completed(out)
        out.mkdir(parents=True, exist_ok=True)
        text = (source_dir / "result.md").read_bytes()
        atomic_write_bytes(out / "result.md", text)
        analysis = fingerprint.code_fingerprints()["analysis"]
        report = _reusable_report(source_dir, analysis, snapshot, out / "result.md", record["id"], record["pdf_sha256"])
        origin = "reused" if report is not None else "counted"
        if report is None:
            report = count_report(record["id"], record["pdf_sha256"], out / "result.md", snapshot,
                                  provenance["selected_pages"])
            self.counted.append(record["id"])
        else:
            self.reused.append(record["id"])
        atomic_write_json(out / "keyword_counts.json", report)
        report_sha = sha256(out / "keyword_counts.json")
        atomic_write_json(out / "keyword_receipt.json", {"report_sha256": report_sha, "identity": report["identity"],
                                                         "analysis_fingerprint": analysis})
        try:
            try:
                verify_document(out / "count_keywords.xlsx", report, snapshot)
            except (OSError, ValueError, KeyError, BadZipFile):
                export_document(report, snapshot, out)
        except OSError as exc:
            raise PublicationError(f"Per-document Excel cannot be published: {exc}") from exc
        validate_report(report, snapshot, out / "result.md", record["id"], record["pdf_sha256"])
        atomic_write_json(out / "keyword_validation.json", {"schema_version": "keyword-validation-v1",
                                                            "status": "PASS", "report_sha256": report_sha})
        atomic_write_json(out / "source.json", {
            "schema_version": SOURCE_SCHEMA, "document_id": record["id"], "pdf_sha256": record["pdf_sha256"],
            "result_md_sha256": sha256(out / "result.md"), "extraction": {k: v for k, v in provenance.items()
                                                                         if k != "via_analysis_run"},
            "via_analysis_run": provenance.get("via_analysis_run", []), "imported_from": str(source_dir),
            "report_origin": origin, "analysis_fingerprint": analysis})
        mark_completed(out, provenance["validation"])
        return {"outcome": "SUCCEEDED", "output": str(out), "report_sha256": report_sha,
                "completion_sha256": sha256(out / "COMPLETED.json"), "validation": provenance["validation"]}


def run_analysis(sources, output, keywords_path, *, keyword_set_version="v1", resume=False,
                 retry_failed=False, processor=None):
    from ocr_pipeline.batch import process_batch
    sources = [Path(s).resolve() for s in sources]
    output = Path(output).resolve()
    for source in sources:
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError(f"Analysis output must be separate from its sources: {output} / {source}")
    pinned = {k: v for k, v in fingerprint.code_fingerprints().items() if k != "extraction"}

    def identity_check():
        current = {k: v for k, v in fingerprint.code_fingerprints().items() if k != "extraction"}
        if current != pinned:
            raise IdentityMismatch("Analysis or publication code changed during the analysis run")

    config = {"mode": RUN_MODE, "sources": [str(s) for s in sources], "keyword_set_version": keyword_set_version,
              "counting_policy": "literal_v1", "code_fingerprints": pinned}
    return process_batch(sources[0], output, config, keywords_path, processor or AnalysisProcessor(),
                         resume=resume, retry_failed=retry_failed, identity_check=identity_check,
                         snapshot_inputs=lambda _: discover_sources(sources))
