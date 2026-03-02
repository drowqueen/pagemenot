FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip pip install .

COPY pagemenot/ pagemenot/
COPY scripts/ scripts/
COPY knowledge/ knowledge/

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

CMD ["python", "-m", "pagemenot.main"]
