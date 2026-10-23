"""Packaging (P10): dependency metadata, the CPU app lock and the installed
wheel layout. The real wheel build/install matrix outside the checkout is
scratch/migration/p10_matrix.py; here the installed layout is reproduced by
copying files by the same rules as setup.py."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from ocr_runtime import fingerprint

ROOT = Path(__file__).resolve().parents[3]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
EXTRAS = PROJECT["optional-dependencies"]


def pins(path):
    text = Path(path).read_text(encoding="utf-8")
    return {canonicalize_name(n): v for n, v in re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", text, re.MULTILINE)}


def test_base_dependencies_are_what_contracts_artifacts_and_keywords_need():
    assert [Requirement(r).name for r in PROJECT["dependencies"]] == ["pydantic"]
    assert all(not Requirement(r).name.startswith(("torch", "vietocr", "onnxruntime"))
               for extra in ("app", "reporting") for r in EXTRAS[extra])


def test_cpu_app_pins_satisfy_the_app_extra_and_both_locks():
    pinned = pins(ROOT / "requirements/v63/cpu-app.in")
    app = {canonicalize_name(Requirement(r).name): Requirement(r) for r in EXTRAS["app"]}
    assert set(pinned) == set(app) | {"pydantic"}
    for name, version in pinned.items():
        requirement = app.get(name) or Requirement(PROJECT["dependencies"][0])
        assert requirement.specifier.contains(version), f"{name}=={version} outside {requirement}"
    constraints = pins(ROOT / "requirements/v63/cpu-app.constraints.txt")
    for platform in ("windows", "linux"):
        lock = ROOT / f"requirements/v63/{platform}-cpu-app.lock"
        locked = pins(lock)
        assert {n: locked.get(n) for n in pinned} == pinned
        assert {n: locked.get(n) for n in constraints} == constraints
        text = lock.read_text(encoding="utf-8")
        assert text.count("--hash=sha256:") >= len(locked)
        assert "scratch/" not in text, "lock provenance must point to tracked files"


def installed_copy(site):
    """The wheel layout: `ocr_*` top-level, legacy `src/ocr`, resources in
    `ocr_runtime/resources` (setup.py BUNDLES)."""
    ignore = shutil.ignore_patterns("__pycache__")
    for package in sorted((ROOT / "src").glob("ocr_*")):
        shutil.copytree(package, site / package.name, ignore=ignore)
    shutil.copytree(ROOT / "src/ocr", site / "src/ocr", ignore=ignore)
    resources = site / "ocr_runtime/resources"
    resources.mkdir()
    for name, source in (("docling_structure_worker.py", "scripts/docling_structure_worker.py"),
                         ("keywords.txt", "config/keywords.txt"), ("profiles.yaml", "config/profiles.yaml"),
                         ("profiles-v63.yaml", "config/profiles-v63.yaml")):
        shutil.copyfile(ROOT / source, resources / name)


PROBE = """
import json
from pathlib import Path
import src.ocr
from ocr_runtime import fingerprint, paths
from ocr_pipeline.backend import prepare_backend
try:
    prepare_backend(paths.runtime_resource("profiles-v63.yaml"), "unified_gpu_full_ocr", Path(".venv-v62"))
    backend = "ACCEPTED"
except ValueError as error:
    backend = str(error)
fingerprint.assert_loaded_code_fingerprinted()
print(json.dumps({"source_tree": paths.source_tree(), "code_roots": [str(p) for p in paths.code_roots()],
                  "resource": str(paths.runtime_resource("keywords.txt")),
                  "docling_server": str(paths.docling_server_module()),
                  "fingerprints": {"full": fingerprint.source_fingerprint(), **fingerprint.code_fingerprints()},
                  "files": len(fingerprint.source_files()), "backend": backend}))
