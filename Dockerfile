# Official multi-platform index digest of Python 3.12.15 Alpine 3.24.
# Verify/update the digest through a reviewed dependency PR; never float it.
# A successful image build does NOT authorize a production deployment.
FROM python:3.15.1-alpine3.24@sha256:54448f67d7c31c39e5cdd3ea2d6382395ce142806c284425f8e897d78a0465b3 AS build

WORKDIR /app
RUN python -m pip install --disable-pip-version-check --no-cache-dir uv==0.13.4
COPY pyproject.toml uv.lock README.md ./
# Install only the locked third-party graph before copying application code.
# A source-only edit must not invalidate this comparatively stable layer.
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
# The final pass still installs the non-editable Boca application itself.
RUN uv sync --locked --no-dev --no-editable

FROM python:3.15.1-alpine3.24@sha256:54448f67d7c31c39e5cdd3ea2d6382395ce142806c284425f8e897d78a0465b3 AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH \
    BOCA_RUNTIME_MODE=simulation \
    BOCA_DB_PATH=/data/boca.sqlite3 \
    BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key

# Alpine v3.24/main backport for CVE-2026-107364 (MITKRB5-SA-2026-001).
# Pin the patched stable package; never mix the edge repository into the image.
# Private panel dates use ZoneInfo; Python does not bundle the IANA database.
# Keep the data-only package on this same signed stable repository.
RUN apk add --no-cache 'krb5-libs=1.22.3-r0' 'tzdata=2026f-r0'

RUN addgroup -S -g 10001 boca && \
    adduser -S -D -H -u 10001 -G boca -s /sbin/nologin boca && \
    mkdir -p /data && chown boca:boca /data
COPY --from=build /app/.venv /app/.venv
WORKDIR /app
USER 10001:10001
RUN /app/.venv/bin/python -c "from datetime import datetime, timezone; from zoneinfo import ZoneInfo; assert datetime(2026, 11, 15, 12, tzinfo=timezone.utc).astimezone(ZoneInfo('America/Argentina/Buenos_Aires')).strftime('%Y-%m-%d %H:%M:%S') == '2026-11-15 09:00:00'"
RUN /app/.venv/bin/python -c "import os, sqlite3; from boca_socios.security.credential_vault import CredentialVault; import boca_socios.storage.database; assert os.getuid() == os.geteuid() == 10001; assert os.getgid() == os.getegid() == 10001; assert sqlite3.connect(':memory:').execute('select 1').fetchone() == (1,); vault = CredentialVault(bytes(32)); assert vault.open(vault.seal('smoke', member_id='smoke'), member_id='smoke') == 'smoke'"
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-m", "boca_socios.healthcheck"]
CMD ["python", "-m", "boca_socios.runtime"]

