"""The v8 knowledge map must only state status that points at real evidence."""
import json
import subprocess

import pytest

from scripts import build_dev_context as context
from scripts import check_knowledge_map as km


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def commit(root, message):
    context.git(root, "add", "-A")
    context.git(root, "-c", "user.name=Map Test", "-c", "user.email=test@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-qm", message)
    return context.git(root, "rev-parse", "HEAD").strip()


BACKLOG_ROW = ("V8-001,Khóa baseline,L0,G01,QA-01,CT-03,docs,P0,TODO,,"
               "src/pkg/mod.py;planned:benchmark/challengers/x.py,,identity locked,\n")


def registry_for(head, source_sha):
    return {
        "schema_version": km.SCHEMA, "program_label": "OCR PDF v8.0", "pipeline_version": "7.0.0",
        "verified_head": head, "last_verified": "2026-11-08", "verified_scope": "fixture",
        "sources": [{"path": "cai tien v2/source.md", "sha256": source_sha}],
        "layers": [{"id": "L3", "name": "Recognition", "capability": "IMPLEMENTED",
                    "quality": "NOT_EVALUATED", "backlog": ["V8-001"],
                    "evidence": [{"path": "src/pkg/mod.py", "symbol": "Engine", "label": "VERIFIED"}]}],
        "gaps": [{"id": "G01", "title": "Benchmark", "status": "PARTIAL", "quality": "NOT_EVALUATED",
                  "qa_ref": ["QA-G01"], "backlog": ["V8-001"],
                  "evidence": [{"path": "src/pkg/mod.py", "symbol": "LIMIT", "label": "VERIFIED"}]},
                 {"id": "G05", "title": "VLM", "status": "MISSING", "searched": "git grep -i paddle",
                  "evidence": [], "backlog": []}],
        "diacritic_gate": {"target": "99,99%", "status": "NOT_EVALUATED", "blocker": "no GT", "evidence": []},
        "phases": [{"id": "P0", "title": "Baseline lock", "status": "TODO", "exit_gate": "identity",
                    "backlog": ["V8-001"]}],
        "exports": [],
    }


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo with spaces"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    write(root, "Cai Tien/README.md", "old index\n")
    archive = commit(root, "archive")
    (root / "Cai Tien/README.md").unlink()
    write(root, ".gitignore", "scratch/\n")
    write(root, km.VERSION_FILE, 'PIPELINE_VERSION = "7.0.0"\n')
    write(root, "src/pkg/mod.py", "LIMIT = 3\n\n\nclass Engine:\n    def run(self):\n        return LIMIT\n")
    source = write(root, "cai tien v2/source.md", "tài liệu nguồn\n")
    write(root, km.BACKLOG, ",".join(km.BACKLOG_HEADER) + "\n" + BACKLOG_ROW)
    write(root, km.RENDER_TARGETS["gaps"], "# Kiểm toán\n\n<!-- v8-status:gaps:begin -->\n"
          "<!-- v8-status:gaps:end -->\n\n[skill](../.claude/skills/ocr-pdf-knowledge-map/SKILL.md)\n")
    write(root, km.RENDER_TARGETS["phases"], "# Lộ trình\n\n<!-- v8-status:phases:begin -->\n"
          "<!-- v8-status:phases:end -->\n")
    write(root, km.ARCHIVE_DOC, f'# Lưu trữ\n\n<a id="ct-00"></a>\n`git show {archive[:7]}:"Cai Tien/README.md"`\n')
    write(root, f"{km.SKILL_DIR}/SKILL.md", "---\nname: ocr-pdf-knowledge-map\n"
          "description: Bản đồ kiến thức; dùng khi hỏi dự án đang ở đâu.\n---\n\n# Bản đồ\n\n"
          "[tầng](references/layers.md), [lưu trữ](../../../cai%20tien%20v2/09_LUU_TRU_CAI_TIEN_V7.md#ct-00)\n")
    write(root, f"{km.SKILL_DIR}/references/layers.md", "# Tầng\n")
    head = commit(root, "map")
    registry = registry_for(head, km.sha256_file(source))
    write(root, km.REGISTRY, json.dumps(registry, ensure_ascii=False, indent=2))
    km.render(root, registry)
    monkeypatch.setattr(context, "DOC_BUDGETS", {rel: 50000 for rel in km.map_documents(root, registry)})
    monkeypatch.setattr(km, "ROOT", root)
    return root


