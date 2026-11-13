"""Prepare source-bound OmniDocBench formula labels and a development scorecard."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from ocr_artifacts.hashing import sha256_file
from . import formula_alignment, formula_scorecard
from .canonical_predictions import collect_predictions
from .omnidocbench_adapter import (
    REPOSITORY, REVISION, SCHEMA, _file, _image_name, _pinned_json, _require, _verify_image_pdf,
)

PREPARATION_SCHEMA = "ocr-omnidocbench-formula-preparation-v1"


def _write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _new_output(output, protected):
    _require(not output.exists() and all(not output.is_relative_to(p) and not p.is_relative_to(output)
                                       for p in protected)
             and not any((parent / marker).exists() for parent in output.parents
                         for marker in ("COMPLETED.json", "batch_input_manifest.json")),
             "Use a new output outside source datasets, inputs and publications")


def _bbox(poly, width, height, page_width, page_height):
    _require(isinstance(poly, list) and len(poly) == 8
             and all(type(v) in (int, float) and math.isfinite(v) for v in poly), "Invalid formula polygon")
    xs, ys = poly[::2], poly[1::2]
    _require(0 <= min(xs) < max(xs) <= width and 0 <= min(ys) < max(ys) <= height,
             "Formula polygon outside pinned image")
    return [min(xs) * page_width / width, min(ys) * page_height / height,
            max(xs) * page_width / width, max(ys) * page_height / height]


def _page_labels(gt, width, height):
    """Keep the dataset's display regions and direct inline spans, without inventing text."""
    info = gt["page_info"]
    formulas, ignores, excluded = [], [], Counter()
    seen = set()
    for block_index, block in enumerate(gt["layout_dets"]):
        # A merged block is represented by its top-level annotation; merge_list is
        # not a second set of independent references.
        entries = [(f"block-{block_index}", block, block.get("ignore", False))]
        entries += [(f"block-{block_index}-span-{i}", span, block.get("ignore", False))
                    for i, span in enumerate(block.get("line_with_spans", []))]
        for key, item, parent_ignored in entries:
            category = item["category_type"]
            if category not in ("equation_isolated", "equation_inline", "equation_ignore"):
                excluded[category] += 1
                continue
            _require(type(item.get("ignore", False)) is bool and type(parent_ignored) is bool,
                     "Formula ignore flags must be boolean")
            box = _bbox(item["poly"], info["width"], info["height"], width, height)
            if parent_ignored or item.get("ignore", False) or category == "equation_ignore":
                ignores.append({"id": key, "bbox": box, "reason": "OmniDocBench ignored formula"})
                continue
            content = item.get("latex")
            _require(isinstance(content, str) and bool(content.strip()), "Formula lacks a LaTeX reference")
            signature = (category, tuple(box), content)
            _require(signature not in seen, "Duplicate formula geometry/content in source annotations")
            seen.add(signature)
            formulas.append({"id": key, "bbox": box, "format": "LATEX", "content_raw": content,
                             "placement": "display" if category == "equation_isolated" else "inline",
                             "equation_label": None, "source_anno_id": item.get("anno_id"),
                             "source_polygon": item["poly"], "source_category": category})
    return {"page": 1, "coordinate_space": "pdf_points_top_left", "transforms": [],
            "width": width, "height": height, "formulas": formulas, "ignore_regions": ignores}, excluded


