FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# sqlite3 is used only by the explicit legacy-backup recovery/migration command.
RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better Docker layer caching
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# /data is retained for controlled imports, exports, and migration input.
ENV DATA_DIR=/data \
    TRANSPORT=http \
    PORT=3000
RUN useradd --create-home --uid 10001 ame \
    && mkdir -p /data/imports \
    && chown -R ame:ame /data /app
USER ame

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=3)); raise SystemExit(0 if d.get('status') == 'ok' else 1)"

# The container defaults to HTTP. Override TRANSPORT=stdio only for local piping.
CMD ["adaptive-memory-server"]
