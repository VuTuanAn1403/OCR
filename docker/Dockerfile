# Lab image (proposal V6 ENV-07, section 7.4). One file, two targets:
#   docker build -f docker/Dockerfile -t ocrpdf:cpu .
#   docker build -f docker/Dockerfile --build-arg DEVICE=cuda -t ocrpdf:gpu .
# The environments come from scripts/setup.sh (same pins as Colab/Linux).
# Weights stay on a volume, never in the image (ENV-06):
#   docker run --rm -v ocr-models:/models ocrpdf:cpu python scripts/setup_models.py
#   docker run --rm -v ocr-models:/models ocrpdf:cpu python scripts/setup_vietocr_model.py
#   docker run --rm -v ocr-models:/models -v "$PWD/inputs:/data/inputs:ro" -v "$PWD/output:/data/output" \
#       ocrpdf:cpu ocrpdf-batch --hardware cpu_local --input /data/inputs --output /data/output --log-format json
# GPU runs need the NVIDIA container toolkit and `docker run --gpus all`.
FROM python:3.11-slim-bookworm

ARG DEVICE=cpu
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OCR_MODELS_DIR=/models \
    OCR_CACHE_DIR=/data/cache \
    OCR_DATA_DIR=/data/inputs \
    OCR_OUTPUT_DIR=/data/output

# libgomp1: onnxruntime/torch OpenMP; libglib2.0-0: OpenCV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN bash scripts/setup.sh --device "${DEVICE}" --python python3 --no-models

ENV PATH="/app/.venv/bin:${PATH}" \
    OCR_DOCLING_PYTHON=/app/.venv-docling/bin/python
VOLUME ["/models", "/data"]
CMD ["ocrpdf", "--help"]