def mutate(root, change):
    registry = json.loads((root / km.REGISTRY).read_text(encoding="utf-8"))
    change(registry)
    write(root, km.REGISTRY, json.dumps(registry, ensure_ascii=False, indent=2))
    return registry


def errors(root):
    return km.check(root)[0].errors


def test_valid_map_passes_and_summary_reads_only_the_registry(repo, capsys):
    report, registry, backlog, head = km.check(repo)
    assert report.errors == [] and report.stale == [] and report.not_evaluated == []
    text = km.summary(registry, backlog, report, head)
    assert "FRESH" in text and "G05" in text and "MISSING" in text and "V8-001" in text
    assert km.main(["--summary"]) == 0
    assert "Cổng dấu 99,99%: NOT_EVALUATED" in capsys.readouterr().out


@pytest.mark.parametrize("change, message", [
    (lambda r: r["gaps"][0].update(status="DONE"), "status must be one of"),
    (lambda r: r["gaps"][0].update(evidence=[]), "PARTIAL needs tracked evidence"),
    (lambda r: r["gaps"][1].update(searched=""), "MISSING needs the search"),
    (lambda r: r["gaps"][0]["evidence"][0].update(path="src/pkg/MOD.py"), "does not exist"),
    (lambda r: r["gaps"][0]["evidence"][0].update(symbol="Missing"), "symbol Missing not defined"),
    (lambda r: r["gaps"][0]["evidence"][0].update(label="PROVEN"), "evidence label"),
    (lambda r: r["layers"][0].update(quality="PASS"), "needs existing gt_evidence"),
    (lambda r: r["diacritic_gate"].update(status="PASS", gt_evidence=["src/pkg/mod.py"]), "gt_source_kind"),
    (lambda r: r["phases"][0].update(backlog=["V8-999"]), "unknown backlog id V8-999"),
    (lambda r: r.update(pipeline_version="8.0.0"), "pipeline_version"),
    (lambda r: r.update(verified_head="08f7602"), "40-character"),
])
def test_status_claims_need_evidence(repo, change, message):
    mutate(repo, change)
    assert any(message in item for item in errors(repo))


def test_ignored_evidence_must_be_declared_local_only(repo):
    write(repo, "scratch/run.json", "{}")
    entry = {"path": "scratch/run.json", "label": "VERIFIED"}
    km.render(repo, mutate(repo, lambda r: r["gaps"][0]["evidence"].append(dict(entry))))
    assert any("Git-ignored" in item for item in errors(repo))
    km.render(repo, mutate(repo, lambda r: r["gaps"][0]["evidence"][-1].update(
        local_only=True, path="scratch/gone.json")))
    report = km.check(repo)[0]
    assert report.errors == [] and any("local-only" in item for item in report.warnings)


@pytest.mark.parametrize("row, message", [
    ("V8-1,x,L0,G01,,,docs,P0,TODO,,,,,\n", "must match V8-NNN"),
    ("V8-001,x,L0,G01,,,docs,P0,TODO,,,,,\n", "Duplicate backlog id"),
    ("V8-002,x,L0,G01,,,docs,P9,TODO,,,,,\n", "priority"),
    ("V8-002,x,L0,G01,,,docs,P1,DONE,,,,,\n", "DONE needs evidence"),
    ("V8-002,x,L0,G01,,,docs,P1,TODO,V8-404,,,,\n", "blocked_by unknown id V8-404"),
    ("V8-002,x,L0,G01,,,docs,P1,TODO,,src/missing.py,,,\n", "path does not exist"),
])
def test_backlog_rows_are_validated(repo, row, message):
    with (repo / km.BACKLOG).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(row)
    assert any(message in item for item in errors(repo))


