"""Greedy CTC decoding and pin checks of the V8-065 candidate crop runner."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from scripts import run_crop_candidate_recognizer as runner

CHARS = ["<blank>", "a", "b", " "]


def _log_probs(indices, prob=0.9):
    rows = []
    for index in indices:
        row = np.full(len(CHARS), math.log((1 - prob) / (len(CHARS) - 1)))
        row[index] = math.log(prob)
        rows.append(row)
    return np.array(rows)


def test_ctc_greedy_collapses_repeats_and_drops_blanks():
    text, prob = runner.ctc_greedy(_log_probs([1, 1, 0, 1, 2, 2, 0]), CHARS)
    assert text == "aab"
    assert prob == pytest.approx(0.9)


def test_ctc_greedy_collapses_whitespace_and_handles_empty_output():
    assert runner.ctc_greedy(_log_probs([3, 0, 1, 3, 0, 3, 2, 3]), CHARS)[0] == "a b"
    assert runner.ctc_greedy(_log_probs([0, 0, 0]), CHARS) == ("", 0.0)


def test_parse_tesseract_tsv_keeps_word_order_and_mean_confidence():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "1\t1\t0\t0\t0\t0\t0\t0\t100\t20\t-1\t\n"
           "4\t1\t1\t1\t1\t0\t0\t0\t100\t20\t-1\t\n"
           "5\t1\t1\t1\t1\t1\t0\t0\t40\t20\t90.0\tBáo\n"
           "5\t1\t1\t1\t1\t2\t45\t0\t40\t20\t70.0\tcáo\n"
           "5\t1\t1\t1\t1\t3\t90\t0\t5\t20\t95.0\t \n")
    text, prob = runner.parse_tesseract_tsv(tsv)
    assert text == "Báo cáo"
    assert prob == pytest.approx(0.8)
    assert runner.parse_tesseract_tsv("") == ("", 0.0)


def test_load_pin_rejects_changed_model_files(tmp_path, monkeypatch):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "w.bin").write_bytes(b"weights")
    pins = tmp_path / "pins"
    pins.mkdir()
    (pins / "demo.json").write_text(json.dumps({"local_dir": "models", "files": {
        "w.bin": {"sha256": runner.hashlib.sha256(b"weights").hexdigest()}}}), encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "PINS", pins)
    assert runner.load_pin("demo")["local_dir"] == "models"
    (tmp_path / "models" / "w.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="differs from the pin"):
        runner.load_pin("demo")
