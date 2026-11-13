FROM python:3.10-slim

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
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

# Fetch verified official Hugging Face files, with ModelScope as fallback,
# then export the same two Small text models to ONNX without running inference.
# Keep completed models and resumable downloads when BuildKit retains its cache;
# copy only the verified runtime files into the image.
COPY ocr_runtime.py image_upload_limits.py ./
COPY scripts/prepare_ocr_model_cache.py ./scripts/prepare_ocr_model_cache.py
COPY scripts/ocr-model-lock.json ./scripts/ocr-model-lock.json
# A 130 MB file needs over half an hour on a healthy 65 KiB/s link. This is a
# build-time file budget, separate from short HTTP/idle timeouts and gunicorn.
ARG DMATE_MODEL_DOWNLOAD_TIMEOUT=3600
RUN --mount=type=cache,id=dmate-ocr-model-cache-v2,target=/var/cache/dmate-model-build,sharing=locked \
    python scripts/prepare_ocr_model_cache.py --cache-dir /var/cache/dmate-model-build \
        --download-timeout "$DMATE_MODEL_DOWNLOAD_TIMEOUT" && \
    python scripts/prepare_ocr_model_cache.py --cache-dir /var/cache/dmate-model-build --verify-only && \
    mkdir -p /opt/dmate-model-cache/paddlex && \
    cp -a /var/cache/dmate-model-build/paddlex/official_models \
        /var/cache/dmate-model-build/paddlex/onnx_models \
        /var/cache/dmate-model-build/paddlex/dmate-model-manifest.json \
        /opt/dmate-model-cache/paddlex/

COPY . .

# Reject application syntax errors during the build, before replacing a running service.
RUN python -m compileall -q -l .

# Regenerate sharp platform-specific icons as part of every production image build.
RUN python scripts/generate_icons.py

# Four independent image requests plus capacity for cancellation, health and chat.
# The local model scheduler, rather than HTTP threads, limits inference memory.
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:${PORT:-8080} app:app"]
