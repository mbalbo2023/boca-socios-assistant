# Official multi-architecture Python image index, pinned for reproducibility.
# No deployment is authorized by creating or modifying this Dockerfile.
FROM python:3.12.15-alpine3.24@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d AS build

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --disable-pip-version-check --no-cache-dir --wheel-dir /wheels .

FROM python:3.12.15-alpine3.24@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BOCA_RUNTIME_MODE=simulation \
    BOCA_DB_PATH=/data/boca.sqlite3 \
    BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key

RUN addgroup -S -g 10001 boca && \
    adduser -S -D -H -u 10001 -G boca -s /sbin/nologin boca && \
    mkdir -p /data && chown boca:boca /data
COPY --from=build /wheels /wheels
RUN python -m pip install --disable-pip-version-check --no-cache-dir --no-index \
    --find-links=/wheels boca-socios-assistant && \
    rm -rf /wheels && \
    python -c "import sqlite3; from boca_socios.security.credential_vault import CredentialVault; assert sqlite3.connect(':memory:').execute('select 1').fetchone() == (1,); vault = CredentialVault(bytes(32)); assert vault.open(vault.seal('smoke', member_id='smoke'), member_id='smoke') == 'smoke'"
WORKDIR /app
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-m", "boca_socios.healthcheck"]
CMD ["python", "-m", "boca_socios.runtime"]

