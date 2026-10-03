# backend.Dockerfile — Konverter backend (FastAPI, CPU-only, remote Docling) for RunPod / any host
#
# Slim production image: NO docling, NO torch. Docling parsing runs on a
# separate RunPod serverless GPU worker (see docling_worker/); this pod only
# does CPU work (API handlers, post-processing, Supabase/RunPod orchestration)
# via KONVERTER_DOCLING_MODE=remote. Docling imports in app/docling_runner.py
# are lazy, so the app boots fine without docling installed — `local` mode
# simply isn't available on this image (that's expected; local dev installs
# the `[docling]` extra separately for that).
#
# Build from the REPO ROOT (so ./backend is in context):
#   docker build -f backend.Dockerfile -t linnhtinnyo/konverter-backend:v4 .

FROM python:3.12-slim

# System libs pymupdf / pillow / pdfium need
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the backend WITHOUT the docling extra. Copy manifest + app first so
# this layer is cached and not rebuilt on every code change.
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app
RUN python -m pip install --no-cache-dir -e "./backend"

# Runtime config defaults. Secrets/URLs are provided at run time, NOT baked in.
ENV KONVERTER_DOCLING_MODE=remote \
    KONVERTER_LOG_LEVEL=INFO \
    KONVERTER_DATA_DIR=/app/data \
    KONVERTER_CORS_ORIGINS=http://localhost:5173

# Documents persist under KONVERTER_DATA_DIR (/app/data). Mount a RunPod volume
# here if you want uploads to survive pod restarts (see README).
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
