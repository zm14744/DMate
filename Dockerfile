# syntax=docker/dockerfile:1
FROM python:3.10-slim AS runtime-deps

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_MODEL_SOURCE=BOS \
    DMATE_MODEL_CACHE_DIR=/opt/dmate-model-cache \
    DMATE_TEXT_OCR_ENGINE=onnxruntime \
    FLAGS_use_mkldnn=0 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-agents.txt ./
RUN --mount=type=cache,id=dmate-pip,target=/root/.cache/pip,sharing=locked \
    unset PIP_NO_CACHE_DIR && python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

FROM runtime-deps AS web-icons
RUN --mount=type=bind,source=scripts/generate_icons.py,target=/opt/dmate-icon-build/scripts/generate_icons.py \
    python /opt/dmate-icon-build/scripts/generate_icons.py --web-only

# Assemble UI updates on the small Python base, independently of OCR weights.
FROM python:3.10-slim AS app-files
WORKDIR /app
COPY . .
RUN python -m compileall -q -l .
COPY --link --from=web-icons /opt/dmate-icon-build/static/icons/ /app/static/icons/

FROM runtime-deps
# Fetch verified official Hugging Face files, with ModelScope as fallback,
# then export the same two Small text models to ONNX without running inference.
# Keep completed models and resumable downloads when BuildKit retains its cache;
# copy only the verified runtime files into the image.
# A 130 MB file needs over half an hour on a healthy 65 KiB/s link. This is a
# build-time file budget, separate from short HTTP/idle timeouts and gunicorn.
ARG DMATE_MODEL_DOWNLOAD_TIMEOUT=3600
RUN --mount=type=bind,source=ocr_runtime.py,target=/app/ocr_runtime.py \
    --mount=type=bind,source=image_upload_limits.py,target=/app/image_upload_limits.py \
    --mount=type=bind,source=scripts/prepare_ocr_model_cache.py,target=/app/scripts/prepare_ocr_model_cache.py \
    --mount=type=bind,source=scripts/ocr-model-lock.json,target=/app/scripts/ocr-model-lock.json \
    --mount=type=cache,id=dmate-ocr-model-cache-v2,target=/var/cache/dmate-model-build,sharing=locked \
    python scripts/prepare_ocr_model_cache.py --cache-dir /var/cache/dmate-model-build \
        --download-timeout "$DMATE_MODEL_DOWNLOAD_TIMEOUT" && \
    mkdir -p /opt/dmate-model-cache/paddlex && \
    cp -a /var/cache/dmate-model-build/paddlex/official_models \
        /var/cache/dmate-model-build/paddlex/onnx_models \
        /var/cache/dmate-model-build/paddlex/dmate-model-manifest.json \
        /opt/dmate-model-cache/paddlex/

# A web-only change can replace this layer without rebuilding the OCR runtime.
COPY --link --from=app-files /app/ /app/

# Four independent image requests plus capacity for cancellation, health and chat.
# The local model scheduler, rather than HTTP threads, limits inference memory.
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:${PORT:-8080} app:app"]
