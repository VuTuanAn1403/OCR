"""Check that a paired raster corpus preserves scope, geometry and file identity."""
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw
import pymupdf
import pytest

from benchmark.scientific_evaluation import degradation_corpus as corpus
from benchmark.scientific_evaluation import degradation_predictions as intake
from benchmark.scientific_evaluation.degradation_metric import evaluate_bundle


@pytest.fixture
def source_plan(tmp_path):
    image = Image.new("L", (160, 200), 255)
    ImageDraw.Draw(image).rectangle([4, 20, 34, 75], fill=0)
    clean = tmp_path / "source.png"
    image.save(clean)
    sources = tmp_path / "inputs"
    sources.mkdir()
    pdf = sources / "scan.pdf"
    corpus._write_image_pdf(clean, pdf, image, 72)
    path = tmp_path / "plan.json"
    plan = {"schema_version": corpus.PLAN_SCHEMA, "partition": "development", "dpi": 72, "seed": 17,
            "sources": [{"id": "p1", "pdf_path": pdf.name, "pdf_sha256": corpus.sha256_file(pdf), "page": 1}],
            "conditions": [{"id": key, "kind": kind, "level": level} for key, kind, level in (
                ("control", "control", 0), ("skew", "skew", 10), ("fade", "contrast", .5),
                ("noise", "salt_pepper", .01), ("stain", "stain", .02))]}
    corpus._save_json(path, plan)
    return path, sources, plan


