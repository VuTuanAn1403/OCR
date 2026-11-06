"""Verify source identity and full Markdown preservation for an external evaluator."""
import json
from pathlib import Path

import pymupdf
import pytest
import yaml

from benchmark.scientific_evaluation import omnidocbench_adapter as adapter
from benchmark.scientific_evaluation import omnidocbench_corpus as corpus
from ocr_artifacts.hashing import sha256_file


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return sha256_file(path)


@pytest.fixture
def paired(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    images, sources, gt = [], [], []
    for index, color in enumerate(((100, 30, 80), (20, 120, 40)), 1):
        name = f"paper.pdf_{index}.png"
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
        pix.clear_with()
        pix.set_rect(pix.irect, color)
        image = dataset / name
        image.write_bytes(pix.tobytes("png"))
        pdf_path = tmp_path / f"p{index}.pdf"
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=40, height=30)
            page.insert_image(page.rect, filename=str(image))
            pdf.save(pdf_path)
        images.append(image)
        sources.append({"image_name": name, "document_id": f"p{index}", "pdf_sha256": sha256_file(pdf_path),
                        "image": {"path": name, "sha256": sha256_file(image)}})
        gt.append({"page_info": {"image_path": f"images/{name}", "width": 40, "height": 30},
                   "layout_dets": [{"category_type": "text_block", "text": "020"}]})
    gt_path = dataset / "ground-truth.json"
    gt_hash = write(gt_path, gt)
    plan_path = tmp_path / "plan.json"
    plan = {"schema_version": adapter.SCHEMA, "partition": "development",
            "evaluator": {"repository": adapter.REPOSITORY, "revision": adapter.REVISION},
            "dataset_version": "PROGRAMMATIC_INTERFACE_CONTROLS", "dataset_revision": "1" * 40,
            "ground_truth": {"path": gt_path.name, "sha256": gt_hash}, "sources": sources}
    write(plan_path, plan)
    inventories = {}
    for side in ("baseline", "candidate"):
        batch = tmp_path / side
        docs = []
        for index in (1, 2):
            directory = batch / f"p{index}"
            directory.mkdir(parents=True)
            asset = directory / "images" / "page.png"
            asset.parent.mkdir()
            asset.write_bytes(images[index-1].read_bytes())
            markdown = directory / "result.md"
            markdown.write_text("# Báo cáo trích xuất tài liệu: p\nProfile\n---\n\n# Trang 1\n\n"
                                + (f"{side} 020\n\n<table><tr><td>(020)</td></tr></table>\n\n"
                                   "$$\\frac{1}{2}$$\n\n![Figure](images/page.png)" if index == 1 else "")
                                + "\n\n---", encoding="utf-8")
            complete = directory / "COMPLETED.json"
            checksum = write(complete, {"files": {"result.md": sha256_file(markdown), "images/page.png": sha256_file(asset)}})
            docs.append({"id": f"p{index}", "total_pages": 1, "source_dir": str(directory),
                         "pdf_path": str(tmp_path / f"p{index}.pdf"), "pdf_sha256": sources[index-1]["pdf_sha256"],
                         "completion_sha256": checksum, "result_md_sha256": sha256_file(markdown)})
        inventories[batch] = {"batches": [{"path": str(batch)}], "documents": docs}
    monkeypatch.setattr(adapter, "collect_predictions", lambda roots: inventories[roots[0]])
    return plan_path, dataset, plan, inventories


def test_paired_export_preserves_full_page_tables_formulas_and_assets(paired, tmp_path):
    plan, dataset, _, inventory = paired
    output = tmp_path / "export"
    report = adapter.export_pairs(plan, sha256_file(plan), dataset, [tmp_path / "baseline"], [tmp_path / "candidate"], output)
    assert report["status"] == "PAIRED_EXPORT_VERIFIED" and report["official_evaluation"] == "NOT_RUN"
    assert report["quality_acceptance"] == "NOT_EVALUATED"
    assert (output / "ground-truth.json").read_bytes() == (dataset / "ground-truth.json").read_bytes()
    for side in inventory:
        name = side.name
        markdown = (output / name / "predictions/paper.pdf_1.md").read_text(encoding="utf-8")
        assert markdown.startswith(name + " 020") and "<table><tr><td>(020)</td></tr></table>" in markdown
        assert "$$\\frac{1}{2}$$" in markdown and "# Trang 1" not in markdown and not markdown.endswith("---")
        assert "![Figure](../assets/p1/images/page.png)" in markdown
        assert (output / name / "assets/p1/images/page.png").read_bytes() == (dataset / "paper.pdf_1.png").read_bytes()
        assert (output / name / "predictions/paper.pdf_2.md").read_bytes() == b""
        config = yaml.safe_load((output / name / "end2end.yaml").read_text(encoding="utf-8"))["end2end_eval"]
        assert config["metrics"]["display_formula"]["metric"] == ["Edit_dist", "CDM"]
        assert config["dataset"]["match_method"] == "quick_match"
    assert all(sha256_file(output / path) == digest for path, digest in report["files"].items())


