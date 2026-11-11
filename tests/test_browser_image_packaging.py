"""Static image contract: only the isolated browser may start the IPC worker."""

from __future__ import annotations

import os
import re
import subprocess
import sys
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
    assert 'CMD ["python", "-m", "boca_socios.browser.ipc_server"]' in text
    assert 'CMD ["python", "-m", "boca_socios.browser.ipc_worker"]' not in text
    assert "EXPOSE " not in text
    assert "COPY . ." not in text
    assert "COPY src/ ./src/" not in text
    assert "--group browser --no-dev" not in text
    assert "--no-sandbox" not in text


def test_browser_image_pythonpath_resolves_bare_synthetic_without_importing_blackbox() -> None:
    """W1 #934: resolve the bare module name without executing owner-controlled code."""
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile.browser").read_text(encoding="utf-8")
    match = re.search(r"\bPYTHONPATH=([^\s\\]+)", dockerfile)
    assert match is not None, "browser image must declare PYTHONPATH"
    paths = match.group(1).split(":")
    assert "/app/src" in paths, "packaged boca_socios imports must remain available"
    env = {
        **os.environ,
        "PYTHONPATH": ":".join(str(root / path.removeprefix("/app/")) for path in paths),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.util; spec=importlib.util.find_spec('synthetic'); "
            "print(spec.origin if spec else 'MISSING')",
        ],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == str(root / "src/boca_socios/browser/synthetic.py")


def test_browser_image_explicitly_installs_chromium_and_system_dependencies() -> None:
    """Only the isolated worker image may install pinned Playwright Chromium OS libs."""
    browser = (Path(__file__).resolve().parents[1] / "Dockerfile.browser").read_text(
        encoding="utf-8"
    )
    command = "/app/.venv/bin/python -m playwright install --with-deps chromium"
    assert command in browser
    assert browser.index("uv sync --locked --only-group browser") < browser.index(command)
    assert browser.index(command) < browser.index("-m pip uninstall --yes setuptools")
    assert browser.index(command) < browser.index("USER 10002:10002")
    assert "playwright install --with-deps firefox" not in browser
    assert "playwright install --with-deps webkit" not in browser
    install_step = browser.split(command, 1)[1].split("\n\n", 1)[0]
    assert "dpkg-query -W -f='${Version}' libbrotli1" in install_step
    assert "for pkg in gstreamer1.0-plugins-bad libgstreamer-plugins-bad1.0-0" in install_step


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
        "virtualenv": "21.14.13",
    }.items():
        assert f"{name}=={fixed}" in dockerfile
    assert "--no-deps" in dockerfile
    assert "--only-binary=:all:" in dockerfile
    assert "python -m pip check" in dockerfile


def test_browser_image_fixes_brotli_and_removes_build_only_vendored_python() -> None:
    text = (Path(__file__).resolve().parents[1] / "Dockerfile.browser").read_text(encoding="utf-8")
    assert "apt-get update" in text
    assert "apt-get install --yes --no-install-recommends libbrotli1=1.1.0-2ubuntu0.1" in text
    assert "dpkg-query -W -f='${Version}' libbrotli1" in text
    assert "-m pip uninstall --yes setuptools virtualenv uv" in text
    assert "-m pip uninstall --yes pip" in text
    assert text.index("-m pip uninstall --yes setuptools virtualenv uv") < text.index(
        "-m pip uninstall --yes pip"
    )
    assert "pip/_vendor" in text  # Require a post-uninstall vendor-tree absence check.
    assert "setuptools/_vendor" in text
    assert "root/.cache/virtualenv" in text
    assert text.index("uv sync --locked --only-group browser") < text.index("-m pip uninstall")
    assert "rm -f" not in text  # Never conceal only a vulnerable BOM or METADATA.


def test_existing_security_workflow_scans_browser_as_strictly_as_controller() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/image-security.yml"
    ).read_text(encoding="utf-8")
    assert (
        "docker build --file Dockerfile.browser --tag boca-browser-scan:${{ github.sha }} ."
        in workflow
    )
    assert workflow.count("run: bash scripts/trivy_scan_image.sh") == 2
    browser_scan = workflow.split("- name: Scan browser OS and library vulnerabilities\n", 1)[1]
    assert 'run: bash scripts/trivy_scan_image.sh "boca-browser-scan:$GITHUB_SHA"' in browser_scan
