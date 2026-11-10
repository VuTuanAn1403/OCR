"""Measurement lock (v3): the section 7.6 choices, the matching rule, sealed screenings, pinned tool bytes."""
import hashlib
import json

import pytest

from scripts import lock_text_layer_measurement as lock_v3

PHASE_A = "bbox-connected-groups-phase-a-v1"
DECISION = {"reviewer": "me", "decided_on": "2026-11-10"}


def _base(tmp_path, metric="DSER_strict"):
    path = tmp_path / "lock-v1.json"
    path.write_text(json.dumps({"schema_version": lock_v3.BASE_SCHEMA, "procedure_version": 1, "status": "LOCKED_PROCEDURE",
                                "parameters": {"metric": metric, "confidence": 0.95}}), encoding="utf-8")
    return path


def _seal(tmp_path, base, name="AAA", status="ACCEPTED"):
    path = tmp_path / f"seal-{name}.json"
    path.write_text(json.dumps({"pdf": f"{name}.pdf", "pdf_sha256": "a" * 64, "producer": "iLovePDF",
                                "lock": {"sha256": hashlib.sha256(base.read_bytes()).hexdigest()},
                                "sealed_sha256": "b" * 64, "verdict": {"status": status}}), encoding="utf-8")
    return path


def _write(tmp_path, name, lock):
    path = tmp_path / name
    path.write_text(lock_v3.dump(lock), encoding="utf-8")
    return path


def test_a_draft_has_no_decision_and_a_lock_needs_reviewer_date_stream_and_matching(tmp_path):
    base = _base(tmp_path)
    draft = lock_v3.build_lock(str(base), draft=True)
    assert draft["status"] == "DRAFT_NOT_LOCKED" and draft["decision"] is None
    assert draft["open_choices"] == ["matching", "stream"] and draft["procedure_version"] == lock_v3.PROCEDURE_VERSION
    assert draft["gt_status"] == "NOT_VERIFIED" and draft["quality_acceptance"] == "NOT_EVALUATED"
    with pytest.raises(lock_v3.LockError, match="carries no decision"):
        lock_v3.build_lock(str(base), draft=True, reviewer="me")
    with pytest.raises(lock_v3.LockError, match="--stream and --matching"):
        lock_v3.build_lock(str(base), draft=False, stream="text_raw", **DECISION)
    with pytest.raises(lock_v3.LockError, match="matching must be one of"):
        lock_v3.build_lock(str(base), draft=False, stream="text_raw", matching="nearest-line", **DECISION)
    locked = lock_v3.build_lock(str(base), draft=False, stream="text_raw", matching=PHASE_A, **DECISION)
    assert locked["status"] == "LOCKED_PROCEDURE" and locked["open_choices"] == []
    assert locked["choices"]["matching"]["method"] == PHASE_A and "text_evidence" in locked["choices"]["matching"]["ocr_side"]
    assert locked["base_lock"]["sha256"] == hashlib.sha256(base.read_bytes()).hexdigest()


def test_choices_are_read_from_the_tools_and_every_tool_is_pinned(tmp_path):
    lock = lock_v3.build_lock(str(_base(tmp_path)), draft=True)
    choices = lock["choices"]
    assert choices["visible_glyphs"]["render_dpi"] == 144 and choices["visible_glyphs"]["min_changed_pixels"] == 2
    assert choices["matching"]["min_vertical_overlap"] == 0.5 and len(choices["matching"]["allowed"]) == 3
    assert choices["gate"] == {**choices["gate"], "metric": "DSER_strict", "errors": "dser_errors", "denominator": "ref_slots"}
    assert choices["rho_upper"]["method"] == "beta-binomial-profile-likelihood-v1"
    assert set(lock["tools"]) == set(lock_v3.TOOLS)
    for path, digest in lock["tools"].items():
        assert digest == hashlib.sha256((lock_v3.ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_base_lock_must_be_a_locked_v1_with_the_dser_metric(tmp_path):
    with pytest.raises(lock_v3.LockError, match="metric must be DSER_strict"):
        lock_v3.build_lock(str(_base(tmp_path, metric="DER_VN_v1")), draft=True)
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"schema_version": "x", "status": "LOCKED_PROCEDURE", "parameters": {}}), encoding="utf-8")
    with pytest.raises(lock_v3.LockError, match="base must be"):
        lock_v3.build_lock(str(path), draft=True)


def test_seals_and_the_superseded_lock_are_recorded_by_sha256(tmp_path):
    base = _base(tmp_path)
    seals = [str(_seal(tmp_path, base, "BBB")), str(_seal(tmp_path, base, "AAA"))]
    old = _write(tmp_path, "old.json", {"schema_version": "ocr-v8-text-layer-measurement-lock-v2"})
    with pytest.raises(lock_v3.LockError, match="needs a reason"):
        lock_v3.build_lock(str(base), draft=True, supersedes=str(old))
    lock = lock_v3.build_lock(str(base), draft=False, stream="text_corrected", matching=PHASE_A, seals=seals,
                              supersedes=str(old), supersede_reason="tables counted as deleted", **DECISION)
    assert [s["pdf"] for s in lock["screening_seals"]] == ["AAA.pdf", "BBB.pdf"]
    assert lock["screening_seals"][0]["sha256"] == hashlib.sha256((tmp_path / "seal-AAA.json").read_bytes()).hexdigest()
    assert lock["supersedes"]["sha256"] == hashlib.sha256(old.read_bytes()).hexdigest()
    other = tmp_path / "other-v1.json"
    other.write_text(base.read_text(encoding="utf-8").replace("0.95", "0.99"), encoding="utf-8")
    with pytest.raises(lock_v3.LockError, match="sealed under another base lock"):
        lock_v3.build_lock(str(other), draft=True, seals=seals)