def test_links_resolve_and_old_folder_is_banned_outside_history(repo):
    write(repo, "CLEANUP_REPORT.md", "[old](Cai%20Tien/README.md)\n")
    write(repo, "docs/note.md", "[old](../Cai%20Tien/README.md)\n")
    found = errors(repo)
    assert any(item.startswith("docs/note.md: link into deleted folder") for item in found)
    assert not any(item.startswith("CLEANUP_REPORT.md") for item in found)
    (repo / "docs/note.md").unlink()
    page = repo / km.RENDER_TARGETS["phases"]
    original = page.read_text(encoding="utf-8")
    page.write_text(original + "[thiếu](missing.md) [neo](09_LUU_TRU_CAI_TIEN_V7.md#ct-99) "
                    "[cục bộ](../scratch/run.json) [web](https://example.invalid/x)\n",
                    encoding="utf-8", newline="\n")
    report = km.check(repo)[0]
    assert any("link target not found: missing.md" in item for item in report.errors)
    assert any("anchor #ct-99" in item for item in report.errors)
    assert any("../scratch/run.json" in item for item in report.warnings)
    assert not any("example.invalid" in item for item in report.errors + report.warnings)


def test_generated_tables_must_match_the_registry(repo):
    registry = mutate(repo, lambda r: r["gaps"][0].update(status="BROKEN"))
    assert any("run --render" in item for item in errors(repo))
    assert km.render(repo, registry) == [km.RENDER_TARGETS["gaps"]]
    assert errors(repo) == []
    assert "| G01 Benchmark | BROKEN |" in (repo / km.RENDER_TARGETS["gaps"]).read_text(encoding="utf-8")


def test_unmeasured_token_claims_and_line_numbers_are_rejected(repo):
    layers = repo / km.SKILL_DIR / "references/layers.md"
    layers.write_text("# Tầng\nGiảm 1.200 tokens mỗi phiên.\nXem src/pkg/mod.py:3\n", encoding="utf-8")
    found = errors(repo)
    assert any("unmeasured token claim" in item for item in found)
    assert any("not .py line numbers" in item for item in found)
    layers.write_text("# Tầng\nTiết kiệm 40% token: NOT_MEASURED.\n", encoding="utf-8")
    assert errors(repo) == []


def test_skill_frontmatter_and_budgets(repo, monkeypatch):
    skill = repo / km.SKILL_DIR / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    skill.write_text(text.replace("name: ocr-pdf-knowledge-map", "name: Other Map"), encoding="utf-8")
    assert any("name must be" in item for item in errors(repo))
    skill.write_text(text.replace("description: Bản đồ", "description: " + "x" * 1100), encoding="utf-8")
    assert any("1..1024" in item for item in errors(repo))
    skill.write_text(text, encoding="utf-8")
    write(repo, f"{km.SKILL_DIR}/references/extra.md", "# Thêm\n")
    assert any("No DOC_BUDGETS entry" in item for item in errors(repo))
    budgets = dict(context.DOC_BUDGETS, **{f"{km.SKILL_DIR}/references/extra.md": 3})
    monkeypatch.setattr(context, "DOC_BUDGETS", budgets)
    assert any("over budget" in item for item in errors(repo))


def test_new_commits_make_the_map_stale_but_not_failing(repo):
    write(repo, "src/pkg/mod.py", "LIMIT = 4\n\n\nclass Engine:\n    pass\n")
    commit(repo, "evidence changed")
    report = km.check(repo)[0]
    assert report.errors == [] and any("src/pkg/mod.py" in item for item in report.stale)
    assert report.exit_code() == 0 and report.exit_code(require_fresh=True) == 1
    mutate(repo, lambda r: r.update(verified_head="f" * 40))
    report = km.check(repo)[0]
    assert any("not in this clone" in item for item in report.not_evaluated)


def test_sources_exports_and_archive_track_drift(repo):
    write(repo, "cai tien v2/source.md", "nguồn đã sửa\n")
    assert any("Source document changed" in item for item in km.check(repo)[0].stale)
    write(repo, "cai tien v2/out.docx", "docx")
    export = {"path": "cai tien v2/out.docx", "sha256": km.sha256_file(repo / "cai tien v2/out.docx"),
              "sources": [{"path": km.RENDER_TARGETS["gaps"], "sha256": "0" * 64}]}
    mutate(repo, lambda r: r["exports"].append(export))
    assert any("older than its source" in item for item in km.check(repo)[0].stale)
    archive = repo / km.ARCHIVE_DOC
    archive.write_text(archive.read_text(encoding="utf-8").replace("README.md", "MISSING.md"), encoding="utf-8")
    assert any("Archive path not in" in item for item in errors(repo))


