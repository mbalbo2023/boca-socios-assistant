# Official Python 3.12.15 slim-Trixie multiarch index; review before refresh.
# No deployment is authorized by creating or modifying this Dockerfile.
FROM python:3.12.15-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS build

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --disable-pip-version-check --no-cache-dir --wheel-dir /wheels .

FROM python:3.12.15-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BOCA_RUNTIME_MODE=simulation \
    BOCA_DB_PATH=/data/boca.sqlite3 \
    BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key

RUN groupadd --gid 10001 boca && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin boca && \
    mkdir -p /data && chown boca:boca /data
COPY --from=build /wheels /wheels
RUN python -m pip install --disable-pip-version-check --no-cache-dir --no-index \
    --find-links=/wheels boca-socios-assistant && \
    rm -rf /wheels
WORKDIR /app
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-m", "boca_socios.healthcheck"]
CMD ["python", "-m", "boca_socios.runtime"]