"""


def test_installed_layout_hashes_the_same_code_and_refuses_the_v63_gpu_backend(tmp_path):
    site = tmp_path / "site-packages"
    installed_copy(site)
    env = {k: v for k, v in os.environ.items() if not k.startswith("OCR_")}
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=tmp_path, capture_output=True, text=True,
                            encoding="utf-8", timeout=120, env={**env, "PYTHONPATH": str(site)})
    assert result.returncode == 0, result.stderr[-3000:]
    info = json.loads(result.stdout.strip().splitlines()[-1])
    assert info["source_tree"] is False
    assert [Path(p) for p in info["code_roots"]] == [site]
    assert Path(info["resource"]) == site / "ocr_runtime/resources/keywords.txt"
    assert Path(info["docling_server"]) == site / "ocr_workers/docling_server.py"
    # Same names, same bytes: an installed wheel and the checkout fingerprint equally.
    assert info["fingerprints"] == {"full": fingerprint.source_fingerprint(), **fingerprint.code_fingerprints()}
    assert info["files"] == len(fingerprint.source_files())
    assert info["backend"].startswith("NOT_SUPPORTED")


def test_installed_layout_detects_an_edited_installed_file(tmp_path):
    site = tmp_path / "site-packages"
    installed_copy(site)
    target = site / "ocr_workers/text_page.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    code = "import json; from ocr_runtime import fingerprint; print(json.dumps(fingerprint.code_fingerprints()))"
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                            encoding="utf-8", timeout=120, env={**os.environ, "PYTHONPATH": str(site)})
    assert result.returncode == 0, result.stderr[-3000:]
    installed = json.loads(result.stdout.strip().splitlines()[-1])
    checkout = fingerprint.code_fingerprints()
    assert installed["extraction"] != checkout["extraction"]
    assert {k: installed[k] for k in ("analysis", "publication")} == {k: checkout[k] for k in ("analysis", "publication")}


KEYWORD_PROBE = """
import json
from pathlib import Path
from src.ocr.application.count_keywords import CountKeywordsUseCase
from ocr_runtime import paths
import ocr_pipeline.analysis_run as analysis_run
from ocr_pipeline.cli import main_v63
seen = {}
analysis_run.run_analysis = lambda sources, output, keywords, **kw: seen.update(cli=str(keywords)) or {"documents": []}
main_v63(argv=["--analysis-from", "source", "--output", "out"])
report = CountKeywordsUseCase.execute(Path("document"), "document")
explicit = CountKeywordsUseCase.resolve_keywords_file("own.txt")
print(json.dumps({"is_checkout": paths.is_checkout(), "legacy": str(CountKeywordsUseCase.resolve_keywords_file()),
                  "cli": seen["cli"], "explicit": str(explicit), "matches": report.total_matches}))
"""


def test_installed_layout_in_another_project_counts_with_the_bundled_dictionary(tmp_path):
    """F04: the working directory is another Python project with its own
    pyproject.toml; legacy counting and the V6.3 CLI default must still use
    the bundled dictionary, and an explicit dictionary still wins."""
    site = tmp_path / "site-packages"
    installed_copy(site)
    project = tmp_path / "unrelated-project"
    (project / "document").mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\nname = "unrelated"\n', encoding="utf-8")
    (project / "document/result.md").write_text("Chuyển đổi số và trí tuệ nhân tạo.", encoding="utf-8")
    (project / "own.txt").write_text("chuyển đổi số\n", encoding="utf-8")
    # Under pytest's base directory a parent is this checkout; OCR_PROJECT_ROOT
    # gives the wheel the same project root it takes from the CWD elsewhere.
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("OCR_")},
           "PYTHONPATH": str(site), "OCR_PROJECT_ROOT": str(project), "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-c", KEYWORD_PROBE], cwd=project, capture_output=True, text=True,
                            encoding="utf-8", timeout=120, env=env)
    assert result.returncode == 0, result.stderr[-3000:]
    info = json.loads(result.stdout.strip().splitlines()[-1])
    bundled = site / "ocr_runtime/resources/keywords.txt"
    assert info["is_checkout"] is False
    assert Path(info["legacy"]) == bundled and Path(info["cli"]) == bundled
    assert Path(info["explicit"]) == (project / "own.txt").resolve()
    assert info["matches"] >= 2


def test_source_tree_names_are_unchanged():
    """Checkout names and order equal the paths relative to the repository, as
    before P10, so checkout fingerprints did not change meaning."""
    expected = [f.relative_to(ROOT).as_posix() for f in sorted((ROOT / "src").rglob("*.py"))]
    expected += [s for s in fingerprint.RUNTIME_SCRIPTS if (ROOT / s).is_file()]
    assert [name for name, _ in fingerprint.closure_entries("full")] == expected
