FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for httpx/uvicorn and sqlite (python:3.12-slim ships sqlite with FTS5)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

# Seed data lives next to /data on first boot (same pattern as Node version)
RUN mkdir -p /seed-data
COPY seed-data/. /seed-data/ 2>/dev/null || true

# Seed empty /data on first boot, then start the server (matches Node behavior)
RUN printf '#!/bin/sh\nset -e\nif [ ! -s /data/memories.db ]; then\n  echo "[Seed] Copying seed data to /data..."\n  cp /seed-data/* /data/ 2>/dev/null || true\nfi\nexec "$@"\n' > /entrypoint.sh \
    && chmod +x /entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["adaptive-memory", "serve"]