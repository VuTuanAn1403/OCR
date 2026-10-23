"""Project paths, each overridable through an environment variable (ENV-03).

Defaults keep the historical CWD-relative layout (`inputs/`, `output/`,
`.cache/`) so existing commands behave the same when run from the repo root.
Functions rather than constants, so a changed environment applies at call time.
"""
from __future__ import annotations

import os
from pathlib import Path

# A checkout is recognized by these files together, never by depth or by a
# lone pyproject.toml. OCR_PROJECT_ROOT overrides the search.
CHECKOUT_MARKERS = ("pyproject.toml", "config/profiles.yaml", "src/ocr_runtime/paths.py")
# Where the code is, independent of PROJECT_ROOT (P10). PACKAGE_ROOT holds the
# `ocr_*` packages: `<checkout>/src`, or site-packages of an installed wheel.
# LEGACY_ROOT holds the legacy namespace package `src` (`src.ocr`): the
# checkout, or the same site-packages.
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = PACKAGE_ROOT.parent if PACKAGE_ROOT.name == "src" else PACKAGE_ROOT


def source_tree() -> bool:
    """Code runs from a source tree (checkout or editable install), not from
    an installed wheel."""
    return PACKAGE_ROOT != LEGACY_ROOT


def _project_root() -> Path:
    configured = os.getenv("OCR_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in Path(__file__).resolve().parents:
        if all((candidate / marker).is_file() for marker in CHECKOUT_MARKERS):
            return candidate
    # Installed wheel: project files (inputs, output, .cache) are relative to
    # the working directory, like the data paths below.
    return Path.cwd().resolve()


PROJECT_ROOT = _project_root()


def is_checkout() -> bool:
    return all((PROJECT_ROOT / marker).is_file() for marker in CHECKOUT_MARKERS)


def code_roots() -> list[Path]:
    """Import roots of the project code: LEGACY_ROOT for the legacy `src.ocr`
    namespace and PACKAGE_ROOT for the `ocr_*` packages (one directory for an
    installed wheel). Worker PYTHONPATH and the source fingerprint both derive
    from this single list."""
    return list(dict.fromkeys([LEGACY_ROOT, PACKAGE_ROOT]))


def worker_pythonpath() -> str:
    return os.pathsep.join(str(path) for path in code_roots())


def runtime_resource(name: str) -> Path:
    """Wheel copies are generated during build (setup.py) into
    `ocr_runtime/resources`, never separately maintained."""
    return PACKAGE_ROOT / "ocr_runtime" / "resources" / name


def default_keywords_path() -> Path:
    """The checkout dictionary only inside a checkout. An installed wheel uses
    its bundled copy, never `config/keywords.txt` of whatever project the
    working directory belongs to (F04)."""
    if is_checkout():
        return PROJECT_ROOT / "config/keywords.txt"
    return runtime_resource("keywords.txt")


def default_profile_path() -> Path:
    if is_checkout():
        return PROJECT_ROOT / "config/profiles.yaml"
    return runtime_resource("profiles.yaml")


def hardware_profile_dir() -> Path:
    if is_checkout():
        return PROJECT_ROOT / "config/hardware"
    return runtime_resource("hardware")


def docling_worker_path() -> Path:
    if is_checkout():
        return PROJECT_ROOT / "scripts/docling_structure_worker.py"
    return runtime_resource("docling_structure_worker.py")


def docling_server_module() -> Path:
    """Implementation behind the Docling worker entry (part of its identity)."""
    return PACKAGE_ROOT / "ocr_workers" / "docling_server.py"


def _env_dir(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def data_dir() -> Path:
    """Input PDFs (`OCR_DATA_DIR`, default `inputs`)."""
    return _env_dir("OCR_DATA_DIR", Path("inputs"))


def output_dir() -> Path:
    """Extraction outputs (`OCR_OUTPUT_DIR`, default `output`)."""
    return _env_dir("OCR_OUTPUT_DIR", Path("output"))


def cache_dir() -> Path:
    """Page cache and Docling job files (`OCR_CACHE_DIR`, default `.cache`)."""
    return _env_dir("OCR_CACHE_DIR", Path(".cache"))


def models_dir() -> Path:
    """Model weights (`OCR_MODELS_DIR`, default `<repo>/models`)."""
    return _env_dir("OCR_MODELS_DIR", PROJECT_ROOT / "models")


# Files the VietOCR engine loads from `vietocr_model_dir()`.
VIETOCR_FILES = ("base.yml", "vgg-seq2seq.yml", "vgg_seq2seq.pth")


def vietocr_model_dir() -> Path:
    """VietOCR weights (`VIETOCR_MODEL_DIR`, default `<models>/vietocr`)."""
    return _env_dir("VIETOCR_MODEL_DIR", models_dir() / "vietocr")


def registry_model_path(name: str) -> Path:
    """Where a phase reads the model registry file `name` (`models/...`) from,
    by the same rules as the engines (F06): the hashes pinned for a run are
    the files the run loads. VietOCR files follow `VIETOCR_MODEL_DIR`, every
    other model `OCR_MODELS_DIR`; the Docling client points its server's
    HF_HOME at `<models>/docling/huggingface`."""
    parts = Path(name).parts
    if parts[:2] == ("models", "vietocr"):
        return vietocr_model_dir().joinpath(*parts[2:])
    if parts[:1] == ("models",):
        return models_dir().joinpath(*parts[1:])
    return PROJECT_ROOT / name


def v63_cache_root() -> Path:
    """Job checkpoints and stage cache of V6.3 (P12): `OCR_CACHE_DIR`
    resolved against the working directory, else `<project root>/.cache`.
    GPU leases stay machine-wide instead (`OCR_GPU_LEASE_DIR`, gpu_lease)."""
    value = os.getenv("OCR_CACHE_DIR")
    return Path(value).expanduser().resolve() if value else PROJECT_ROOT / ".cache"


# Path variables a child process must read as this process does.
PATH_VARIABLES = ("OCR_PROJECT_ROOT", "OCR_CONFIG_PATH", "OCR_DATA_DIR", "OCR_OUTPUT_DIR", "OCR_CACHE_DIR",
                  "OCR_MODELS_DIR", "OCR_GPU_LEASE_DIR", "VIETOCR_MODEL_DIR", "OCR_BRIDGE_FONT")


def absolute_path_env(environ=None) -> dict[str, str]:
    """The set path variables, absolute against this process's working
    directory. Workers start with the checkout as working directory; a
    relative value would otherwise name another place there, and a GPU
    lease directory that differs between processes excludes nothing."""
    environ = os.environ if environ is None else environ
    return {name: str(Path(environ[name]).expanduser().resolve()) for name in PATH_VARIABLES if environ.get(name)}
