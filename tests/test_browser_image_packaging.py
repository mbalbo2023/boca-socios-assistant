"""Static image contract: only the isolated browser may start the IPC worker."""

from __future__ import annotations

from pathlib import Path


def test_browser_image_installs_pinned_package_and_fixed_worker_entrypoint() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile.browser"
    text = dockerfile.read_text(encoding="utf-8")
    assert "mcr.microsoft.com/playwright/python:v1.64.1-noble@sha256:" in text
    assert "PYTHONPATH=/app/src" in text
    assert "COPY src/boca_socios/browser/ ./src/boca_socios/browser/" in text
    assert "COPY src/boca_socios/domain/__init__.py src/boca_socios/domain/policy.py" in text
    assert "uv sync --locked --only-group browser --no-editable --no-cache" in text
    assert "USER 10002:10002" in text
    assert 'CMD ["python", "-m", "boca_socios.browser.ipc_worker"]' in text
    assert "EXPOSE " not in text
    assert "COPY . ." not in text
    assert "COPY src/ ./src/" not in text
    assert "--group browser --no-dev" not in text
    assert "--no-sandbox" not in text


def test_controller_image_does_not_gain_browser_dependency_or_entrypoint() -> None:
    root = Path(__file__).resolve().parents[1]
    controller = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "playwright" not in controller.casefold()
    assert "boca_socios.browser.ipc_worker" not in controller
