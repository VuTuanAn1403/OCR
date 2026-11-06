"""Submission custody fixtures exercise contracts, never OCR accuracy."""
import json
import unicodedata

import pytest

from benchmark.ground_truth_tools import human_annotations as human
from benchmark.scientific_evaluation.keyword_acceptance import _reference_units
from ocr_artifacts.hashing import sha256_file
from ocr_keywords.contract import dictionary_snapshot


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def unsealed(tmp_path):
    # Opaque fixture bytes test hashing, not PDF rendering or image accuracy.
    pdf, image = tmp_path / "input.pdf", tmp_path / "image.bin"
    pdf.write_bytes(b"opaque source PDF fixture")
    image.write_bytes(b"opaque image fixture")
    source = write(tmp_path / "source.json", {
        "schema_version": human.SOURCE_SCHEMA, "role": "development_candidate", "document_id": "DOC",
        "pdf_path": pdf.name, "pdf_sha256": sha256_file(pdf), "units": [
            {"unit_id": key, "physical_page": number, "image": image.name, "image_sha256": sha256_file(image),
             "bbox": [10, 10, 90, 30], "clip_bbox": [0, 0, 100, 40], "coordinate_space": "pdf_points_top_left"}
            for number, key in enumerate(("number", "accent"), 1)]})
    guideline = tmp_path / "guide.md"
    guideline.write_text("Frozen fixture guideline, source images only", encoding="utf-8")
    packets = tmp_path / "packets"
    packets.mkdir()
    actors = {}
    for role in ("A", "B"):
        packet = {"schema_version": "keyword-pilot-transcription-v1", "role": "annotator_" + role,
                  "actor_type": "HUMAN", "annotator_id": "Nguyễn" if role == "A" else "fixture_B",
                  "completed_at": "2000-01-01T00:00:00+07:00", "pdf_sha256": sha256_file(pdf), "units": []}
        for original, text in zip(read(source)["units"], ("020 O2O" if role == "A" else "020 020", "tri\u0301 tuệ")):
            packet["units"].append({key: original[key] for key in ("unit_id", "physical_page", "image", "image_sha256")})
            packet["units"][-1].update(target_xyxy_fraction_in_image=[.1, .25, .9, .75], transcription=text,
                                        ambiguity_reason=None)
        path = write(packets / human.FILES[role], packet)
        actors[role] = {"actor_id": packet["annotator_id"], "actor_type": "HUMAN", "packet_sha256": sha256_file(path),
                        "completed_at": packet["completed_at"], "confirmed_at": "2000-01-01T00:01:00+07:00",
                        "source_images_checked": True, "no_model_or_workbook": True, "no_peer_before_submission": True}
    declarations = write(tmp_path / "declarations.json", {"schema_version": human.DECLARATIONS_SCHEMA,
                         "source_manifest_sha256": sha256_file(source), "guideline_sha256": sha256_file(guideline),
                         "actors": actors})
    keywords = tmp_path / "keywords.txt"
    keywords.write_text("020\nO2O\ntrí tuệ\n", encoding="utf-8")
    dictionary = write(tmp_path / "dictionary.json", dictionary_snapshot(keywords, version="fixture"))
    return dict(root=tmp_path, source=source, guideline=guideline, packets=packets, declarations=declarations,
                seal=tmp_path / "seal.json", c_decl=tmp_path / "C-declaration.json", dictionary=dictionary)


def seal(bundle):
    return human.seal_submissions(bundle["source"], bundle["packets"], bundle["guideline"], bundle["declarations"],
                                   bundle["seal"], received_by="fixture_custodian", source_root=bundle["root"])


