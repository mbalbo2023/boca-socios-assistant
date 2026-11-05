# Disposable size COMPARISON, never a Boca release or droplet image.
# The production Dockerfile.browser keeps full Chromium + Firefox + WebKit.
ARG BENCHMARK_BASE=ubuntu:24.04
FROM ${BENCHMARK_BASE}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/app/.venv/bin:$PATH \
    HOME=/home/boca-browser \
    XDG_CACHE_HOME=/tmp/browser-cache \
    XDG_CONFIG_HOME=/tmp/browser-config

RUN apt-get update -o Acquire::Retries=0 && \
    apt-get install -y --no-install-recommends \
      python3 python3-venv ca-certificates passwd && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /app/.venv && \
    /app/.venv/bin/python -m pip install --no-cache-dir playwright==1.64.1

# Deliberately the same Playwright 1.64.1 browser/deps installation command as
# the product, but unlike the full MCR base no Firefox or WebKit is preinstalled.
RUN /app/.venv/bin/python -m playwright install --with-deps chromium && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10002 boca-browser && \
    useradd --uid 10002 --gid 10002 --create-home --shell /usr/sbin/nologin boca-browser
COPY scripts/verify_chromium_worker.py /app/verify_chromium_worker.py
USER 10002:10002

CMD ["python", "/app/verify_chromium_worker.py"]
