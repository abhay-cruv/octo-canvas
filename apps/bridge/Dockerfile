FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /workspace

COPY pyproject.toml uv.lock* ./
COPY apps/orchestrator ./apps/orchestrator
COPY apps/bridge ./apps/bridge
COPY python_packages ./python_packages

RUN uv sync --package bridge --no-dev

CMD ["uv", "run", "python", "-m", "bridge"]
