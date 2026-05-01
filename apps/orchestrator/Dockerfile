FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /workspace

# Copy the entire workspace so uv can resolve workspace members.
COPY pyproject.toml uv.lock* ./
COPY apps/orchestrator ./apps/orchestrator
COPY apps/bridge ./apps/bridge
COPY python_packages ./python_packages

RUN uv sync --package orchestrator --no-dev

EXPOSE 3001

CMD ["uv", "run", "uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "3001"]
