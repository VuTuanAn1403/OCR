"""Export image-backed operator review packets from verified extraction outputs."""
from __future__ import annotations

from collections import Counter
import hashlib
import heapq
import json
import math
from pathlib import Path
import re

import pymupdf

from ocr_artifacts.atomic_io import atomic_write_bytes, atomic_write_json, atomic_write_text
from ocr_artifacts.hashing import sha256_file
from ocr_document.source_identity import valid_bbox
from ocr_keywords.contract import dictionary_snapshot
from ocr_keywords.counter import KeywordCounter
from ocr_pdf_io.document_view import processing_pdf
from ocr_pipeline.analysis_run import discover_sources, read, verify_source
from ocr_text.numeric_guard import preserves_numeric_evidence, protected_numeric_spans
from ocr_text.vietnamese_diacritics import diacritic_suspicions


LOOKALIKE = re.compile(r"(?<!\w)[o0]2[o0](?!\w)", re.IGNORECASE)


def _lookalike_spans(text):
    matches = list(LOOKALIKE.finditer(text))
    if not matches:
        return []
    numeric_ranges = [(start, end) for start, end in protected_numeric_spans(text)
                      if sum(char.isdigit() for char in text[start:end]) > 3]
    spans = []
    for match in matches:
        start, end = match.span()
        larger_numeric_span = next(([left, right] for left, right in numeric_ranges if left <= start and end <= right), None)
        spans.append({"token": match.group(), "start": start, "end": end, "larger_numeric_span": larger_numeric_span})
    return spans


def _candidate(document_id, pdf_hash, page, value, locator, frozen, keywords):
    raw = value.get("text_raw", value.get("text", ""))
    text = value.get("text_corrected", value.get("text", raw))
    reasons = list(value.get("review_reason_codes") or [])
    if value.get("review_reason"):
        reasons.append(value["review_reason"])
    if value.get("needs_review") is not False:
        reasons.append("extraction_review_required")
    if frozen.get("fallback_reason") and not frozen.get("reviewed"):
        reasons.append(frozen["fallback_reason"])
    reasons.extend(diacritic_suspicions(text, extra_phrases=keywords))
    corrected_spans = _lookalike_spans(text)
    lookalikes = [span["token"] for span in corrected_spans if span["larger_numeric_span"] is None]
    if lookalikes:
        reasons.append("O2O_020_source_check")
    if not reasons:
        return None
    source_id = value.get("source_id", frozen.get("source_id"))
    identity = {"document_id": document_id, "pdf_sha256": pdf_hash, "page": page["page"],
                "source_id": source_id, "locator": locator}
    review_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    matches = [{"keyword": key, "start": start, "end": end}
               for key, start, end in KeywordCounter.iter_occurrences(text, keywords)]
    proposal = (frozen.get("recognition_provenance") or {}).get("repetition", {}).get("candidate_text")
    return {"review_id": review_id, **identity, "text_raw": raw,
            "text_corrected": text, "bbox": value.get("bbox", []), "bbox_source": value.get("bbox_source"),
            "coordinate_space": page["coordinate_space"], "transforms": page["transforms"],
            "page_width": page["width"], "page_height": page["height"],
            "confidence": value.get("confidence"), "confidence_source": value.get("confidence_source", "unavailable"),
            "quality_score": value.get("quality_score"),
            "recognition_provenance": value.get("recognition_provenance", frozen.get("recognition_provenance", {})),
            "reasons": list(dict.fromkeys(reasons)), "keyword_matches": matches,
            "keyword_offsets_space": "text_corrected_nfc_casefold", "lookalike_tokens": lookalikes,
            "lookalike_spans": {"text_raw": corrected_spans if raw == text else _lookalike_spans(raw or ""),
                                "text_corrected": corrected_spans},
            "proposal": proposal, "proposal_preserves_numbers": None if proposal is None
                else preserves_numeric_evidence(text, proposal),
            "priority": 0 if lookalikes else 1 if matches else 2, "review_status": "UNREVIEWED"}


def page_candidates(document_id, pdf_hash, page, keywords):
    frozen = {row["source_id"]: row for row in (page.get("text_evidence") or {}).get("items", [])}
    seen = set()
    layout_reasons = {}
    for issue in page.get("layout_review") or []:
        for item_id in issue.get("item_ids", []):
            layout_reasons.setdefault(item_id, []).append(issue["code"])

    def reason_codes(value):
        return [*(value.get("review_reason_codes") or []),
                *(code for key in (value.get("source_id"), value.get("id"))
                  for code in layout_reasons.get(key, []))]

    for item in page["items"]:
        source_id = item.get("source_id")
        seen.add(source_id)
        original = frozen.get(source_id, {})
        value = {**item, "review_reason_codes": reason_codes(item)}
        candidate = _candidate(document_id, pdf_hash, page, value, {"item_id": item["id"]}, original, keywords)
        if candidate is not None:
            yield candidate
        for cell in item.get("cells", []):
            locator = {"item_id": item["id"], "row": cell["row"], "col": cell["col"]}
            value = {**cell, "source_id": source_id}
            candidate = _candidate(document_id, pdf_hash, page, value, locator, {}, keywords)
            if candidate is not None:
                yield candidate
    for source_id, original in frozen.items():
        if source_id not in seen:
            value = {**original, "needs_review": bool(original.get("fallback_reason")) and not original.get("reviewed"),
                     "review_reason_codes": reason_codes(original)}
            candidate = _candidate(document_id, pdf_hash, page, value, {"frozen_source_id": source_id}, original, keywords)
            if candidate is not None:
                yield candidate


