"""Export paired canonical predictions for the pinned OmniDocBench evaluator."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import pymupdf
import yaml

from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file

from . import markdown_evaluator
from .canonical_predictions import collect_predictions, pair_predictions
from .degradation_metric import _unique_object

SCHEMA = "ocr-omnidocbench-export-plan-v1"
REVISION = "ea2d138c7d2e185feb71ef8014e97d7206820b34"
REPOSITORY = "https://github.com/opendatalab/OmniDocBench"
METHOD = "canonical-single-image-pdf-to-page-markdown-v1"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _pinned_json(path, expected, watched):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    _require(digest == expected and watched.get(path, digest) == digest, f"JSON hash mismatch: {path}")
    watched[path] = digest
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)


def _file(root, descriptor, watched):
    relative = Path(descriptor["path"])
    path = (root / relative).resolve()
    _require(not relative.anchor and path.is_relative_to(root) and sha256_file(path) == descriptor["sha256"],
             f"Dataset artifact identity differs: {relative}")
    watched[path] = descriptor["sha256"]
    return path


def _image_name(value):
    _require(isinstance(value, str) and value and "\\" not in value, "Expected a POSIX image path")
    name = value.rsplit("/", 1)[-1]
    _require(Path(name).suffix.lower() in (".jpg", ".png") and name not in (".jpg", ".png")
             and not re.search(r'[<>:"|?*]', name)
             and not re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", name.split(".")[0], re.I),
             "Use a portable JPG/PNG image name")
    # The pinned official resolver uses img_name[:-4] + '.md'.
    return name


def _verify_image_pdf(pdf_path, image_path):
    """Require the original page pixels, with no native text or added marks."""
    original = pymupdf.Pixmap(image_path)
    _require(not original.alpha, "Benchmark source images must be opaque")
    original = pymupdf.Pixmap(pymupdf.csRGB, original)
    with pymupdf.open(pdf_path) as pdf:
        _require(len(pdf) == 1, "Benchmark input PDF must contain one image-only page")
        page = pdf[0]
        images = page.get_images(full=True)
        _require(page.rotation == 0 and not page.get_text() and not page.get_drawings()
                 and page.first_annot is None and page.first_widget is None and len(images) == 1,
                 "Benchmark input PDF must preserve only its source image")
        _require(images[0][1] == 0 and all(pdf.xref_get_key(images[0][0], key)[0] == "null"
                                         for key in ("Mask", "SMask")),
                 "Benchmark input PDF must not mask its source image")
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.Pixmap(pdf, images[0][0]))
        rects = page.get_image_rects(images[0][0], transform=True)
        _require(len(rects) == 1 and all(abs(a-b) <= .001 for a, b in zip(rects[0][0], page.rect, strict=True)),
                 "Benchmark image must fill the PDF page without clipping")
        matrix = rects[0][1]
        _require(matrix.a > 0 and matrix.d > 0 and matrix.b == matrix.c == 0
                 and (pixmap.width, pixmap.height, pixmap.samples) == (original.width, original.height, original.samples),
                 "Benchmark input PDF pixels or orientation differ from the pinned image")
        rendered = page.get_pixmap(matrix=pymupdf.Matrix(original.width / page.rect.width,
                                                       original.height / page.rect.height),
                                   colorspace=pymupdf.csRGB, alpha=False)
        _require((rendered.width, rendered.height, rendered.samples) == (original.width, original.height, original.samples),
                 "Visible benchmark PDF pixels differ from the pinned image")
    return {"image_width": original.width, "image_height": original.height,
            "rgb_pixels_sha256": hashlib.sha256(original.samples).hexdigest(),
            "rendered_rgb_pixels_sha256": hashlib.sha256(rendered.samples).hexdigest()}


def _page_markdown(raw):
    text = raw.decode("utf-8").replace("\r\n", "\n")
    markers = list(markdown_evaluator._PAGE_MARKER_PATTERN.finditer(text))
    _require(len(markers) == 1 and int(markers[0].group(1) or markers[0].group(2)) == 1,
             "Expected exactly one physical page marker")
    prefix, body = text[:markers[0].start()], text[markers[0].end():]
    body = body.strip("\n")
    if prefix.startswith("# Báo cáo trích xuất tài liệu:"):
        if body == "---":
            body = ""
        elif body.endswith("\n\n---"):
            body = body[:-5].strip("\n")
    return body


def _export_document(doc, image_name, output, watched):
    directory = Path(doc["source_dir"])
    complete_path = directory / "COMPLETED.json"
    complete = _pinned_json(complete_path, doc["completion_sha256"], watched)
    markdown = directory / "result.md"
    _require(sha256_file(markdown) == doc["result_md_sha256"] == complete["files"]["result.md"], "Published Markdown differs")
    watched[markdown] = doc["result_md_sha256"]
    body = _page_markdown(markdown.read_bytes())
    assets = {}

    def asset(match):
        relative = Path(match.group(2))
        source = (directory / relative).resolve()
        digest = complete["files"].get(relative.as_posix())
        _require(not relative.anchor and source.is_relative_to(directory) and digest
                 and sha256_file(source) == digest, "Image reference differs from publication")
        watched[source] = digest
        target = output / "assets" / doc["id"] / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(source.read_bytes())
        _require(sha256_file(target) == digest, "Exported asset changed")
        assets[target.relative_to(output).as_posix()] = digest
        return f"![{match.group(1)}](../{target.relative_to(output).as_posix()})"

    body = markdown_evaluator._IMAGE_LINK_PATTERN.sub(asset, body)
    target = output / "predictions" / (image_name[:-4] + ".md")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(body)
    return {"document_id": doc["id"], "image_name": image_name, "completion_sha256": doc["completion_sha256"],
            "result_md_sha256": doc["result_md_sha256"], "prediction": target.relative_to(output).as_posix(),
            "prediction_sha256": sha256_file(target), "assets": assets}


def export_pairs(plan_path, plan_hash, dataset_root, baseline_roots, candidate_roots, output):
    plan_path, dataset_root, output = (Path(path).resolve() for path in (plan_path, dataset_root, output))
    baseline_roots, candidate_roots = ([Path(path).resolve() for path in roots] for roots in (baseline_roots, candidate_roots))
    roots = [*baseline_roots, *candidate_roots]
    _require(not output.exists() and not output.is_relative_to(dataset_root)
             and not any(output.is_relative_to(path) for path in roots)
             and not any((parent / name).is_file() for parent in output.parents
                         for name in ("batch_input_manifest.json", "COMPLETED.json")),
             "Use a new export directory outside dataset and publications")
    watched = {}
    plan = _pinned_json(plan_path, plan_hash, watched)
    _require(plan.get("schema_version") == SCHEMA and plan.get("partition") == "development"
             and plan.get("evaluator") == {"repository": REPOSITORY, "revision": REVISION}
             and isinstance(plan.get("dataset_version"), str) and bool(plan["dataset_version"].strip())
             and re.fullmatch(r"[0-9a-f]{40}", plan.get("dataset_revision", "")),
             "Expected a development OmniDocBench plan with explicit dataset and evaluator revisions")
    gt_path = _file(dataset_root, plan["ground_truth"], watched)
    ground_truth = _pinned_json(gt_path, plan["ground_truth"]["sha256"], watched)
    _require(isinstance(ground_truth, list) and ground_truth, "Expected official page annotations")
    names = [_image_name(row["page_info"]["image_path"]) for row in ground_truth]
    sources = plan["sources"]
    by_image = {_image_name(row["image_name"]): row for row in sources}
    _require(len(names) == len(set(name.casefold() for name in names)) == len(sources) == len(by_image)
             and set(names) == by_image.keys() and len({name[:-4].casefold() for name in names}) == len(names),
             "Map each frozen GT image exactly once with unique Markdown filenames")
    identifiers = {row["document_id"] for row in sources}
    _require(len({key.casefold() for key in identifiers}) == len(identifiers), "PDF ID aliases must use one spelling")
    aliases = {key: [row["image_name"] for row in sources if row["document_id"] == key] for key in sorted(identifiers)}
    images = {name: _file(dataset_root, by_image[name]["image"], watched) for name in names}
    _require(all(images[name].name == name for name in names), "Dataset image filename differs from its GT name")
    baseline, candidate = collect_predictions(list(baseline_roots)), collect_predictions(list(candidate_roots))
    pairs = pair_predictions(baseline, candidate)
    _require({row["id"] for row in pairs} == {row["document_id"] for row in sources},
             "Canonical PDF membership differs from the frozen image plan")
    documents = {side: {row["id"]: row for row in inventory["documents"]}
                 for side, inventory in (("baseline", baseline), ("candidate", candidate))}
    source_proof = {}
    for name, gt_row in zip(names, ground_truth, strict=True):
        mapping = by_image[name]
        pdf = documents["candidate"][mapping["document_id"]]
        _require(pdf["pdf_sha256"] == mapping["pdf_sha256"] and pdf["total_pages"] == 1, "Mapped PDF identity or page count differs")
        path = Path(pdf["pdf_path"])
        _require(sha256_file(path) == mapping["pdf_sha256"], "Benchmark PDF changed")
        watched[path] = mapping["pdf_sha256"]
        source_proof[name] = _verify_image_pdf(path, images[name])
        gt = gt_row["page_info"]
        _require((gt["width"], gt["height"]) == (source_proof[name]["image_width"], source_proof[name]["image_height"]),
                 "GT dimensions differ from the pinned source image")
    output.mkdir(parents=True, exist_ok=False)
    with (output / "ground-truth.json").open("xb") as stream:
        stream.write(gt_path.read_bytes())
    exports = {}
    for side in ("baseline", "candidate"):
        destination = output / side
        exports[side] = [_export_document(documents[side][by_image[name]["document_id"]], name, destination, watched) for name in names]
        config = {"end2end_eval": {"metrics": {
            "text_block": {"metric": ["Edit_dist"]}, "display_formula": {"metric": ["Edit_dist", "CDM"], "cdm_workers": 1},
            "table": {"metric": ["TEDS", "Edit_dist"], "teds_workers": 1}, "reading_order": {"metric": ["Edit_dist"]}},
            "dataset": {"dataset_name": "end2end_dataset", "ground_truth": {"data_path": str(output / "ground-truth.json")},
                        "prediction": {"data_path": str(destination / "predictions")}, "match_method": "quick_match",
                        "match_workers": 1, "quick_match_truncated_timeout_sec": 300, "match_timeout_sec": 420,
                        "timeout_fallback_max_chunk_span": 10, "timeout_fallback_order_penalty": .10}}}
        with (destination / "end2end.yaml").open("x", encoding="utf-8") as stream:
            yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False)
    _require(all(sha256_file(path) == digest for path, digest in watched.items()), "Export sources changed")
    report = {"schema_version": "ocr-omnidocbench-paired-export-v1", "method": METHOD, "status": "PAIRED_EXPORT_VERIFIED",
              "quality_acceptance": "NOT_EVALUATED", "official_evaluation": "NOT_RUN", "partition": "development",
              "plan_sha256": plan_hash, "dataset_version": plan["dataset_version"], "dataset_revision": plan["dataset_revision"],
              "ground_truth_sha256": plan["ground_truth"]["sha256"], "evaluator": plan["evaluator"], "source_images": source_proof,
              "image_units": len(sources), "distinct_pdf_inputs": len(identifiers),
              "pdf_alias_groups": {key: names for key, names in aliases.items() if len(names) > 1},
              "source_policy": "pinned_image_only_pdf_without_native_text", "exports": exports,
              "prediction_inventory_sha256": {"baseline": sha256_json_compact(baseline), "candidate": sha256_json_compact(candidate)},
              "adapter_sha256": sha256_file(Path(__file__)),
              "page_marker_parser_sha256": sha256_file(Path(markdown_evaluator.__file__)),
              "files": {path.relative_to(output).as_posix(): sha256_file(path) for path in sorted(output.rglob("*")) if path.is_file()}}
    with (output / "export.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("plan", "dataset-root", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    for side in ("baseline", "candidate"):
        parser.add_argument("--" + side, type=Path, nargs="+", required=True)
    args = parser.parse_args(argv)
    try:
        report = export_pairs(args.plan, args.plan_sha256, args.dataset_root, args.baseline, args.candidate, args.output)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(f"Exported paired Markdown for {len(report['source_images'])} benchmark pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
