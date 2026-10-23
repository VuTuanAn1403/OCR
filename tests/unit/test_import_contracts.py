"""Enforce the dependency table, including controlled violations (P13)."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Internal dependencies from the design's "Quy tắc phụ thuộc" table. Self
# imports are implicit. Keeping this independent of pyproject.toml makes the
# negative probe catch a missing forbidden edge in that configuration.
ALLOWED = {
    "ocr_contracts": set(),
    "ocr_artifacts": {"ocr_contracts"},
    "ocr_text": set(),
    "ocr_runtime": {"ocr_contracts", "ocr_artifacts"},
    "ocr_keywords": {"ocr_contracts", "ocr_artifacts"},
    "ocr_reporting": {"ocr_contracts", "ocr_artifacts", "ocr_keywords"},
    "ocr_pdf_io": {"ocr_contracts", "ocr_artifacts", "ocr_runtime", "ocr_text"},
    "ocr_recognition": {"ocr_contracts", "ocr_artifacts", "ocr_runtime", "ocr_text", "ocr_pdf_io"},
    "ocr_layout": {"ocr_contracts", "ocr_artifacts", "ocr_runtime", "ocr_text", "ocr_pdf_io"},
    "ocr_structure": {"ocr_contracts", "ocr_artifacts", "ocr_runtime", "ocr_text", "ocr_pdf_io"},
    "ocr_document": {"ocr_contracts", "ocr_artifacts", "ocr_runtime", "ocr_text", "ocr_pdf_io"},
}
ALLOWED["ocr_workers"] = set(ALLOWED) - {"ocr_keywords", "ocr_reporting"}
ALLOWED["ocr_pipeline"] = set(ALLOWED) - {"ocr_workers"}


def _lint(checkout, *contracts):
    executable = shutil.which("lint-imports", path=str(Path(sys.executable).parent)) or shutil.which("lint-imports")
    assert executable, "import-linter is required for tests (pip install -e .[test])"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join([str(checkout / "src"), str(checkout)])}
    command = [executable, "--no-cache", "--config", str(checkout / "pyproject.toml")]
    for contract in contracts:
        command.extend(["--contract", contract])
    return subprocess.run(command, cwd=checkout, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=300)


def _details(result):
    return result.stdout + result.stderr


def _module(checkout, name, source=""):
    """Create only inert Python files; import-linter parses rather than runs them."""
    parts = name.split(".")
    location = checkout / "src"
    for part in parts[:-1]:
        location /= part
        location.mkdir(exist_ok=True)
        (location / "__init__.py").touch()
    (location / f"{parts[-1]}.py").write_text(source, encoding="utf-8")


@pytest.fixture
def boundary_checkout(tmp_path):
    """Use the real contract config against an isolated, disposable source tree.

    No checkout source is edited and no optional model runtime is imported. All
    packages exist in this tree, so a probe cannot accidentally lint an editable
    or installed copy from the development environment.
    """
    shutil.copy2(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "src").mkdir()
    for package in (*ALLOWED, "src"):
        _module(tmp_path, f"{package}.__init__")
        _module(tmp_path, f"{package}._boundary_target")
    # Exercise the exact legacy exclusions as well; a typo/over-broad exclusion
    # cannot silently pass due to unmatched_ignore_imports_alerting defaults.
    _module(tmp_path, "src.ocr.application.process_page")
    _module(tmp_path, "src.ocr.application.export_document")
    _module(tmp_path, "src.ocr.application.count_keywords")
    _module(tmp_path, "ocr_workers.phase_text", "import src.ocr.application.process_page\n")
    _module(tmp_path, "ocr_workers.phase_export", "import src.ocr.application.export_document\n")
    return tmp_path


def test_import_linter_contracts_are_kept():
    result = _lint(ROOT)
    assert result.returncode == 0, _details(result)


def test_import_linter_accepts_every_documented_internal_dependency(boundary_checkout):
    for source, targets in ALLOWED.items():
        imports = "".join(f"import {target}._boundary_target\n" for target in sorted(targets))
        _module(boundary_checkout, f"{source}._boundary_allowed", imports)
    result = _lint(boundary_checkout)
    assert result.returncode == 0, _details(result)


def test_import_linter_rejects_every_undocumented_internal_dependency(boundary_checkout):
    forbidden_edges = []
    for source, allowed in ALLOWED.items():
        targets = (set(ALLOWED) | {"src"}) - allowed - {source}
        imports = "".join(f"import {target}._boundary_target\n" for target in sorted(targets))
        _module(boundary_checkout, f"{source}._boundary_violation", imports)
        forbidden_edges.extend((source, target) for target in targets)

    result = _lint(boundary_checkout)
    output = _details(result)
    assert result.returncode == 1, output
    # Require evidence for every direct edge, including private implementations;
    # one unrelated broken contract is insufficient to make this test pass.
    for source, target in forbidden_edges:
        edge = f"{source}._boundary_violation -> {target}._boundary_target"
        assert edge in output, f"Unenforced dependency: {edge}\n{output}"


def test_import_linter_rejects_indirect_boundary_bypass(boundary_checkout):
    _module(boundary_checkout, "ocr_artifacts._boundary_violation",
            "import ocr_contracts._boundary_bridge\n")
    _module(boundary_checkout, "ocr_contracts._boundary_bridge",
            "import ocr_pipeline._boundary_target\n")
    result = _lint(boundary_checkout, "artifacts")
    output = _details(result)
    assert result.returncode == 1, output
    assert "ocr_artifacts._boundary_violation -> ocr_contracts._boundary_bridge" in output
    assert "ocr_contracts._boundary_bridge -> ocr_pipeline._boundary_target" in output


def test_worker_legacy_exclusions_do_not_allow_other_importers(boundary_checkout):
    _module(boundary_checkout, "ocr_workers.text_page", "import src.ocr.application.process_page\n")
    result = _lint(boundary_checkout, "workers")
    output = _details(result)
    assert result.returncode == 1, output
    assert "ocr_workers.text_page -> src.ocr.application.process_page" in output


@pytest.mark.parametrize(("source", "target", "contract"), [
    ("ocr_contracts", "torch", "contracts"),
    ("ocr_keywords", "openpyxl", "keywords"),
    ("ocr_pipeline", "torch", "pipeline"),
    ("ocr_runtime", "benchmark", "benchmark"),
    ("ocr_workers", "benchmark", "benchmark-direct"),
])
def test_import_linter_rejects_forbidden_external_runtime(boundary_checkout, source, target, contract):
    _module(boundary_checkout, f"{source}._boundary_violation", f"import {target}\n")
    result = _lint(boundary_checkout, contract)
    output = _details(result)
    assert result.returncode == 1, output
    assert f"{source}._boundary_violation -> {target}" in output


def test_legacy_exclusions_are_documented():
    # import-linter validates the expressions themselves. Here verify that every
    # remaining exemption still has the migration map's rationale/removal rule.
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10; import-linter supplies tomli.
        import tomli as tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    actual = {edge.replace(" ", "")
              for contract in config["tool"]["importlinter"]["contracts"]
              for edge in contract.get("ignore_imports", [])}
    documented = json.loads((ROOT / "docs/architecture/module_map.json").read_text(encoding="utf-8"))
    assert actual == set(documented["temporary_legacy_imports"])
    assert all(documented["temporary_legacy_imports"].values())


def _private(name):
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else None


def private_cross_imports(src):
    """`importer->target` for each use of another package's private module or
    name (`_x`): imports at any level, and `module._x` through an imported
    module. import-linter checks package edges only; an allowed edge does not
    open the implementation behind it. The frozen legacy `src.ocr` is out of
    scope."""
    def is_module(dotted):
        path = src.joinpath(*dotted.split("."))
        return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()

    found = set()
    for path in sorted(src.glob("ocr_*/**/*.py")):
        importer = ".".join(path.relative_to(src).with_suffix("").parts)
        package = importer.split(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {}  # local name -> module of another package
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [(alias.name, alias.asname) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported = [(node.module, None)]
            else:
                continue
            for name, asname in imported:
                if name.split(".")[0] == package or not name.startswith("ocr_"):
                    continue
                if any(_private(part) for part in name.split(".")[1:]):
                    found.add(f"{importer}->{name}")
                if isinstance(node, ast.Import):
                    modules[asname or name.split(".")[0]] = name if asname else name.split(".")[0]
                    continue
                for alias in node.names:
                    if _private(alias.name):
                        found.add(f"{importer}->{name}.{alias.name}")
                    elif is_module(f"{name}.{alias.name}"):
                        modules[alias.asname or alias.name] = f"{name}.{alias.name}"
        for node in ast.walk(tree):
            dotted = _dotted(node) if isinstance(node, ast.Attribute) else None
            head, _, rest = (dotted or "").partition(".")
            if head in modules and any(_private(part) for part in rest.split(".")):
                found.add(f"{importer}->{modules[head]}.{rest}")
    return found


def test_packages_use_only_public_names_of_other_packages():
    documented = json.loads((ROOT / "docs/architecture/module_map.json").read_text(encoding="utf-8"))
    exceptions = documented["private_import_exceptions"]
    assert private_cross_imports(ROOT / "src") == set(exceptions)
    assert all(exceptions.values())


def test_private_import_check_catches_controlled_violations(boundary_checkout):
    src = boundary_checkout / "src"
    _module(boundary_checkout, "ocr_artifacts.completion", "_sha256 = MARKER = None\n")
    _module(boundary_checkout, "ocr_runtime.paths", "def _env_dir(): pass\n")
    _module(boundary_checkout, "ocr_pipeline.from_import", "from ocr_artifacts.completion import MARKER, _sha256\n")
    _module(boundary_checkout, "ocr_document.private_module", "import ocr_runtime._boundary_target\n")
    _module(boundary_checkout, "ocr_workers.lazy", "def f():\n    from ocr_text._boundary_target import x\n")
    _module(boundary_checkout, "ocr_layout.attribute",
            "from ocr_runtime import paths\nimport ocr_artifacts.completion as done\n"
            "paths._env_dir()\ndone._sha256\n")
    _module(boundary_checkout, "ocr_structure.chained", "import ocr_runtime.paths\nocr_runtime.paths._env_dir()\n")
    # Public names, dunders and a package's own private names are allowed.
    _module(boundary_checkout, "ocr_runtime.own", "from ocr_runtime.paths import _env_dir\n")
    _module(boundary_checkout, "ocr_pipeline.public", "from ocr_artifacts import completion\n"
                                                      "completion.MARKER\ncompletion.__name__\n")
    assert private_cross_imports(src) == {
        "ocr_pipeline.from_import->ocr_artifacts.completion._sha256",
        "ocr_document.private_module->ocr_runtime._boundary_target",
        "ocr_workers.lazy->ocr_text._boundary_target",
        "ocr_layout.attribute->ocr_runtime.paths._env_dir",
        "ocr_layout.attribute->ocr_artifacts.completion._sha256",
        "ocr_structure.chained->ocr_runtime.paths._env_dir",
    }