@pytest.fixture
def bundle(unsealed):
    b = unsealed
    seal(b)
    human.adjudication_template(b["source"], b["packets"], b["guideline"], b["declarations"],
                                 b["packets"] / human.FILES["C"], seal_path=b["seal"], source_root=b["root"])
    decision = read(b["packets"] / human.FILES["C"])
    decision.update(actor_type="HUMAN", adjudicator_id="fixture_C", completed_at=read(b["seal"])["sealed_at"])
    for row, text in zip(decision["units"], ("020 O2O", "tri\u0301 tuệ")):
        row.update(transcription=text, source_checked=True, decision_reason="Checked source image in fixture")
    write(b["packets"] / human.FILES["C"], decision)
    human.declaration_template(b["source"], b["packets"], b["guideline"], b["c_decl"], role="C",
                               seal_path=b["seal"], source_root=b["root"])
    declaration = read(b["c_decl"])
    declaration.update(actor_type="HUMAN", confirmed_at=decision["completed_at"],
                       source_images_checked=True, no_model_or_workbook=True)
    write(b["c_decl"], declaration)
    return b


def audit(b, **changes):
    options = dict(source_root=b["root"], seal_path=b["seal"], adjudicator_declaration=b["c_decl"])
    options.update(changes)
    return human.audit(b["source"], b["packets"], b["guideline"], b["declarations"], **options)


def export(b, target):
    return human.export_keyword_gt(b["source"], b["packets"], b["guideline"], b["declarations"], b["dictionary"], target,
                                    seal_path=b["seal"], adjudicator_declaration=b["c_decl"], source_root=b["root"])


def test_custody_checks_do_not_grant_quality_or_normalize_raw_transcriptions(bundle):
    report = audit(bundle)
    assert report["status"] == human.READY and not report["issues"]
    assert report["quality_acceptance_status"] == "NOT_EVALUATED" and not report["eligible_for_quality_acceptance"]
    assert report["paired_human_transcriptions"] == 2
    assert report["observed_disagreements"] == report["adjudicator_corrections"] == ["number"]
    before = {path: path.read_bytes() for path in bundle["packets"].iterdir()}
    output = export(bundle, bundle["root"] / "source-gt.json")
    assert output["intended_partition"] == "development" and not output["eligible_for_quality_acceptance"]
    assert output["units"][0]["transcription"] == "020 O2O"
    assert output["units"][1]["transcription"] == "tri\u0301 tuệ"
    snapshot = read(bundle["dictionary"])
    _, references, missing = _reference_units(output, {"keywords": snapshot["canonical_keywords"], "selected_pages": [1, 2]})
    assert len(references) == 3 and not missing
    assert {path: path.read_bytes() for path in before} == before


def test_template_has_no_automatic_human_attestations(unsealed):
    target = unsealed["root"] / "template.json"
    value = human.declaration_template(unsealed["source"], unsealed["packets"], unsealed["guideline"], target,
                                       source_root=unsealed["root"])
    for row in value["actors"].values():
        assert row["actor_type"] is row["source_images_checked"] is row["no_model_or_workbook"] is None
        assert row["confirmed_at"] is row["no_peer_before_submission"] is None


def test_adjudication_template_cannot_be_created_before_sealing(unsealed):
    b = unsealed
    target = b["packets"] / human.FILES["C"]
    with pytest.raises(human.PacketNotReady) as error:
        human.adjudication_template(b["source"], b["packets"], b["guideline"], b["declarations"], target,
                                    seal_path=b["seal"], source_root=b["root"])
    assert error.value.issues == ["A/B submission seal is missing"]
    assert not target.exists()


@pytest.mark.parametrize("mutate", [
    lambda packet, declaration: packet.update(actor_type="AI"),
    lambda packet, declaration: packet.update(status="AI_DRAFT"),
    lambda packet, declaration: declaration.update(no_peer_before_submission=False),
    lambda packet, declaration: declaration.update(source_images_checked=1),
    lambda packet, declaration: declaration.update(confirmed_at="2000-01-01T00:00:00"),
    lambda packet, declaration: declaration.update(confirmed_at="2999-01-01T00:00:00+07:00"),
])
def test_sealing_rejects_nonhuman_or_incomplete_declarations(unsealed, mutate):
    packet_path = unsealed["packets"] / human.FILES["A"]
    packet, declarations = read(packet_path), read(unsealed["declarations"])
    mutate(packet, declarations["actors"]["A"])
    write(packet_path, packet)
    declarations["actors"]["A"]["packet_sha256"] = sha256_file(packet_path)
    write(unsealed["declarations"], declarations)
    with pytest.raises(human.PacketNotReady):
        seal(unsealed)
    assert not unsealed["seal"].exists()


