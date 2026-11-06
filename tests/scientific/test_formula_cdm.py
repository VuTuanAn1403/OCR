"""Counterexamples for formula rendering and denominator preservation."""
from __future__ import annotations

import hashlib
import subprocess
import sys

import pytest

from benchmark.scientific_evaluation import formula_cdm as cdm


def rendered(tokens):
    return {"status": "RENDERED", "method": cdm.METHOD, "tokens": [
        {"token": token, "bbox": [index * 12 + 2, 3, index * 12 + 10, 14]}
        for index, token in enumerate(tokens)], "tex_engine": "lualatex", "image_size": [max(20, len(tokens) * 12 + 4), 20]}


def test_vendor_manifest_identifies_all_unmodified_files():
    evidence = cdm.verify_vendor()
    assert evidence["revision"] == "5a2c80d96b1d2dba447ff18d873e5fb73ba03c35"
    assert evidence["verified_files"] == 32


def test_formula_module_import_does_not_require_other_metric_or_model_packages():
    script = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'bs4', 'apted', 'torch', 'docling', 'numpy', 'scipy', 'skimage', 'PIL', 'pymupdf'}:
            raise AssertionError('Unexpected eager import: ' + fullname)
sys.meta_path.insert(0, Block())
from benchmark.scientific_evaluation import formula_cdm
assert formula_cdm.METHOD.startswith('unimernet-cdm-')
"""
    subprocess.run([sys.executable, "-B", "-c", script], check=True, capture_output=True, text=True)


def test_existing_public_exports_remain_available():
    import benchmark.scientific_evaluation as suite
    from benchmark.scientific_evaluation.teds_metric import compute_teds
    assert suite.compute_teds is compute_teds
    assert set(suite.__all__) == set(suite._MODULE_BY_EXPORT)
    assert set(suite.__all__) <= set(dir(suite))
    with pytest.raises(AttributeError):
        getattr(suite, "unknown_metric")


def test_counts_are_not_rounded_to_perfect():
    reference = rendered(["x"] * 1000)
    prediction = rendered(["x"] * 999 + ["y"])
    result = cdm.compare_renders(reference, prediction)
    assert (result["tp"], result["fp"], result["fn"]) == (999, 1, 1)
    assert result["cdm_f1"] == .999
    assert result["rendered_character_exact"] is False


def test_matching_keeps_insertions_and_deletions():
    reference, prediction = rendered(["x", "=", "a", "+", "b"]), rendered(["x", "=", "a"])
    result = cdm.compare_renders(reference, prediction)
    assert (result["tp"], result["fp"], result["fn"]) == (3, 0, 2)
    reverse = cdm.compare_renders(prediction, reference)
    assert (reverse["tp"], reverse["fp"], reverse["fn"]) == (3, 2, 0)


def test_visually_equivalent_aliases_follow_pinned_matcher():
    result = cdm.compare_renders(rendered([r"\leq"]), rendered([r"\le"]))
    assert result["cdm_f1"] == 1
    assert result["matches"][0]["token_cost"] == .005


def test_unicode_math_aliases_preserve_variants_and_numeric_content():
    reference = rendered(["α", "ϵ", "−", "0", "2", "0"])
    equivalent = rendered([r"\alpha", r"\epsilon", "-", "0", "2", "0"])
    variant_and_number_change = rendered([r"\alpha", r"\varepsilon", "-", "O", "2", "0"])
    assert cdm.compare_renders(reference, equivalent)["cdm_f1"] == 1
    difference = cdm.compare_renders(reference, variant_and_number_change)
    assert (difference["tp"], difference["fp"], difference["fn"]) == (4, 2, 2)


def test_no_reference_does_not_create_a_score():
    result = cdm.compare_renders({"status": "RENDER_FAILED"}, rendered(["x"]))
    assert result["status"] == "NOT_EVALUATED"
    assert result["cdm_f1"] is None and result["tp"] is None


def test_missing_prediction_counts_all_reference_deletions():
    result = cdm.compare_renders(rendered(["x", "=", "1"]), None)
    assert result["status"] == "MEASURED"
    assert (result["tp"], result["fp"], result["fn"]) == (0, 0, 3)
    assert result["cdm_f1"] == 0 and result["rendered_character_exact"] is False


def test_failed_prediction_has_zero_pair_score_but_unknown_character_insertions():
    result = cdm.compare_renders(rendered(["x", "=", "1"]),
                                 {"status": "RENDER_FAILED", "error_kind": "CONTENT_RENDER_FAILURE"})
    assert result["cdm_f1"] == 0 and result["fn"] == 3
    assert result["fp"] is None and result["prediction_characters"] is None


def test_coloring_keeps_subscripts_superscripts_and_fraction_bar():
    tex, normalized, tokens, colors = cdm._colored(r"x _ { 1 } ^ { 2 } = \frac { a } { b }")
    assert tokens == ["x", "1", "2", "=", r"\frac", "a", "b"]
    assert len(colors) == len(set(colors)) == len(tokens)
    assert "<color_" not in tex and r"\frac" in tex


def fake_runtime(tmp_path):
    executable = tmp_path / "tool.exe"
    executable.write_bytes(b"controlled fixture executable identity")
    return {"method": cdm.LEGACY_METHOD, "tools": {name: {"path": str(executable), "sha256": cdm._sha(executable)}
                                           for name in ("node", "pdflatex")}}


@pytest.mark.parametrize("raw,fmt,reason", [
    (r"\input{secret}", "LATEX", "Unsupported non-math"),
    (r"\csname input\endcsname", "LATEX", "Unsupported non-math"),
    (r"\latelua{os.execute('bad')}", "LATEX", "Unsupported non-math"),
    ("^^5cinput", "LATEX", "Unsupported non-math"),
    ("x²", "TEXT", "UNSUPPORTED_REPRESENTATION:TEXT"),
    ("<math>x</math>", "MATHML", "UNSUPPORTED_REPRESENTATION:MATHML"),
    ("", "LATEX", "Empty formula"),
])
def test_invalid_representation_preserves_raw_and_never_spawns(tmp_path, monkeypatch, raw, fmt, reason):
    def unexpected(*args, **kwargs):
        raise AssertionError("Invalid source must not spawn an evaluator process")
    monkeypatch.setattr(cdm, "_run", unexpected)
    result = cdm.render_formula(raw, tmp_path / "render", fake_runtime(tmp_path), content_format=fmt)
    assert result["status"] == "RENDER_FAILED" and reason in result["reason"]
    assert (tmp_path / "render/source.txt").read_text(encoding="utf-8") == raw
    assert result["raw_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_render_cannot_reuse_a_previous_output(tmp_path):
    directory = tmp_path / "existing"
    directory.mkdir()
    with pytest.raises(FileExistsError):
        cdm.render_formula("x", directory, {})


def test_source_limit_includes_whitespace_and_rejects_before_copy_or_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(cdm, "_run", lambda *args, **kwargs: pytest.fail("Must not spawn an oversized source"))
    raw = " " * cdm.MAX_CHARACTERS + "x"
    result = cdm.render_formula(raw, tmp_path / "oversized", fake_runtime(tmp_path))
    assert result["error_kind"] == "EVALUATOR_LIMIT"
    assert result["source_characters"] == len(raw)
    assert not (tmp_path / "oversized/source.txt").exists()


def test_runtime_hash_always_identifies_the_same_serialized_artifact(tmp_path):
    runtime = fake_runtime(tmp_path)
    cdm._write(tmp_path / "runtime.json", runtime)
    result = cdm.render_formula("x²", tmp_path / "render", runtime, content_format="TEXT")
    assert result["runtime_sha256"] == cdm._sha(tmp_path / "runtime.json")


@pytest.mark.parametrize("message,kind", [
    ("Expected group after '\\frac' at position 8: expression", "CONTENT_RENDER_FAILURE"),
    ("Expected '}', got 'EOF' at position 7: expression", "CONTENT_RENDER_FAILURE"),
    ("Unexpected character: 'ế' at position 3: expression", "TOKENIZER_UNSUPPORTED_OR_FAILED"),
    ("Undefined control sequence: \\qty at position 1: expression", "TOKENIZER_UNSUPPORTED_OR_FAILED"),
])
def test_tokenizer_reports_unsupported_latex_separately_from_known_syntax_errors(tmp_path, message, kind):
    (tmp_path / "tokenize.stderr").write_text("ParseError: KaTeX parse error: " + message, encoding="utf-8")
    assert cdm._tokenizer_error(tmp_path, {"stderr": "tokenize.stderr"}) == kind


@pytest.mark.parametrize("kind", ["UNSUPPORTED_REPRESENTATION", "EVALUATOR_ERROR", "EVALUATOR_LIMIT",
                                  "RUNTIME_IDENTITY_MISMATCH", "MISSING_TEX_DEPENDENCY", None])
def test_evaluator_limits_or_unsupported_text_do_not_become_model_errors(kind):
    result = cdm.compare_renders(rendered(["x"]), {"status": "RENDER_FAILED", "error_kind": kind})
    assert result["status"] == "NOT_EVALUATED"
    assert result["cdm_f1"] is None and result["tp"] is None and result["fn"] is None
    assert result["reference_characters"] == 1


def test_character_exact_does_not_hide_a_superscript_subscript_change():
    reference, prediction = rendered(["x", "2"]), rendered(["x", "2"])
    reference["normalized_latex"] = "x ^ { 2 }"
    prediction["normalized_latex"] = "x _ { 2 }"
    result = cdm.compare_renders(reference, prediction)
    assert result["rendered_character_exact"] is True and result["cdm_f1"] == 1
    assert result["normalized_latex_equal"] is False
    assert result["review_reasons"] == ["CHARACTER_MATCH_DOES_NOT_VALIDATE_CRITICAL_STRUCTURE"]


@pytest.mark.parametrize("box", [[], [0, 0, 0, 5], [0, 0, float('nan'), 5], [0, 0, 300, 5]])
def test_incomplete_or_invalid_rendered_glyphs_cannot_shrink_the_denominator(box):
    reference = rendered(["x"])
    reference["tokens"][0]["bbox"] = box
    with pytest.raises(ValueError, match="glyph requires"):
        cdm.compare_renders(reference, rendered(["x"]))


def test_failed_reference_is_not_hidden_in_cohort_mean(tmp_path, monkeypatch):
    monkeypatch.setattr(cdm, "runtime_identity", lambda *args: {"method": cdm.METHOD})
    monkeypatch.setattr(cdm, "render_formula", lambda raw, *args, **kwargs:
                        {"status": "RENDER_FAILED"} if raw == "bad" else rendered([raw]))
    rows = [{"id": "one", "reference": "x", "prediction": "x"},
            {"id": "two", "reference": "bad", "prediction": "x"}]
    report = cdm.evaluate_pairs(rows, tmp_path / "pairs", node="fixture", pdflatex="fixture")
    assert report["status"] == "NOT_EVALUATED" and report["mean_cdm"] is None
    assert report["pairs"] == 2 and report["measured_pairs"] == 1
    assert report["diagnostic_measured_subset_mean"] == 1
    assert report["acceptance_status"] == "NOT_EVALUATED"


def test_process_timeout_terminates_owned_process_and_keeps_logs(tmp_path):
    result = cdm._run([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, "timeout", timeout=.2)
    assert result["timed_out"] is True and result["returncode"] != 0
    assert (tmp_path / result["stderr"]).is_file()


def test_process_uses_argument_vector_for_shell_metacharacters(tmp_path):
    argument = "x & echo must-not-execute; $(echo literal)"
    result = cdm._run([sys.executable, "-c", "import sys; print(sys.argv[1])", argument], tmp_path, "literal")
    assert result["returncode"] == 0
    assert (tmp_path / result["stdout"]).read_text().strip() == argument


@pytest.mark.parametrize("pairs", [[], [{"id": "x"}, {"id": "x"}], [None]])
def test_pair_identity_rejected_before_output_creation(tmp_path, pairs):
    with pytest.raises(ValueError):
        cdm.evaluate_pairs(pairs, tmp_path / "output", node="unused", pdflatex="unused")
    assert not (tmp_path / "output").exists()
