#!/usr/bin/env python3
"""Paired comparison of captured primary text detections between two batch runs (V8-060).

Phase A stores the `primary-text-detections-v1` snapshot of the full-page detector in
every page JSON. This tool reads the snapshots of a baseline run and a candidate run of
the same PDFs, then scores them with the production evaluator
`benchmark.scientific_evaluation.text_detection_metric.evaluate_page` against two references:

* `agreement`: the baseline boxes are the reference for the candidate, so TP/FP/FN become
  matched, candidate-only and baseline-only boxes. Agreement is not accuracy. Spec 04
  section 5 allows engine disagreement only to select regions for review.
* `text_layer` (optional): line boxes of the born-digital text layer on inventory pages
  that are CANDIDATE and not mostly covered by an image, scored for both runs. The text
  layer is unverified (GROUND_TRUTH_PROTOCOL section 7), so these numbers are diagnostics.

Both references live in memory and are never written as ground truth. Pages are paired
only when both snapshots were CAPTURED on identical pixels. Quality acceptance stays
NOT_EVALUATED and, without a locked protocol and independent GT, the only decision the
challenger contract allows is INCONCLUSIVE (`benchmark/challengers/experiment.py`).

  python scripts/compare_detector_snapshots.py --baseline output/<v4> --candidate output/<v6> \
      --baseline-lock <lock>.json --candidate-lock <lock>.json --pdf-root inputs \
      --inventory <inventory>.json --experiment-id EXP-V8-DET-YYYYMMDD-NNN --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark.challengers import experiment  # noqa: E402
from benchmark.scientific_evaluation import text_detection_metric as metric  # noqa: E402

SCHEMA = "ocr-v8-detector-paired-comparison-v1"
SETTINGS = {"protocol": metric.PROTOCOL, "iou_threshold": 0.5, "ignore_overlap": 0.5}
MAX_IMAGE_COVER = 0.5  # declared before scoring: pages mostly covered by an image hide text the layer lacks
EDGE = 0.005


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def documents(output: Path) -> Dict[str, Dict]:
    """Batch documents with their outcome; a document counts only when COMPLETED.json exists."""
    uri = f"file:{(output / 'batch_state.sqlite').as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute("select id, payload from documents order by ordinal").fetchall()
    result = {}
    for doc_id, payload in rows:
        data = json.loads(payload)
        result[doc_id] = {"outcome": data.get("outcome"), "pdf_sha256": data.get("pdf_sha256"),
                          "total_pages": data.get("total_pages"),
                          "completed": (output / doc_id / "COMPLETED.json").is_file()}
    return result


def extraction_pages(doc_dir: Path) -> Dict[int, Dict]:
    data = json.loads((doc_dir / "extraction.json").read_text(encoding="utf-8"))
    return {page["page"]: page for page in data["pages"]}


def clip_regions(boxes: Iterable[List[float]], width: float, height: float, prefix: str) -> tuple[List[Dict], int]:
    """Clip reference boxes to the page; zero-area boxes cannot be a reference and are counted."""
    regions, dropped = [], 0
    for index, box in enumerate(boxes):
        x0, y0 = max(0.0, box[0]), max(0.0, box[1])
        x1, y1 = min(width, box[2]), min(height, box[3])
        if x1 - x0 <= EDGE or y1 - y0 <= EDGE:
            dropped += 1
            continue
        regions.append({"id": f"{prefix}{index:06d}", "bbox": [x0, y0, x1, y1]})
    return regions, dropped


def snapshot_page_boxes(snapshot: Dict) -> List[List[float]]:
    scale = (snapshot["pixel_to_page"][0][0], snapshot["pixel_to_page"][1][1])
    return [[value * scale[i % 2] for i, value in enumerate(row["bbox"])] for row in snapshot["detections"]]


def identity_frame(page_record: Dict) -> bool:
    steps = page_record.get("metadata", {}).get("coordinate_space", {}).get("native_to_output", {}).get("steps", [])
    return all(step.get("matrix") == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]] for step in steps)


def text_layer_lines(pdf_page) -> List[List[float]]:
    lines = []
    for block in pdf_page.get_text("dict")["blocks"]:
        for line in block.get("lines", ()):
            if "".join(span["text"] for span in line["spans"]).strip():
                lines.append(list(line["bbox"]))
    return lines


def score(regions: List[Dict], image_sha: str, page_record: Dict, extraction_page: Dict) -> Dict:
    return metric.evaluate_page({"input_image_sha256": image_sha, "regions": regions}, page_record,
                                extraction_page, SETTINGS)


def iou_summary(values: List[float]) -> Dict:
    if not values:
        return {"matched": 0, "mean_iou": None, "median_iou": None}
    return {"matched": len(values), "mean_iou": round(statistics.fmean(values), 4),
            "median_iou": round(statistics.median(values), 4)}


def summarize(rows: List[Dict], key: str) -> Dict:
    """Counts and rates of one scored field over the rows that carry it."""
    scored = [row[key] for row in rows if row.get(key) is not None]
    summary = metric.summarize(scored)
    summary.update(iou_summary([pair["iou"] for row in scored for pair in row.get("matched", [])]))
    return summary


def compact(result: Optional[Dict]) -> Optional[Dict]:
    if result is None:
        return None
    return {"status": result["status"], "counts": result["counts"], "predicted_regions": result.get("predicted_regions"),
            "reference_regions": result.get("reference_regions"), "matched": result.get("matched", []),
            "reason": result.get("reason")}


def compare_page(base_page: Dict, cand_page: Dict, base_extraction: Dict, cand_extraction: Dict,
                 text_lines: Optional[List[List[float]]]) -> Dict:
    row = {"page": cand_page["page_num"], "status": None, "agreement": None, "text_layer": None,
           "baseline_degenerate_boxes": None}
    base_snapshot, base_missing = metric.captured_snapshot(base_page)
    cand_snapshot, cand_missing = metric.captured_snapshot(cand_page)
    if base_snapshot is None or cand_snapshot is None:
        row["status"] = f"NOT_CAPTURED:{base_missing or '-'}/{cand_missing or '-'}"
        return row
    image_sha = cand_snapshot["input_image"]["sha256"]
    if base_snapshot["input_image"]["sha256"] != image_sha:
        row["status"] = "INPUT_PIXELS_DIFFER"
        return row
    width, height = cand_snapshot["page_size"]
    reference, dropped = clip_regions(snapshot_page_boxes(base_snapshot), width, height, "b")
    row.update(status="PAIRED", baseline_degenerate_boxes=dropped, input_image_sha256=image_sha,
               agreement=compact(score(reference, image_sha, cand_page, cand_extraction)))
    if text_lines is not None:
        lines, _ = clip_regions(text_lines, width, height, "t")
        row["text_layer"] = {"lines": len(lines),
                             "baseline": compact(score(lines, image_sha, base_page, base_extraction)),
                             "candidate": compact(score(lines, image_sha, cand_page, cand_extraction))}
    return row


def page_hmean(result: Optional[Dict]) -> Optional[float]:
    counts = (result or {}).get("counts")
    if counts is None:
        return None
    denominator = 2 * counts["tp"] + counts["fp"] + counts["fn"]
    return 2 * counts["tp"] / denominator if counts["tp"] + counts["fn"] else None


def paired_text_layer(rows: List[Dict]) -> Dict:
    """Page-level sign counts of the candidate minus baseline Hmean against the text layer."""
    better = worse = tied = 0
    for row in rows:
        layer = row.get("text_layer")
        if not layer:
            continue
        base, cand = page_hmean(layer["baseline"]), page_hmean(layer["candidate"])
        if base is None or cand is None:
            continue
        better += cand > base
        worse += cand < base
        tied += cand == base
    return {"pages": better + worse + tied, "candidate_higher": better, "candidate_lower": worse, "tied": tied}


def scope_report(rows: List[Dict]) -> Dict:
    paired = [row for row in rows if row["status"] == "PAIRED"]
    agreement = summarize(paired, "agreement")
    report = {"pages": len(rows), "paired_pages": len(paired),
              "unpaired": sorted({row["status"] for row in rows if row["status"] != "PAIRED"}),
              "agreement": {"matched": agreement["observed_counts"] and agreement["observed_counts"]["tp"],
                            "candidate_only": agreement["observed_counts"] and agreement["observed_counts"]["fp"],
                            "baseline_only": agreement["observed_counts"] and agreement["observed_counts"]["fn"],
                            "candidate_boxes_matched_share": agreement["precision"],
                            "baseline_boxes_matched_share": agreement["recall"],
                            "mean_iou": agreement["mean_iou"], "median_iou": agreement["median_iou"]}}
    layered = [row for row in paired if row.get("text_layer")]
    if layered:
        report["text_layer"] = {"pages": len(layered),
                                "baseline": summarize([row["text_layer"] for row in layered], "baseline"),
                                "candidate": summarize([row["text_layer"] for row in layered], "candidate"),
                                "paired_pages": paired_text_layer(layered)}
    return report


def registry_detector(rel: str, expected_sha256: Optional[str], commit: str) -> Optional[Dict]:
    """Detector entry of the model registry whose bytes the lock hashed (working tree, then the lock commit)."""
    blobs = []
    if (ROOT / rel).is_file():
        blobs.append((ROOT / rel).read_bytes())
    shown = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=ROOT, capture_output=True)
    if shown.returncode == 0:
        # Git stores LF; a Windows checkout with core.autocrlf hashes CRLF bytes.
        blobs += [shown.stdout, shown.stdout.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")]
    for blob in blobs:
        if expected_sha256 and sha256_bytes(blob) == expected_sha256:
            return json.loads(blob.decode("utf-8"))["text_detector"]
    return None


def run_manifest(role: str, experiment_id: str, run_dir: Path, lock_path: Path, data: Dict, exit_code) -> Dict:
    """Fill the spec 05 section 3 fields that the run and its baseline lock record; leave the rest absent."""
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    registry_rel = lock["models"]["registry"]
    commit = lock["git"]["head"]
    detector = registry_detector(registry_rel, lock["models"]["sha256"].get(registry_rel), commit)
    source = (detector or {}).get("source") or {}
    gpu = (lock.get("gpu") or {}).get("gpus") or [{}]
    candidate = {"weights_sha256": (detector or {}).get("sha256"), "repository": source.get("repo"),
                 "revision": source.get("revision"), "weights_licence": source.get("license"),
                 "tokenizer": "none (text detector)"}
    environment = {"gpu": gpu[0].get("name"), "driver": gpu[0].get("driver"),
                   "cuda": (lock.get("gpu") or {}).get("driver_cuda_version"),
                   "backend": (detector or {}).get("adapter")}
    memory = str(gpu[0].get("memory_total", "")).split()
    if memory and memory[0].isdigit():
        environment["vram_mb"] = int(memory[0])
    if exit_code is not None:
        environment["exit_code"] = exit_code
    return {"schema_version": experiment.SCHEMA, "experiment_id": experiment_id, "role": role,
            "run_id": run_dir.name,
            "code": {"commit": commit, "dirty_diff_sha256": lock["git"].get("full_diff_sha256"),
                     "code_fingerprints": lock["code"]["code_fingerprints"]},
            "config": {"profiles_sha256": lock["config"]["sha256"],
                       "model_registry_sha256": lock["models"]["sha256"].get(registry_rel),
                       "lock_sha256": sha256_bytes(lock_path.read_bytes())},
            "candidate": {key: value for key, value in candidate.items() if value is not None},
            "detector_settings": {key: value for key, value in (detector or {}).items() if key != "source"},
            "data": data,
            "protocol": {"metric_versions": {"text_detection": metric.PROTOCOL},
                         "thresholds": {key: SETTINGS[key] for key in ("iou_threshold", "ignore_overlap")}},
            "environment": {key: value for key, value in environment.items() if value is not None},
            "provenance": {"baseline_lock": lock["lock_id"], "environment_source": "baseline lock (captured before the run)"}}


def build(baseline: Path, candidate: Path, *, pdf_root: Optional[Path], inventory: Optional[Dict],
          base_exit, cand_exit, baseline_lock: Path, candidate_lock: Path, experiment_id: str) -> Dict:
    base_docs, cand_docs = documents(baseline), documents(candidate)
    inventory_docs = {doc["pdf"]: doc for doc in (inventory or {}).get("documents", [])}
    doc_reports, all_rows = [], []
    for doc_id in base_docs:
        base, cand = base_docs[doc_id], cand_docs.get(doc_id, {})
        record = {"document": doc_id, "baseline_outcome": base["outcome"], "candidate_outcome": cand.get("outcome"),
                  "pdf_sha256": base["pdf_sha256"], "pages": base["total_pages"], "status": "PAIRED", "rows": []}
        if not (base["completed"] and cand.get("completed")):
            record["status"] = "MISSING_OUTPUT"
            doc_reports.append(record)
            continue
        if base["pdf_sha256"] != cand.get("pdf_sha256"):
            raise ValueError(f"{doc_id}: baseline and candidate read different PDF bytes")
        base_ext, cand_ext = extraction_pages(baseline / doc_id), extraction_pages(candidate / doc_id)
        layer_doc = inventory_docs.get(f"{doc_id}.pdf")
        if layer_doc is not None and layer_doc["sha256"] != base["pdf_sha256"]:
            raise ValueError(f"{doc_id}: inventory PDF bytes differ from the runs")
        pdf = None
        if layer_doc is not None and pdf_root is not None:
            import pymupdf
            path = pdf_root / f"{doc_id}.pdf"
            if sha256_bytes(path.read_bytes()) != base["pdf_sha256"]:
                raise ValueError(f"{doc_id}: PDF under {pdf_root} differs from the runs")
            pdf = pymupdf.open(path)
        layer_pages = {row["page"]: row for row in (layer_doc or {}).get("page_records", [])}
        try:
            for page_path in sorted((candidate / doc_id / "pages").glob("page-*.json")):
                base_path = baseline / doc_id / "pages" / page_path.name
                cand_page, _ = metric.read_page(page_path)
                base_page, _ = metric.read_page(base_path)
                number = cand_page["page_num"]
                if base_page is None:
                    record["rows"].append({"page": number, "status": "MISSING_BASELINE_PAGE"})
                    continue
                lines, layer_state = None, "NOT_REQUESTED" if pdf is None else None
                info = layer_pages.get(number)
                if pdf is not None:
                    pdf_page = pdf[number - 1]
                    if not info or info["status"] != "CANDIDATE":
                        layer_state = "NOT_CANDIDATE"
                    elif info["max_image_cover"] > MAX_IMAGE_COVER:
                        layer_state = "IMAGE_COVERED"
                    elif (pdf_page.rotation != 0 or tuple(pdf_page.rect) != tuple(pdf_page.mediabox)
                          or not identity_frame(cand_page)
                          or abs(pdf_page.rect.width - cand_page["width"]) > 0.01
                          or abs(pdf_page.rect.height - cand_page["height"]) > 0.01):
                        layer_state = "UNSUPPORTED_FRAME"
                    else:
                        lines, layer_state = text_layer_lines(pdf_page), "SCORED"
                row = compare_page(base_page, cand_page, base_ext[number], cand_ext[number], lines)
                row["text_layer_state"] = "NOT_PAIRED" if layer_state == "SCORED" and row["status"] != "PAIRED" else layer_state
                row["dpi"] = cand_page.get("rendered_dpi")
                record["rows"].append(row)
        finally:
            if pdf is not None:
                pdf.close()
        if len(record["rows"]) != base["total_pages"]:
            record["status"] = "INCOMPLETE_PAGES"
        all_rows += record["rows"]
        doc_reports.append(record)
    paired_docs = [doc for doc in doc_reports if doc["status"] == "PAIRED"]
    image_pairs, dpis = [], set()
    for doc in paired_docs:
        for row in doc["rows"]:
            if row["status"] == "PAIRED":
                image_pairs.append([doc["document"], row["page"], row["input_image_sha256"]])
                dpis.add(row.get("dpi"))
    data = {"pdf_manifest_sha256": sha256_json(sorted([doc["document"], doc["pdf_sha256"]] for doc in paired_docs)),
            "page_selection": [f"{doc}:{page}" for doc, page, _ in image_pairs],
            "image_manifest_sha256": sha256_json(image_pairs), "split": "development"}
    if len(dpis) == 1 and type(next(iter(dpis))) in (int, float):
        data["dpi"] = next(iter(dpis))
    manifests = {"baseline": run_manifest("baseline", experiment_id, baseline, baseline_lock, data, base_exit),
                 "candidate": run_manifest("candidate", experiment_id, candidate, candidate_lock, data, cand_exit)}
    pair = experiment.validate_pair(manifests["baseline"], manifests["candidate"])
    declared_pages = sum(doc["pages"] for doc in doc_reports)
    for doc in doc_reports:
        doc["summary"] = scope_report(doc["rows"]) if doc["rows"] else None
    return {
        "schema_version": SCHEMA, "experiment_id": experiment_id, "quality_acceptance": "NOT_EVALUATED",
        "reference_kinds": {"agreement": "baseline detector boxes; agreement, not accuracy",
                            "text_layer": "unverified born-digital text-layer lines; diagnostic, not GT"},
        "settings": {**SETTINGS, "max_image_cover": MAX_IMAGE_COVER, "stage": "PHASE_A_PRIMARY_DETECTOR_BEFORE_RETRY"},
        "runs": {"baseline": str(baseline), "candidate": str(candidate)},
        "coverage": {"declared_documents": len(doc_reports), "paired_documents": len(paired_docs),
                     "declared_pages": declared_pages, "paired_pages": len(image_pairs),
                     "missing_documents": [{key: doc[key] for key in ("document", "baseline_outcome", "candidate_outcome")}
                                           for doc in doc_reports if doc["status"] != "PAIRED"],
                     "text_layer_states": {state: sum(row.get("text_layer_state") == state for row in all_rows)
                                           for state in sorted({row.get("text_layer_state") for row in all_rows} - {None})}},
        "overall_paired_scope": scope_report(all_rows),
        "documents": [{key: doc[key] for key in doc if key != "rows"} | {"pages_detail": doc["rows"]} for doc in doc_reports],
        "manifests": manifests, "pair_validation": pair,
        "decision_options": list(experiment.decision_options(pair, protocol_locked=False, independent_gt=False)),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-lock", type=Path, required=True)
    parser.add_argument("--candidate-lock", type=Path, required=True)
    parser.add_argument("--baseline-exit-code", type=int, help="Batch exit code, when it was recorded")
    parser.add_argument("--candidate-exit-code", type=int, help="Batch exit code, when it was recorded")
    parser.add_argument("--pdf-root", type=Path)
    parser.add_argument("--inventory", type=Path, help="Text-layer inventory JSON (needs --pdf-root)")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--report", type=Path, required=True, help="New JSON report (never overwritten)")
    args = parser.parse_args(argv)
    experiment.parse_experiment_id(args.experiment_id)
    if args.report.exists():
        parser.error(f"{args.report} exists")
    if args.inventory and not args.pdf_root:
        parser.error("--inventory needs --pdf-root")
    inventory = json.loads(args.inventory.read_text(encoding="utf-8")) if args.inventory else None
    report = build(args.baseline, args.candidate, pdf_root=args.pdf_root, inventory=inventory,
                   base_exit=args.baseline_exit_code, cand_exit=args.candidate_exit_code,
                   baseline_lock=args.baseline_lock, candidate_lock=args.candidate_lock,
                   experiment_id=args.experiment_id)
    if inventory is not None:
        report["inventory_sha256"] = sha256_bytes(args.inventory.read_bytes())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    coverage, overall = report["coverage"], report["overall_paired_scope"]
    print(f"paired {coverage['paired_documents']}/{coverage['declared_documents']} documents, "
          f"{coverage['paired_pages']}/{coverage['declared_pages']} pages; pair {report['pair_validation']['status']}")
    print("agreement:", json.dumps(overall["agreement"]))
    if "text_layer" in overall:
        for role in ("baseline", "candidate"):
            row = overall["text_layer"][role]
            print(f"text layer {role}: P {row['precision']} R {row['recall']} H {row['hmean']} "
                  f"mean IoU {row['mean_iou']} counts {row['observed_counts']}")
        print("paired pages:", json.dumps(overall["text_layer"]["paired_pages"]))
    print(f"decision options {report['decision_options']} -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
