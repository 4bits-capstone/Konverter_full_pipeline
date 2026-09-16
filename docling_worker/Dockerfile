# docling_worker/Dockerfile — RunPod Serverless GPU worker for Docling parsing.
#
# Build from the REPO ROOT (folder containing `backend/` and `docling_worker/`):
#   docker build --platform linux/amd64 -f docling_worker/Dockerfile \
#       -t linnhtinnyo/konverter-docling-worker:v1 .
#   docker push linnhtinnyo/konverter-docling-worker:v1
#
# Torch/torchvision/timm/scipy versions match backend.gpu.Dockerfile's proven
# cu121 combination (table-structure detection needs timm+scipy at import
# time; torch/torchvision must be a matched cu121 pair for CUDA to attach).
# Deploy the RunPod endpoint with a CUDA >= 12.1 filter.

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3-pip \
        libgl1 libglib2.0-0 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
       torch==2.5.1 torchvision==0.20.1 \
       --index-url https://download.pytorch.org/whl/cu121

RUN python -m pip install --no-cache-dir timm scipy

COPY docling_worker/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

# Ship the SHARED core so the worker parses identically to local mode.
# docling_runner.py must have no imports from backend.app (see its module
# docstring) or this copy step's whole point — parity with local mode — breaks.
COPY backend/app/docling_runner.py /app/docling_runner.py
COPY docling_worker/handler.py /app/handler.py

# Pre-download Docling models so there's no cold-start HF fetch.
RUN python -m docling.cli.models download layout tableformer \
    || echo "WARN: model pre-download failed; will fetch at runtime"

CMD ["python", "-u", "handler.py"]
