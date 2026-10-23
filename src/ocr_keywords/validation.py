"""Validate the declared V6.3 keyword group: files, report and receipts.

The workbook itself is checked by reporting; callers compose both.
"""
import json
from pathlib import Path

from ocr_artifacts.hashing import sha256_file
from ocr_contracts.processing import KEYWORD_ARTIFACTS
from ocr_keywords.contract import validate_report


def validate_keyword_group(output, manifest):
    """Return (report, snapshot) for a declared group, None for outputs that
    declare none (legacy). A V6.3 output must declare the group."""
    contract = manifest.get("keyword_contract")
    if contract is None:
        if manifest.get("configuration", {}).get("ocr_source_policy") == "gpu_ocr_only_v1":
            raise ValueError("V6.3 keyword_contract is missing")
        return None
    if contract.get("schema_version") != "keyword-contract-v1" or contract.get("required_artifacts") != list(KEYWORD_ARTIFACTS):
        raise ValueError("Invalid keyword_contract declaration")
    output = Path(output)
    for name in KEYWORD_ARTIFACTS:
        if not (output/name).is_file():
            raise ValueError(f"Required keyword artifact missing: {name}")
    snapshot = contract["dictionary"]
    report = json.loads((output/"keyword_counts.json").read_text(encoding="utf-8"))
    validate_report(report,snapshot,output/"result.md", output.name)
    if report["selected_pages"] != manifest["selected_pages"]:
        raise ValueError("Keyword page scope differs from OCR output")
    for name in ("keyword_validation.json","keyword_receipt.json"):
        seal = json.loads((output/name).read_text(encoding="utf-8"))
        if seal.get("report_sha256") != sha256_file(output/"keyword_counts.json"):
            raise ValueError(f"{name} keyword report checksum mismatch")
        if name == "keyword_validation.json" and seal.get("status") != "PASS":
            raise ValueError("Keyword validation is not PASS")
    return report, snapshot
