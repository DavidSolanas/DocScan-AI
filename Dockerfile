# Stage 1 — builder: install dependencies with uv
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./

# Install all deps (core + advanced-ocr) into .venv
RUN uv sync --frozen --no-dev --extra advanced-ocr

# Copy application code
COPY backend/ backend/
COPY frontend/ frontend/

# Stage 2 — runtime: lean image with only runtime deps
FROM python:3.12-slim AS runtime

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    ghostscript \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -m -s /bin/bash docscanai
WORKDIR /app

# Copy venv and app from builder (no build tools in final image)
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/backend backend/
COPY --from=builder /app/frontend frontend/
COPY --from=builder /app/pyproject.toml .
COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Ensure data dirs writable
RUN mkdir -p /app/data && chown -R docscanai:docscanai /app

ENV PATH="/app/.venv/bin:$PATH"
ENV DOCSCAN_DATA_DIR=/app/data

USER docscanai
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
