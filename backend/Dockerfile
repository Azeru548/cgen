# Render Free PoC image: Python 3.12 slim + CadQuery binary wheels.
# CadQuery needs libgl/libglib system libs for OCCT (OCP) — install them via apt.
# Keep this image minimal: no frontend, no AI, just FastAPI + CadQuery.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# OCCT runtime deps (headless). Without these, `import OCP` fails with libGL errors.
# NOTE: OCP pip wheels bundle OCCT itself — only system GL/glib libs are needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglx-mesa0 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app

# Render sets $PORT; default to 10000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
