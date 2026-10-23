"""Validate the model files selected by a locked GPU request, without loading models."""
from __future__ import annotations

from pathlib import Path

from ocr_contracts.processing import IdentityMismatch
from ocr_runtime.paths import VIETOCR_FILES, registry_model_path


# Selection made by the locked Docling 2.137.0 default pipeline. These are
# loader inputs, independent of dependency versions and weight checksums.
DOCLING_MODEL_REFS = {
    "layout": ("docling-project/docling-layout-heron", "main"),
    "table": ("docling-project/docling-models", "v2.3.0"),
    "formula": ("docling-project/CodeFormulaV2", "main"),
}


def model_selection(registry):
    """Registry name -> effective file path, using the engines' resolver."""
    return {name: str(registry_model_path(name).resolve()) for name in registry["files"]}


def validate_registry(registry):
    """Reject incomplete locks, including extra files in selected HF snapshots.

    A model loader reads configs/tokenizers as well as weights. A file omitted
    from the registry must not become an unverified input just because all the
    *listed* hashes still match. Scan only selected snapshots, not the whole
    model store (which may contain unrelated models or other revisions).
    """
    files = registry.get("files")
    if not isinstance(files, dict) or not files:
        raise IdentityMismatch("MODEL_REGISTRY_INCOMPLETE: files must be a nonempty mapping")
    required = {f"models/vietocr/{name}" for name in VIETOCR_FILES}
    try:
        detector = registry["text_detector"]["model_path"]
        layout = registry["layout_model"]["model_path"]
    except (KeyError, TypeError) as exc:
        raise IdentityMismatch("MODEL_REGISTRY_INCOMPLETE: detector/layout selection is missing") from exc
    required.add(detector)
    missing = sorted(required - files.keys())
    if missing:
        raise IdentityMismatch(f"MODEL_REGISTRY_INCOMPLETE: files are not pinned: {', '.join(missing)}")

    selection = model_selection(registry)
    pinned = {Path(path) for path in selection.values()}
    directories = set()
    snapshots = registry.get("snapshots", {})
    for role, (repo, ref) in DOCLING_MODEL_REFS.items():
        meta = snapshots.get(role, {})
        if not meta.get("repo") or not meta.get("revision"):
            raise IdentityMismatch(f"MODEL_REGISTRY_INCOMPLETE: {role} snapshot is not declared")
        if meta["repo"] != repo:
            raise IdentityMismatch(f"MODEL_SELECTION_CHANGED: locked Docling loads {repo}, not {meta['repo']}")
        hub = Path("models/docling/huggingface/hub") / ("models--" + repo.replace("/", "--"))
        reference = (hub / "refs" / ref).as_posix()
        if reference not in files:
            raise IdentityMismatch(f"MODEL_REGISTRY_INCOMPLETE: revision reference is not pinned: {reference}")
        reference_path = registry_model_path(reference)
        if not reference_path.is_file():
            raise FileNotFoundError(f"MODEL_MISSING: revision reference {reference_path}")
        if reference_path.read_text(encoding="utf-8").strip() != meta["revision"]:
            raise IdentityMismatch(f"MODEL_SELECTION_CHANGED: {reference} does not select {meta['revision']}")
        directories.add(registry_model_path(str(hub / "snapshots" / meta["revision"])).resolve())
    layout_path = registry_model_path(layout).resolve()
    if layout_path.is_dir():
        directories.add(layout_path)
    elif layout_path not in pinned:
        raise IdentityMismatch(f"MODEL_REGISTRY_INCOMPLETE: layout is not pinned: {layout_path}")

    # Snapshot roots are identified by registry names, not by directory depth
    # in the external store. Blob files elsewhere in the HF cache are not read
    # directly by these loaders and need not be scanned.
    for name in files:
        parts = Path(name).parts
        if "snapshots" in parts:
            index = parts.index("snapshots")
            if index + 1 < len(parts):
                directories.add(registry_model_path(str(Path(*parts[:index + 2]))).resolve())
    for path in sorted(directories):
        if not path.is_dir():
            raise FileNotFoundError(f"MODEL_MISSING: snapshot {path}")
        actual = {p.resolve() for p in path.rglob("*") if p.is_file()
                  and not {".cache", ".locks"}.intersection(p.relative_to(path).parts)}
        if not actual:
            raise IdentityMismatch(f"MODEL_REGISTRY_INCOMPLETE: empty model snapshot: {path}")
        unpinned = sorted(actual - pinned)
        if unpinned:
            raise IdentityMismatch(f"MODEL_REGISTRY_INCOMPLETE: snapshot file is not pinned: {unpinned[0]}")
    expected = registry["text_detector"].get("sha256")
    if expected is not None and expected != files[detector]:
        raise IdentityMismatch("MODEL_LOCK_MISMATCH: detector hash disagrees with the registry files")
    return selection
