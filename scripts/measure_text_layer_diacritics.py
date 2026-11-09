#!/usr/bin/env python3
"""Measure diacritic preservation of an OCR output against the screened text layer.

GROUND_TRUTH_PROTOCOL section 7.3 and 7.4 C. CPU only; it reads an existing batch
output and never runs a model.

Order of the protocol, enforced here:
  * The measurement choices of section 7.6 must be locked first (``--measurement-lock``,
    ``lock_text_layer_measurement.py``): status LOCKED_PROCEDURE, bound to ``--lock``,
    the same stream, and every pinned tool unchanged. A draft is refused.
  * Only PDFs whose screening is sealed ACCEPTED are measured (``--screening-seal``);
    the sealed decisions file must still match its sha256. Without that the tool
    refuses: the reviewer screens the text layer before any OCR result is compared.
  * The output must match the locked identity (``--identity-report`` from
    ``check_baseline_identity.py`` with status MATCH for the same output).
  * Every eligible slot of an accepted PDF is in the denominator: CANDIDATE pages of
    the locked inventory with slots, no uncomposed mark after NFC, and visible glyphs
    only (``text_layer_reference``). Nothing is dropped after looking at results.

Matching (item 7): OCR lines (extraction items of kind ``b``) and visible text-layer
lines are joined when their boxes overlap by at least half the smaller height and
intersect horizontally; each connected group is one unit. Characters are aligned only
inside a unit, so a reading-order difference is not a deleted slot. A text-layer line
without OCR is a unit with an empty prediction: its slots count as deleted. OCR lines
without a text-layer line are reported apart (text inside images, or spurious lines).

The gate is the one-sided Clopper-Pearson bound on DSER_strict errors over reference
slots (lock parameter ``metric``); DER_VN_v1 is reported beside it. Units with any
DSER error, base mismatch or spurious mark form the adjudication worklist (7.4 C).
On development the page intra-cluster correlation is estimated for the holdout DEFF.

  python scripts/measure_text_layer_diacritics.py --lock <lock.json> --measurement-lock <lock v2>.json \
      --screening-seal <seal.json>... --identity-report <identity.json> --output output/<run> --pdf-root inputs --stream text_corrected \
      --report scratch/v8/<new>.json [--design-effect-from <development report>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.ground_truth_tools import text_layer_reference as tlr  # noqa: E402
from benchmark.scientific_evaluation.cluster_correlation import holdout_design_effect, page_icc  # noqa: E402
from benchmark.scientific_evaluation.diacritic_acceptance import uncomposed_vietnamese_marks  # noqa: E402
from benchmark.scientific_evaluation.exact_bounds import upper_bound_gate  # noqa: E402
from benchmark.scientific_evaluation.ocr_metric import compute_der_detailed, compute_dser_strict_detailed  # noqa: E402
from scripts import lock_text_layer_measurement as measurement_lock_v2  # noqa: E402

SCHEMA = "ocr-v8-text-layer-diacritic-measurement-v1"
STREAMS = ("text_corrected", "text_raw")
MIN_VERTICAL_OVERLAP = 0.5
MATCHING_METHOD = "bbox-connected-groups-v1"
STRICT_FIELDS = ("ref_slots", "dser_errors", "shape_errors", "tone_errors", "stroke_errors", "deleted_slots",
                 "spurious_marks", "uncomposed_prediction_marks", "base_mismatch_slots", "inserted_char_marks")
DER_FIELDS = ("ref_diacritics", "diacritic_errors")

Box = Tuple[float, float, float, float]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accepted_screenings(lock: Dict, seal_paths: Sequence[Path]) -> Dict[str, Dict]:
    """PDF sha256 -> seal summary, for sealed ACCEPTED screenings of this lock only."""
    lock_sha = None
    accepted = {}
    for path in seal_paths:
        report = json.loads(path.read_bytes())
        sealed = path.parent / report["sealed_file"]
        if sha256_file(sealed) != report["sealed_sha256"]:
            raise ValueError(f"{sealed}: sealed decisions changed after sealing")
        lock_sha = lock_sha or report["lock"]["sha256"]
        if report["lock"]["sha256"] != lock_sha:
            raise ValueError("screening seals refer to different locks")
        status = report["verdict"]["status"]
        if status != "ACCEPTED":
            raise ValueError(f"{report['pdf']}: screening is {status}, not ACCEPTED; it cannot be measured")
        accepted[report["pdf_sha256"]] = {"pdf": report["pdf"], "seal": path.as_posix(), "sealed_sha256": report["sealed_sha256"],
                                          "match_slots": report["verdict"]["match_slots_complete_pages"]}
    if not accepted:
        raise ValueError("no ACCEPTED screening seal: the text layer must be screened before measurement (7.4 B)")
    known = {document["sha256"] for document in lock["documents"]}
    stray = sorted(set(accepted) - known)
    if stray:
        raise ValueError(f"seals for PDFs outside the lock: {stray}")
    return accepted


def batch_documents(output: Path) -> Dict[str, Dict]:
    with sqlite3.connect(f"file:{output / 'batch_state.sqlite'}?mode=ro", uri=True) as connection:
        rows = connection.execute("select id, payload from documents order by ordinal").fetchall()
    documents = {}
    for doc_id, payload in rows:
        data = json.loads(payload)
        documents[data.get("pdf_sha256")] = {"id": doc_id, "outcome": data.get("outcome"),
                                             "completed": (output / doc_id / "COMPLETED.json").is_file()}
    return documents


def check_identity(report_path: Path, output: Path, doc_ids: Sequence[str]) -> Dict:
    report = json.loads(report_path.read_bytes())
    if report.get("status") != "MATCH":
        raise ValueError(f"identity report status is {report.get('status')}, not MATCH")
    if Path(report.get("output", "")).resolve() != output.resolve():
        raise ValueError(f"identity report is for {report.get('output')}, not {output}")
    matched = {document["id"] for document in report.get("documents", []) if document.get("receipt_valid") and document.get("full_pages")}
    missing = sorted(set(doc_ids) - matched)
    if missing:
        raise ValueError(f"identity report does not cover {missing}")
    return {"path": report_path.as_posix(), "sha256": sha256_file(report_path), "lock_id": report.get("lock_id")}


def vertical_overlap(a: Box, b: Box) -> float:
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    smaller = min(a[3] - a[1], b[3] - b[1])
    return overlap / smaller if smaller > 0 else 0.0


def touches(a: Box, b: Box) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and vertical_overlap(a, b) >= MIN_VERTICAL_OVERLAP


def reading_sequence(items: List[Dict]) -> List[Dict]:
    """Rows by vertical overlap, top to bottom; left to right inside a row."""
    rows: List[List[Dict]] = []
    for item in sorted(items, key=lambda i: ((i["bbox"][1] + i["bbox"][3]) / 2, i["bbox"][0])):
        for row in rows:
            box = tlr._union(member["bbox"] for member in row)
            if vertical_overlap(box, item["bbox"]) >= MIN_VERTICAL_OVERLAP:
                row.append(item)
                break
        else:
            rows.append([item])
    rows.sort(key=lambda row: min(member["bbox"][1] for member in row))
    return [item for row in rows for item in sorted(row, key=lambda i: i["bbox"][0])]


def match_units(reference_lines: List[Dict], ocr_lines: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Connected groups of overlapping reference and OCR lines; unmatched OCR lines apart."""
    nodes = [("r", index) for index in range(len(reference_lines))] + [("o", index) for index in range(len(ocr_lines))]
    parent = {node: node for node in nodes}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for r, reference in enumerate(reference_lines):
        for o, ocr in enumerate(ocr_lines):
            if touches(reference["bbox"], ocr["bbox"]):
                parent[find(("r", r))] = find(("o", o))
    groups: Dict[Tuple[str, int], Dict[str, List[Dict]]] = {}
    for kind, index in nodes:
        group = groups.setdefault(find((kind, index)), {"r": [], "o": []})
        group[kind].append(reference_lines[index] if kind == "r" else ocr_lines[index])
    units, unmatched = [], []
    for group in groups.values():
        if not group["r"]:
            unmatched.extend(group["o"])
            continue
        references, predictions = reading_sequence(group["r"]), reading_sequence(group["o"])
        units.append({"reference": " ".join(item["text"] for item in references),
                      "prediction": " ".join(item["text"] for item in predictions),
                      "reference_line_ids": [item["id"] for item in references],
                      "ocr_source_ids": [item["id"] for item in predictions],
                      "bbox": list(tlr._union([item["bbox"] for item in group["r"] + group["o"]]))})
    units.sort(key=lambda unit: (unit["bbox"][1], unit["bbox"][0]))
    return units, unmatched


