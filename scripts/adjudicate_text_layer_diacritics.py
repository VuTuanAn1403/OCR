#!/usr/bin/env python3
"""Blind A/B adjudication of OCR vs text-layer disagreements (GROUND_TRUTH_PROTOCOL 7.4 C).

  build  From a measurement report, cut every disagreement into items: inside each unit
         the reference and OCR tokens are aligned and each differing segment that
         carries a diacritic slot or mark becomes one item. The sheet shows a crop and two
         strings A and B; which side is OCR is decided by ascending sha256 of
         ``seed:adjudicate:<item_id>`` and kept in ``ab_key.json`` next to the sheet,
         never in the HTML.
  seal   Map the reviewer's choices back through the key and recount DSER_strict on the
         corrected references:
           text layer correct -> OCR error, reference kept;
           OCR correct        -> GT error, reference replaced by the OCR segment;
           both wrong         -> OCR error, reference replaced by the reviewer's text;
           unresolved         -> OCR error; base-letter mismatches of the segment count too.
         The sealed decisions are written once, named by their sha256.

When the measurement lock sets ``choices.adjudication.sample_size`` (lock v4), only that many
items are put on the sheet, chosen by ascending sha256 of ``seed:adjudication-sample:<item_id>``
so nobody picks them. Every item left out counts as UNRESOLVED (an OCR error, the conservative
count). The seal also reports the outcome shares of the sample with Clopper-Pearson intervals
and a scaled estimate of the fully adjudicated count; the estimate is never a gate.

When the lock sets ``choices.adjudication.partial`` (lock v5), the seal accepts a sheet that is
only partly decided: every item without a decision counts as UNRESOLVED, the outcome shares
are descriptive only and no population estimate is given (the decided items follow the sheet
order, not a random draw). The seal reports, per PDF, how many items were decided and the
counts, so fully adjudicated PDFs get exact figures.

  python scripts/adjudicate_text_layer_diacritics.py build --measurement <report.json> --pdf-root inputs --out scratch/v8/adjudication/<new>
  python scripts/adjudicate_text_layer_diacritics.py seal --sheet <sheet dir> --decisions <export.jsonl> --out scratch/v8/adjudication/<sealed>
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.ground_truth_tools import text_layer_reference as tlr  # noqa: E402
from benchmark.scientific_evaluation.cluster_correlation import page_icc  # noqa: E402
from benchmark.scientific_evaluation.diacritic_acceptance import uncomposed_vietnamese_marks  # noqa: E402
from benchmark.scientific_evaluation.exact_bounds import clopper_pearson_upper, upper_bound_gate  # noqa: E402
from benchmark.scientific_evaluation.ocr_metric import compute_dser_strict_detailed  # noqa: E402
from scripts import lock_text_layer_measurement as measurement_lock_v2  # noqa: E402
from scripts.measure_text_layer_diacritics import reading_sequence, reference_lines  # noqa: E402
from scripts.screen_text_layer import CROP_PAD_POINTS, SHEET_ZOOM, dumps, read_jsonl, sha256_bytes, tool_commit, write_new  # noqa: E402

SHEET_SCHEMA = "ocr-v8-diacritic-adjudication-sheet-v1"
RECORD_SCHEMA = "ocr-v8-diacritic-adjudication-decision-v1"
SEAL_SCHEMA = "ocr-v8-diacritic-adjudication-seal-v1"
CHOICES = ("A_CORRECT", "B_CORRECT", "BOTH_WRONG", "UNRESOLVED")
TIMEZONE = "+07:00"
SAMPLE_RANK = "sha256(seed:adjudication-sample:item_id), ascending"


def sample_rank(seed: str, item_id: str) -> str:
    return hashlib.sha256(f"{seed}:adjudication-sample:{item_id}".encode("utf-8")).hexdigest()


def adjudication_rule(measurement: Dict) -> Dict:
    """The adjudication choice of the measurement lock (sample size, partial)."""
    entry = measurement["measurement_lock"]
    lock = json.loads(measurement_lock_v2.resolve(entry["path"]).read_bytes())
    return lock.get("choices", {}).get("adjudication") or {}


def sample_size_of(measurement: Dict):
    """The sample size the measurement lock fixed, or None for every item."""
    return adjudication_rule(measurement).get("sample_size")


def interval(count: int, total: int, confidence: float = .95) -> Dict:
    """Two-sided Clopper-Pearson interval of a share."""
    if not total:
        return {"count": count, "of": total, "share": None, "lower": None, "upper": None}
    side = 1 - (1 - confidence) / 2
    upper = clopper_pearson_upper(count, total, side) if count < total else 1.0
    lower = 1 - clopper_pearson_upper(total - count, total, side) if count > 0 else 0.0
    return {"count": count, "of": total, "share": count / total, "lower": lower, "upper": upper, "confidence": confidence}


def marked(text: str) -> bool:
    return bool(tlr.diacritic_slots(text) or uncomposed_vietnamese_marks(text))


def segments(reference: str, prediction: str) -> List[Dict]:
    """Differing token segments that carry a diacritic slot or mark on either side."""
    ref_tokens, pred_tokens = reference.split(), prediction.split()
    matcher = difflib.SequenceMatcher(a=ref_tokens, b=pred_tokens, autojunk=False)
    found = []
    for tag, i0, i1, j0, j1 in matcher.get_opcodes():
        if tag == "equal":
            continue
        ref_text, pred_text = " ".join(ref_tokens[i0:i1]), " ".join(pred_tokens[j0:j1])
        if marked(ref_text) or marked(pred_text):
            found.append({"ref_tokens": [i0, i1], "pred_tokens": [j0, j1], "text_layer": ref_text, "ocr": pred_text})
    return found


CONTEXT_TOKENS = 3


def item_kind(segment: Dict) -> str:
    """INSERTION: only the OCR has words here; DELETION: only the text layer; else SUBSTITUTION.

    The kind is shown without saying which side is OCR: for both INSERTION and DELETION one
    string is empty and the reviewer is asked whether the other string is printed there.
    """
    if not segment["text_layer"] or not segment["ocr"]:
        return "ONE_SIDE_EMPTY"
    return "SUBSTITUTION"


def context(reference: str, prediction: str, segment: Dict):
    """Up to three tokens before and after the segment that are equal on both sides.

    Only tokens inside ``equal`` blocks of the same alignment that cut the segments are used,
    and the context stops at the first token that differs, so it never shows a word that
    belongs to one side only and cannot reveal which side is OCR.
    """
    ref_tokens, pred_tokens = reference.split(), prediction.split()
    matcher = difflib.SequenceMatcher(a=ref_tokens, b=pred_tokens, autojunk=False)
    equal = set()
    for tag, i0, i1, _, _ in matcher.get_opcodes():
        if tag == "equal":
            equal.update(range(i0, i1))
    start, end = segment["ref_tokens"]
    before = []
    for index in range(start - 1, max(-1, start - 1 - CONTEXT_TOKENS), -1):
        if index not in equal:
            break
        before.insert(0, ref_tokens[index])
    after = []
    for index in range(end, min(len(ref_tokens), end + CONTEXT_TOKENS)):
        if index not in equal:
            break
        after.append(ref_tokens[index])
    return " ".join(before), " ".join(after)


def gap_box(boxes: Sequence[Tuple[float, float, float, float]], at: int, fallback: Sequence[float]):
    """Box of the empty place where text was inserted before reference word ``at``.

    The box marks the space itself, never a neighbouring word: between two words on one line it is
    the space between them; after the last word of a line (or before the first) it is a stretch of
    two line heights next to that word. The neighbours stay visible in the padded view around it.
    """
    before = boxes[at - 1] if 0 < at <= len(boxes) else None
    after = boxes[at] if 0 <= at < len(boxes) else None
    same_line = before and after and after[0] > before[2] and min(before[3], after[3]) > max(before[1], after[1])
    if same_line:
        return (before[2], min(before[1], after[1]), after[0], max(before[3], after[3]))
    if before:
        height = before[3] - before[1]
        return (before[2], before[1], before[2] + 2 * height, before[3])
    if after:
        height = after[3] - after[1]
        return (after[0] - 2 * height, after[1], after[0], after[3])
    return tuple(fallback)


def a_is_text_layer(seed: str, item_id: str) -> bool:
    return int(hashlib.sha256(f"{seed}:adjudicate:{item_id}".encode()).hexdigest()[0], 16) % 2 == 0


def unit_words(pdf_bytes: bytes, page: int, line_ids: Sequence[str]) -> List[Tuple[float, float, float, float]]:
    """Boxes of the reference tokens of a unit, in the order the measurement joined them."""
    units = tlr.page_units(pdf_bytes, page)
    lines, _ = reference_lines(units)
    wanted = [line for line in lines if line["id"] in set(line_ids)]
    words_by_line = {line.line_id: [w for w in line.words if w.visibility == "VISIBLE"] for line in units["lines"]}
    boxes = []
    for line in reading_sequence(wanted):
        boxes.extend(word.bbox for word in words_by_line[line["id"]])
    return boxes


def check_measurement_lock(measurement: Dict) -> None:
    """The section 7.6 lock the measurement ran under must still hold: same bytes, same tools."""
    entry = measurement.get("measurement_lock")
    if not entry:
        raise measurement_lock_v2.LockError("the measurement has no v2 measurement lock")
    path = measurement_lock_v2.resolve(entry["path"])
    if sha256_bytes(path.read_bytes()) != entry["sha256"]:
        raise measurement_lock_v2.LockError(f"{entry['path']}: lock bytes changed after the measurement")
    problems = measurement_lock_v2.verify(path)
    if problems:
        raise measurement_lock_v2.LockError(f"{entry['path']}: " + "; ".join(problems))


def build_sheet(measurement_path: Path, pdf_root: Path, out: Path, reviewer: str) -> Dict:
    import numpy
    import pymupdf

    measurement_bytes = measurement_path.read_bytes()
    measurement = json.loads(measurement_bytes)
    check_measurement_lock(measurement)
    lock = json.loads((ROOT / measurement["lock"]["path"]).read_bytes() if not Path(measurement["lock"]["path"]).is_absolute()
                      else Path(measurement["lock"]["path"]).read_bytes())
    seed = lock["parameters"]["seed"]
    if out.exists():
        raise FileExistsError(f"{out} exists; build a new adjudication directory")
    candidates = [f"{unit['unit_id']}:s{index:02d}" for document in measurement["documents"]
                  for unit in document["units"] if unit["needs_adjudication"]
                  for index, _ in enumerate(segments(unit["reference"], unit["prediction"]))]
    size = sample_size_of(measurement)
    chosen_ids = set(candidates if size is None or size >= len(candidates)
                     else sorted(candidates, key=lambda item_id: sample_rank(seed, item_id))[:size])
    (out / "pages").mkdir(parents=True)
    items, key, unsampled, pages_out = [], {}, {}, {}
    for document in measurement["documents"]:
        pdf_bytes = (pdf_root / document["pdf"]).read_bytes()
        if sha256_bytes(pdf_bytes) != document["pdf_sha256"]:
            raise ValueError(f"{document['pdf']}: bytes differ from the measured PDF")
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
            for unit in document["units"]:
                if not unit["needs_adjudication"]:
                    continue
                found = segments(unit["reference"], unit["prediction"])
                for index, segment in enumerate(found):
                    item_id = f"{unit['unit_id']}:s{index:02d}"
                    if item_id not in chosen_ids:
                        unsampled[item_id] = {"unit_id": unit["unit_id"], "pdf_sha256": document["pdf_sha256"],
                                              "page": unit["page"], **segment}
                if not any(f"{unit['unit_id']}:s{index:02d}" in chosen_ids for index in range(len(found))):
                    continue
                page = pdf[unit["page"] - 1]
                image_key = f"{document['pdf_sha256'][:16]}-p{unit['page']:04d}"
                if image_key not in pages_out:
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(SHEET_ZOOM, SHEET_ZOOM), alpha=False, colorspace=pymupdf.csRGB)
                    png = pixmap.tobytes("png")
                    write_new(out / "pages" / f"{image_key}.png", png)
                    pages_out[image_key] = {"image": f"pages/{image_key}.png", "image_sha256": sha256_bytes(png),
                                            "image_size": [pixmap.width, pixmap.height], "zoom": SHEET_ZOOM,
                                            "rotation_matrix": list(page.rotation_matrix),
                                            "pixels": numpy.frombuffer(pixmap.samples, dtype=numpy.uint8).reshape(pixmap.height, pixmap.width, 3)}
                image = pages_out[image_key]
                boxes = unit_words(pdf_bytes, unit["page"], unit["reference_line_ids"])
                for index, segment in enumerate(found):
                    if f"{unit['unit_id']}:s{index:02d}" not in chosen_ids:
                        continue
                    i0, i1 = segment["ref_tokens"]
                    word_box = tlr._union(boxes[i0:i1]) if i1 > i0 and boxes[i0:i1] else gap_box(boxes, i0, unit["bbox"])
                    padded = (word_box[0] - CROP_PAD_POINTS, word_box[1] - CROP_PAD_POINTS,
                              word_box[2] + CROP_PAD_POINTS, word_box[3] + CROP_PAD_POINTS)
                    px = tlr.pixel_box(page, padded, SHEET_ZOOM, image["image_size"][0], image["image_size"][1])
                    crop = numpy.ascontiguousarray(image["pixels"][px[1]:px[3], px[0]:px[2]])
                    item_id = f"{unit['unit_id']}:s{index:02d}"
                    text_layer_first = a_is_text_layer(seed, item_id)
                    a_text, b_text = (segment["text_layer"], segment["ocr"]) if text_layer_first else (segment["ocr"], segment["text_layer"])
                    key[item_id] = {"A": "TEXT_LAYER" if text_layer_first else "OCR", "unit_id": unit["unit_id"],
                                    "pdf_sha256": document["pdf_sha256"], "page": unit["page"], **segment}
                    items.append({"item_id": item_id, "page": unit["page"], "pdf": document["pdf"], "image": image_key,
                                  "a": a_text, "b": b_text, "crop_px": list(px), "crop_sha256": sha256_bytes(crop.tobytes()),
                                  "context_bbox": list(unit["bbox"]), "kind": item_kind(segment),
                                  "context": list(context(unit["reference"], unit["prediction"], segment))})
    pages_public = {name: {k: v for k, v in page.items() if k != "pixels"} for name, page in pages_out.items()}
    sheet_id = sha256_bytes(measurement_bytes)[:16]
    manifest = {"schema_version": SHEET_SCHEMA, "mode": "adjudication", "sheet_id": sheet_id,
                "measurement": {"path": measurement_path.as_posix(), "sha256": sha256_bytes(measurement_bytes)},
                "reviewer": reviewer, "tool_commit": tool_commit(), "choices": list(CHOICES), "pages": pages_public,
                "sample": {"size": len(items), "population": len(candidates), "requested": size, "rank": SAMPLE_RANK,
                           "unsampled_rule": "every item left out counts as UNRESOLVED"},
                "items": items, "created_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds")}
    write_new(out / "sheet.json", dumps(manifest))
    write_new(out / "ab_key.json", dumps({"sheet_id": sheet_id, "seed": seed, "items": key, "unsampled": unsampled}))
    template = (ROOT / "benchmark" / "ground_truth_tools" / "adjudication_sheet.html").read_text(encoding="utf-8")
    public = {k: manifest[k] for k in ("sheet_id", "reviewer", "choices", "pages", "items", "tool_commit")}
    write_new(out / "index.html", template.replace("/*__SHEET__*/null", json.dumps(public, ensure_ascii=False).replace("</", "<\\/")).encode("utf-8"))
    return manifest


def check_records(manifest: Dict, records: List[Dict], allow_missing: bool = False) -> List[str]:
    items = {item["item_id"]: item for item in manifest["items"]}
    problems, seen = [], set()
    for index, record in enumerate(records, start=1):
        where = f"record {index}"
        item = items.get(record.get("item_id"))
        if record.get("schema_version") != RECORD_SCHEMA:
            problems.append(f"{where}: schema_version {record.get('schema_version')!r}")
        if item is None:
            problems.append(f"{where}: item {record.get('item_id')!r} is not on the sheet")
            continue
        if record.get("crop_sha256") != item["crop_sha256"] or record.get("a") != item["a"] or record.get("b") != item["b"]:
            problems.append(f"{where}: shown crop or strings differ from the sheet")
        if record.get("choice") not in CHOICES:
            problems.append(f"{where}: choice {record.get('choice')!r}")
        if record.get("choice") == "BOTH_WRONG" and not (record.get("corrected_text") or "").strip():
            problems.append(f"{where}: BOTH_WRONG needs the correct text read from the image")
        if not record.get("reviewer") or not (record.get("decided_at") or "").endswith(TIMEZONE):
            problems.append(f"{where}: reviewer or Asia/Bangkok timestamp missing")
        if record.get("item_id") in seen:
            problems.append(f"{where}: item decided twice")
        seen.add(record.get("item_id"))
    missing = sorted(set(items) - seen)
    if missing and not allow_missing:
        problems.append(f"{len(missing)} items have no decision, e.g. {missing[:3]}")
    return problems


def corrected_reference(reference: str, decisions: List[Tuple[Dict, str, str]]) -> str:
    tokens = reference.split()
    for segment, outcome, corrected in sorted(decisions, key=lambda d: d[0]["ref_tokens"][0], reverse=True):
        i0, i1 = segment["ref_tokens"]
        if outcome == "OCR_CORRECT":
            tokens[i0:i1] = segment["ocr"].split()
        elif outcome == "BOTH_WRONG":
            tokens[i0:i1] = corrected.split()
    return " ".join(tokens)


def recount(measurement: Dict, by_unit: Dict[str, List[Tuple[Dict, str, str]]]):
    """DSER_strict errors and slots after applying the per-unit decisions; page clusters for rho."""
    errors = slots = gt_error_items = 0
    clusters: Dict[Tuple[str, int], List[int]] = {}
    for document in measurement["documents"]:
        for page in document["pages"]:
            clusters[(document["pdf_sha256"], page["page"])] = [page["dser_errors"], page["slots"]]
        for unit in document["units"]:
            decisions = by_unit.get(unit["unit_id"], [])
            before = unit["dser_strict"]
            if not decisions:
                continue
            reference = corrected_reference(unit["reference"], decisions)
            after = compute_dser_strict_detailed(reference, unit["prediction"])
            extra = sum(compute_dser_strict_detailed(s["text_layer"], s["ocr"])["base_mismatch_slots"]
                        for s, outcome, _ in decisions if outcome == "UNRESOLVED")
            gt_error_items += sum(outcome in ("OCR_CORRECT", "BOTH_WRONG") for _, outcome, _ in decisions)
            cell = clusters[(document["pdf_sha256"], unit["page"])]
            cell[0] += after["dser_errors"] + extra - before["dser_errors"]
            cell[1] += after["ref_slots"] - before["ref_slots"]
    for value in clusters.values():
        errors += value[0]
        slots += value[1]
    return errors, slots, clusters, gt_error_items


def per_document(measurement: Dict, key: Dict, unsampled: Dict, decided: set, clusters: Dict) -> List[Dict]:
    """Per PDF: items, decided items and the DSER_strict count after the decisions applied."""
    out = []
    for document in measurement["documents"]:
        sha = document["pdf_sha256"]
        items = [item_id for item_id, segment in {**key, **unsampled}.items() if segment["pdf_sha256"] == sha]
        done = sum(item_id in decided for item_id in items)
        errors = sum(value[0] for (pdf, _), value in clusters.items() if pdf == sha)
        slots = sum(value[1] for (pdf, _), value in clusters.items() if pdf == sha)
        out.append({"pdf": document["pdf"], "pdf_sha256": sha, "items": len(items), "decided": done,
                    "fully_adjudicated": done == len(items), "errors": errors, "slots": slots,
                    "rate": errors / slots if slots else None})
    return out


def seal(sheet_dir: Path, decision_paths: List[Path], out: Path) -> Dict:
    manifest_bytes = (sheet_dir / "sheet.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    key_file = json.loads((sheet_dir / "ab_key.json").read_bytes())
    key, unsampled = key_file["items"], key_file.get("unsampled", {})
    measurement_path = Path(manifest["measurement"]["path"])
    measurement_bytes = measurement_path.read_bytes()
    if sha256_bytes(measurement_bytes) != manifest["measurement"]["sha256"]:
        raise ValueError("the measurement report changed after the sheet was built")
    measurement = json.loads(measurement_bytes)
    check_measurement_lock(measurement)
    partial = bool(adjudication_rule(measurement).get("partial"))
    records = read_jsonl(decision_paths)
    problems = check_records(manifest, records, allow_missing=partial)
    if problems:
        raise ValueError("adjudication decisions do not match the sheet:\n  " + "\n  ".join(problems[:40]))
    outcome_of = {"A_CORRECT": lambda side: "TEXT_LAYER_CORRECT" if side == "TEXT_LAYER" else "OCR_CORRECT",
                  "B_CORRECT": lambda side: "OCR_CORRECT" if side == "TEXT_LAYER" else "TEXT_LAYER_CORRECT",
                  "BOTH_WRONG": lambda side: "BOTH_WRONG", "UNRESOLVED": lambda side: "UNRESOLVED"}
    by_unit: Dict[str, List[Tuple[Dict, str, str]]] = {}
    unresolved_all: Dict[str, List[Tuple[Dict, str, str]]] = {}
    outcomes: Dict[str, int] = {}
    for record in records:
        segment = key[record["item_id"]]
        outcome = outcome_of[record["choice"]](segment["A"])
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        by_unit.setdefault(segment["unit_id"], []).append((segment, outcome, record.get("corrected_text") or ""))
        unresolved_all.setdefault(segment["unit_id"], []).append((segment, "UNRESOLVED", ""))
    for segment in unsampled.values():  # left out of the sample: counted as UNRESOLVED
        by_unit.setdefault(segment["unit_id"], []).append((segment, "UNRESOLVED", ""))
        unresolved_all.setdefault(segment["unit_id"], []).append((segment, "UNRESOLVED", ""))
    if unsampled:
        outcomes["UNRESOLVED_NOT_SAMPLED"] = len(unsampled)
    decided = {record["item_id"] for record in records}
    undecided = [item_id for item_id in key if item_id not in decided]
    for item_id in undecided:  # partial adjudication: not decided, counted as UNRESOLVED
        segment = key[item_id]
        by_unit.setdefault(segment["unit_id"], []).append((segment, "UNRESOLVED", ""))
        unresolved_all.setdefault(segment["unit_id"], []).append((segment, "UNRESOLVED", ""))
    if undecided:
        outcomes["UNRESOLVED_NOT_DECIDED"] = len(undecided)
    errors, slots, clusters, gt_error_items = recount(measurement, by_unit)
    sample = manifest.get("sample") or {"size": len(records), "population": len(records)}
    estimate = None
    if undecided:
        estimate = {"status": "NOT_ESTIMATED",
                    "reason": "partial adjudication follows the sheet order, not a random draw"}
    elif unsampled:
        all_unresolved = recount(measurement, unresolved_all)[0]
        scale = sample["population"] / sample["size"] if sample["size"] else None
        estimate = {"status": "ESTIMATE_NOT_A_GATE",
                    "method": "error reduction seen on the sampled items, scaled by population/sample (Horvitz-Thompson)",
                    "errors_if_every_item_unresolved": all_unresolved,
                    "estimated_errors_after_full_adjudication": round(all_unresolved - (all_unresolved - errors) * scale) if scale else None}
    shares = {name: interval(sum(1 for r in records if outcome_of[r["choice"]](key[r["item_id"]]["A"]) == name), len(records))
              for name in ("TEXT_LAYER_CORRECT", "OCR_CORRECT", "BOTH_WRONG", "UNRESOLVED")}
    sealed_bytes = b"".join(json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                            for record in sorted(records, key=lambda r: r["item_id"]))
    sealed_sha = sha256_bytes(sealed_bytes)
    if out.exists():
        raise FileExistsError(f"{out} exists; a sealed record is never rewritten")
    write_new(out / f"adjudication-{sealed_sha[:16]}.jsonl", sealed_bytes)
    parameters = json.loads((ROOT / measurement["lock"]["path"]).read_bytes() if not Path(measurement["lock"]["path"]).is_absolute()
                            else Path(measurement["lock"]["path"]).read_bytes())["parameters"]
    report = {"schema_version": SEAL_SCHEMA, "sheet_id": manifest["sheet_id"], "sheet_sha256": sha256_bytes(manifest_bytes),
              "measurement": manifest["measurement"], "partition": measurement["partition"], "stream": measurement["stream"],
              "sealed_file": f"adjudication-{sealed_sha[:16]}.jsonl", "sealed_sha256": sealed_sha, "items": len(records),
              "outcomes": outcomes, "gt_error_items": gt_error_items, "sample": sample, "sample_shares": shares,
              "sample_shares_scope": "descriptive for the decided items only" if undecided else "the sheet's items",
              "documents": per_document(measurement, key, unsampled, decided, clusters),
              "dser_strict_after_adjudication": {"errors": errors, "slots": slots, "rate": errors / slots if slots else None,
                                                 "count": "conservative: items left out of the sample count as UNRESOLVED"
                                                 if unsampled else "conservative: undecided items count as UNRESOLVED"
                                                 if undecided else "every item adjudicated"},
              "estimate": estimate,
              "gate_in_sample": upper_bound_gate(errors, slots, confidence=parameters["confidence"],
                                                 maximum_rate=parameters["maximum_error_rate"]) if slots else None,
              "page_icc": page_icc([tuple(v) for v in clusters.values()]),
              "limits": "Identical errors in OCR and text layer are not detectable; bounded by the screening bound (7.4 C, G).",
              "sealed_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).isoformat(timespec="seconds")}
    write_new(out / "seal.json", dumps(report))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--measurement", type=Path, required=True)
    build.add_argument("--pdf-root", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--reviewer", default="VuTuanAn1403")
    sealer = commands.add_parser("seal")
    sealer.add_argument("--sheet", type=Path, required=True)
    sealer.add_argument("--decisions", type=Path, nargs="+", required=True)
    sealer.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifest = build_sheet(args.measurement, args.pdf_root, args.out, args.reviewer)
        print(f"{len(manifest['items'])}/{manifest['sample']['population']} adjudication items -> {args.out / 'index.html'}")
    else:
        report = seal(args.sheet, args.decisions, args.out)
        result = report["dser_strict_after_adjudication"]
        print(f"after adjudication: DSER_strict {result['errors']}/{result['slots']}, GT error items {report['gt_error_items']}; "
              f"sealed {report['sealed_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
