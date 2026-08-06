FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# build-essential is needed for any wheel that needs to compile (httpx, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better Docker layer caching
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Persistent storage for memories.db + knowledge-graph.json.
# Mount a volume here in production:  -v $(pwd)/data:/data
ENV DATA_DIR=/data

EXPOSE 3000

# stdio by default. Set TRANSPORT=http PORT=3000 for the HTTP MCP server.
CMD ["adaptive-memory-server"]