def reference_lines(units: Dict) -> Tuple[List[Dict], int]:
    """Visible words of each text-layer line; the slots of words that are not fully visible."""
    lines, hidden_slots = [], 0
    for line in units["lines"]:
        visible = [word for word in line.words if word.visibility == "VISIBLE"]
        hidden_slots += sum(word.slots for word in line.words if word.visibility != "VISIBLE")
        if visible:
            lines.append({"id": line.line_id, "text": " ".join(word.text for word in visible),
                          "bbox": tlr._union(word.bbox for word in visible), "slots": sum(word.slots for word in visible)})
    return lines, hidden_slots


def ocr_lines(extraction_page: Dict, stream: str) -> List[Dict]:
    lines = []
    for item in extraction_page.get("items", ()):
        text = item.get(stream)
        if item.get("kind") != "b" or not isinstance(text, str) or not text.strip() or not item.get("bbox"):
            continue
        lines.append({"id": item.get("source_id") or item.get("id"), "text": text, "bbox": tuple(item["bbox"])})
    return lines


def identity_frame(units: Dict, extraction_page: Dict) -> bool:
    frame = units["frame"]
    return (frame["rotation"] == 0 and frame["mediabox"] == frame["cropbox"]
            and extraction_page.get("coordinate_space") == "pdf_points_top_left" and not extraction_page.get("transforms"))


