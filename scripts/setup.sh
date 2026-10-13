#!/usr/bin/env bash
# Linux / macOS / Colab setup (ENV-02, ENV-05); the Windows equivalents are
# the PowerShell commands in README.md and scripts/setup_docling.ps1.
#
#   bash scripts/setup.sh [--device cpu|cuda] [--models-dir DIR] [--wheel-cache DIR]
#                         [--python PYTHON] [--no-docling]
#
# --device cpu   installs CPU-only PyTorch wheels (default; matches REQ-01..03).
# --device cuda  installs the default CUDA wheels from PyPI.
# --models-dir   keeps model weights on persistent storage (exports OCR_MODELS_DIR).
# --wheel-cache  reuses/stores downloaded wheels there (e.g. on Google Drive).
set -euo pipefail

DEVICE=cpu
MODELS_DIR=""
WHEEL_CACHE=""
PYTHON_BIN="${PYTHON:-python3}"
WITH_DOCLING=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) DEVICE="$2"; shift 2 ;;
    --models-dir) MODELS_DIR="$2"; shift 2 ;;
    --wheel-cache) WHEEL_CACHE="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --no-docling) WITH_DOCLING=0; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$DEVICE" in
  cpu) TORCH_INDEX=(--extra-index-url https://download.pytorch.org/whl/cpu) ;;
  cuda) TORCH_INDEX=() ;;
  *) echo "--device must be cpu or cuda" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PIP_EXTRA=()
if [[ -n "$WHEEL_CACHE" ]]; then
  mkdir -p "$WHEEL_CACHE"
  PIP_EXTRA=(--find-links "$WHEEL_CACHE")
fi
if [[ -n "$MODELS_DIR" ]]; then
  mkdir -p "$MODELS_DIR"
  export OCR_MODELS_DIR="$MODELS_DIR"
fi

echo "[1/4] Main environment (.venv, device=$DEVICE)"
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
if [[ -n "$WHEEL_CACHE" ]]; then
  .venv/bin/python -m pip wheel -r requirements.txt -w "$WHEEL_CACHE" ${TORCH_INDEX[@]+"${TORCH_INDEX[@]}"} ${PIP_EXTRA[@]+"${PIP_EXTRA[@]}"}
fi
.venv/bin/python -m pip install -r requirements.txt ${TORCH_INDEX[@]+"${TORCH_INDEX[@]}"} ${PIP_EXTRA[@]+"${PIP_EXTRA[@]}"}
.venv/bin/python -m pip install -e . --no-deps

echo "[2/4] OCR models"
.venv/bin/python scripts/setup_models.py
.venv/bin/python scripts/setup_vietocr_model.py

if [[ "$WITH_DOCLING" == 1 ]]; then
  echo "[3/4] Docling worker environment (.venv-docling)"
  # Isolated on purpose: Docling's dependencies conflict with VietOCR's.
  spec=requirements-docling.lock.txt
  [[ -f "$spec" ]] || spec=requirements-docling.txt
  if command -v uv >/dev/null 2>&1; then
    [[ -x .venv-docling/bin/python ]] || uv venv .venv-docling --python "$PYTHON_BIN"
    uv pip install --python .venv-docling/bin/python -r "$spec" ${TORCH_INDEX[@]+"${TORCH_INDEX[@]}"} --index-strategy unsafe-best-match
  else
    "$PYTHON_BIN" -m venv .venv-docling
    .venv-docling/bin/python -m pip install --upgrade pip
    .venv-docling/bin/python -m pip install -r "$spec" ${TORCH_INDEX[@]+"${TORCH_INDEX[@]}"} ${PIP_EXTRA[@]+"${PIP_EXTRA[@]}"}
  fi
else
  echo "[3/4] Docling skipped (--no-docling); use the 'fast' profile or set docling.enabled: false"
fi

echo "[4/4] Environment check"
.venv/bin/python scripts/check_installation.py
if [[ -n "$MODELS_DIR" ]]; then
  echo "Remember to export OCR_MODELS_DIR=$MODELS_DIR in later sessions."
fi
