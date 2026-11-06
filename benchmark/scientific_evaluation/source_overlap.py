"""Produce a read-only pair review worklist for benchmark source leakage."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import unicodedata

import numpy as np
from PIL import Image
import pymupdf

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.hashing import sha256_file
from src.ocr.collect.catalog import read_sources

from .canonical_predictions import collect_predictions


THUMBNAIL_EDGE = 160
LAYOUT_GRID = 24
SHINGLE_SIZE = 4
MIN_TEXT_SHINGLES = 20
MIN_SHARED_SHINGLES = 8
ASPECT_TOLERANCE = 1.1
TOP_PAGES = 3
WORDS = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class PageSignature:
    page: int
    aspect: float
    layout: np.ndarray | None
    raster_sha256: str | None
    shingles: frozenset[tuple[str, ...]]
    render_warnings: int
    native_text_warnings: int


def _shingles(lines) -> frozenset[tuple[str, ...]]:
    shingles = set()
    for line in lines:
        words = WORDS.findall(unicodedata.normalize("NFC", line.casefold()))
        shingles.update(zip(*(words[offset:] for offset in range(SHINGLE_SIZE))))
    return frozenset(shingles)


def _signature(page, lines) -> PageSignature:
    width, height = page.rect.width, page.rect.height
    scale = THUMBNAIL_EDGE / max(width, height)
    raster = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY, alpha=False)
    render_warnings = len(pymupdf.TOOLS.mupdf_warnings().splitlines())
    native_text_warnings = 0
    if lines is None:
        lines = page.get_text("text").splitlines()
        native_text_warnings = len(pymupdf.TOOLS.mupdf_warnings().splitlines())
        if render_warnings or native_text_warnings:
            lines = []
    pixels = raster.samples
    thumbnail = Image.frombytes("L", (raster.width, raster.height), pixels)
    layout = np.asarray(thumbnail.resize((LAYOUT_GRID, LAYOUT_GRID), Image.Resampling.BOX), dtype=np.float32).ravel()
    layout -= layout.mean()
    norm = np.linalg.norm(layout)
    # Exclude flat pages and repaired raster content from visual comparisons.
    usable = not render_warnings and norm / LAYOUT_GRID >= 2
    fingerprint = hashlib.sha256(f"{raster.width}x{raster.height}:".encode() + pixels).hexdigest() if usable else None
    return PageSignature(page.number + 1, width / height, layout / norm if usable else None,
                         fingerprint, _shingles(lines), render_warnings, native_text_warnings)


def _recorded_lines(publication: dict, row: dict) -> tuple[dict, str]:
    doc_id = row["document_id"]
    if (publication["pdf_sha256"], publication["total_pages"]) != (row["sha256"], int(row["pages"])):
        raise ValueError(f"Canonical PDF identity differs for {doc_id}")
    directory = Path(publication["source_dir"])
    receipt_bytes = (directory / "ocr_receipt.json").read_bytes()
    extraction_bytes = (directory / "extraction.json").read_bytes()
    extraction_hash = hashlib.sha256(extraction_bytes).hexdigest()
    if (hashlib.sha256(receipt_bytes).hexdigest() != publication["ocr_receipt_sha256"]
            or json.loads(receipt_bytes)["files"]["extraction.json"] != extraction_hash):
        raise ValueError(f"Canonical extraction changed for {doc_id}")
    extraction = json.loads(extraction_bytes)
    page_rows = extraction["pages"]
    lines = {page["page"]: [item["text_raw"] for item in page.get("text_evidence", {}).get("items", [])]
             for page in page_rows}
    if (extraction["doc_id"], extraction["doc_sha16"]) != (doc_id, row["sha256"][:16]) or (
        len(lines) != len(page_rows) or lines.keys() != set(range(1, int(row["pages"]) + 1))
    ):
        raise ValueError(f"Canonical extraction coverage or identity differs for {doc_id}")
    return lines, extraction_hash


def _document(source_root: Path, row: dict, publication: dict | None) -> tuple[dict, list[PageSignature]]:
    doc_id = row["document_id"]
    pdf = (source_root / row["relative_path"]).resolve()
    if not pdf.is_relative_to(source_root) or sha256_file(pdf) != row["sha256"]:
        raise ValueError(f"Source PDF path or hash differs for {doc_id}")
    recorded, extraction_hash = _recorded_lines(publication, row) if publication is not None else (None, None)
    with pymupdf.open(pdf) as document:
        if not document.is_pdf or document.needs_pass or document.page_count != int(row["pages"]):
            raise ValueError(f"Source PDF cannot be read with its inventory page count for {doc_id}")
        pages = []
        for index in range(document.page_count):
            pymupdf.TOOLS.mupdf_warnings()
            pages.append(_signature(document.load_page(index), recorded[index + 1] if recorded is not None else None))
    if sha256_file(pdf) != row["sha256"]:
        raise ValueError(f"Source PDF changed during review for {doc_id}")
    return {"document_id": doc_id, "pdf_sha256": row["sha256"], "pages": len(pages),
            "relative_path": row["relative_path"], "company_id": row["company_id"],
            "company_name": row["company_name"], "extraction_sha256": extraction_hash,
            "ocr_receipt_sha256": publication["ocr_receipt_sha256"] if publication is not None else None,
            "visual_pages": sum(page.layout is not None for page in pages),
            "render_warning_pages": {str(page.page): page.render_warnings for page in pages if page.render_warnings},
            "native_text_warning_pages": {str(page.page): page.native_text_warnings for page in pages
                                          if page.native_text_warnings},
            "text_pages": sum(len(page.shingles) >= MIN_TEXT_SHINGLES for page in pages)}, pages


def _compare_pages(left: list[PageSignature], right: list[PageSignature]) -> dict:
    text_matches, raster_matches = [], []
    for a in left:
        for b in right:
            if a.raster_sha256 is not None and a.raster_sha256 == b.raster_sha256:
                raster_matches.append({"pages": [a.page, b.page], "sha256": a.raster_sha256})
            if len(a.shingles) < MIN_TEXT_SHINGLES or len(b.shingles) < MIN_TEXT_SHINGLES:
                continue
            shared = len(a.shingles & b.shingles)
            if shared >= MIN_SHARED_SHINGLES:
                text_matches.append({"pages": [a.page, b.page], "shared_shingles": shared,
                                     "jaccard": shared / (len(a.shingles) + len(b.shingles) - shared)})
    left_layout = [page for page in left if page.layout is not None]
    right_layout = [page for page in right if page.layout is not None]
    layout_matches = []
    if left_layout and right_layout:
        left_vectors = np.stack([page.layout for page in left_layout])
        right_vectors = np.stack([page.layout for page in right_layout])
        scores = np.clip(left_vectors @ right_vectors.T, -1, 1)
        layout_matches = [
            {"pages": [a.page, b.page], "cosine": round(float(scores[i, j]), 6)}
            for i, a in enumerate(left_layout) for j, b in enumerate(right_layout)
            if max(a.aspect, b.aspect) <= min(a.aspect, b.aspect) * ASPECT_TOLERANCE
        ]
    return {
        "exact_thumbnail_matches": raster_matches,
        "layout_candidates": sorted(layout_matches, key=lambda row: (-row["cosine"], row["pages"]))[:TOP_PAGES],
        "layout_page_pairs_compared": len(layout_matches),
        "text_candidates": sorted(text_matches, key=lambda row: (-row["jaccard"], -row["shared_shingles"],
                                                                 row["pages"]))[:TOP_PAGES],
        "text_page_pairs_eligible": sum(len(page.shingles) >= MIN_TEXT_SHINGLES for page in left)
        * sum(len(page.shingles) >= MIN_TEXT_SHINGLES for page in right),
    }


def _known_issuer(value: str) -> str | None:
    name = " ".join(unicodedata.normalize("NFC", value.casefold()).split())
    return name if name not in {"", "unknown"} else None


def review_worklist(sources: Path, source_root: Path, canonical_batches: list[Path]) -> dict:
    source_hash = sha256_file(sources)
    rows = sorted(read_sources(sources), key=lambda row: row["document_id"])
    if len(rows) < 2 or any(row["status"] not in {"OK", "DUPLICATE"} for row in rows):
        raise ValueError("Worklist requires at least two PDFs with usable page inventories")
    originals = {row["sha256"]: row["pages"] for row in rows if row["status"] == "OK"}
    for row in rows:
        if row["status"] == "DUPLICATE" and row["pages"] == "unknown":
            row["pages"] = originals.get(row["sha256"], "unknown")
        if not row["pages"].isascii() or not row["pages"].isdigit() or int(row["pages"]) < 1:
            raise ValueError(f"Missing usable inventory page count for {row['document_id']}")
    inventory = collect_predictions(canonical_batches) if canonical_batches else None
    publications = {row["id"]: row for row in inventory["documents"]} if inventory else {}
    if inventory and publications.keys() != {row["document_id"] for row in rows}:
        raise ValueError("Canonical batch and source inventory membership differ")
    root = source_root.resolve()
    documents = [_document(root, row, publications.get(row["document_id"])) for row in rows]
    pairs = []
    for (a, left), (b, right) in combinations(documents, 2):
        issuer_a = _known_issuer(a["company_name"])
        issuer_b = _known_issuer(b["company_name"])
        pairs.append({"documents": [a["document_id"], b["document_id"]],
                      "same_issuer_name": issuer_a == issuer_b if issuer_a and issuer_b else None,
                      "identical_pdf_bytes": a["pdf_sha256"] == b["pdf_sha256"],
                      **_compare_pages(left, right), "template_relation": None, "near_duplicate_relation": None,
                      "review_reason": None, "reviewed_by": None, "reviewed_at": None})
    if sha256_file(sources) != source_hash:
        raise ValueError("Source inventory changed during review")
    return {"schema_version": "ocr-source-overlap-worklist-v1", "status": "DRAFT_FOR_CURATOR",
            "split_acceptance": "NOT_EVALUATED", "sources_sha256": source_hash,
            "pymupdf_version": pymupdf.VersionBind,
            "canonical_batches": [{key: batch[key] for key in ("batch_id", "published_revision")}
                                  for batch in inventory["batches"]] if inventory else [],
            "method": {"text_source": "frozen_ocr_lines" if inventory else "native_pdf_lines",
                       "shingle_size": SHINGLE_SIZE, "min_text_shingles": MIN_TEXT_SHINGLES,
                       "min_shared_shingles": MIN_SHARED_SHINGLES, "thumbnail_long_edge_px": THUMBNAIL_EDGE,
                       "layout_grid": LAYOUT_GRID, "layout_aspect_ratio_limit": ASPECT_TOLERANCE,
                       "top_page_pairs_per_signal": TOP_PAGES},
            "documents": [record for record, _ in documents], "pairs": pairs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--canonical-batch", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report_path = args.report.resolve()
        if report_path.exists() or any(report_path.is_relative_to(path.resolve()) for path in (
            args.source_root, *args.canonical_batch,
        )):
            raise ValueError("Use a new report path outside input and batch directories")
        report = review_worklist(args.sources, args.source_root, args.canonical_batch)
        atomic_write_json(args.report, report)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        parser.exit(2, f"Source overlap worklist rejected: {exc}\n")
    print(f"DRAFT_FOR_CURATOR: {len(report['documents'])} PDFs, {len(report['pairs'])} pairs. {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