def add_counts(total: Dict, details: Dict, fields: Sequence[str]) -> None:
    for field in fields:
        total[field] = total.get(field, 0) + int(details.get(field) or 0)


def measure_pdf(pdf_path: Path, inventory_document: Dict, extraction: Dict, stream: str, unit_prefix: str) -> Dict:
    pdf_bytes = pdf_path.read_bytes()
    pages_by_number = {page["page"]: page for page in extraction["pages"]}
    strict_total, der_total = {}, {}
    pages, units_out, excluded = [], [], {"NOT_CANDIDATE_OR_NO_SLOT": 0, "UNCOMPOSED_REFERENCE": 0,
                                          "UNSUPPORTED_FRAME": 0, "NOT_VISIBLE_SLOTS": 0, "MISSING_OCR_PAGE": 0}
    unmatched_lines = 0
    import pymupdf

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        page_texts = {number: document[number - 1].get_text("text") for number in range(1, document.page_count + 1)}
    for record in inventory_document["page_records"]:
        number = record["page"]
        if record["status"] != "CANDIDATE" or not record.get("diacritic_slots"):
            excluded["NOT_CANDIDATE_OR_NO_SLOT"] += 1
            continue
        if uncomposed_vietnamese_marks(page_texts[number]):
            excluded["UNCOMPOSED_REFERENCE"] += 1
            continue
        extraction_page = pages_by_number.get(number)
        if extraction_page is None:
            excluded["MISSING_OCR_PAGE"] += 1  # an output gap is a failure, reported loudly by the caller
            continue
        units = tlr.page_units(pdf_bytes, number)
        if not identity_frame(units, extraction_page):
            excluded["UNSUPPORTED_FRAME"] += 1
            continue
        references, hidden = reference_lines(units)
        excluded["NOT_VISIBLE_SLOTS"] += hidden
        matched, unmatched = match_units(references, ocr_lines(extraction_page, stream))
        unmatched_lines += len(unmatched)
        page_strict = {}
        for index, unit in enumerate(matched):
            strict = compute_dser_strict_detailed(unit["reference"], unit["prediction"])
            der = compute_der_detailed(unit["reference"], unit["prediction"])
            add_counts(page_strict, strict, STRICT_FIELDS)
            add_counts(der_total, der, DER_FIELDS)
            if strict["ref_slots"] or strict["spurious_marks"] or strict["inserted_char_marks"]:
                units_out.append({"unit_id": f"{unit_prefix}:p{number:04d}:u{index:04d}", "page": number, **unit,
                                  "dser_strict": {field: strict[field] for field in STRICT_FIELDS},
                                  "needs_adjudication": bool(strict["dser_errors"] or strict["base_mismatch_slots"]
                                                             or strict["spurious_marks"] or strict["inserted_char_marks"])})
        add_counts(strict_total, page_strict, STRICT_FIELDS)
        pages.append({"page": number, "slots": page_strict.get("ref_slots", 0), "dser_errors": page_strict.get("dser_errors", 0),
                      "base_mismatch_slots": page_strict.get("base_mismatch_slots", 0), "units": len(matched),
                      "unmatched_ocr_lines": len(unmatched)})
    return {"pages": pages, "units": units_out, "strict": strict_total, "der": der_total,
            "excluded": excluded, "unmatched_ocr_lines": unmatched_lines}


