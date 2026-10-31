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

# Cache official packages and export the two Small text models to ONNX without
# running inference. Ordinary source changes reuse these prepared model layers.
COPY ocr_runtime.py image_upload_limits.py ./
COPY scripts/prepare_ocr_model_cache.py ./scripts/prepare_ocr_model_cache.py
RUN python scripts/prepare_ocr_model_cache.py && \
    python scripts/prepare_ocr_model_cache.py --verify-only

COPY . .

# Regenerate sharp platform-specific icons as part of every production image build.
RUN python scripts/generate_icons.py

# Four independent image requests plus capacity for cancellation, health and chat.
# The local model scheduler, rather than HTTP threads, limits inference memory.
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 --timeout 300 -b 0.0.0.0:${PORT:-8080} app:app"]
