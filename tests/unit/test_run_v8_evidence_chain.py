"""The V8 evidence chain runs only steps whose reviewer input exists and never decides for the reviewer."""
import json

from scripts import run_v8_evidence_chain as chain


def _sheet(folder, items, prefix=None, decided=0):
    folder.mkdir(parents=True)
    (folder / "sheet.json").write_text(json.dumps({"sheet_id": folder.name, "items": [{}] * items}), encoding="utf-8")
    if prefix:
        (folder / "autosave").mkdir()
        (folder / "autosave" / f"{prefix}_x.decisions.jsonl").write_text("{}\n" * decided, encoding="utf-8")


def _paths(tmp_path):
    paths = {key: tmp_path / value for key, value in chain.DEFAULTS.items()}
    _sheet(paths["holdout_screening"] / "BRC", 10, "screening", 4)
    _sheet(paths["holdout_screening"] / "C47", 12)
    _sheet(paths["adjudication_sheet"], 20)
    (paths["adjudication_sheet"] / "migrated-old.jsonl").write_text("{}\n", encoding="utf-8")
    return paths


def test_status_counts_saved_decisions_per_sheet(tmp_path):
    status = chain.collect_status(_paths(tmp_path))
    assert [(r["units"], r["decided"]) for r in status["holdout_screening"]] == [(10, 4), (12, 0)]
    assert status["adjudication"]["decided"] == 0 and status["structured_gt_exports"] == []


def test_plan_runs_only_ready_steps_and_leaves_reviewer_decisions_out(tmp_path):
    paths = _paths(tmp_path)
    steps = {s["step"]: s for s in chain.plan(chain.collect_status(paths), paths, tmp_path / "out")}
    assert steps["seal screening BRC"]["run"] and not steps["seal screening C47"]["run"]
    assert not steps["seal adjudication v8"]["run"]  # migrated decisions alone are never sealed
    assert not steps["export structured labels"]["run"]
    assert not steps["holdout measurement lock and measurement"]["run"]


def test_synthetic_gt_is_never_scored(tmp_path):
    paths = _paths(tmp_path)
    paths["structured_gt"].mkdir(parents=True, exist_ok=True)
    (paths["structured_gt"] / "SYNTHETIC_NOT_GT_ABT.structure.json").write_text("{}", encoding="utf-8")
    (paths["structured_gt"] / "ABT_Baocaothuongnien_2020.structure.json").write_text("{}", encoding="utf-8")
    steps = chain.plan(chain.collect_status(paths), paths, tmp_path / "out")
    scored = [s["step"] for s in steps if s["step"].startswith("score ")]
    assert scored == [
        "score ABT_Baocaothuongnien_2020 on baseline",
        "score ABT_Baocaothuongnien_2020 on candidate",
        "score ABT_Baocaothuongnien_2020 on candidate_rec",
    ]
