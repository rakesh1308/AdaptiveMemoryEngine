FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for httpx/uvicorn (sqlite + FTS5 ship with python:3.12-slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better Docker layer caching
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# First-boot entrypoint. If /data/memories.db is missing AND seed-data/ is
# bundled into the image at build time, copy it in. Existing Zeabur volumes
# already contain /data/memories.db, so this is a no-op for live deployments.
# To bundle seed data: commit a non-empty seed-data/ directory.
RUN mkdir -p /seed-data
COPY --chmod=755 entrypoint.sh /entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["adaptive-memory", "serve"]