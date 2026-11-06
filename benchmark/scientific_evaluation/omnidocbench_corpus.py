"""Prepare pixel-preserving PDF inputs and a frozen OmniDocBench export plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import pymupdf

from ocr_artifacts.hashing import sha256_file

from .omnidocbench_adapter import REPOSITORY, REVISION, SCHEMA, _file, _image_name, _pinned_json, _require, _verify_image_pdf


def _pdf_bytes(image, width, height, dpi):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=width * 72 / dpi, height=height * 72 / dpi)
        page.insert_image(page.rect, stream=image)
        return pdf.tobytes(garbage=4, deflate=True, no_new_id=True)


def prepare_corpus(gt_path, gt_hash, dataset_root, image_directory, dataset_version, dataset_revision, output, *, dpi=180):
    dataset_root, gt_path, output = (Path(path).resolve() for path in (dataset_root, gt_path, output))
    image_root = (dataset_root / image_directory).resolve()
    _require(gt_path.is_relative_to(dataset_root) and image_root.is_relative_to(dataset_root)
             and not output.exists() and not output.is_relative_to(dataset_root)
             and not any((parent / marker).is_file() for parent in output.parents
                         for marker in ("batch_input_manifest.json", "COMPLETED.json")),
             "Use source paths inside the dataset and a new preparation output outside datasets and publications")
    _require(type(dpi) is int and dpi > 0 and isinstance(dataset_version, str) and dataset_version.strip()
             and isinstance(dataset_revision, str) and re.fullmatch(r"[0-9a-f]{40}", dataset_revision),
             "Dataset version/revision and positive integral DPI are required")
    watched = {}
    ground_truth = _pinned_json(gt_path, gt_hash, watched)
    _require(isinstance(ground_truth, list) and ground_truth, "Expected a nonempty OmniDocBench GT page list")
    names = [_image_name(row["page_info"]["image_path"]) for row in ground_truth]
    _require(len(names) == len({name.casefold() for name in names})
             and len(names) == len({name[:-4].casefold() for name in names}), "GT image/Markdown filenames must be unique")
    sources = []
    pdfs = {}
    runtime = {"python": sys.version.split()[0], "pymupdf": pymupdf.__version__}
    output.mkdir(parents=True, exist_ok=False)
    (output / "inputs").mkdir()
    for name, gt in zip(names, ground_truth, strict=True):
        image = image_root / name
        descriptor = {"path": image.relative_to(dataset_root).as_posix(), "sha256": sha256_file(image)}
        image = _file(dataset_root, descriptor, watched)
        pixmap = pymupdf.Pixmap(image)
        _require(not pixmap.alpha and (gt["page_info"]["width"], gt["page_info"]["height"]) == (pixmap.width, pixmap.height),
                 f"GT dimensions or source image opacity differ: {name}")
        raw = _pdf_bytes(image.read_bytes(), pixmap.width, pixmap.height, dpi)
        digest = hashlib.sha256(raw).hexdigest()
        key = "omni-" + digest[:24]
        _require(key not in pdfs or pdfs[key]["pdf_sha256"] == digest, "Prepared PDF ID collision")
        pdf = output / "inputs" / f"{key}.pdf"
        if key not in pdfs:
            with pdf.open("xb") as stream:
                stream.write(raw)
            pdfs[key] = {"document_id": key, "pdf_sha256": digest, "path": pdf.relative_to(output).as_posix(),
                         "image_names": []}
        proof = _verify_image_pdf(pdf, image)
        pdfs[key]["image_names"].append(name)
        sources.append({"image_name": name, "image": descriptor, "document_id": key,
                        "pdf_sha256": digest, "pixel_proof": proof})
    _require(all(sha256_file(path) == digest for path, digest in watched.items()), "Dataset source changed during preparation")
    plan = {"schema_version": SCHEMA, "partition": "development", "dataset_version": dataset_version,
            "dataset_revision": dataset_revision, "evaluator": {"repository": REPOSITORY, "revision": REVISION},
            "ground_truth": {"path": gt_path.relative_to(dataset_root).as_posix(), "sha256": gt_hash},
            "sources": sources, "preparation": {"method": "embedded-source-image-v1", "dpi": dpi,
                                               "generator_sha256": sha256_file(Path(__file__)), "runtime": runtime}}
    plan_path = output / "export-plan.json"
    with plan_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    report = {"schema_version": "ocr-omnidocbench-input-preparation-v1", "status": "INPUTS_PREPARED",
              "quality_acceptance": "NOT_EVALUATED", "new_model_inference": False, "ground_truth_sha256": gt_hash,
              "plan": {"path": plan_path.name, "sha256": sha256_file(plan_path)}, "dataset_revision": dataset_revision,
              "image_units": len(sources), "distinct_pdf_inputs": len(pdfs), "inputs": list(pdfs.values()),
              "alias_groups": [row for row in pdfs.values() if len(row["image_names"]) > 1],
              "generator_sha256": sha256_file(Path(__file__)), "runtime": runtime}
    with (output / "prepared.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("ground-truth", "dataset-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("ground-truth-sha256", "dataset-version", "dataset-revision"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--image-directory", default="images")
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args(argv)
    try:
        report = prepare_corpus(args.ground_truth, args.ground_truth_sha256, args.dataset_root, args.image_directory,
                                args.dataset_version, args.dataset_revision, args.output, dpi=args.dpi)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Prepared {report['distinct_pdf_inputs']} image-only PDF inputs for {report['image_units']} GT pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
