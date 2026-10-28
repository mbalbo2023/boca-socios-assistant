# Official multi-architecture Python image index, pinned for reproducibility.
# Verify/update the digest through a reviewed dependency PR; never float it.
# A successful image build does NOT authorize a production deployment.
FROM python:3.12.15-alpine3.24@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d AS build

WORKDIR /app
RUN python -m pip install --disable-pip-version-check --no-cache-dir uv==0.13.4
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12.15-alpine3.24@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH \
    BOCA_RUNTIME_MODE=simulation \
    BOCA_DB_PATH=/data/boca.sqlite3 \
    BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key

RUN addgroup -S -g 10001 boca && \
    adduser -S -D -H -u 10001 -G boca -s /sbin/nologin boca && \
    mkdir -p /data && chown boca:boca /data
COPY --from=build /app/.venv /app/.venv
WORKDIR /app
USER 10001:10001
RUN python -c "import os, sqlite3; from boca_socios.security.credential_vault import CredentialVault; import boca_socios.storage.database; assert os.getuid() == 10001; assert sqlite3.connect(':memory:').execute('select 1').fetchone() == (1,); vault = CredentialVault(bytes(32)); assert vault.open(vault.seal('smoke', member_id='smoke'), member_id='smoke') == 'smoke'"
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-m", "boca_socios.healthcheck"]
CMD ["python", "-m", "boca_socios.runtime"]