def test_outside_folder_and_line_suffix_links_are_errors_not_crashes(repo):
    page = repo / km.RENDER_TARGETS["phases"]
    page.write_text(page.read_text(encoding="utf-8") + "[ngoài](../../outside.md) [thư mục cũ](../Cai%20Tien) "
                    "[dòng](MISSING.md:12)\n", encoding="utf-8", newline="\n")
    assert km.main([]) == 1
    found = errors(repo)
    assert any("leaves the checkout: ../../outside.md" in item for item in found)
    assert any("deleted folder: ../Cai%20Tien" in item for item in found)
    assert any("link target not found: MISSING.md:12" in item for item in found)


def test_ignored_evidence_with_symbol_is_reported_without_reading_it(repo):
    km.render(repo, mutate(repo, lambda r: r["gaps"][0]["evidence"].append(
        {"path": "scratch/absent.py", "symbol": "X", "label": "VERIFIED"})))
    assert any("Git-ignored" in item for item in errors(repo))


def test_commit_without_evidence_change_stays_fresh(repo):
    write(repo, "notes.md", "# Ghi chú\n")
    commit(repo, "unrelated")
    report = km.check(repo)[0]
    assert report.stale == [] and report.freshness == "FRESH_EVIDENCE_UNCHANGED"
    assert report.exit_code(require_fresh=True) == 0


@pytest.mark.parametrize("change", [
    lambda r: r["gaps"][0].update(evidence=["src/pkg/mod.py"]),
    lambda r: r.update(verified_head=None),
    lambda r: r["phases"][0].update(status=None, backlog="V8-001"),
])
def test_wrong_registry_types_are_usage_errors(repo, change, capsys):
    mutate(repo, change)
    assert km.main(["--summary"]) == 2
    assert "Cannot check knowledge map" in capsys.readouterr().err


def test_crlf_checkout_keeps_hashes_and_budgets(repo, monkeypatch):
    for rel in ("cai tien v2/source.md", f"{km.SKILL_DIR}/SKILL.md", km.RENDER_TARGETS["gaps"]):
        path = repo / rel
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    skill = f"{km.SKILL_DIR}/SKILL.md"
    lf_size = len((repo / skill).read_bytes().replace(b"\r\n", b"\n"))
    monkeypatch.setattr(context, "DOC_BUDGETS", dict(context.DOC_BUDGETS, **{skill: lf_size}))
    report = km.check(repo)[0]
    assert report.errors == [] and report.stale == []


def test_missing_registry_is_a_usage_error(repo, capsys):
    (repo / km.REGISTRY).unlink()
    assert km.main([]) == 2
    assert "Cannot check knowledge map" in capsys.readouterr().err


def test_real_checkout_map_has_no_errors():
    report = km.check(km.ROOT)[0]
    assert report.errors == []


def test_source_removed_by_the_user_is_verified_in_its_commit(repo):
    head = km.run_git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    (repo / "cai tien v2/source.md").unlink()
    assert "Source document missing: cai tien v2/source.md" in errors(repo)
    mutate(repo, lambda r: r["sources"][0].update(git_preserved={"commit": head}))
    assert not [item for item in errors(repo) if "source.md" in item]
    mutate(repo, lambda r: r["sources"][0].update(sha256="0" * 64))
    assert "Preserved source differs from its mapped sha256: cai tien v2/source.md" in errors(repo)
    mutate(repo, lambda r: r["sources"][0].update(git_preserved={"commit": "0" * 40}))
    assert any(item.startswith("Source document missing and not in commit") for item in errors(repo))


def test_preserved_source_in_a_shallow_clone_is_not_evaluated(repo, tmp_path):
    # CI checks out depth 1: the preserving commit is absent, which is unverifiable, not missing.
    preserving = km.run_git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    (repo / "cai tien v2/source.md").unlink()
    mutate(repo, lambda r: r["sources"][0].update(git_preserved={"commit": preserving}))
    commit(repo, "remove the source")
    assert not [item for item in errors(repo) if "source.md" in item]
    clone = tmp_path / "shallow clone"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-local", str(repo), str(clone)], check=True)
    report = km.check(clone)[0]
    assert not [item for item in report.errors if "source.md" in item]
    assert any(item.endswith("not in this shallow clone: cai tien v2/source.md") for item in report.not_evaluated)
