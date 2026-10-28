# Official multi-platform index digest of Python 3.12.15 slim-bookworm.
# Verify/update the digest through a reviewed dependency PR; never float it.
# A successful image build does NOT authorize a production deployment.
FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS build

WORKDIR /app
RUN python -m pip install --disable-pip-version-check --no-cache-dir uv==0.13.4
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH \
    BOCA_RUNTIME_MODE=simulation \
    BOCA_DB_PATH=/data/boca.sqlite3 \
    BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key

RUN groupadd --gid 10001 boca && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin boca && \
    mkdir -p /data && chown boca:boca /data
COPY --from=build /app/.venv /app/.venv
RUN /app/.venv/bin/python -c "import boca_socios.security.credential_vault; import boca_socios.storage.database"
WORKDIR /app
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-m", "boca_socios.healthcheck"]
CMD ["python", "-m", "boca_socios.runtime"]

