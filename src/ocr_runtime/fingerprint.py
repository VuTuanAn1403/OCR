"""Code fingerprints used in cache keys, identities and run manifests (ENV-04).

Hashing the pipeline sources means any code edit invalidates cached pages,
instead of silently restoring output produced by older logic. The hashed set
covers every module reachable through `code_roots()`: all of `src/` (the
legacy `src.ocr` namespace and the `ocr_*` packages) plus the scripts that
runtime code loads. An installed wheel hashes its installed copies under the
same checkout-relative names.

The set is split into closures (P11a). Analysis (keyword counting) and
publication (workbooks, ledger) files are listed explicitly; every other file
is extraction code. The OCR identity uses only the extraction closure, so
editing keyword or Excel code never forces OCR again. The import-linter
contract `extraction` proves the extraction phases cannot import the listed
files; listing a file wrongly can only make the split less precise when the
contract still holds, never let changed extraction code go unnoticed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

from ocr_runtime.paths import LEGACY_ROOT, PACKAGE_ROOT, code_roots, source_tree

# Scripts imported or launched by runtime code (not packaged modules).
RUNTIME_SCRIPTS = ("scripts/docling_structure_worker.py",)

# Paths relative to the project root; a trailing "/" covers a directory.
SHARED_CONTRACTS = ("src/ocr_contracts/", "src/ocr_artifacts/")
ANALYSIS_CODE = (
    "src/ocr_keywords/",
    "src/ocr_pipeline/keyword_finalization.py",
    "src/ocr_pipeline/analysis_run.py",
    "src/ocr_pipeline/artifact_validation.py",
    "src/ocr_pipeline/keyword_validation.py",
    # Legacy keyword counting and the compatibility aliases of moved modules.
    "src/ocr/application/count_keywords.py",
    "src/ocr/application/export_document.py",
    "src/ocr/application/keyword_finalization.py",
    "src/ocr/application/analysis_run.py",
    "src/ocr/infrastructure/export/artifact_validator.py",
    "src/ocr/infrastructure/export/keyword_validator.py",
    "src/ocr/infrastructure/postprocessing/keyword_counter.py",
    "src/ocr/infrastructure/postprocessing/keyword_contract.py",
)
PUBLICATION_CODE = (
    "src/ocr_reporting/",
    "src/ocr_pipeline/batch.py",
    "src/ocr_pipeline/publication.py",
    "src/ocr_pipeline/recount.py",
    "src/ocr_pipeline/batch_store.py",
    # Compatibility aliases of moved modules.
    "src/ocr/application/process_batch.py",
    "src/ocr/application/publish_keyword_matrix.py",
    "src/ocr/application/recount_document.py",
    "src/ocr/infrastructure/state/batch_store.py",
    "src/ocr/infrastructure/export/keyword_exporter.py",
    "src/ocr/infrastructure/export/keyword_v63.py",
)


def _source_entries() -> list[tuple[str, Path]]:
    """(name, file) of every hashed file. Names are checkout-relative
    (`src/ocr_runtime/paths.py`, `scripts/...`) for an installed wheel too, so
    the same code gives the same fingerprint in both layouts (P10)."""
    if source_tree():
        files = sorted((LEGACY_ROOT / "src").rglob("*.py"))
        entries = [(f.relative_to(LEGACY_ROOT).as_posix(), f) for f in files]
        scripts = [(name, LEGACY_ROOT / name) for name in RUNTIME_SCRIPTS]
    else:
        resources = PACKAGE_ROOT / "ocr_runtime" / "resources"
        files = [f for top in sorted(PACKAGE_ROOT.glob("ocr_*")) for f in top.rglob("*.py")
                 if resources not in f.parents]
        entries = [("src/" + f.relative_to(PACKAGE_ROOT).as_posix(), f) for f in files]
        entries += [(f.relative_to(LEGACY_ROOT).as_posix(), f) for f in (LEGACY_ROOT / "src").rglob("*.py")]
        # Same order as the sorted checkout paths below one common root.
        entries.sort(key=lambda entry: Path(entry[0]))
        scripts = [(name, resources / Path(name).name) for name in RUNTIME_SCRIPTS]
    return entries + [(name, path) for name, path in scripts if path.is_file()]


def source_files() -> list[Path]:
    return [path for _, path in _source_entries()]


def _matches(name: str, patterns) -> bool:
    return any(name.startswith(p) if p.endswith("/") else name == p for p in patterns)


def closure_entries(closure: str) -> list[tuple[str, Path]]:
    entries = _source_entries()
    if closure == "full":
        return entries
    if closure == "extraction":
        return [e for e in entries if not _matches(e[0], ANALYSIS_CODE + PUBLICATION_CODE)]
    if closure == "analysis":
        return [e for e in entries if _matches(e[0], ANALYSIS_CODE + SHARED_CONTRACTS)]
    if closure == "publication":
        return [e for e in entries if _matches(e[0], PUBLICATION_CODE + ANALYSIS_CODE + SHARED_CONTRACTS)]
    raise ValueError(f"Unknown code closure: {closure}")


def closure_files(closure: str) -> list[Path]:
    return [path for _, path in closure_entries(closure)]


def _digest(entries) -> str:
    digest = hashlib.sha256()
    for name, file in entries:
        digest.update(name.encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()[:16]


def source_fingerprint() -> str:
    """All project code (legacy cache keys, run manifests)."""
    return _digest(_source_entries())


def extraction_fingerprint() -> str:
    """Code that can change OCR/structure/export artifacts."""
    return _digest(closure_entries("extraction"))


def code_fingerprints() -> dict[str, str]:
    return {closure: _digest(closure_entries(closure)) for closure in ("extraction", "analysis", "publication")}


def assert_loaded_code_fingerprinted() -> None:
    """Fail when project code was imported from outside the hashed files, for
    example an old installed copy shadowing the checkout."""
    hashed = {path.resolve() for path in source_files()}
    roots = [root.resolve() for root in code_roots()]
    for name, module in list(sys.modules.items()):
        top = name.split(".")[0]
        if not (top.startswith("ocr_") or name.startswith("src.ocr") or top == "scripts"):
            continue
        file = getattr(module, "__file__", None)
        if file is None:
            continue
        path = Path(file).resolve()
        if path not in hashed:
            raise RuntimeError(f"UNFINGERPRINTED_CODE: {name} loaded from {path} "
                               f"(code roots: {', '.join(map(str, roots))})")


# Stage closures (P11b). Each extraction phase runs in its own process; its
# code identity is the static import closure of its entry modules over the
# project files (module- and function-level imports, same names in both
# layouts). What a static walk cannot see is declared: legacy entry modules
# reached only with V6.2 settings, and scripts launched as processes.
# `assert_loaded_code_in_stage` refuses a phase that loaded any project
# module outside its closure, so a missed import fails instead of letting
# changed code reuse a stale stage result.
STAGES = ("text", "structure", "export")
STAGE_ROOTS = {
    "text": ("ocr_workers.phases", "ocr_workers.phase_text"),
    "structure": ("ocr_workers.phases", "ocr_workers.phase_structure", "ocr_workers.docling_server"),
    "export": ("ocr_workers.phases", "ocr_workers.phase_export"),
}
STAGE_SCRIPTS = {"structure": ("scripts/docling_structure_worker.py",)}


def _module_name(name: str) -> str | None:
    if not name.startswith("src/") or not name.endswith(".py"):
        return None
    parts = name[len("src/"):-len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(["src", *parts] if parts[0] == "ocr" else parts)


def _imported_names(path: Path, module: str) -> set[str]:
    import ast
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    names = set()
    for node in ast.walk(ast.parse(path.read_bytes(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[:len(package.split(".")) - node.level + 1]
                base = ".".join(anchor + ([base] if base else []))
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def stage_entries(stage: str, *, legacy: bool = False) -> list[tuple[str, Path]]:
    """Project files the phase can load, in fingerprint order."""
    if legacy:
        raise ValueError("Legacy phase routes were retired; there is one phase implementation")
    entries = _source_entries()
    modules = {_module_name(name): (name, path) for name, path in entries if _module_name(name)}
    roots = list(STAGE_ROOTS[stage])
    seen, todo = set(), roots
    while todo:
        module = todo.pop()
        if module in seen or module not in modules:
            continue
        seen.add(module)
        # A module loads its parent packages first.
        todo += [".".join(module.split(".")[:i]) for i in range(1, module.count(".") + 1)]
        for name in _imported_names(modules[module][1], module):
            parts = name.split(".")
            todo += [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
    names = {modules[m][0] for m in seen} | set(STAGE_SCRIPTS.get(stage, ()))
    return [entry for entry in entries if entry[0] in names]


def stage_fingerprint(stage: str, *, legacy: bool = False) -> str:
    return _digest(stage_entries(stage, legacy=legacy))


def assert_loaded_code_in_stage(stage: str, *, legacy: bool = False) -> None:
    allowed = {path.resolve() for _, path in stage_entries(stage, legacy=legacy)}
    for name, module in list(sys.modules.items()):
        top = name.split(".")[0]
        if not (top.startswith("ocr_") or name.startswith("src.ocr")):
            continue
        file = getattr(module, "__file__", None)
        if file is not None and Path(file).resolve() not in allowed:
            raise RuntimeError(f"STAGE_CLOSURE_VIOLATION: phase {stage} loaded {name} from {file}, "
                               f"outside its fingerprinted closure")


# Code that builds the phase requests and worker environments (F05): the
# supervisor and the document owner run it outside every phase process, so
# no phase closure holds it, and every stage key carries its digest. Only
# these files: their keyword imports belong to the analysis closure, and
# what their helpers contribute reaches a phase as request fields that are
# themselves key parts (config, model and lock hashes, interpreters).
COORDINATOR_CODE = (
    "src/ocr_pipeline/scheduler.py",
    "src/ocr_pipeline/backend.py",
    "src/ocr_pipeline/document.py",
    "src/ocr_pipeline/document_owner.py",
)


def coordinator_entries() -> list[tuple[str, Path]]:
    entries = [entry for entry in _source_entries() if entry[0] in COORDINATOR_CODE]
    missing = set(COORDINATOR_CODE) - {name for name, _ in entries}
    if missing:
        raise RuntimeError(f"Coordinator code missing from the hashed files: {', '.join(sorted(missing))}")
    return entries


def coordinator_fingerprint() -> str:
    return _digest(coordinator_entries())
