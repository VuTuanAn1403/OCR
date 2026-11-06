"""Build reproducible image-only development PDFs for paired degradation tests."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sys

from ocr_artifacts.hashing import sha256_file

from .degradation_metric import INPUT_SCHEMA, _conditions, _unique_object

PLAN_SCHEMA = "paired-degradation-render-plan-v1"
MANIFEST_SCHEMA = "paired-degradation-render-manifest-v1"
METHOD = "grayscale-common-canvas-v1"
MAX_PIXELS = 20_000_000
MAX_VARIANTS = 256


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _safe_id(value):
    return (isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value) is not None
            and re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", value) is None)


def _save_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def _load_plan(path, pdf_root):
    raw = path.read_bytes()
    plan = json.loads(raw, object_pairs_hook=_unique_object)
    fields = {"schema_version", "partition", "dpi", "seed", "sources", "conditions"}
    _require(isinstance(plan, dict) and plan.keys() == fields and plan["schema_version"] == PLAN_SCHEMA
             and plan["partition"] == "development", "Expected a development raster plan")
    _require(type(plan["dpi"]) is int and 72 <= plan["dpi"] <= 300 and type(plan["seed"]) is int
             and 0 <= plan["seed"] < 2**64, "Invalid development raster DPI or seed")
    _conditions(plan["conditions"])
    _require(all(_safe_id(row["id"]) for row in plan["conditions"]), "Condition IDs must be safe filenames")
    _require(all(row["kind"] != "salt_pepper" or row["level"] <= .05 for row in plan["conditions"]),
             "Development salt-and-pepper density is limited to five percent")
    sources = plan["sources"]
    _require(isinstance(sources, list) and sources and len(sources) * len(plan["conditions"]) <= MAX_VARIANTS,
             "Invalid source list or too many source/condition pairs")
    paths, source_hashes, ids, units = {}, {}, set(), set()
    for row in sources:
        _require(isinstance(row, dict) and row.keys() == {"id", "pdf_path", "pdf_sha256", "page"}
                 and _safe_id(row["id"]) and row["id"] not in ids and type(row["page"]) is int and row["page"] > 0,
                 "Expected unique source IDs and positive physical pages")
        relative = Path(row["pdf_path"])
        pdf = (pdf_root / relative).resolve()
        _require(not relative.anchor and pdf.is_relative_to(pdf_root) and pdf.suffix.lower() == ".pdf",
                 "Source PDFs must be inside the declared PDF root")
        if pdf not in source_hashes:
            source_hashes[pdf] = sha256_file(pdf)
        unit = source_hashes[pdf], row["page"]
        _require(source_hashes[pdf] == row["pdf_sha256"] and unit not in units,
                 "Source PDF hash differs or source page is duplicated")
        ids.add(row["id"])
        units.add(unit)
        paths[row["id"]] = pdf
    return plan, hashlib.sha256(raw).hexdigest(), paths, source_hashes


def _canvas_size(size, conditions):
    width, height = size
    expanded_w, expanded_h = width, height
    for row in conditions:
        if row["kind"] == "skew":
            theta = math.radians(row["level"])
            c, s = abs(math.cos(theta)), abs(math.sin(theta))
            expanded_w = max(expanded_w, math.ceil(c * width + s * height) + 2)
            expanded_h = max(expanded_h, math.ceil(s * width + c * height) + 2)
    # Equal parity makes the unrotated control an exact pixel copy.
    return expanded_w + (expanded_w - width) % 2, expanded_h + (expanded_h - height) % 2


def _variant(source, canvas_size, condition, seed):
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    width, height = canvas_size
    w, h = source.size
    x, y = (width - w) // 2, (height - h) // 2
    control = Image.new("L", canvas_size, 255)
    control.paste(source, (x, y))
    kind, level = condition["kind"], condition["level"]
    inverse = [1, 0, -x, 0, 1, -y]
    details = {"target_to_source_affine_pixel_edges": inverse, "fill_luma": 255}
    if kind == "control":
        return control, details
    if kind == "skew":
        theta = math.radians(level)
        c, s = math.cos(theta), math.sin(theta)
        inverse = [c, -s, w / 2 - c * width / 2 + s * height / 2,
                   s, c, h / 2 - s * width / 2 - c * height / 2]
        result = source.transform(canvas_size, Image.Transform.AFFINE, inverse, Image.Resampling.BICUBIC, fillcolor=255)
        details.update(target_to_source_affine_pixel_edges=inverse, angle_ccw_degrees=level, resampling="BICUBIC")
    elif kind == "contrast":
        result = control.point([round(255 - level * (255 - value)) for value in range(256)])
        details["luma_mapping"] = "round(255 - level * (255 - source_luma))"
    elif kind == "salt_pepper":
        rng = random.Random(seed)
        count = round(level * width * height)
        offsets = rng.sample(range(width * height), count)
        pixels = bytearray(control.tobytes())
        for index, offset in enumerate(offsets):
            pixels[offset] = 0 if index < count // 2 else 255
        result = Image.frombytes("L", canvas_size, bytes(pixels))
        details.update(seed=seed, black_impulses=count // 2, white_impulses=count - count // 2,
                       selected_pixel_fraction=count / (width * height))
    else:  # stain
        rng = random.Random(seed)
        radius = math.sqrt(level * width * height / math.pi)
        center = [width * rng.uniform(.35, .65), height * rng.uniform(.35, .65)]
        outline = []
        for index in range(18):
            angle = index * math.tau / 18
            distance = radius * rng.uniform(.8, 1.2)
            outline.append((round(center[0] + distance * math.cos(angle)), round(center[1] + distance * math.sin(angle))))
        mask = Image.new("L", canvas_size, 0)
        ImageDraw.Draw(mask).polygon(outline, fill=255)
        radius_px = max(1., radius * .09)
        alpha = mask.filter(ImageFilter.GaussianBlur(radius_px)).point([round(.42 * value) for value in range(256)])
        result = Image.composite(Image.new("L", canvas_size, 45), control, alpha)
        details.update(seed=seed, polygon_px=outline, blur_radius_px=radius_px, stain_luma=45, opacity_scale=.42,
                       polygon_pixel_fraction=mask.histogram()[255] / (width * height))
    details["changed_from_control_pixels"] = width * height - ImageChops.difference(control, result).histogram()[0]
    return result, details


def _file(path, output):
    return {"path": path.relative_to(output).as_posix(), "sha256": sha256_file(path)}


def _write_image_pdf(png, pdf, image, dpi):
    import pymupdf

    width, height = image.size
    with pymupdf.open() as output:
        page = output.new_page(width=width * 72 / dpi, height=height * 72 / dpi)
        page.insert_image(page.rect, stream=png.read_bytes())
        data = output.tobytes(garbage=4, deflate=True, no_new_id=True)
    with pdf.open("xb") as stream:
        stream.write(data)
    with pymupdf.open(pdf) as output:
        _require(len(output) == 1 and not output[0].get_text("words"), "Derived PDF must contain one image-only page")
        images = output[0].get_images(full=True)
        _require(len(images) == 1, "Derived PDF must contain exactly one image")
        embedded = pymupdf.Pixmap(output, images[0][0])
        _require((embedded.width, embedded.height, embedded.n) == (width, height, 1)
                 and embedded.samples == image.tobytes(), "Derived PDF did not preserve the PNG pixel samples")


def build_corpus(plan_path, pdf_root, output):
    from PIL import Image, __version__ as pillow_version
    import pymupdf

    plan_path, pdf_root, output = (Path(value).resolve() for value in (plan_path, pdf_root, output))
    _require(not output.is_relative_to(pdf_root) and not plan_path.is_relative_to(output)
             and not any((parent / marker).is_file() for parent in output.parents
                         for marker in ("batch_input_manifest.json", "COMPLETED.json")),
             "Corpus output must be separate from sources and publications")
    plan, plan_hash, paths, source_hashes = _load_plan(plan_path, pdf_root)
    output.mkdir(parents=True, exist_ok=False)
    (output / "sources").mkdir()
    conditions, dpi = plan["conditions"], plan["dpi"]
    for condition in conditions:
        (output / "conditions" / condition["id"]).mkdir(parents=True)
    units = []
    for source in plan["sources"]:
        key = source["id"]
        with pymupdf.open(paths[key]) as pdf:
            _require(source["page"] <= len(pdf), "Physical page is outside its source PDF")
            page = pdf[source["page"] - 1]
            rect = page.rect
            _require(math.ceil(rect.width * dpi / 72) * math.ceil(rect.height * dpi / 72) <= MAX_PIXELS,
                     "Source page exceeds raster size limit")
            pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
            image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
            frame = {"page_rect_pt": list(rect), "cropbox_pt": list(page.cropbox), "pdf_rotation": page.rotation,
                     "source_raster_size_px": list(image.size)}
        clean = output / "sources" / f"{key}.png"
        image.save(clean, format="PNG", dpi=(dpi, dpi))
        canvas = _canvas_size(image.size, conditions)
        _require(math.prod(canvas) <= MAX_PIXELS, "Common canvas exceeds raster size limit")
        variants = []
        for condition in conditions:
            cond_id = condition["id"]
            seed = int.from_bytes(hashlib.sha256(f"{plan['seed']}:{key}:{cond_id}".encode()).digest()[:8], "big")
            variant, recipe = _variant(image, canvas, condition, seed)
            directory = output / "conditions" / cond_id
            png, pdf = (directory / f"{key}.{suffix}" for suffix in ("png", "pdf"))
            variant.save(png, format="PNG", dpi=(dpi, dpi))
            _write_image_pdf(png, pdf, variant, dpi)
            variants.append({"condition_id": cond_id, "recipe": recipe, "png": _file(png, output), "pdf": _file(pdf, output)})
        units.append({**source, **frame, "canvas_size_px": list(canvas), "source_image": _file(clean, output), "variants": variants})
    ids = [source["id"] for source in plan["sources"]]
    input_path = output / "score-input.draft.json"
    _save_json(input_path, {"schema_version": INPUT_SCHEMA, "expected_ids": ids, "conditions": conditions,
                           "references": dict.fromkeys(ids), "predictions": {row["id"]: dict.fromkeys(ids) for row in conditions}})
    _require(sha256_file(plan_path) == plan_hash and all(sha256_file(path) == digest for path, digest in source_hashes.items()),
             "Corpus inputs changed during generation")
    manifest = {"schema_version": MANIFEST_SCHEMA, "status": "DEVELOPMENT_CORPUS_RENDERED", "partition": "development",
                "quality_acceptance_status": "NOT_EVALUATED", "method": METHOD, "plan_sha256": plan_hash,
                "generator_sha256": sha256_file(Path(__file__)), "dpi": dpi, "seed": plan["seed"],
                "runtime": {"python": sys.version.split()[0], "pymupdf": pymupdf.__version__, "pillow": pillow_version},
                "conditions": conditions, "sources": units, "score_input_draft": _file(input_path, output)}
    _save_json(output / "manifest.json", manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--pdf-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_corpus(args.plan, args.pdf_root, args.output)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Development corpus: {len(report['sources'])} sources, {len(report['conditions'])} conditions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