def _crop(document, row, output, dpi=200):
    page = document[row["page"] - 1]
    rotation = page.rotation
    try:
        transforms = row["transforms"]
        if row["coordinate_space"] == "pdf_points_top_left_rotated" and len(transforms) == 1:
            step = transforms[0]
            if step.get("op") != "rotate" or step.get("degrees") not in (90, 180, 270):
                return {"status": "UNAVAILABLE", "reason": "unsupported_page_transform"}
            page.set_rotation((rotation + step["degrees"]) % 360)
        elif row["coordinate_space"] != "pdf_points_top_left" or transforms:
            return {"status": "UNAVAILABLE", "reason": "unsupported_page_transform"}
        if (abs(page.rect.width - row["page_width"]) > .2
                or abs(page.rect.height - row["page_height"]) > .2):
            return {"status": "UNAVAILABLE", "reason": "page_dimensions_differ"}
        if not valid_bbox(row["bbox"]):
            return {"status": "UNAVAILABLE", "reason": "unplaced_source"}
        box = pymupdf.Rect(row["bbox"]) & page.rect
        if box.is_empty:
            return {"status": "UNAVAILABLE", "reason": "source_outside_page"}
        assets = {}
        for name, padding in (("target", 2), ("context", 20)):
            clip = (box + (-padding, -padding, padding, padding)) & page.rect
            scale = min(dpi / 72, math.sqrt(4_000_000 / clip.get_area()))
            pymupdf.TOOLS.mupdf_warnings()
            image = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
            warnings = pymupdf.TOOLS.mupdf_warnings().splitlines()
            path = output / "images" / f"{row['review_id']}-{name}.png"
            atomic_write_bytes(path, image.tobytes("png"))
            assets[name] = {"path": path.relative_to(output).as_posix(), "sha256": sha256_file(path),
                            "bbox": list(clip), "scale": scale, "width": image.width, "height": image.height,
                            "render_warnings": warnings}
        return {"status": "AVAILABLE_WITH_WARNINGS" if any(asset["render_warnings"] for asset in assets.values())
                else "AVAILABLE", "assets": assets}
    finally:
        page.set_rotation(rotation)


def _markdown(rows, total, offset):
    lines = ["# Gói rà OCR từ ảnh nguồn", "", f"Có {len(rows)} mục trong gói, từ vị trí {offset} của {total} ứng viên.",
             "", "Gói này có chữ OCR và đề xuất để người vận hành rà. Bộ nhãn GT A/B độc lập dùng gói ảnh nguồn riêng.",
             "Điền phiếu trong annotations.template.json, gồm bản chép sau kiểm và thời gian review thực đo.",
             "Các vị trí keyword là match literal trên chữ OCR của mục này. Căn occurrence với Markdown cần đối soát riêng.", ""]
    for row in rows:
        lines.extend([f"## {row['review_id']}", "", f"Trang vật lý {row['page']}", ""])
        keyword_context = [f"{match['keyword']} [{match['start']}, {match['end']})" for match in row["keyword_matches"]]
        lookalike_context = []
        for field, spans in row["lookalike_spans"].items():
            for span in spans:
                location = f"{field} [{span['start']}, {span['end']})"
                fragment = span["larger_numeric_span"]
                detail = f"trong cụm số {row[field][slice(*fragment)]}" if fragment else "cần đối chiếu ảnh"
                lookalike_context.append(f"{span['token']} {location} · {detail}")
        for value in (row["document_id"], row["source_id"] or "Nguồn chưa có source ID",
                      json.dumps(row["locator"], ensure_ascii=False), *row["reasons"],
                      "Keyword literal trong chữ xuất", *keyword_context, *lookalike_context,
                      "Chữ thô", row["text_raw"], "Chữ xuất", row["text_corrected"], "Đề xuất", row["proposal"] or ""):
            lines.extend("    " + line for line in str(value).splitlines())
            lines.append("")
        for asset in (row["crop"].get("assets") or {}).values():
            lines.extend([f"![Ảnh nguồn]({asset['path']})", ""])
        if row["crop"]["status"] == "UNAVAILABLE":
            lines.extend([f"Ảnh chưa đặt được. {row['crop']['reason']}", ""])
        if row["bbox_source"] == "table_fallback":
            lines.extend(["Vị trí ở cấp bảng. Cần xác định ô trên ảnh.", ""])
        if row["crop"]["status"] == "AVAILABLE_WITH_WARNINGS":
            lines.extend(["Ảnh có cảnh báo render. Cần kiểm nguyên trang.", ""])
    return "\n".join(lines)


