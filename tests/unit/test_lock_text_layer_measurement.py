"""Lock v2 of the text-layer procedure: the section 7.6 measurement choices, pinned tool bytes."""
import hashlib
import json

import pytest

from scripts import lock_text_layer_measurement as lock_v2


def _base(tmp_path, metric="DSER_strict"):
    path = tmp_path / "lock-v1.json"
    path.write_text(json.dumps({"schema_version": lock_v2.BASE_SCHEMA, "procedure_version": 1, "status": "LOCKED_PROCEDURE",
                                "parameters": {"metric": metric, "confidence": 0.95}}), encoding="utf-8")
    return path


def _write(tmp_path, name, lock):
    path = tmp_path / name
    path.write_text(lock_v2.dump(lock), encoding="utf-8")
    return path


def test_a_draft_has_no_decision_and_a_lock_needs_the_reviewer_date_and_stream(tmp_path):
    base = _base(tmp_path)
    draft = lock_v2.build_lock(str(base), draft=True)
    assert draft["status"] == "DRAFT_NOT_LOCKED" and draft["decision"] is None and draft["open_choices"] == ["stream"]
    assert draft["gt_status"] == "NOT_VERIFIED" and draft["quality_acceptance"] == "NOT_EVALUATED"
    with pytest.raises(lock_v2.LockError, match="carries no decision"):
        lock_v2.build_lock(str(base), draft=True, reviewer="me")
    with pytest.raises(lock_v2.LockError, match="--reviewer, --decided-on and --stream"):
        lock_v2.build_lock(str(base), draft=False, reviewer="me", decided_on="2026-11-10")
    locked = lock_v2.build_lock(str(base), draft=False, stream="text_raw", reviewer="me", decided_on="2026-11-10")
    assert locked["status"] == "LOCKED_PROCEDURE" and locked["open_choices"] == []
    assert locked["base_lock"]["sha256"] == hashlib.sha256(base.read_bytes()).hexdigest()


def test_choices_are_read_from_the_tools_and_every_tool_is_pinned(tmp_path):
    lock = lock_v2.build_lock(str(_base(tmp_path)), draft=True)
    choices = lock["choices"]
    assert choices["visible_glyphs"]["render_dpi"] == 144 and choices["visible_glyphs"]["min_changed_pixels"] == 2
    assert choices["matching"]["min_vertical_overlap"] == 0.5
    assert choices["gate"] == {**choices["gate"], "metric": "DSER_strict", "errors": "dser_errors", "denominator": "ref_slots"}
    assert choices["rho_upper"]["method"] == "beta-binomial-profile-likelihood-v1"
    assert set(lock["tools"]) == set(lock_v2.TOOLS)
    for path, digest in lock["tools"].items():
        assert digest == hashlib.sha256((lock_v2.ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_base_lock_must_be_a_locked_v1_with_the_dser_metric(tmp_path):
    with pytest.raises(lock_v2.LockError, match="metric must be DSER_strict"):
        lock_v2.build_lock(str(_base(tmp_path, metric="DER_VN_v1")), draft=True)
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"schema_version": "x", "status": "LOCKED_PROCEDURE", "parameters": {}}), encoding="utf-8")
    with pytest.raises(lock_v2.LockError, match="base must be"):
        lock_v2.build_lock(str(path), draft=True)


def test_verify_finds_changed_tools_edited_choices_and_a_changed_base(tmp_path):
    base = _base(tmp_path)
    lock = lock_v2.build_lock(str(base), draft=False, stream="text_corrected", reviewer="me", decided_on="2026-11-10")
    assert lock_v2.verify(_write(tmp_path, "ok.json", lock)) == []
    tool = dict(lock, tools={**lock["tools"], lock_v2.TOOLS[0]: "0" * 64})
    assert lock_v2.verify(_write(tmp_path, "tool.json", tool)) == [f"tool bytes changed since the lock: {lock_v2.TOOLS[0]}"]
    edited = json.loads(lock_v2.dump(lock))
    edited["choices"]["matching"]["min_vertical_overlap"] = 0.3
    assert lock_v2.verify(_write(tmp_path, "edited.json", edited)) == ["lock content differs from a rebuild with the current tools"]
    base.write_text(base.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert lock_v2.verify(_write(tmp_path, "ok2.json", lock)) == ["base lock bytes differ from the lock"]


def test_a_measurement_needs_a_verified_lock_on_its_base_and_stream(tmp_path):
    base = _base(tmp_path)
    base_sha = hashlib.sha256(base.read_bytes()).hexdigest()
    draft = _write(tmp_path, "draft.json", lock_v2.build_lock(str(base), draft=True, stream="text_corrected"))
    with pytest.raises(lock_v2.LockError, match="status DRAFT_NOT_LOCKED"):
        lock_v2.require_locked(draft, base_sha, "text_corrected")
    locked = _write(tmp_path, "locked.json", lock_v2.build_lock(str(base), draft=False, stream="text_corrected",
                                                                reviewer="me", decided_on="2026-11-10"))
    with pytest.raises(lock_v2.LockError, match="another base lock"):
        lock_v2.require_locked(locked, "f" * 64, "text_corrected")
    with pytest.raises(lock_v2.LockError, match="locked stream is text_corrected, not text_raw"):
        lock_v2.require_locked(locked, base_sha, "text_raw")
    entry = lock_v2.require_locked(locked, base_sha, "text_corrected")
    assert entry["status"] == "LOCKED_PROCEDURE" and entry["sha256"] == hashlib.sha256(locked.read_bytes()).hexdigest()


def test_cli_never_overwrites_and_verify_exits_nonzero_on_a_problem(tmp_path, capsys):
    base = _base(tmp_path)
    report = tmp_path / "draft.json"
    assert lock_v2.main(["--base-lock", str(base), "--draft", "--report", str(report)]) == 0
    with pytest.raises(SystemExit):
        lock_v2.main(["--base-lock", str(base), "--draft", "--report", str(report)])
    assert lock_v2.main(["--verify", str(report)]) == 0
    base.write_text("{}", encoding="utf-8")
    assert lock_v2.main(["--verify", str(report)]) == 1
    assert "MISMATCH" in capsys.readouterr().out
