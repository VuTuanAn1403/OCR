from __future__ import annotations

import csv
import hashlib
import io
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from src.ocr.runtime.atomic_io import atomic_write_json, atomic_write_text

FIELDS = ("document_id", "relative_path", "company_id", "company_name", "exchange", "year", "industry", "size",
          "dbi_object", "language", "source_url", "collected_at", "sha256", "pages", "encrypted", "copy_restricted",
          "status", "error")
# sources-v1 inventories lack the C2.0 name/exchange/language columns; they
# read as "unknown" rather than being rejected.
V1_FIELDS = tuple(field for field in FIELDS if field not in ("company_name", "exchange", "language"))
# Supplied by the person verifying the source, never inferred from the file name.
SUPPLIED_FIELDS = ("company_name", "exchange", "year", "industry", "size", "dbi_object", "language",
                   "source_url", "collected_at")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def company_id(value) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip().casefold() == "unknown":
        return "unknown"
    result = unicodedata.normalize("NFC", value).strip().casefold()
    if any(c.isspace() for c in result):
        raise ValueError("company_id must be a stable identifier, not a company display name")
    return result


def collect_sources(root: Path, output: Path, metadata: dict | None = None) -> list[dict]:
    root, output = Path(root).resolve(), Path(output)
    if not root.is_dir():
        raise ValueError("Source root must be a directory")
    metadata = metadata or {}
    rows, identifiers, first_by_hash = [], set(), {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.casefold() == ".pdf"):
        relative = path.relative_to(root).as_posix()
        if path.stem.casefold() in identifiers:
            raise ValueError(f"Duplicate document stem {path.stem}; runtime document IDs would collide")
        identifiers.add(path.stem.casefold())
        info = metadata.get(relative, {})
        if not isinstance(info, dict):
            raise ValueError(f"Metadata for {relative} must be a mapping")
        row = {key: "unknown" for key in FIELDS}
        for key in SUPPLIED_FIELDS:
            value = info.get(key)
            if value is not None:
                row[key] = str(value)
        row.update(document_id=path.stem, relative_path=relative, company_id=company_id(info.get("company_id")),
                   sha256=file_sha256(path), status="OK", error="")
        first = first_by_hash.setdefault(row["sha256"], path.stem)
        if first != path.stem:
            # Kept in the inventory so the copy is visible; drafts skip non-OK rows.
            rows.append({**row, "status": "DUPLICATE", "error": f"Same SHA-256 as {first}"})
            continue
        try:
            with pymupdf.open(path) as doc:
                row["pages"] = doc.page_count
                row["encrypted"] = bool(doc.is_encrypted or doc.needs_pass)
                row["copy_restricted"] = not bool(doc.permissions & pymupdf.PDF_PERM_COPY)
                if doc.needs_pass:
                    row.update(status="PASSWORD_REQUIRED", error="Source needs a password; no annotation pages prepared")
        except Exception as exc:
            row.update(status="UNREADABLE", error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
    if not rows:
        raise ValueError("No PDFs found")
    content = io.StringIO(newline="")
    writer = csv.DictWriter(content, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(output, content.getvalue())
    # Several distinct PDFs for one verified company and year may be amended
    # reports; listed for the curator, not resolved automatically.
    editions: dict = {}
    for row in rows:
        if row["status"] == "OK" and "unknown" not in (row["company_id"], row["year"]):
            editions.setdefault(f"{row['company_id']}|{row['year']}", []).append(row["document_id"])
    atomic_write_json(output.with_suffix(".catalog.json"), {
        "schema_version": "sources-v2", "source_root": str(root), "sources_sha256": file_sha256(output),
        "generated_at": datetime.now(timezone.utc).isoformat(), "documents": len(rows),
        "unknown_company_documents": sum(row["company_id"] == "unknown" for row in rows),
        "duplicate_documents": [row["document_id"] for row in rows if row["status"] == "DUPLICATE"],
        "revision_candidates": {key: ids for key, ids in sorted(editions.items()) if len(ids) > 1},
        "status": "METADATA_INCOMPLETE" if any(row["company_id"] == "unknown" for row in rows) else "COLLECTED",
        "annotation_status": "NOT_EVALUATED",
    })
    return rows


def read_sources(path: Path) -> list[dict]:
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(V1_FIELDS) <= set(reader.fieldnames or []):
            raise ValueError("Source inventory is missing required columns")
        rows = [{key: "unknown" for key in FIELDS} | row for row in reader]
    if not rows or len({row["document_id"].casefold() for row in rows}) != len(rows):
        raise ValueError("Source inventory is empty or contains duplicate document IDs")
    for row in rows:
        row["company_id"] = company_id(row["company_id"])
        if len(row["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in row["sha256"]):
            raise ValueError("Source SHA-256 is invalid")
        relative = Path(row["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Source paths must be relative to source_root")
        if row["document_id"] != relative.stem or row["document_id"] in (".", ".."):
            raise ValueError("document_id must match the source filename stem")
    return rows


def lock_company_splits(sources: Path, assignments: dict, output: Path) -> dict:
    rows = read_sources(sources)
    if set(assignments) != {"train", "dev", "test"}:
        raise ValueError("Assignments must declare train, dev and test")
    assignment, normalized = {}, {}
    for split in ("train", "dev", "test"):
        if not isinstance(assignments[split], list):
            raise ValueError("Each split must be a list of company IDs")
        normalized[split] = []
        for value in assignments[split]:
            company = company_id(value)
            if company == "unknown" or company in assignment:
                raise ValueError("Unknown/duplicate company or leakage across splits")
            assignment[company] = split
            normalized[split].append(company)
        normalized[split].sort()
    if set(assignment) != {row["company_id"] for row in rows} or "unknown" in assignment:
        raise ValueError("Every source requires verified company_id and exactly one company split")
    if any(not normalized[split] for split in normalized):
        raise ValueError("Each train/dev/test split needs at least one verified company")
    hash_owners = {}
    documents = []
    for row in rows:
        owner = hash_owners.setdefault(row["sha256"], row["company_id"])
        if owner != row["company_id"]:
            raise ValueError("Identical PDF content is attributed to different companies")
        documents.append({key: row[key] for key in ("document_id", "company_id", "sha256", "relative_path")})
        documents[-1]["split"] = assignment[row["company_id"]]
    snapshot = {"schema_version": "splits-v1", "locked": True, "companies": normalized,
                "sources_sha256": file_sha256(sources), "documents": documents}
    output = Path(output)
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous != snapshot:
            raise ValueError("Locked splits are immutable; create a new versioned split file")
        return previous
    atomic_write_json(output, snapshot)
    return snapshot


def prepare_gt_drafts(sources: Path, splits: Path, output: Path, *, pages: int = 50, seed: int = 42,
                      source_root: Path | None = None) -> dict:
    """Create unannotated draft files with .pending suffixes, never valid GT."""
    import random
    if type(pages) is not int or pages < 1:
        raise ValueError("Pilot page count must be positive")
    locked = json.loads(Path(splits).read_text(encoding="utf-8"))
    if locked.get("schema_version") != "splits-v1" or locked.get("locked") is not True:
        raise ValueError("A locked splits-v1 file is required before annotation")
    # Revalidate membership and inventory checksum, not merely the locked flag.
    expected = lock_company_splits(sources, locked["companies"], Path(splits))
    if expected != locked:
        raise ValueError("Split inventory changed")
    rows = read_sources(sources)
    docs = {item["document_id"]: item for item in locked["documents"]}
    from collections import defaultdict, Counter
    from src.ocr.infrastructure.pdf.pdf_inspector import PDFInspector
    catalog = Path(sources).with_suffix(".catalog.json")
    if source_root is None and catalog.is_file():
        source_root = Path(json.loads(catalog.read_text(encoding="utf-8"))["source_root"])
    if source_root is None:
        raise ValueError("source_root is required for stratified pilot sampling")
    source_root = Path(source_root).resolve()
    strata, seen = defaultdict(list), set()
    for row in rows:
        if row["status"] != "OK" or row["sha256"] in seen or docs[row["document_id"]]["split"] == "test":
            continue
        seen.add(row["sha256"])
        pdf = (source_root / row["relative_path"]).resolve()
        if not pdf.is_relative_to(source_root) or file_sha256(pdf) != row["sha256"]:
            raise ValueError("Source PDF changed or leaves source_root")
        with pymupdf.open(pdf) as document:
            inspector = PDFInspector(document)
            for page in range(1, document.page_count + 1):
                meta = inspector.inspect_page(page)
                kind = ("scan_with_ocr_layer_candidate" if meta.get("has_hidden_ocr_layer") else
                        "native" if meta["char_count"] >= 30 and not meta["has_images"] else
                        "mixed" if meta["char_count"] >= 30 else "scan_or_image")
                dpi = None
                for image in document[page-1].get_image_info():
                    matrix = image["transform"]
                    physical = (matrix[0]**2+matrix[1]**2)**.5
                    if physical > 0:
                        value = 72*image["width"]/physical
                        dpi = value if dpi is None else min(dpi, value)
                group = "native_or_unknown" if dpi is None else "low" if dpi <= 100 else "medium" if dpi <= 150 else "high"
                key = (row["company_id"], row["industry"], row["size"], row["year"], kind, group)
                strata[key].append((row, page, key))
    rng = random.Random(seed)
    keys = sorted(strata)
    rng.shuffle(keys)
    for values in strata.values():
        rng.shuffle(values)
    selected = []
    while len(selected) < pages and any(strata.values()):
        for key in keys:
            if strata[key] and len(selected) < pages:
                selected.append(strata[key].pop())
    selected.sort(key=lambda item: (item[0]["document_id"], item[1]))
    output = Path(output)
    if (output / "pilot_drafts.json").exists():
        raise ValueError("Drafts already exist; do not overwrite manual annotation")
    records = []
    for row, page, stratum in selected:
        directory = output / "drafts" / row["document_id"] / f"page-{page:04d}"
        directory.mkdir(parents=True, exist_ok=True)
        atomic_write_text(directory / "text.txt.pending", "")
        atomic_write_json(directory / "layout.json.pending", {"status": "UNANNOTATED", "boxes": [], "ignore": []})
        atomic_write_json(directory / "structure.json.pending", {"status": "UNANNOTATED", "sections": []})
        atomic_write_text(directory / "tables.html.pending", "")
        records.append({"document_id": row["document_id"], "company_id": row["company_id"], "page": page,
                        "pdf_sha256": row["sha256"], "split": docs[row["document_id"]]["split"],
                        "draft_directory": directory.relative_to(output).as_posix(), "stratum": list(stratum),
                        "status": "UNANNOTATED"})
    result = {"schema_version": "pilot-drafts-v1", "seed": seed, "requested_pages": pages,
              "selected_pages": len(records), "sampling": "balanced_round_robin_dev_train_strata",
              "strata_source": "supplied_company_metadata_and_pdf_inspector_heuristics_not_GT",
              "strata_counts": dict(Counter("|".join(record["stratum"]) for record in records)),
              "sources_sha256": file_sha256(sources), "splits_sha256": file_sha256(splits),
              "annotation_status": "UNANNOTATED", "eligible_for_acceptance": False, "records": records}
    atomic_write_json(output / "pilot_drafts.json", result)
    return result
