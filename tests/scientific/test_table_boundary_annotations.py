"""Controlled inputs for L5 custody and source-cell coordinates."""
from datetime import datetime, timedelta, timezone
import json

from PIL import Image
import pytest

from benchmark.ground_truth_tools import table_boundary_annotations as tool


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def read(path):
    return json.loads(path.read_bytes())


def submit(path, name, relation="SAME_TABLE"):
    value = read(path)
    value.update(status="SUBMITTED", actor_type="HUMAN", annotator_id=name,
                 submitted_at=datetime.now(timezone.utc).isoformat(), source_images_checked=True, no_predictions=True,
                 no_peer_before_submission=None if value["role"] == "C" else True)
    row, = value["units"]
    row.update(relationship=relation, source_reason="Controlled fixture source observation")
    if relation == "SAME_TABLE":
        row.update(boundary="SPLIT_ROW", column_count=3, repeated_header_rows=1,
                   cell_links=[{"column": 1, "column_span": 1,
                                "previous": {"image_id": "previous-0", "bbox_xyxy_px": [2, 2, 20, 30],
                                             "state": "OBSERVED_TEXT", "text_raw": "(020)"},
                                "next": {"image_id": "next-0", "bbox_xyxy_px": [2, 2, 20, 30],
                                         "state": "OBSERVED_TEXT", "text_raw": "đơn vị"}}])
    write(path, value)


@pytest.fixture
def packet(tmp_path):
    source, pdf_root = (tmp_path / name for name in ("source", "pdf"))
    for folder in (source, pdf_root):
        folder.mkdir()
    pdf = pdf_root / "fixture.pdf"
    pdf.write_bytes(b"Controlled source fixture, never opened as a PDF")
    guideline = source / "guide.md"
    guideline.write_text("controlled", encoding="utf-8")
    images = []
    for side, page in (("previous", 7), ("next", 8)):
        image = source / f"{side}.png"
        Image.new("RGB", (64, 48), color="white").save(image)
        images.append({"image_id": f"{side}-0", "side": side, "path": image.name, "sha256": tool.sha256_file(image),
                       "physical_page": page, "clip_xyxy_pt": [0, 0, 64, 48], "size_px": [64, 48]})
    units = [{"pair_id": "case", "pdf_path": pdf.name, "pdf_sha256": tool.sha256_file(pdf), "pages": [7, 8], "images": images}]
    guide_hash = tool.sha256_file(guideline)
    manifest = write(source / "source.json", {"schema_version": tool.SOURCE_SCHEMA, "partition": "development",
                                             "guideline_sha256": guide_hash, "pairs": units})
    ab = {role: write(tmp_path / f"{role}.json", tool._blank({"case": units[0]}, tool.sha256_file(manifest), guide_hash, role))
          for role in ("A", "B")}
    common = ["--source", str(manifest), "--pdf-root", str(pdf_root), "--guideline", str(guideline),
              "--annotation-a", str(ab["A"]), "--annotation-b", str(ab["B"])]

    def run(command, output, *options):
        return tool.main([command, *common, "--output", str(tmp_path / output), *(str(arg) for arg in options)])

    return tmp_path, ab, run


def test_blank_source_only_packets_never_create_a_seal(packet):
    root, _, run = packet
    assert run("audit", "audit.json") == 1
    assert read(root / "audit.json")["paired_human_labels"] == 0
    with pytest.raises(SystemExit, match="2"):
        run("seal", "seal.json", "--received-by", "fixture")
    assert not (root / "seal.json").exists()


def test_export_binds_adjudication_to_exact_seal_and_preserves_raw_text(packet):
    root, ab, run = packet
    submit(ab["A"], "Fixture A")
    submit(ab["B"], "Fixture B", "DIFFERENT_TABLES")
    seal, c, report = (root / name for name in ("seal.json", "C.json", "labels.json"))
    assert run("seal", seal.name, "--received-by", "Fixture coordinator") == 0
    assert run("adjudication-template", c.name, "--seal", seal) == 0
    assert read(c)["status"] == "BLANK" and read(c)["seal_sha256"] == tool.sha256_file(seal)
    submit(c, "Fixture C")
    assert run("export", report.name, "--seal", seal, "--adjudication", c) == 0
    labels = read(report)
    assert labels["partition"] == "development" and not labels["eligible_for_quality_acceptance"]
    assert labels["quality_acceptance_status"] == "NOT_EVALUATED"
    record, = labels["records"]
    assert record["ab_disagreement"] and record["decision"]["cell_links"][0]["previous"]["text_raw"] == "(020)"
    for role, file in (*ab.items(), ("C", c)):
        assert labels["submission_sha256"][role] == tool.sha256_file(file)

    old = read(c)
    write(c, {**old, "submitted_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()})
    with pytest.raises(SystemExit, match="2"):
        run("export", "pre-seal-c.json", "--seal", seal, "--adjudication", c)
    write(c, old)
    ab["A"].write_bytes(ab["A"].read_bytes() + b"\n")
    with pytest.raises(SystemExit, match="2"):
        run("export", "changed-ab.json", "--seal", seal, "--adjudication", c)
    assert not (root / "changed-ab.json").exists()


@pytest.mark.parametrize("invalid", ["same-actor", "wrong-image-side", "outside-image", "unverified-image", "overlapping-cells"])
def test_seal_rejects_custody_and_cell_ownership_failures(packet, invalid, capsys):
    root, ab, run = packet
    submit(ab["A"], "Fixture A")
    submit(ab["B"], "fixture a " if invalid == "same-actor" else "Fixture B")
    if invalid in ("wrong-image-side", "outside-image", "overlapping-cells"):
        value = read(ab["B"])
        links = value["units"][0]["cell_links"]
        part = links[0]["next"]
        if invalid == "wrong-image-side":
            part["image_id"] = "previous-0"
        elif invalid == "outside-image":
            part["bbox_xyxy_px"][-1] = 49
        else:
            links.append({**links[0], "column": 2, "next": {**part, "bbox_xyxy_px": [19, 2, 40, 30]}})
        write(ab["B"], value)
    if invalid == "unverified-image":
        image = root / "source/next.png"
        image.write_bytes(image.read_bytes() + b"changed")
    with pytest.raises(SystemExit, match="2"):
        run("seal", "rejected.json", "--received-by", "fixture")
    assert not (root / "rejected.json").exists()
    expected = {"same-actor": "distinct", "wrong-image-side": "correct side", "outside-image": "in-image",
                "unverified-image": "image is reused or its SHA-256 differs", "overlapping-cells": "overlap within"}
    assert expected[invalid] in capsys.readouterr().err