def test_verify_finds_changed_tools_seals_edited_choices_and_a_changed_base(tmp_path):
    base = _base(tmp_path)
    seal = _seal(tmp_path, base)
    lock = lock_v3.build_lock(str(base), draft=False, stream="text_corrected", matching=PHASE_A, seals=[str(seal)], **DECISION)
    assert lock_v3.verify(_write(tmp_path, "ok.json", lock)) == []
    tool = dict(lock, tools={**lock["tools"], lock_v3.TOOLS[0]: "0" * 64})
    assert lock_v3.verify(_write(tmp_path, "tool.json", tool)) == [f"tool bytes changed since the lock: {lock_v3.TOOLS[0]}"]
    edited = json.loads(lock_v3.dump(lock))
    edited["choices"]["matching"]["min_vertical_overlap"] = 0.3
    assert lock_v3.verify(_write(tmp_path, "edited.json", edited)) == ["lock content differs from a rebuild with the current tools"]
    seal.write_text(seal.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert lock_v3.verify(_write(tmp_path, "seal.json", lock)) == [f"screening seal missing or changed since the lock: {seal}"]
    assert lock_v3.verify(_write(tmp_path, "v2.json", dict(lock, schema_version="ocr-v8-text-layer-measurement-lock-v2")))[0].startswith("schema must be")


def test_a_measurement_needs_a_verified_lock_on_its_base_stream_and_seals(tmp_path):
    base = _base(tmp_path)
    base_sha = hashlib.sha256(base.read_bytes()).hexdigest()
    seals = [_seal(tmp_path, base, "AAA"), _seal(tmp_path, base, "BBB")]
    draft = _write(tmp_path, "draft.json", lock_v3.build_lock(str(base), draft=True, stream="text_corrected"))
    with pytest.raises(lock_v3.LockError, match="status DRAFT_NOT_LOCKED"):
        lock_v3.require_locked(draft, base_sha, "text_corrected")
    locked = _write(tmp_path, "locked.json", lock_v3.build_lock(
        str(base), draft=False, stream="text_corrected", matching=PHASE_A, seals=[str(s) for s in seals], **DECISION))
    with pytest.raises(lock_v3.LockError, match="another base lock"):
        lock_v3.require_locked(locked, "f" * 64, "text_corrected", seals)
    with pytest.raises(lock_v3.LockError, match="locked stream is text_corrected, not text_raw"):
        lock_v3.require_locked(locked, base_sha, "text_raw", seals)
    with pytest.raises(lock_v3.LockError, match="differ from the 2 seals"):
        lock_v3.require_locked(locked, base_sha, "text_corrected", seals[:1])
    entry = lock_v3.require_locked(locked, base_sha, "text_corrected", seals)
    assert entry["status"] == "LOCKED_PROCEDURE" and entry["matching"] == PHASE_A and entry["procedure_version"] == lock_v3.PROCEDURE_VERSION
    assert entry["sha256"] == hashlib.sha256(locked.read_bytes()).hexdigest()


def test_the_adjudication_sample_is_a_locked_positive_size(tmp_path):
    base = _base(tmp_path)
    for bad in (0, -5, 2.5):
        with pytest.raises(lock_v3.LockError, match="positive whole number"):
            lock_v3.build_lock(str(base), draft=True, adjudication_sample=bad)
    full = lock_v3.build_lock(str(base), draft=True)["choices"]["adjudication"]
    assert full["sample_size"] is None and full["unsampled_items"] is None
    lock = lock_v3.build_lock(str(base), draft=False, stream="text_corrected", matching=PHASE_A,
                              adjudication_sample=3000, **DECISION)
    sample = lock["choices"]["adjudication"]
    assert sample["sample_size"] == 3000 and sample["unsampled_items"] == "count as UNRESOLVED"
    assert sample["sample_rank"].startswith("sha256(seed:adjudication-sample:")
    assert lock_v3.verify(_write(tmp_path, "sample.json", lock)) == []


def test_cli_never_overwrites_and_verify_exits_nonzero_on_a_problem(tmp_path, capsys):
    base = _base(tmp_path)
    report = tmp_path / "draft.json"
    assert lock_v3.main(["--base-lock", str(base), "--draft", "--report", str(report)]) == 0
    with pytest.raises(SystemExit):
        lock_v3.main(["--base-lock", str(base), "--draft", "--report", str(report)])
    assert lock_v3.main(["--verify", str(report)]) == 0
    base.write_text("{}", encoding="utf-8")
    assert lock_v3.main(["--verify", str(report)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_partial_adjudication_is_locked_and_excludes_a_sample(tmp_path):
    base = _base(tmp_path)
    with pytest.raises(lock_v3.LockError, match="exclude each other"):
        lock_v3.build_lock(str(base), draft=True, adjudication_sample=10, adjudication_partial=True)
    lock = lock_v3.build_lock(str(base), draft=False, stream="text_corrected", matching=PHASE_A,
                              adjudication_partial=True, **DECISION)
    rule = lock["choices"]["adjudication"]
    assert rule["partial"] is True and rule["sample_size"] is None and "no population estimate" in rule["undecided_items"]
    assert lock_v3.verify(_write(tmp_path, "partial.json", lock)) == []
