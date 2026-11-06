"""One literal counter, separate canonical phrases and ordered display rows."""
import hashlib
from pathlib import Path
import unicodedata
from datetime import datetime, timezone

from ocr_artifacts.digest import sha256_json_compact
from ocr_contracts.processing import KEYWORD_SCHEMA, POLICY, POLICY_VERSION
from ocr_keywords.counter import KeywordCounter
from ocr_keywords.citations import SCHEMA as CITATION_SCHEMA, build_citations


# Kept under its historical name for callers of this module.
digest = sha256_json_compact
DEFAULT_KEYWORD_SET_VERSION = "v1"
V1_REVISED_DISPLAY_SHA256 = "e3cf6e249b46960e306990d23bb38e5e6ef9210b43c27af55762d2299c169717"


def dictionary_snapshot(path, version=None):
    version = version or DEFAULT_KEYWORD_SET_VERSION
    raw = Path(path).read_bytes()
    display = [unicodedata.normalize("NFC", line.strip()) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
    if not display:
        raise ValueError("Empty keyword dictionary")
    if len(display) > 16383:
        raise ValueError("Keyword columns exceed XLSX capacity")
    canonical, mapping = [], []
    by_key = {}
    for phrase in display:
        key = phrase.casefold()
        if key not in by_key:
            by_key[key] = "kw-" + hashlib.sha256(key.encode()).hexdigest()[:16]
            canonical.append({"id": by_key[key], "keyword": phrase})
        mapping.append(by_key[key])
    revised_v1 = (len(display) == 86 and len(canonical) == 86 and digest(display) == V1_REVISED_DISPLAY_SHA256)
    if version == "v1" and not ((len(display), len(canonical)) == (88, 87) or revised_v1):
        raise ValueError("Keyword v1 requires 88 display/87 canonical originally, or the approved 86/86 user list")
    result = {"schema_version": "keyword-dictionary-v1", "keyword_set_version": version,
              "source_sha256": hashlib.sha256(raw).hexdigest(), "canonical_keywords": canonical,
              "display_columns": display, "display_to_canonical": mapping}
    if version == "v1" and revised_v1:
        result["keyword_set_revision"] = "2026-11-06"
    result["snapshot_sha256"] = digest(result)
    return result


def validate_snapshot(snapshot):
    payload = {k:v for k,v in snapshot.items() if k!="snapshot_sha256"}
    if digest(payload) != snapshot.get("snapshot_sha256"):
        raise ValueError("Dictionary snapshot checksum mismatch")
    canonical = snapshot["canonical_keywords"]
    by_id = {r["id"]:r["keyword"].casefold() for r in canonical}
    if len(by_id) != len(canonical) or len(snapshot["display_columns"]) != len(snapshot["display_to_canonical"]):
        raise ValueError("Invalid dictionary mapping")
    if any(by_id.get(ref) != word.casefold() for ref,word in zip(snapshot["display_to_canonical"],snapshot["display_columns"])):
        raise ValueError("Display phrase mapped to another keyword")


def keyword_identity(text_path, snapshot):
    return {"result_md_sha256": hashlib.sha256(Path(text_path).read_bytes()).hexdigest(),
            "dictionary_sha256": snapshot["snapshot_sha256"], "counting_policy": POLICY,
            "counting_version": POLICY_VERSION}


def count_report(doc_id, pdf_sha256, text_path, snapshot, pages, *, citation_source_dir=None):
    identity = keyword_identity(text_path, snapshot)
    report = KeywordCounter.count_keywords(Path(text_path).read_text(encoding="utf-8-sig"),
        [r["keyword"] for r in snapshot["canonical_keywords"]], doc_id, str(text_path))
    counts = {row["id"]: count.count for row, count in zip(snapshot["canonical_keywords"], report.keywords)}
    display = [counts[ref] for ref in snapshot["display_to_canonical"]]
    context, citations = build_citations(Path(text_path).read_text(encoding="utf-8-sig"), snapshot, pages,
                                         source_dir=citation_source_dir or Path(text_path).parent)
    return {"schema_version": KEYWORD_SCHEMA, "document_id": doc_id, "pdf_sha256": pdf_sha256,
            "source_file": str(text_path), "identity": identity, "selected_pages": pages,
            "counted_at_utc":datetime.now(timezone.utc).isoformat(),
            "keyword_set_version": snapshot["keyword_set_version"], "canonical_counts": counts,
            "display_counts": display, "total_canonical_matches": sum(counts.values()),
            "total_display_matches": sum(display),
            **({"keyword_set_revision": snapshot["keyword_set_revision"]} if "keyword_set_revision" in snapshot else {}),
            "citation_schema_version": CITATION_SCHEMA,
            "citation_context": context, "citations": citations}


def validate_report(report, snapshot, text_path, doc_id=None, pdf_sha256=None, *, citation_source_dir=None):
    validate_snapshot(snapshot)
    if (report.get("schema_version") != KEYWORD_SCHEMA or report.get("identity") != keyword_identity(text_path, snapshot)
            or doc_id is not None and report.get("document_id") != doc_id
            or pdf_sha256 is not None and report.get("pdf_sha256") != pdf_sha256):
        raise ValueError("Keyword report identity/schema mismatch")
    if (report.get("keyword_set_version") != snapshot["keyword_set_version"]
            or report.get("keyword_set_revision") != snapshot.get("keyword_set_revision")):
        raise ValueError("Keyword report dictionary version/revision mismatch")
    counts = report.get("canonical_counts", {})
    if set(counts) != {row["id"] for row in snapshot["canonical_keywords"]}:
        raise ValueError("Missing or extra canonical keyword")
    if any(type(n) is not int or n < 0 for n in counts.values()):
        raise ValueError("Counts must be non-negative integers")
    expected = [counts[key] for key in snapshot["display_to_canonical"]]
    if (any(type(n) is not int or n < 0 for n in report.get("display_counts",[]))
            or any(type(report.get(k)) is not int for k in ("total_canonical_matches","total_display_matches"))
            or report.get("display_counts") != expected or report.get("total_canonical_matches") != sum(counts.values())
            or report.get("total_display_matches") != sum(expected)):
        raise ValueError("Keyword mapping/totals mismatch")
    if "citation_schema_version" in report:
        if report["citation_schema_version"] != CITATION_SCHEMA:
            raise ValueError("Unknown keyword citation schema")
        context, citations = build_citations(Path(text_path).read_text(encoding="utf-8-sig"), snapshot, report["selected_pages"],
                                             source_dir=citation_source_dir or Path(text_path).parent)
        if (digest(context) != digest(report.get("citation_context"))
                or digest(citations) != digest(report.get("citations"))):
            raise ValueError("Keyword citations differ from the exact counted source or page provenance")
        citation_counts = {key: 0 for key in counts}
        for citation in citations:
            citation_counts[citation["keyword_id"]] += 1
        if citation_counts != counts:
            raise ValueError("Keyword citations do not reconcile with canonical counts")
    return True