def test_blank_packet_and_missing_custody_remain_unevaluated(unsealed):
    for role in ("A", "B"):
        path = unsealed["packets"] / human.FILES[role]
        value = read(path)
        value.update(annotator_id=None, actor_type=None, completed_at=None)
        for row in value["units"]:
            row["transcription"] = None
        write(path, value)
    report = human.audit(unsealed["source"], unsealed["packets"], unsealed["guideline"], source_root=unsealed["root"])
    assert report["status"] == "NOT_EVALUATED" and report["paired_human_transcriptions"] == 0
    assert any("C: packet file is missing" in issue for issue in report["issues"])


def test_missing_declarations_are_not_counted_as_paired_human_labels(bundle):
    report = human.audit(bundle["source"], bundle["packets"], bundle["guideline"], source_root=bundle["root"],
                         seal_path=bundle["seal"], adjudicator_declaration=bundle["c_decl"])
    assert report["status"] == "NOT_EVALUATED" and report["paired_human_transcriptions"] == 0


def test_actor_identity_unicode_alias_cannot_count_as_another_person(bundle):
    path = bundle["packets"] / human.FILES["C"]
    decision, declaration = read(path), read(bundle["c_decl"])
    alias = unicodedata.normalize("NFD", read(bundle["packets"] / human.FILES["A"])["annotator_id"]).upper()
    decision["adjudicator_id"] = declaration["actor_id"] = alias
    write(path, decision)
    declaration["packet_sha256"] = sha256_file(path)
    write(bundle["c_decl"], declaration)
    report = audit(bundle)
    assert report["status"] == "NOT_EVALUATED"
    assert any("distinct human identities" in issue for issue in report["issues"])


@pytest.mark.parametrize("case", ["pdf", "image", "unit", "page", "target", "sealed_packet", "guideline"])
def test_changed_source_or_sealed_input_is_rejected(bundle, case):
    root = bundle["root"]
    if case in ("pdf", "image"):
        (root / ("input.pdf" if case == "pdf" else "image.bin")).write_bytes(b"changed")
    elif case == "guideline":
        bundle["guideline"].write_text("changed", encoding="utf-8")
    elif case == "unit":
        value = read(bundle["source"])
        value["units"][1]["unit_id"] = value["units"][0]["unit_id"]
        write(bundle["source"], value)
    else:
        path = bundle["packets"] / human.FILES["A"]
        value = read(path)
        if case == "page":
            value["units"][0]["physical_page"] = True
        elif case == "target":
            value["units"][0]["target_xyxy_fraction_in_image"][0] += .1
        else:
            value["units"][0]["transcription"] = "O2O O2O"
        write(path, value)
    with pytest.raises(ValueError):
        audit(bundle)


@pytest.mark.parametrize("case", ["seal", "source_check", "reason", "date"])
def test_adjudication_requires_sealed_inputs_and_source_confirmation(bundle, case):
    decision_path = bundle["packets"] / human.FILES["C"]
    decision, declaration = read(decision_path), read(bundle["c_decl"])
    if case == "seal":
        declaration["ab_seal_sha256"] = "0" * 64
    elif case == "date":
        decision["completed_at"] = declaration["completed_at"] = "2000-01-01T00:00:00+07:00"
    else:
        decision["units"][0]["source_checked" if case == "source_check" else "decision_reason"] = None
    write(decision_path, decision)
    declaration["packet_sha256"] = sha256_file(decision_path)
    write(bundle["c_decl"], declaration)
    target = bundle["root"] / "not-exported.json"
    with pytest.raises(human.PacketNotReady):
        export(bundle, target)
    assert not target.exists()


