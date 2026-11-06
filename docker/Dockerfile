# ==============================================================================
# Production & Benchmark Image for Vietnamese PDF OCR Pipeline (V6.3 / V7.0)
#
# Build targets:
#   CPU (Supervisor & keyword analytics):
#     docker build -f docker/Dockerfile -t ocrpdf:cpu .
#
#   GPU (Full-page GPU OCR + Docling structures + keyword Excel):
#     docker build -f docker/Dockerfile --build-arg DEVICE=cuda -t ocrpdf:gpu .
#
# Setup weights on persistent volume (weights never baked into image):
#   docker run --rm -v ocr-models:/models ocrpdf:gpu python scripts/setup_vietocr_model.py
#   docker run --rm -v ocr-models:/models ocrpdf:gpu python scripts/setup_models.py
#
# Execution with GPU (requires NVIDIA Container Toolkit):
#   docker run --gpus all --rm \
#       -v ocr-models:/models \
#       -v "$PWD/inputs:/data/inputs:ro" \
#       -v "$PWD/output:/data/output" \
#       ocrpdf:gpu ocrpdf-batch --input /data/inputs --output /data/output
#
# Recount / Analytics only (CPU-speed, zero GPU needed):
#   docker run --rm \
#       -v "$PWD/output:/data/output" \
#       ocrpdf:cpu python scripts/run_count_only.py /data/output/run1 --output /data/output/recount
# ==============================================================================
FROM python:3.11-slim-bookworm

ARG DEVICE=cuda

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OCR_MODELS_DIR=/models \
    VIETOCR_MODEL_DIR=/models/vietocr \
    HF_HOME=/models/docling/huggingface \
    OCR_CACHE_DIR=/data/cache \
    OCR_DATA_DIR=/data/inputs \
    OCR_OUTPUT_DIR=/data/output

# System dependencies:
# - libgomp1: PyTorch / ONNX Runtime OpenMP threading
# - libglib2.0-0, libgl1: OpenCV and image processing
# - curl, ca-certificates: Secure transport for wheel / model downloads
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
        libgl1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache Layer 1: Copy only package manifests and setup scripts first.
# This prevents code changes from busting multi-gigabyte dependency caches.
COPY requirements*.txt ./
COPY requirements/ ./requirements/
COPY pyproject.toml setup.py README.md ./
COPY scripts/setup.sh scripts/setup_v62.py ./scripts/

# Install uv package manager for fast, reliable, hash-verified installs
RUN pip install --no-cache-dir uv==0.12.10

# Create supervisor virtual environment (.venv)
RUN uv venv .venv --python python3.11 \
    && uv pip install --python .venv/bin/python \
        "pymupdf>=1.24.0,<=1.28.2" \
        "pydantic>=2.0.0,<=2.14.0" \
        "PyYAML>=6.0,<=6.0.3" \
        "psutil>=5.9.0,<=7.2.2" \
        "openpyxl>=3.1.0,<4.0.0" \
        "tabulate>=0.9.0,<=0.10.0"

# Setup worker environments based on requested DEVICE:
# - For CUDA: setup locked dual GPU workers (.venv-v62/text and .venv-v62/docling)
#   using hash-locked requirements, skipping live GPU assertions during build time.
# - For CPU: setup legacy/fallback CPU environment via setup.sh.
RUN if [ "${DEVICE}" = "cuda" ]; then \
        bash scripts/setup.sh --device cuda --python python3 --no-models --no-device-check --no-editable && \
        .venv/bin/python scripts/setup_v62.py --python 3.11 --env-root /app/.venv-v62 --no-cuda-check; \
    else \
        bash scripts/setup.sh --device cpu --python python3 --no-models --no-device-check --no-editable; \
    fi

# Cache Layer 2: Copy full application source code and configurations
COPY . /app

# Install project in editable mode so console_scripts (ocrpdf, ocrpdf-batch) bind to /app
RUN .venv/bin/pip install --no-deps -e .

ENV PATH="/app/.venv/bin:${PATH}" \
    OCR_DOCLING_PYTHON=/app/.venv-docling/bin/python

VOLUME ["/models", "/data"]

# Default command: display CLI help
CMD ["ocrpdf-batch", "--help"]
