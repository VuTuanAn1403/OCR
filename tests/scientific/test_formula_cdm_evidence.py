"""CDM evidence is bound to exact pairs, observed runtime and rendered glyphs."""
from copy import deepcopy
import hashlib
import json

import pytest

from benchmark.scientific_evaluation import formula_cdm as cdm


def _runtime():
    return {"method": cdm.LEGACY_METHOD, "vendor": cdm.verify_vendor(), "packages": {"package": "fixture"},
            "adapter_sha256": cdm._sha(cdm.__file__), "dpi": 200, "antialias_bits": 0, "color_tolerance_rgb": 1, "limits": {},
            "python": {"version": "fixture", "sha256": "b" * 64, "executable": "old-path"},
            "tools": {name: {"sha256": "c" * 64, "version": "fixture", "adjacent_dlls": [], "path": "old-path",
                              "probe": {"seconds": 1}} for name in ("node", "pdflatex")}}


def _render(raw, directory, runtime, *, content_format, tex_cache):
    directory.mkdir(parents=True)
    rows = [{"token": value, "bbox": [2 + i * 12, 3, 10 + i * 12, 14]} for i, value in enumerate(raw)]
    (directory / "source.txt").write_bytes(raw.encode("utf-8"))
    cdm._write(directory / "glyphs.json", rows)
    for name in ("colored.png", "base.png", "formula.tex", "formula.pdf"):
        (directory / name).write_bytes(b"controlled fixture, not a renderer result")
    report = {"schema_version": cdm.SCHEMA, "method": cdm.LEGACY_METHOD, "status": "RENDERED", "error_kind": None,
              "content_format": content_format, "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
              "runtime_sha256": hashlib.sha256(cdm._json_bytes(runtime)).hexdigest(),
              "tex_inputs": [{"path": str(directory / "formula.tex"), "sha256": cdm._sha(directory / "formula.tex")}],
              "tokens": rows, "image_size": [60, 20], "artifacts": [{"path": path.name, "sha256": cdm._sha(path),
                 "bytes": path.stat().st_size} for path in directory.iterdir()]}
    cdm._write(directory / "render.json", report)
    return report


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    observed = _runtime()
    locked = deepcopy(observed)
    locked["tools"]["node"]["probe"]["seconds"] = 99
    locked["python"]["executable"] = "other-path"
    monkeypatch.setattr(cdm, "runtime_identity", lambda *_: observed)
    monkeypatch.setattr(cdm, "render_formula", _render)
    expected, pairs, output = tmp_path / "runtime.json", tmp_path / "pairs.json", tmp_path / "cdm"
    cdm._write(expected, locked)
    cdm._write(pairs, [{"id": "different", "reference": "x=1", "prediction": "x=2"},
                       {"id": "missing", "reference": "x", "prediction": None}])
    cdm.evaluate_pair_file(pairs, output, node="fixture", pdflatex="fixture", expected_runtime_path=expected,
                           expected_runtime_sha256=cdm._sha(expected))
    return pairs, output, expected


def test_verified_comparison_recomputes_glyph_matching_and_missing_denominator(comparison):
    pairs, output, expected = comparison
    scores, evidence = cdm.verify_comparison(output, pairs, expected_runtime_path=expected,
                                             expected_runtime_sha256=cdm._sha(expected))
    assert scores == {"different": 2 / 3, "missing": 0}
    assert evidence["render_evidence_verified"] and evidence["runtime_sha256"] == cdm._sha(output / "runtime.json")


def test_arithmetically_consistent_forged_counts_fail_render_recomputation(comparison):
    pairs, output, _ = comparison
    path = output / "comparison.json"
    report = json.loads(path.read_bytes())
    report["details"][0].update(tp=3, fp=0, fn=0, cdm_f1=1.0)
    path.write_bytes(cdm._json_bytes(report))
    with pytest.raises(ValueError, match="recomputed render matching"):
        cdm.verify_comparison(output, pairs)


def test_render_artifact_and_pair_tampering_are_rejected(comparison):
    pairs, output, _ = comparison
    row = json.loads((output / "comparison.json").read_bytes())["details"][0]
    (output / row["directory"] / "reference/formula.pdf").write_bytes(b"different PDF")
    with pytest.raises(ValueError, match="render artifact changed"):
        cdm.verify_comparison(output, pairs)
    pairs.write_bytes(pairs.read_bytes() + b" ")
    with pytest.raises(ValueError, match="input, method or runtime"):
        cdm.verify_comparison(output, pairs)


def test_runtime_difference_blocks_before_any_formula_render(tmp_path, monkeypatch):
    observed, locked = _runtime(), _runtime()
    observed["packages"]["package"] = "changed"
    monkeypatch.setattr(cdm, "runtime_identity", lambda *_: observed)
    monkeypatch.setattr(cdm, "render_formula", lambda *_args, **_kwargs: pytest.fail("Rendered using different runtime"))
    with pytest.raises(ValueError, match="differs from the locked renderer"):
        cdm.evaluate_pairs([{"id": "x", "reference": "x", "prediction": "x"}], tmp_path / "out",
                           node="fixture", pdflatex="fixture", expected_runtime=locked)
    assert not (tmp_path / "out/comparison.json").exists()


def test_repinned_locked_runtime_change_is_rejected(comparison):
    pairs, output, expected = comparison
    raw = json.loads(expected.read_bytes())
    raw["tools"]["pdflatex"]["adjacent_dlls"] = [{"name": "changed.dll", "sha256": "e" * 64}]
    expected.write_bytes(cdm._json_bytes(raw))
    with pytest.raises(ValueError, match="locked renderer"):
        cdm.verify_comparison(output, pairs, expected_runtime_path=expected, expected_runtime_sha256=cdm._sha(expected))


def test_cached_renderer_preserves_evidence_digest_and_rejects_changed_execution_logs(comparison, monkeypatch):
    from benchmark.scientific_evaluation.formula_holdout_replay import _cached_pairs

    pairs, output, expected = comparison
    process = {"returncode": 0, "timed_out": False, "output_limit_exceeded": False}
    for name in ("stdout", "stderr"):
        path = output.parent / name
        path.write_bytes(b"controlled completed process log")
        process.update({name: path.name, f"{name}_sha256": cdm._sha(path)})
    cdm._write(output.parent / "cdm-process.json", process)
    original_hash = cdm._sha(output / "comparison.json")
    monkeypatch.setattr(cdm, "_run", lambda *_args, **_kwargs: pytest.fail("Cached verification must not spawn"))
    _, first = _cached_pairs(output, pairs, expected, cdm._sha(expected))
    _, second = _cached_pairs(output, pairs, expected, cdm._sha(expected))
    assert first == second and first["comparison_sha256"] == original_hash
    (output.parent / "stdout").write_bytes(b"changed execution log")
    with pytest.raises(ValueError, match="process log changed"):
        _cached_pairs(output, pairs, expected, cdm._sha(expected))
    locked = json.loads(expected.read_bytes())
    locked["adapter_sha256"] = "e" * 64
    expected.write_bytes(cdm._json_bytes(locked))
    with pytest.raises(ValueError, match="renderer code differs"):
        _cached_pairs(output, pairs, expected, cdm._sha(expected))