def run_review(sources, output, keywords_path, *, limit=100, offset=0, keyword_set_version=None):
    sources = [Path(source).resolve() for source in sources]
    output = Path(output).resolve()
    if type(limit) is not int or type(offset) is not int or limit < 1 or offset < 0:
        raise ValueError("Review limit must be positive and offset nonnegative")
    if not sources or output.exists() or any(output.is_relative_to(source) or source.is_relative_to(output) for source in sources):
        raise ValueError("Review requires a new output outside its sources")
    snapshot = dictionary_snapshot(keywords_path, keyword_set_version)
    keywords = [row["keyword"] for row in snapshot["canonical_keywords"]]
    records = discover_sources(sources)
    output.mkdir(parents=True)
    totals = Counter()
    origins = {}

    def candidates(stream):
        for record in records:
            provenance = verify_source(Path(record["source_dir"]))
            origin = Path(provenance["source_dir"])
            manifest = read(origin / "manifest.json")
            keyword_report = read(origin / "keyword_counts.json")
            pdf_hash = keyword_report["pdf_sha256"]
            extraction_path = origin / "extraction.json"
            raw = extraction_path.read_bytes()
            checksum = hashlib.sha256(raw).hexdigest()
            if checksum != read(origin / "ocr_receipt.json")["files"]["extraction.json"]:
                raise ValueError("Extraction changed after source verification")
            extraction = json.loads(raw)
            if (extraction["doc_id"], extraction["doc_sha16"]) != (record["id"], pdf_hash[:16]):
                raise ValueError("Review source document identity differs")
            pdf = Path(manifest.get("file_path") or record["path"])
            if sha256_file(pdf) != pdf_hash:
                raise ValueError("Review source PDF bytes differ from the verified output")
            origins[record["id"]] = {"pdf_path": str(pdf), "pdf_sha256": pdf_hash,
                "render_policy": manifest["configuration"].get("pdf_render_policy", "original_v1"), "source_dir": str(origin),
                "extraction_sha256": checksum, "completion_sha256": provenance["completion_sha256"],
                "ocr_receipt_sha256": provenance["ocr_receipt_sha256"]}
            totals[record["id"]] = 0
            for page in extraction["pages"]:
                for row in page_candidates(record["id"], pdf_hash, page, keywords):
                    totals[record["id"]] += 1
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    yield row

    try:
        with (output / "queue.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            selected = heapq.nsmallest(offset + limit, candidates(stream), key=lambda row: (
                row["priority"], row["document_id"], row["page"], row["review_id"]))[offset:]
        for document_id in dict.fromkeys(row["document_id"] for row in selected):
            origin = origins[document_id]
            with processing_pdf(origin["pdf_path"], origin["render_policy"], expected_sha256=origin["pdf_sha256"]) as (pdf, view):
                for row in selected:
                    if row["document_id"] == document_id:
                        row["crop"] = _crop(pdf, row, output)
                        row["processing_view"] = view
        for origin in origins.values():
            directory = Path(origin["source_dir"])
            for name, key in (("COMPLETED.json", "completion_sha256"), ("ocr_receipt.json", "ocr_receipt_sha256"),
                              ("extraction.json", "extraction_sha256")):
                if sha256_file(directory / name) != origin[key]:
                    raise ValueError("Source changed while rendering the review packet")
            if sha256_file(Path(origin["pdf_path"])) != origin["pdf_sha256"]:
                raise ValueError("Source PDF changed while rendering the review packet")
        atomic_write_json(output / "review.json", {"schema_version": "operator-review-items-v1", "items": selected})
        atomic_write_json(output / "annotations.template.json", {"schema_version": "operator-review-annotations-v1",
            "review_items_sha256": sha256_file(output / "review.json"), "reviewer": None, "completed_at": None,
            "items": [{"review_id": row["review_id"], "text_after_review": None, "seconds": None, "note": None}
                      for row in selected]})
        atomic_write_text(output / "review.md", _markdown(selected, sum(totals.values()), offset))
        report = {"schema_version": "operator-review-packet-v1", "status": "READY_FOR_OPERATOR_REVIEW",
            "quality_acceptance": "NOT_EVALUATED", "new_model_inference": False,
            "usage": "development_operator_review", "contains_predictions": True,
            "dictionary_sha256": snapshot["snapshot_sha256"], "origins": origins,
            "queue_items_by_document": dict(totals), "total_queue_items": sum(totals.values()), "offset": offset,
            "selected_items": len(selected), "remaining_items": max(0, sum(totals.values()) - offset - len(selected)),
            "priority_policy": "lookalike_tokens_then_literal_keyword_context_then_other_review_reasons_v1",
            "crop_statuses": dict(Counter(row["crop"]["status"] for row in selected)),
            "files": {path.relative_to(output).as_posix(): sha256_file(path)
                      for path in sorted(output.rglob("*")) if path.is_file()}}
        atomic_write_json(output / "packet.json", report)
        return report
    except BaseException as exc:
        atomic_write_json(output / "failure.json", {"status": "INCOMPLETE", "error": f"{type(exc).__name__}: {exc}"})
        raise
