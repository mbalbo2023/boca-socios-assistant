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


def test_browser_image_removes_unfixed_optional_multimedia_and_pins_python_fixes() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile.browser").read_text(
        encoding="utf-8"
    )
    assert (
        "apt-get purge --yes gstreamer1.0-plugins-bad libgstreamer-plugins-bad1.0-0" in dockerfile
    )
    assert "for pkg in gstreamer1.0-plugins-bad libgstreamer-plugins-bad1.0-0" in dockerfile
    assert "dpkg-query -W" in dockerfile  # Positive post-removal image gate.
    assert "apt-get autoremove" not in dockerfile
    for name, fixed in {
        "certifi": "2026.10.18",
        "distlib": "0.4.4",
        "filelock": "4.2.1",
        "msgpack": "1.2.3",
        "packaging": "26.3",
        "platformdirs": "4.14.2",
        "python-discovery": "1.6.6",
        "setuptools": "78.1.1",
        "urllib3": "2.8.0",
        "virtualenv": "21.14.9",
    }.items():
        assert f"{name}=={fixed}" in dockerfile
    assert "--no-deps" in dockerfile
    assert "--only-binary=:all:" in dockerfile
    assert "python -m pip check" in dockerfile


def test_existing_security_workflow_scans_browser_as_strictly_as_controller() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/image-security.yml"
    ).read_text(encoding="utf-8")
    assert (
        "docker build --file Dockerfile.browser --tag boca-browser-scan:${{ github.sha }} ."
        in workflow
    )
    assert (
        workflow.count("uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25")
        == 2
    )
    browser_scan = workflow.split("- name: Scan browser OS and library vulnerabilities\n", 1)[1]
    for line in (
        "image-ref: boca-browser-scan:${{ github.sha }}",
        "version: v0.76.1",
        "scanners: vuln",
        "vuln-type: os,library",
        "severity: HIGH,CRITICAL",
        'ignore-unfixed: "false"',
        'exit-code: "1"',
    ):
        assert line in browser_scan