def prepare(plan_path, plan_hash, dataset_root, inputs, output):
    plan_path, dataset_root, inputs, output = (
        Path(p).resolve() for p in (plan_path, dataset_root, inputs, output))
    _new_output(output, [dataset_root, inputs, plan_path])
    watched = {}
    plan = _pinned_json(plan_path, plan_hash, watched)
    _require(plan.get("schema_version") == SCHEMA and plan.get("partition") == "development"
             and plan.get("evaluator") == {"repository": REPOSITORY, "revision": REVISION},
             "Expected a pinned development OmniDocBench export plan")
    gt_path = _file(dataset_root, plan["ground_truth"], watched)
    ground_truth = _pinned_json(gt_path, plan["ground_truth"]["sha256"], watched)
    sources = plan["sources"]
    by_image = {_image_name(s["image_name"]): s for s in sources}
    names = [_image_name(gt["page_info"]["image_path"]) for gt in ground_truth]
    _require(names and len(names) == len({n.casefold() for n in names}) == len(sources) == len(by_image)
             and set(names) == by_image.keys(), "Map every pinned GT image exactly once")
    # The formula scorecard is keyed by PDF, not image alias. Refuse alias datasets
    # rather than silently dropping or multiplying annotations for the same PDF.
    ids = [s["document_id"] for s in sources]
    _require(all(isinstance(k, str) and k and Path(k).name == k and not any(c in k for c in '/\\:') for k in ids)
             and len({k.casefold() for k in ids}) == len(ids), "Formula preparation requires distinct portable PDF IDs")
    _require({p.stem for p in inputs.glob("*.pdf")} == set(ids), "Input PDF membership differs from plan")
    documents, proofs, catalog = [], {}, []
    excluded = Counter()
    for name, gt in zip(names, ground_truth, strict=True):
        source = by_image[name]
        image = _file(dataset_root, source["image"], watched)
        _require(image.name == name, "Pinned image name differs from GT")
        pdf = inputs / (source["document_id"] + ".pdf")
        _require(sha256_file(pdf) == source["pdf_sha256"], "Input PDF hash differs from plan")
        watched[pdf] = source["pdf_sha256"]
        proof = _verify_image_pdf(pdf, image)
        _require((gt["page_info"]["width"], gt["page_info"]["height"])
                 == (proof["image_width"], proof["image_height"]), "GT dimensions differ from image")
        with pymupdf.open(pdf) as doc:
            page, omitted = _page_labels(gt, doc[0].rect.width, doc[0].rect.height)
        excluded.update(omitted)
        documents.append({"document_id": source["document_id"], "pdf_sha256": source["pdf_sha256"],
                          "total_pages": 1, "pages": [page], "source_image": name})
        proofs[name] = proof
        catalog.append({"document_id": source["document_id"], "relative_path": pdf.name,
                        "company_id": "unknown", "sha256": source["pdf_sha256"], "pages": 1, "status": "OK"})
    _require(all(sha256_file(p) == h for p, h in watched.items()), "Source changed during preparation")
    output.mkdir(parents=True)
    annotation = {"schema_version": formula_alignment.ANNOTATION_SCHEMA, "documents": documents,
                  "annotation_origin": "PINNED_EXTERNAL_DATASET", "plan_sha256": plan_hash,
                  "ground_truth_sha256": plan["ground_truth"]["sha256"]}
    _write(output / "annotations.json", annotation)
    # Unknown companies prevent invented company-cluster confidence intervals.
    from src.ocr.collect.catalog import FIELDS
    with (output / "sources.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({**dict.fromkeys(FIELDS, "unknown"), **row, "error": ""} for row in catalog)
    counts = Counter(f["placement"] for d in documents for f in d["pages"][0]["formulas"])
    report = {"schema_version": PREPARATION_SCHEMA, "partition": "development",
              "status": "PREPARED", "quality_acceptance": "NOT_EVALUATED", "plan_sha256": plan_hash,
              "dataset_revision": plan["dataset_revision"], "ground_truth_sha256": plan["ground_truth"]["sha256"],
              "documents": len(documents), "formula_references": dict(counts), "excluded_categories": dict(excluded),
              "geometry_method": "source_polygon_axis_aligned_envelope_scaled_to_pdf_points",
              "source_images": proofs, "adapter_sha256": sha256_file(Path(__file__)),
              "limitations": ["Development external dataset; not a release holdout or official OmniDocBench score",
                              "LaTeX references cannot establish TEXT CER", "No independent critical-symbol review",
                              "Absent inline references do not establish inline quality", "Company IDs are unknown"],
              "files": {n: sha256_file(output / n) for n in ("annotations.json", "sources.csv")}}
    _write(output / "prepared.json", report)
    return report


def score(prepared, prepared_hash, batches, output, *, iou_threshold, cdm=None, critical=None):
    prepared, output = Path(prepared).resolve(), Path(output).resolve()
    batches = [Path(p).resolve() for p in batches]
    _new_output(output, [prepared, *batches])
    watched = {}
    metadata = _pinned_json(prepared / "prepared.json", prepared_hash, watched)
    _require(metadata.get("schema_version") == PREPARATION_SCHEMA and metadata.get("partition") == "development",
             "Expected prepared development formula labels")
    for name in ("annotations.json", "sources.csv"):
        _require(sha256_file(prepared / name) == metadata["files"][name], "Prepared formula evidence changed")
        watched[prepared / name] = metadata["files"][name]
    annotations = _pinned_json(prepared / "annotations.json", metadata["files"]["annotations.json"], watched)
    publication = collect_predictions(batches)
    labels = {d["document_id"]: d for d in annotations["documents"]}
    _require(len(labels) == len(annotations["documents"]) and {d["id"] for d in publication["documents"]} == labels.keys(),
             "Publication must cover the entire frozen formula sample exactly")
    _require(type(iou_threshold) in (int, float) and math.isfinite(iou_threshold) and 0 < iou_threshold <= 1,
             "IoU threshold must be in (0, 1]")
    alignment, pairs = formula_alignment._align_publication(
        publication, labels, metadata["files"]["annotations.json"], iou_threshold)
    output.mkdir(parents=True)
    alignment_path, pairs_path = formula_alignment.write_alignment(output / "alignment", alignment, pairs)
    report = formula_scorecard.evaluate(SimpleNamespace(
        sources=prepared / "sources.csv", sample=None, candidate_alignment=alignment_path, candidate_pairs=pairs_path,
        candidate_critical=critical, candidate_cdm=cdm, baseline_alignment=None, baseline_pairs=None,
        baseline_critical=None, baseline_cdm=None, seed=42, resamples=2000, confidence=.95, min_companies=2))
    _write(output / "scorecard.json", report)
    _require(all(sha256_file(p) == h for p, h in watched.items()), "Prepared formula evidence changed during scoring")
    result = {"schema_version": "ocr-omnidocbench-formula-run-v1", "status": "SCORED_DEVELOPMENT",
              "quality_acceptance": "NOT_EVALUATED", "official_evaluation": "NOT_RUN",
              "prepared_sha256": prepared_hash, "iou_threshold": iou_threshold, "batches": publication["batches"],
              "adapter_sha256": sha256_file(Path(__file__)), "limitations": metadata["limitations"],
              "files": {str(p.relative_to(output)).replace("\\", "/"): sha256_file(p)
                        for p in sorted(output.rglob("*")) if p.is_file()}}
    _write(output / "run.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", allow_abbrev=False)
    for name in ("plan", "dataset-root", "inputs", "output"):
        prep.add_argument("--" + name, type=Path, required=True)
    prep.add_argument("--plan-sha256", required=True)
    run = commands.add_parser("score", allow_abbrev=False)
    for name in ("prepared", "output"):
        run.add_argument("--" + name, type=Path, required=True)
    run.add_argument("--prepared-sha256", required=True)
    run.add_argument("--batch", type=Path, nargs="+", required=True)
    run.add_argument("--iou-threshold", type=float, required=True)
    run.add_argument("--cdm", type=Path)
    run.add_argument("--critical", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            report = prepare(args.plan, args.plan_sha256, args.dataset_root, args.inputs, args.output)
        else:
            report = score(args.prepared, args.prepared_sha256, args.batch, args.output,
                           iou_threshold=args.iou_threshold, cdm=args.cdm, critical=args.critical)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({k: report[k] for k in ("status", "quality_acceptance")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
