"""Scanned-table experiment A/B/C (proposal V6 C3.5(a), review item R-10).

B is the current path: Docling on the scan page (no text layer) with empty
cells filled from OCR lines by box. A runs the same Docling options on a
derived page carrying the same OCR lines as hidden words. C (TableFormer fed
OCR tokens directly) is reported NOT_IMPLEMENTED: the bridge passes no tokens
and the docling-ibm-models API is unverified (C3.5f). A and B share one OCR
run, so only the table path differs.

Without L5 GT the comparison stays NOT_EVALUATED: counts and word/cell checks
describe behaviour, not correctness. Stopping rule (proposal): keep A only if
it beats B and C on TEDS, TEDS-S, cell-content F1 and duplicated/misplaced
words; otherwise drop A, and if nothing reaches the minimum keep scanned
tables NEEDS_REVIEW as a known limitation.

    python -m benchmark.scientific_evaluation.scan_table_experiment \
        --pdf inputs/X.pdf --pages 12,15 --output scratch/scan-tables [--font NotoSans-Regular.ttf] \
        [--ground-truth DIR]   # DIR/<document_id>_page_NNNN.tables.json: {"tables": [{"bbox", "html"}]}
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pymupdf
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.scientific_evaluation.spatial_matching import match_tables  # noqa: E402
from benchmark.scientific_evaluation.teds_metric import compute_teds, compute_teds_struct  # noqa: E402
from src.ocr.application.convert_document import ConvertDocumentUseCase  # noqa: E402
from src.ocr.cli.run_ocr import parse_pages_arg  # noqa: E402
from src.ocr.domain.models.table import TableStructure  # noqa: E402
from src.ocr.infrastructure.layout.docling_structure import DoclingStructureExtractor  # noqa: E402
from src.ocr.infrastructure.table.hidden_text_layer import (  # noqa: E402
    assign_words_to_cells, build_derived_page, font_record)
from src.ocr.runtime.atomic_io import atomic_write_json  # noqa: E402
from src.ocr.runtime.run_manifest import git_state, file_sha256  # noqa: E402
from src.ocr.runtime.config import config_hash  # noqa: E402
from src.ocr.runtime.models import model_hashes  # noqa: E402
from src.ocr.runtime.fingerprint import source_fingerprint  # noqa: E402

SCHEMA = "scan-table-experiment-v1"
SCAN_TYPES = {"SCANNED_IMAGE", "SCANNED_WITH_OCR_LAYER", "IMAGE_ONLY", "NATIVE_TEXT_LOW_QUALITY"}
_NUMBER = re.compile(r"\d")


def default_font() -> Optional[Path]:
    for candidate in (Path("C:/Windows/Fonts/NotoSans-Regular.ttf"),
                      Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
                      Path("/usr/share/fonts/noto/NotoSans-Regular.ttf")):
        if candidate.is_file():
            return candidate
    return None


def _table_summary(tables: List[Dict[str, Any]]) -> Dict[str, Any]:
    cells = [cell for table in tables for cell in table["cells"]]
    filled = [cell for cell in cells if cell["text"].strip()]
    return {"tables": len(tables), "engines": sorted({t["engine"] for t in tables}),
            "cells": len(cells), "filled_cells": len(filled),
            "numeric_cells": sum(bool(_NUMBER.search(cell["text"])) for cell in filled)}


def _table_dict(table: TableStructure) -> Dict[str, Any]:
    """Both variants are scored on HTML rendered from their final cells."""
    return {"bbox": list(table.bbox), "engine": table.engine, "num_rows": table.num_rows,
            "num_cols": table.num_cols, "html": table.to_html(),
            "cells": [{"row": c.row_idx, "col": c.col_idx, "text": c.text, "bbox": c.bbox} for c in table.cells]}


def _score(reference: Optional[List[Dict[str, Any]]], prediction: List[Dict[str, Any]]) -> Dict[str, Any]:
    if reference is None:
        return {"status": "NOT_EVALUATED", "reason": "no L5 ground truth for this page"}
    pairs = dict(match_tables(reference, [p for p in prediction if p.get("html")]))
    predicted = [p for p in prediction if p.get("html")]
    teds, teds_s = [], []
    for index, gt in enumerate(reference):
        if index in pairs:  # unmatched GT tables are MISSING_OUTPUT and score 0
            teds.append(compute_teds(gt["html"], predicted[pairs[index]]["html"]))
            teds_s.append(compute_teds_struct(gt["html"], predicted[pairs[index]]["html"]))
        else:
            teds.append(0.0)
            teds_s.append(0.0)
    return {"status": "MEASURED", "gt_tables": len(reference), "matched": len(pairs),
            "missing_output": len(reference) - len(pairs), "extra_predictions": len(predicted) - len(pairs),
            "teds_mean": sum(teds) / len(teds) if teds else None,
            "teds_struct_mean": sum(teds_s) / len(teds_s) if teds_s else None}


def _ground_truth(directory: Optional[Path], document_id: str, page: int) -> Optional[List[Dict[str, Any]]]:
    if directory is None:
        return None
    path = Path(directory) / f"{document_id}_page_{page:04d}.tables.json"
    if not path.is_file():
        return None
    return [{**table, "page": page} for table in json.loads(path.read_text(encoding="utf-8"))["tables"]]


def run(pdf: Path, pages: List[int], output: Path, *, font: Optional[Path] = None, profile: str = "balanced",
        config: Optional[str] = None, ground_truth: Optional[Path] = None,
        extractor_factory: Callable[[Dict[str, Any]], Any] = DoclingStructureExtractor) -> Dict[str, Any]:
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Experiment output must be new or empty: {output}")
    font = Path(font) if font else default_font()
    if font is None:
        raise ValueError("Variant A needs a Unicode font with Vietnamese glyphs (--font)")
    font_info = font_record(font)
    if not font_info["covers_vietnamese"]:
        raise ValueError(f"Font {font} lacks Vietnamese glyphs; hidden words would not round-trip")
    converter = ConvertDocumentUseCase(config or str(Path(__file__).resolve().parents[1] / "baselines/profiles-v61.yaml"))
    # Preserve the paired OCR evidence before tables consume their blocks.
    # Use an inspectable config file, included in the run's provenance.
    profiles = copy.deepcopy(converter.profiles)
    if profile not in profiles:
        raise ValueError(f"Unknown processing profile {profile!r}")
    profiles[profile]["retain_table_ocr_lines"] = True
    output.mkdir(parents=True, exist_ok=True)
    experiment_config = output / "experiment_profiles.yaml"
    experiment_config.write_text(yaml.safe_dump({"profiles": profiles}, allow_unicode=True), encoding="utf-8")
    converter = ConvertDocumentUseCase(str(experiment_config))
    profile_config = converter.resolve_profile(profile, "cpu")
    cache = Path(tempfile.mkdtemp(prefix="scan-table-cache-"))
    started = time.perf_counter()
    try:
        document = converter.execute(str(pdf), profile, pages=pages, output_dir=str(output / "B"),
                                     cache_dir=str(cache), assets_mode="none")
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    b_seconds = time.perf_counter() - started
    extractor = extractor_factory(profile_config.get("docling", {})) if profile_config.get("docling", {}).get(
        "enabled") else None
    records = []
    try:
        with pymupdf.open(pdf) as source:
            for page in document.pages:
                page_json = json.loads((output / "B" / document.document_id / "pages" /
                                        f"page-{page.page_num:04d}.json").read_text(encoding="utf-8"))
                reference = _ground_truth(ground_truth, document.document_id, page.page_num)
                b_tables = [_table_dict(TableStructure.model_validate(t)) for t in page_json["tables"]]
                record = {"page": page.page_num, "page_type": page.page_type.value,
                          "B": {"status": "RUN", **_table_summary(b_tables),
                                "docling": (page_json["metadata"].get("docling_structure") or {}).get("status"),
                                "quality": _score(reference, [{"page": page.page_num, **t} for t in b_tables])},
                          "C": {"status": "NOT_IMPLEMENTED",
                                "reason": "bridge passes no OCR tokens to TableFormer; direct API unverified (C3.5f)"}}
                record["A"] = _variant_a(source[page.page_num - 1], page, page_json, extractor, font, reference,
                                          output / "A")
                records.append(record)
    finally:
        if extractor is not None:
            extractor.close()
    evaluated = [r for r in records if r["A"].get("quality", {}).get("status") == "MEASURED"
                 and r["B"]["quality"]["status"] == "MEASURED"]
    result = {
        "schema": SCHEMA, "pdf": str(pdf), "pdf_sha256": file_sha256(pdf),
        "document_id": document.document_id, "pages": document.selected_pages,
        "profile": profile, "docling_options": profile_config.get("docling"),
        "font": font_info, "git": git_state(), "source_fingerprint": source_fingerprint(),
        "config": {"path": str(experiment_config), "sha256": file_sha256(experiment_config),
                   "resolved_sha256": config_hash(profile_config)},
        "models": model_hashes(profile_config),
        "b_pipeline_seconds_including_ocr": round(b_seconds, 3), "records": records,
        "pages_with_gt": len(evaluated),
        "conclusion": "NOT_EVALUATED" if len(evaluated) < 5 else "GT_MEASURED_PENDING_PROTOCOL_DECISION",
        "conclusion_rule": "Proposal C3.5(a): >=5 GT scan-table pages; keep A only if it beats B and C on "
                           "TEDS, TEDS-S, cell F1 and duplicated/misplaced words; C missing means the "
                           "comparison lacks a control and A cannot be declared best.",
    }
    atomic_write_json(output / "scan_table_experiment.json", result)
    return result


def _variant_a(source_page, page, page_json, extractor, font: Path, reference,
               artifact_dir: Optional[Path] = None) -> Dict[str, Any]:
    if page.page_type.value not in SCAN_TYPES:
        return {"status": "SKIPPED_NOT_A_SCAN_PAGE"}
    metadata = page_json["metadata"]
    if source_page.rotation or "rotate" in str(metadata.get("orientation_fallback") or ""):
        return {"status": "SKIPPED_COORDINATE_TRANSFORM_REQUIRED"}
    evidence = metadata.get("table_ocr_evidence", {})
    evidence_blocks = evidence.get("lines", page_json["blocks"])
    lines = [{"text": b["text"], "bbox": b["bbox"]} for b in evidence_blocks
             if b.get("source") in ("primary_ocr", "fallback_ocr", "image_ocr") and len(b.get("bbox") or []) == 4]
    started = time.perf_counter()
    derived, layer = None, None
    try:
        derived, words, layer = build_derived_page(source_page, lines, font)
        if layer["existing_text_chars"]:
            return {"status": "SKIPPED_EXISTING_TEXT_LAYER", "layer": layer}
        if not words:
            return {"status": "SKIPPED_NO_OCR_WORDS", "layer": layer}
        if not layer["reextraction_exact"]:
            return {"status": "FAILED_WORD_ROUND_TRIP", "layer": layer}
        if artifact_dir is not None:
            artifact_dir = Path(artifact_dir)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            derived.save(artifact_dir / f"page-{page.page_num:04d}.pdf")
        if extractor is None:
            return {"status": "SKIPPED_DOCLING_DISABLED", "layer": layer}
        result = extractor.extract_page(derived[0], page.page_num)
        tables = [_table_dict(t) for t in result["tables"]]
        record = {"status": "RUN", "seconds_layer_and_docling": round(time.perf_counter() - started, 3),
                "layer": layer, **_table_summary(tables), "word_cells": assign_words_to_cells(words, result["tables"]),
                "ocr_evidence_source": evidence.get("method", "final_blocks_legacy"),
                "docling": result.get("metadata", {}),
                "quality": _score(reference, [{"page": page.page_num, **t} for t in tables])}
        if artifact_dir is not None:
            atomic_write_json(artifact_dir / f"page-{page.page_num:04d}.json", {
                **record, "table_predictions": tables,
                "words": [{"text": w.text, "bbox": list(w.bbox), "line_index": w.line_index} for w in words]})
            record["artifacts"] = [f"A/page-{page.page_num:04d}.pdf", f"A/page-{page.page_num:04d}.json"]
        return record
    except Exception as exc:  # recorded per page; one failure must not hide the others
        return {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "layer": layer}
    finally:
        if derived is not None:
            derived.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages", required=True, help="Scan pages with tables, e.g. 12,15 (proposal: >= 5)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--font", default=None, help="Unicode TTF with Vietnamese glyphs (default: Noto Sans)")
    parser.add_argument("--profile", default="balanced")
    parser.add_argument("--config", default=None)
    parser.add_argument("--ground-truth", default=None, help="L5 GT directory (see module docstring)")
    args = parser.parse_args()
    try:
        result = run(Path(args.pdf), parse_pages_arg(args.pages), Path(args.output), font=args.font,
                     profile=args.profile, config=args.config,
                     ground_truth=Path(args.ground_truth) if args.ground_truth else None)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"conclusion": result["conclusion"], "pages": [
        {"page": r["page"], "A": r["A"]["status"], "B_tables": r["B"]["tables"],
         "A_tables": r["A"].get("tables")} for r in result["records"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
