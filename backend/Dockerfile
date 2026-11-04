FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app/backend
COPY app/backend/pyproject.toml app/backend/uv.lock ./
RUN uv sync --no-dev --frozen
COPY app/backend/bizos ./bizos
COPY data/mock/bizos.db /data/bizos.db
ENV BIZOS_DB=/data/bizos.db BIZOS_AUDIT=/tmp/audit.jsonl
# Build from repo root: docker build -f app/backend/Dockerfile .  Secrets come in as env vars, never baked in.
CMD ["uv", "run", "--no-dev", "uvicorn", "bizos.main:app", "--host", "0.0.0.0", "--port", "8080"]