@pytest.mark.parametrize("change", ["plan_hash", "same_publication", "image_bytes", "native_text", "clipped_image",
                                  "soft_mask", "hidden_layer", "clipped_content", "gt_dimensions", "filename_collision"])
def test_wrong_sources_fail_before_export(paired, tmp_path, change):
    plan, dataset, data, inventories = paired
    expected = sha256_file(plan)
    baseline = tmp_path / "baseline"
    if change == "plan_hash":
        expected = "f" * 64
    elif change == "same_publication":
        baseline = tmp_path / "candidate"
    elif change == "image_bytes":
        path = dataset / "paper.pdf_1.png"
        path.write_bytes((dataset / "paper.pdf_2.png").read_bytes())
        data["sources"][0]["image"]["sha256"] = sha256_file(path)
        expected = write(plan, data)
    elif change in {"native_text", "clipped_image", "soft_mask", "hidden_layer", "clipped_content"}:
        path = tmp_path / "p1.pdf"
        revised = tmp_path / "revised.pdf"
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=40, height=30)
            options = {}
            if change == "soft_mask":
                mask = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 40, 30), False)
                mask.clear_with(0)
                options["mask"] = mask.tobytes("png")
            elif change == "hidden_layer":
                options["oc"] = pdf.add_ocg("Hidden source", on=False)
            page.insert_image(pymupdf.Rect(5, 0, 40, 30) if change == "clipped_image" else page.rect,
                              filename=str(dataset / "paper.pdf_1.png"), **options)
            if change == "native_text":
                page.insert_text((1, 12), "native", fontsize=7)
            elif change == "clipped_content":
                content, = page.get_contents()
                pdf.update_stream(content, b"q\n0 0 1 1 re W n\n" + pdf.xref_stream(content) + b"\nQ\n")
            pdf.save(revised)
        path.write_bytes(revised.read_bytes())
        digest = sha256_file(path)
        for inventory in inventories.values():
            inventory["documents"][0]["pdf_sha256"] = digest
        data["sources"][0]["pdf_sha256"] = digest
        expected = write(plan, data)
    elif change == "gt_dimensions":
        path = dataset / "ground-truth.json"
        gt = json.loads(path.read_bytes())
        gt[0]["page_info"]["width"] = 41
        data["ground_truth"]["sha256"] = write(path, gt)
        expected = write(plan, data)
    elif change == "filename_collision":
        path = dataset / "ground-truth.json"
        gt = json.loads(path.read_bytes())
        gt[1]["page_info"]["image_path"] = "images/paper.pdf_1.jpg"
        data["sources"][1]["image_name"] = "paper.pdf_1.jpg"
        data["ground_truth"]["sha256"] = write(path, gt)
        expected = write(plan, data)
    output = tmp_path / "rejected"
    with pytest.raises(ValueError):
        adapter.export_pairs(plan, expected, dataset, [baseline], [tmp_path / "candidate"], output)
    assert not output.exists()


def test_repeated_markers_do_not_silently_drop_content():
    with pytest.raises(ValueError, match="exactly one physical"):
        adapter._page_markdown(b"# Trang 1\nfirst\n# Trang 1\nsecond")