def build(lock_path: Path, seal_paths: Sequence[Path], identity_report: Path, output: Path, pdf_root: Path,
          stream: str, design_effect_from: Optional[Path] = None, *, measurement_lock: Path) -> Dict:
    if stream not in STREAMS:
        raise ValueError(f"stream must be one of {STREAMS}")
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    choices = measurement_lock_v2.require_locked(measurement_lock, hashlib.sha256(lock_bytes).hexdigest(), stream)
    accepted = accepted_screenings(lock, seal_paths)
    inventory_path = ROOT / lock["inventory"]["path"] if not Path(lock["inventory"]["path"]).is_absolute() else Path(lock["inventory"]["path"])
    if sha256_file(inventory_path) != lock["inventory"]["sha256"]:
        raise ValueError(f"{inventory_path}: inventory bytes differ from the lock")
    inventory = {document["sha256"]: document for document in json.loads(inventory_path.read_bytes())["documents"]}
    documents = batch_documents(output)
    lock_documents = {document["sha256"]: document for document in lock["documents"]}
    partitions = {lock_documents[sha]["partition"] for sha in accepted}
    if len(partitions) != 1:
        raise ValueError(f"accepted PDFs mix partitions {sorted(partitions)}; measure each partition apart")
    missing = [accepted[sha]["pdf"] for sha in accepted if sha not in documents or not documents[sha]["completed"]]
    if missing:
        raise ValueError(f"output has no completed document for {missing}")
    identity = check_identity(identity_report, output, [documents[sha]["id"] for sha in accepted])
    per_pdf, strict_total, der_total, clusters, adjudication = [], {}, {}, [], []
    for sha, screening in sorted(accepted.items(), key=lambda item: item[1]["pdf"]):
        pdf_path = pdf_root / screening["pdf"]
        if sha256_file(pdf_path) != sha:
            raise ValueError(f"{pdf_path}: bytes differ from the screened PDF")
        doc_dir = output / documents[sha]["id"]
        extraction = json.loads((doc_dir / "extraction.json").read_bytes())
        result = measure_pdf(pdf_path, inventory[sha], extraction, stream, sha[:16])
        if result["excluded"]["MISSING_OCR_PAGE"]:
            raise ValueError(f"{screening['pdf']}: {result['excluded']['MISSING_OCR_PAGE']} eligible pages have no OCR page")
        add_counts(strict_total, result["strict"], STRICT_FIELDS)
        add_counts(der_total, result["der"], DER_FIELDS)
        clusters.extend((page["dser_errors"], page["slots"]) for page in result["pages"] if page["slots"])
        adjudication.extend(unit["unit_id"] for unit in result["units"] if unit["needs_adjudication"])
        per_pdf.append({"pdf": screening["pdf"], "pdf_sha256": sha, "document": documents[sha]["id"],
                        "screening": screening, "strict": result["strict"], "der": result["der"],
                        "excluded": result["excluded"], "unmatched_ocr_lines": result["unmatched_ocr_lines"],
                        "pages": result["pages"], "units": result["units"]})
    partition = partitions.pop()
    errors, slots = strict_total.get("dser_errors", 0), strict_total.get("ref_slots", 0)
    icc = page_icc(clusters)
    deff_block = {"status": "NOT_REQUESTED"}
    deff = None
    if design_effect_from is not None:
        development = json.loads(design_effect_from.read_bytes())
        if development.get("partition") != "development":
            raise ValueError("the design effect must come from a development measurement")
        deff_block = holdout_design_effect(development["page_icc"], [size for _, size in clusters])
        deff_block["source"] = {"path": design_effect_from.as_posix(), "sha256": sha256_file(design_effect_from)}
        deff = deff_block.get("design_effect") if deff_block.get("status") == "MEASURED" else None
    in_sample = upper_bound_gate(errors, slots, confidence=lock["parameters"]["confidence"],
                                 maximum_rate=lock["parameters"]["maximum_error_rate"]) if slots else None
    clustered = (upper_bound_gate(errors, slots, confidence=lock["parameters"]["confidence"],
                                  maximum_rate=lock["parameters"]["maximum_error_rate"], deff=deff)
                 if slots and deff is not None else None)
    return {
        "schema_version": SCHEMA, "protocol": "docs/quality_assurance/GROUND_TRUTH_PROTOCOL.md#7",
        "lock": {"path": lock_path.as_posix(), "sha256": hashlib.sha256(lock_bytes).hexdigest()},
        "measurement_lock": choices,
        "partition": partition, "stream": stream, "output": output.as_posix(), "identity": identity,
        "metric": lock["parameters"]["metric"], "matching": {"method": MATCHING_METHOD,
                                                             "min_vertical_overlap": MIN_VERTICAL_OVERLAP,
                                                             "visibility": tlr.VISIBILITY_METHOD},
        "dser_strict": {**strict_total, "rate": errors / slots if slots else None},
        "der_vn_v1": {**der_total, "rate": der_total.get("diacritic_errors", 0) / der_total["ref_diacritics"]
                      if der_total.get("ref_diacritics") else None},
        "gate_in_sample": in_sample, "gate_clustered": clustered, "design_effect": deff_block,
        "page_icc": icc, "adjudication_units": len(adjudication),
        "adjudication_status": "PENDING_REVIEW" if adjudication else "NOT_NEEDED",
        "claim_status": "NOT_EVALUATED" if adjudication or clustered is None else clustered["status"],
        "claim_note": ("Counts become final only after blind adjudication (7.4 C) and the re-check (7.4 D). "
                       "A development measurement never supports the general claim; only a holdout with a "
                       "development DEFF does (7.3 item 5)."),
        "documents": per_pdf,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--measurement-lock", type=Path, required=True, help="LOCKED v2 lock of the section 7.6 choices")
    parser.add_argument("--screening-seal", type=Path, nargs="+", required=True)
    parser.add_argument("--identity-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--stream", choices=STREAMS, required=True)
    parser.add_argument("--design-effect-from", type=Path, help="development measurement report (holdout only)")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; write a new report")
    try:
        report = build(args.lock, args.screening_seal, args.identity_report, args.output, args.pdf_root, args.stream,
                       args.design_effect_from, measurement_lock=args.measurement_lock)
    except measurement_lock_v2.LockError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 3
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    strict = report["dser_strict"]
    print(f"{report['partition']}: DSER_strict {strict.get('dser_errors', 0)}/{strict.get('ref_slots', 0)}; "
          f"adjudication units {report['adjudication_units']}; claim {report['claim_status']} -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
