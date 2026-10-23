"""Keyword finalization of one accepted document (analysis closure, P11a).

Counts `result.md` with the batch dictionary, writes the keyword group and
the per-document workbook, then seals the document with its completion
marker. The keyword receipt records the analysis code fingerprint; an existing
report is reused only when that code is unchanged.
"""
import json
from pathlib import Path
from zipfile import BadZipFile

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.hashing import sha256_file as sha256
from ocr_contracts.processing import KEYWORD_ARTIFACTS, PublicationError
from ocr_keywords.contract import count_report, validate_report
from ocr_reporting.workbooks import export_document, verify_document
from ocr_runtime.fingerprint import code_fingerprints


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def finalize_keywords(output, snapshot, pdf_sha256):
    from ocr_pipeline.completion import clear_completed, mark_completed
    from ocr_pipeline.artifact_validation import validate_document_artifacts
    from ocr_pipeline.keyword_validation import GROUP_VALIDATORS
    output = Path(output)
    analysis = code_fingerprints()["analysis"]
    clear_completed(output)
    manifest = read(output/"manifest.json")
    manifest["keyword_contract"] = {"schema_version":"keyword-contract-v1", "required_artifacts":list(KEYWORD_ARTIFACTS),
                                    "dictionary":snapshot}
    atomic_write_json(output/"manifest.json",manifest)
    text_path = output/"result.md"
    report_path = output/"keyword_counts.json"
    try:
        seal = read(output/"keyword_receipt.json")
        if seal["report_sha256"] != sha256(report_path):
            raise ValueError("Keyword report hash mismatch")
        if seal.get("analysis_fingerprint") != analysis:
            raise ValueError("Keyword report was counted by other keyword code")
        report = read(report_path)
        validate_report(report, snapshot, text_path, output.name, pdf_sha256)
    except (OSError, ValueError, KeyError, TypeError):
        report = count_report(output.name, pdf_sha256, text_path, snapshot, manifest["selected_pages"])
        atomic_write_json(report_path,report)
        atomic_write_json(output/"keyword_receipt.json", {"report_sha256":sha256(report_path),"identity":report["identity"],
                                                         "analysis_fingerprint":analysis})
    # XLSX failure propagates as infrastructure failure, never a blank-row PDF error.
    try:
        try:
            verify_document(output/"count_keywords.xlsx", report, snapshot)
        except (OSError, ValueError, KeyError, BadZipFile):
            export_document(report,snapshot,output)
    except OSError as exc:
        raise PublicationError(f"Per-document Excel cannot be published: {exc}") from exc
    validate_report(report,snapshot,text_path,output.name,pdf_sha256)
    atomic_write_json(output/"keyword_validation.json", {"schema_version":"keyword-validation-v1", "status":"PASS",
                                                       "report_sha256":sha256(report_path)})
    result = validate_document_artifacts(output)
    if result["status"] == "FAIL":
        raise ValueError(f"Final artifact contract failed: {result['errors'][:3]}")
    mark_completed(output,result["status"],group_validators=GROUP_VALIDATORS)
    return {"outcome":"SUCCEEDED","output":str(output),"report_sha256":sha256(report_path),
            "completion_sha256":sha256(output/"COMPLETED.json"),"validation":result["status"]}