def test_empty_unit_must_be_explicitly_confirmed_not_inferred_from_missing_text(unsealed):
    for role in ("A", "B"):
        path = unsealed["packets"] / human.FILES[role]
        value = read(path)
        value["units"][0].update(transcription="", annotation_state="annotated_empty", empty_reason="Confirmed empty target")
        write(path, value)
        declaration = read(unsealed["declarations"])
        declaration["actors"][role]["packet_sha256"] = sha256_file(path)
        write(unsealed["declarations"], declaration)
    seal(unsealed)
    assert unsealed["seal"].is_file()
    path = unsealed["packets"] / human.FILES["A"]
    packet = read(path)
    del packet["units"][0]["annotation_state"]
    write(path, packet)
    declarations = read(unsealed["declarations"])
    declarations["actors"]["A"]["packet_sha256"] = sha256_file(path)
    write(unsealed["declarations"], declarations)
    with pytest.raises(human.PacketNotReady):
        human.seal_submissions(unsealed["source"], unsealed["packets"], unsealed["guideline"], unsealed["declarations"],
                               unsealed["root"] / "second-seal.json", received_by="fixture", source_root=unsealed["root"])


def test_files_cannot_change_during_keyword_export(bundle, monkeypatch):
    from ocr_keywords.counter import KeywordCounter
    original = KeywordCounter.iter_occurrences
    calls = []

    def changed(text, keywords):
        if not calls:
            path = bundle["packets"] / human.FILES["C"]
            path.write_bytes(path.read_bytes() + b"\n")
        calls.append(True)
        yield from original(text, keywords)

    monkeypatch.setattr(KeywordCounter, "iter_occurrences", changed)
    output = bundle["root"] / "raced.json"
    with pytest.raises(ValueError, match="changed during inspection"):
        export(bundle, output)
    assert not output.exists()


def test_export_cannot_write_inside_received_packet_directory_or_overwrite_result(bundle):
    with pytest.raises(ValueError, match="outside received packets"):
        export(bundle, bundle["packets"] / "gt.json")
    target = bundle["root"] / "gt.json"
    export(bundle, target)
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        export(bundle, target)
    assert target.read_bytes() == original


def test_cli_audit_of_unsubmitted_packet_returns_unevaluated(unsealed, capsys):
    output = unsealed["root"] / "audit.json"
    code = human.main(["audit", "--source", str(unsealed["source"]), "--packets", str(unsealed["packets"]),
                       "--guideline", str(unsealed["guideline"]), "--source-root", str(unsealed["root"]),
                       "--output", str(output)])
    assert code == 1 and read(output)["status"] == "NOT_EVALUATED"
    assert json.loads(capsys.readouterr().out)["quality_acceptance_status"] == "NOT_EVALUATED"


def test_dictionary_mutation_during_export_cannot_publish_counts(bundle, monkeypatch):
    from ocr_keywords import contract
    original = contract.validate_snapshot

    def changed(snapshot):
        original(snapshot)
        bundle["dictionary"].write_bytes(bundle["dictionary"].read_bytes() + b"\n")

    monkeypatch.setattr(contract, "validate_snapshot", changed)
    target = bundle["root"] / "changed-dictionary.json"
    with pytest.raises(ValueError, match="Dictionary changed"):
        export(bundle, target)
    assert not target.exists()


def test_source_root_cannot_be_escaped_with_a_relative_reference(unsealed):
    data = read(unsealed["source"])
    data["pdf_path"] = "../outside.pdf"
    write(unsealed["source"], data)
    with pytest.raises(ValueError, match="escapes the declared source root"):
        seal(unsealed)
