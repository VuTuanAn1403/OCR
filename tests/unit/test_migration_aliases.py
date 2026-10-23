"""Compatibility aliases and import hygiene of the module migration.

config/module_map.json records every moved module. The old path
must resolve to the very same module object, so `mock.patch` on either name
patches the code that runs.
"""
import ast
import importlib
import json
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOVES = json.loads((ROOT / "config/module_map.json").read_text(encoding="utf-8"))["moves"]
CODE_DIRS = [ROOT / "src", ROOT / "scripts", ROOT / "tests", ROOT / "benchmark"]


@pytest.mark.parametrize("old,new", [(old, entry["to"]) for old, entry in MOVES.items()])
def test_old_path_is_the_new_module(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)


def test_patch_through_old_path_reaches_new_module():
    if not MOVES:
        pytest.skip("NOT_RUN: no module moved yet")
    old, entry = next(iter(MOVES.items()))
    module = importlib.import_module(entry["to"])
    name = next(n for n in vars(module) if not n.startswith("_"))
    sentinel = object()
    with mock.patch(f"{old}.{name}", sentinel):
        assert getattr(module, name) is sentinel


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module


def test_no_double_import_names():
    """`src/` on sys.path makes `src/ocr` importable as `ocr` and the new
    packages as `src.ocr_*`; both would create second copies of modules."""
    offenders = []
    for directory in CODE_DIRS:
        for path in directory.rglob("*.py"):
            for name in _imports(path):
                if name == "ocr" or name.startswith("ocr.") or name.startswith("src.ocr_"):
                    offenders.append(f"{path.relative_to(ROOT)}: {name}")
    assert not offenders


def test_new_packages_do_not_import_legacy_namespace():
    exceptions = set(json.loads((ROOT / "config/module_map.json").read_text(
        encoding="utf-8")).get("temporary_legacy_imports", {}))
    offenders = []
    for path in (ROOT / "src").glob("ocr_*/**/*.py"):
        module = ".".join(path.relative_to(ROOT / "src").with_suffix("").parts)
        for name in _imports(path):
            if (name == "src.ocr" or name.startswith("src.ocr.")) and f"{module}->{name}" not in exceptions:
                offenders.append(f"{module} -> {name}")
    assert not offenders


ENGINE_CLASSES = ("PDFInspector", "PDFRenderer", "NativeTextExtractor", "VietnameseSeq2SeqEngine", "RapidOCREngine",
                  "OCRQualityEvaluator", "DocumentLayoutEngine", "PageContentAnalyzer", "DLAEngine", "FallbackEngine",
                  "DoclingStructureExtractor")


def test_engine_patches_target_the_composition_root():
    """Page engines are built in ocr_workers.page_engines (P09b). A patch of the
    same class name on process_page silently stops applying and lets real
    models run, so it is refused."""
    import re
    pattern = re.compile(r"""(setattr\(\s*(module|process_page)\s*,\s*["'](?P<a>\w+)["']"""
                         r"""|patch\(\s*["']src\.ocr\.application\.process_page\.(?P<b>\w+)["'])""")
    offenders = []
    for path in (ROOT / "tests").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "process_page" not in text:
            continue
        for match in pattern.finditer(text):
            name = match.group("a") or match.group("b")
            if name in ENGINE_CLASSES and ("process_page" in text[max(0, match.start() - 400):match.end()]):
                offenders.append(f"{path.relative_to(ROOT)}: {name}")
    assert not offenders