def test_source_frames_and_image_only_variants_are_reproducible(source_plan, tmp_path):
    plan, sources, _ = source_plan
    first, repeat = tmp_path / "first", tmp_path / "repeat"
    manifest = corpus.build_corpus(plan, sources, first)
    assert corpus.build_corpus(plan, sources, repeat) == manifest
    source, = manifest["sources"]
    variants = {row["condition_id"]: row for row in source["variants"]}
    for row in variants.values():
        for key in ("png", "pdf"):
            relative, digest = row[key]["path"], row[key]["sha256"]
            assert corpus.sha256_file(first / relative) == corpus.sha256_file(repeat / relative) == digest
        with Image.open(first / row["png"]["path"]) as png:
            assert list(png.size) == source["canvas_size_px"]
        with pymupdf.open(first / row["pdf"]["path"]) as pdf:
            assert len(pdf) == 1 and not pdf[0].get_text() and len(pdf[0].get_images()) == 1
    clean_recipe = variants["control"]["recipe"]
    x = -clean_recipe["target_to_source_affine_pixel_edges"][2]
    y = -clean_recipe["target_to_source_affine_pixel_edges"][5]
    with Image.open(first / variants["fade"]["png"]["path"]) as fade:
        assert fade.getpixel((x + 10, y + 30)) == 128 and fade.getpixel((0, 0)) == 255
    a, b, c, d, e, f = variants["skew"]["recipe"]["target_to_source_affine_pixel_edges"]
    det = a * e - b * d
    width, height = source["source_raster_size_px"]
    for sx, sy in ((0, 0), (width, 0), (0, height), (width, height)):
        tx, ty = (e * (sx - c) - b * (sy - f)) / det, (-d * (sx - c) + a * (sy - f)) / det
        assert 0 <= tx <= source["canvas_size_px"][0] and 0 <= ty <= source["canvas_size_px"][1]
    noise = variants["noise"]["recipe"]
    assert noise["black_impulses"] + noise["white_impulses"] == round(.01 * math.prod(source["canvas_size_px"]))
    report = evaluate_bundle(first / "score-input.draft.json")
    assert report["status"] == "NOT_EVALUATED" and report["quality_acceptance_status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("change", ["hash", "repeat-page", "holdout", "unsafe-id"])
def test_bad_plan_fails_before_any_output(source_plan, tmp_path, change):
    path, sources, plan = source_plan
    if change == "hash":
        plan["sources"][0]["pdf_sha256"] = "0" * 64
    elif change == "repeat-page":
        plan["sources"].append({**plan["sources"][0], "id": "p2"})
    elif change == "holdout":
        plan["partition"] = "holdout"
    else:
        plan["conditions"][0]["id"] = "../outside"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError):
        corpus.build_corpus(path, sources, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


@pytest.fixture
def paired_publications(source_plan, tmp_path, monkeypatch):
    plan_path, sources, plan = source_plan
    plan["conditions"] = plan["conditions"][:2]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    root = tmp_path / "corpus"
    manifest = corpus.build_corpus(plan_path, sources, root)
    batches, inventory = {}, {}
    for variant in manifest["sources"][0]["variants"]:
        condition = variant["condition_id"]
        batch = tmp_path / condition
        doc = batch / "p1"
        doc.mkdir(parents=True)
        pdf = variant["pdf"]
        config = batch / "batch_config.json"
        corpus._save_json(config, {"input_path": str((root / pdf["path"]).parent), "backend": {"device": "cuda"}})
        data = {"COMPLETED.json": condition, "ocr_receipt.json": condition, "gpu_scheduler.json": condition,
                "result.md": "GENERATED PREFACE\n\n# Trang 1\n\n" + ("Dấu 020" if condition == "control" else "Dấu O20")}
        for name, text in data.items():
            (doc / name).write_text(text, encoding="utf-8")
        inventory[batch] = {
            "batches": [{"path": str(batch), "configuration_sha256": corpus.sha256_file(config)}],
            "documents": [{"id": "p1", "source_dir": str(doc), "total_pages": 1, "pdf_sha256": pdf["sha256"],
                           "pdf_path": str(root / pdf["path"]), "result_md_sha256": corpus.sha256_file(doc / "result.md"),
                           "completion_sha256": corpus.sha256_file(doc / "COMPLETED.json"),
                           "ocr_receipt_sha256": corpus.sha256_file(doc / "ocr_receipt.json"), "pipeline_version": "v7.0",
                           "export_source_fingerprint": "fixture", "export_model_hashes": {"text": "fixture"},
                           "scheduler": {"gpu": {"device": "fixture-gpu", "total_mib": 4096},
                                         "scheduler_sha256": corpus.sha256_file(doc / "gpu_scheduler.json")}}],
        }
        batches[condition] = [batch]
    monkeypatch.setattr(intake, "collect_predictions", lambda paths: inventory[paths[0]])
    path = root / "manifest.json"
    return path, corpus.sha256_file(path), batches, inventory


def test_degradation_intake_hands_off_full_page_markdown_to_metric(paired_publications, tmp_path):
    path, digest, batches, _ = paired_publications
    text = tmp_path / "label.txt"
    text.write_bytes("Dấu 020".encode("utf-8"))
    references = tmp_path / "references.json"
    corpus._save_json(references, {"schema_version": intake.REFERENCE_SCHEMA, "corpus_sha256": digest,
                                   "reference_origin": "DECLARED_HUMAN_ADJUDICATED",
                                   "references": {"p1": {"path": text.name, "sha256": corpus.sha256_file(text)}}})
    output = tmp_path / "intake"
    report = intake.bind_predictions(path, digest, batches, output, references)
    assert report["status"] == "CANONICAL_PREDICTIONS_BOUND"
    assert report["quality_acceptance_status"] == "NOT_EVALUATED"
    assert report["score_input"]["sha256"] == corpus.sha256_file(output / "score-input.json")
    assert (output / "predictions/control/p1.txt").read_bytes() == text.read_bytes()
    scored = evaluate_bundle(output / "score-input.json")
    assert scored["status"] == "EVALUATED"
    assert scored["quality_acceptance_status"] == "NOT_EVALUATED"
    assert scored["points"][0]["counts"]["substitutions"] == 0
    assert scored["points"][1]["counts"]["substitutions"] == 1


def test_unpublished_variants_are_pending_and_do_not_create_score_input(paired_publications, tmp_path):
    path, digest, batches, _ = paired_publications
    output = tmp_path / "partial"
    report = intake.bind_predictions(path, digest, {"control": batches["control"]}, output)
    assert report["status"] == "MISSING_CANONICAL_PREDICTIONS"
    assert report["coverage"] == {"control": {"published_ids": ["p1"], "missing_ids": []},
                                  "skew": {"published_ids": [], "missing_ids": ["p1"]}}
    assert report["score_input"] is None and sorted(file.name for file in output.iterdir()) == ["intake.json"]


def test_published_empty_page_remains_an_observed_empty_prediction(paired_publications, tmp_path):
    path, digest, batches, inventory = paired_publications
    doc = inventory[batches["skew"][0]]["documents"][0]
    markdown = Path(doc["source_dir"]) / "result.md"
    markdown.write_bytes(b"# Trang 1\n")
    doc["result_md_sha256"] = corpus.sha256_file(markdown)
    output = tmp_path / "empty"
    report = intake.bind_predictions(path, digest, batches, output)
    assert report["status"] == "CANONICAL_PREDICTIONS_BOUND"
    assert (output / "predictions/skew/p1.txt").read_bytes() == b""


@pytest.mark.parametrize(("change", "reason"), [
    ("unpinned", "locked lowercase corpus"),
    ("manifest", "JSON hash mismatch"),
    ("variant", "Artifact hash mismatch"),
    ("wrong-condition", "frozen PDF"),
    ("wrong-page", "frozen PDF"),
    ("reused-publication", "only one condition"),
    ("changed-result", "Artifact hash mismatch"),
    ("marker", "physical-page marker"),
    ("config", "same system settings"),
    ("export", "export identity"),
    ("gpu", "same system settings"),
])
def test_invalid_degradation_intake_fails_without_writing(paired_publications, tmp_path, change, reason):
    path, digest, batches, inventory = paired_publications
    skew = inventory[batches["skew"][0]]
    doc = skew["documents"][0]
    if change == "unpinned":
        digest = None
    elif change == "manifest":
        digest = "0" * 64
    elif change == "variant":
        Path(doc["pdf_path"]).write_bytes(b"mutated")
    elif change == "wrong-condition":
        batches["control"], batches["skew"] = batches["skew"], batches["control"]
    elif change == "wrong-page":
        doc["total_pages"] = 2
    elif change == "reused-publication":
        batches["skew"] = batches["control"]
    elif change in {"changed-result", "marker"}:
        result = Path(doc["source_dir"]) / "result.md"
        result.write_bytes(b"# Trang 1\n\nfirst\n\n# Trang 1\n\nsecond\n")
        if change == "marker":
            doc["result_md_sha256"] = corpus.sha256_file(result)
    elif change == "config":
        config = Path(skew["batches"][0]["path"]) / "batch_config.json"
        config.write_bytes(b'{"backend":{"device":"cuda","dpi":200}}')
        skew["batches"][0]["configuration_sha256"] = corpus.sha256_file(config)
    elif change == "export":
        doc["export_source_fingerprint"] = "changed"
    elif change == "gpu":
        doc["scheduler"]["gpu"]["device"] = "other"
    output = tmp_path / "rejected"
    with pytest.raises(ValueError, match=reason):
        intake.bind_predictions(path, digest, batches, output)
    assert not output.exists()