def test_preparation_freezes_pixel_preserving_inputs_and_reproduces_bytes(paired, tmp_path):
    _, dataset, _, _ = paired
    gt = dataset / "ground-truth.json"
    original = {path.name: sha256_file(path) for path in dataset.iterdir()}
    first, repeat = tmp_path / "prepared", tmp_path / "replayed"
    report = corpus.prepare_corpus(gt, sha256_file(gt), dataset, ".", "CONTROLLED_FIXTURE", "1"*40, first)
    replay = corpus.prepare_corpus(gt, sha256_file(gt), dataset, ".", "CONTROLLED_FIXTURE", "1"*40, repeat)
    assert report == replay and report["distinct_pdf_inputs"] == report["image_units"] == 2
    assert report["new_model_inference"] is False and report["alias_groups"] == []
    assert {path.name: sha256_file(path) for path in dataset.iterdir()} == original
    assert report["plan"]["sha256"] == sha256_file(first / report["plan"]["path"])
    assert {path.relative_to(first): sha256_file(path) for path in first.rglob("*") if path.is_file()} == {
        path.relative_to(repeat): sha256_file(path) for path in repeat.rglob("*") if path.is_file()}
    plan = json.loads((first / "export-plan.json").read_bytes())
    for source in plan["sources"]:
        pdf = first / "inputs" / (source["document_id"] + ".pdf")
        assert sha256_file(pdf) == source["pdf_sha256"]
        proof = adapter._verify_image_pdf(pdf, dataset / source["image"]["path"])
        assert proof == source["pixel_proof"]


def test_preparation_handles_rgb_jpeg_without_changing_decoded_pixels(paired, tmp_path):
    from PIL import Image

    _, dataset, _, _ = paired
    path = dataset / "research.report.page_1.jpg"
    image = Image.new("RGB", (160, 120))
    image.putdata([(x, y, (x + y) % 256) for y in range(120) for x in range(160)])
    image.save(path, quality=92)
    gt = dataset / "jpeg-gt.json"
    digest = write(gt, [{"page_info": {"image_path": path.name, "width": 160, "height": 120}, "layout_dets": []}])
    output = tmp_path / "jpeg"
    report = corpus.prepare_corpus(gt, digest, dataset, ".", "CONTROLLED_FIXTURE", "1"*40, output)
    source, = json.loads((output / "export-plan.json").read_bytes())["sources"]
    proof = adapter._verify_image_pdf(output / "inputs" / (source["document_id"] + ".pdf"), path)
    assert source["pixel_proof"] == proof and report["distinct_pdf_inputs"] == 1


def test_duplicate_image_inputs_use_explicit_aliases_through_paired_export(paired, tmp_path):
    _, dataset, _, inventories = paired
    image = dataset / "paper.pdf_1.png"
    (dataset / "paper.pdf_2.png").write_bytes(image.read_bytes())
    gt = dataset / "ground-truth.json"
    prepared = tmp_path / "prepared"
    report = corpus.prepare_corpus(gt, sha256_file(gt), dataset, ".", "CONTROLLED_FIXTURE", "1"*40, prepared)
    assert report["image_units"] == 2 and report["distinct_pdf_inputs"] == 1
    group, = report["alias_groups"]
    assert group["image_names"] == ["paper.pdf_1.png", "paper.pdf_2.png"]
    for inventory in inventories.values():
        doc = inventory["documents"][0]
        doc.update(id=group["document_id"], pdf_sha256=group["pdf_sha256"], pdf_path=str(prepared / group["path"]))
        inventory["documents"] = [doc]
    plan = prepared / "export-plan.json"
    output = tmp_path / "export"
    exported = adapter.export_pairs(plan, sha256_file(plan), dataset, [tmp_path / "baseline"], [tmp_path / "candidate"], output)
    assert exported["image_units"] == 2 and exported["distinct_pdf_inputs"] == 1
    assert exported["pdf_alias_groups"] == {group["document_id"]: group["image_names"]}
    for side in ("baseline", "candidate"):
        directory = output / side / "predictions"
        assert (directory / "paper.pdf_1.md").read_bytes() == (directory / "paper.pdf_2.md").read_bytes()


@pytest.mark.parametrize("change", ["gt_hash", "dimensions", "output_inside_source"])
def test_preparation_refuses_changed_or_invalid_sources(paired, tmp_path, change):
    _, dataset, _, _ = paired
    gt = dataset / "ground-truth.json"
    digest = sha256_file(gt)
    output = tmp_path / "invalid"
    if change == "gt_hash":
        digest = "f"*64
    elif change == "dimensions":
        data = json.loads(gt.read_bytes())
        data[0]["page_info"]["height"] = 100
        digest = write(gt, data)
    else:
        output = dataset / "invalid"
    with pytest.raises(ValueError):
        corpus.prepare_corpus(gt, digest, dataset, ".", "CONTROLLED_FIXTURE", "1"*40, output)
    assert not (output / "prepared.json").exists()
