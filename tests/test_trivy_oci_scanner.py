"""The OCI scanner replaces the recurrent curl download failure without weakening gates."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = (ROOT / "scripts/trivy_scan_image.sh").read_text(encoding="utf-8")
SECURITY = (ROOT / ".github/workflows/image-security.yml").read_text(encoding="utf-8")
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github/workflows/release-image.yml").read_text(encoding="utf-8")


def test_trivy_image_pinned_by_both_semver_and_immutable_publisher_digest() -> None:
    assert (
        "ghcr.io/aquasecurity/trivy:0.76.1@sha256:"
        "790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c"
    ) in SCAN
    assert "--pull=missing" in SCAN
    assert "--cap-drop=ALL" in SCAN
    assert "--security-opt=no-new-privileges" in SCAN
    assert '--user "$(id -u):$(id -g)" --group-add "$socket_gid"' in SCAN
    assert "--env HOME=/tmp --env TRIVY_CACHE_DIR=/tmp/trivy-cache" in SCAN
    assert "target=/tmp/trivy-cache" in SCAN
    assert (
        "--mount type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock,readonly" in SCAN
    )
    assert "--image-src docker" in SCAN
    assert "install.sh" not in SECURITY + RELEASE
    assert "uses: aquasecurity/trivy-action@" not in SECURITY + RELEASE


def test_all_six_trivy_gates_keep_exact_local_sha_and_high_critical_fail_closed() -> None:
    for ref in (
        "boca-socios-scan:$GITHUB_SHA",
        "boca-browser-scan:$GITHUB_SHA",
    ):
        assert f'bash scripts/trivy_scan_image.sh "{ref}"' in SECURITY

    for ref in (
        "boca-release-validation:$GITHUB_SHA",
        "boca-browser-release-validation:$GITHUB_SHA",
        "ghcr.io/mbalbo2023/boca-socios-assistant:sha-$GITHUB_SHA",
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser:sha-$GITHUB_SHA",
    ):
        assert f'bash scripts/trivy_scan_image.sh "{ref}"' in RELEASE + CI

    assert SECURITY.count("bash scripts/trivy_scan_image.sh") == 2
    assert RELEASE.count("bash scripts/trivy_scan_image.sh") == 2
    assert CI.count("bash scripts/trivy_scan_image.sh") == 2
    for required in (
        "--scanners vuln",
        "--vuln-type os,library",
        "--severity HIGH,CRITICAL",
        "--ignore-unfixed=false",
        "--exit-code 1",
        "--timeout 10m",
        'docker image inspect "$image_ref"',
        '"${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$',
        '"${RUNNER_ENVIRONMENT:-}" != github-hosted',
        '"${GITHUB_ACTIONS:-}" != true',
    ):
        assert required in SCAN


def test_controller_and_browser_security_scans_are_parallel_and_both_required() -> None:
    controller = SECURITY.split("  controller-scan:\n", 1)[1].split("  browser-scan:\n", 1)[0]
    browser = SECURITY.split("  browser-scan:\n", 1)[1].split("  scan:\n", 1)[0]
    gate = SECURITY.split("  scan:\n", 1)[1]

    assert "name: image-security-controller-scan" in controller
    assert "name: image-security-browser-scan" in browser
    assert (
        controller.count("docker/build-push-action@263435318d21b8e681c14492fe198d362a7d2c83")
        == browser.count("docker/build-push-action@263435318d21b8e681c14492fe198d362a7d2c83")
        == 1
    )
    assert controller.count("bash scripts/trivy_scan_image.sh") == 1
    assert browser.count("bash scripts/trivy_scan_image.sh") == 1
    assert "needs:" not in controller + browser  # No serial cross-image dependency.
    # Cached builders may fall back to the original cold build, but both
    # independent scanner steps remain mandatory and fail-closed.
    for body, role in ((controller, "controller"), (browser, "browser")):
        assert body.count("continue-on-error: true") == 2  # setup and build only
        assert f"steps.cached_{role}_build.outcome == 'failure'" in body
        scan = body.split("      - name: Scan ", 1)[1]
        assert "continue-on-error" not in scan
    assert "name: image-security-scan" in gate  # Existing named check remains.
    assert "needs: [controller-scan, browser-scan]" in gate
    assert "if: always()" in gate  # Report failure even when one scan fails/skips.
    assert 'test "$CONTROLLER_RESULT" = success' in gate
    assert 'test "$BROWSER_RESULT" = success' in gate


def test_trivy_failure_cannot_skip_release_login_or_report_success() -> None:
    publish = RELEASE.split("  publish:\n", 1)[1]
    assert (
        publish.index("Scan the image that will be published")
        < publish.index("Scan browser image before any publication")
        < publish.index("Log in only after successful scan")
        < publish.index("Publish both scanned images and record immutable digests")
    )
    assert "set -euo pipefail" in SCAN
    assert "|| true" not in SCAN
    assert "continue-on-error" not in RELEASE
    for name in (
        "Scan OS and library vulnerabilities",
        "Scan browser OS and library vulnerabilities",
    ):
        scan = SECURITY.split(f"      - name: {name}\n", 1)[1].split("      - name:", 1)[0]
        assert "continue-on-error" not in scan


def test_trivy_cli_refuses_unreviewed_image_without_running_docker(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_SHA": "a" * 40,
            "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted",
            "RUNNER_TEMP": str(tmp_path),
        }
    )
    result = subprocess.run(  # noqa: S603 - fixed local script and synthetic input
        ["/usr/bin/bash", str(ROOT / "scripts/trivy_scan_image.sh"), "foreign-image:latest"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "reason=unreviewed_image_reference" in result.stderr


def test_trivy_cli_uses_pinned_docker_source_and_propagates_scanner_failure(
    tmp_path: Path,
) -> None:
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$BOCA_DOCKER_TEST_LOG"\n'
        'if [ "$1" = run ]; then exit "${BOCA_DOCKER_TEST_RC:-0}"; fi\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o700)
    fake_stat = tmp_path / "stat"
    fake_stat.write_text("#!/bin/sh\nprintf '123\\n'\n", encoding="utf-8")
    fake_stat.chmod(0o700)
    log_path = tmp_path / "calls.log"
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_SHA": "a" * 40,
            "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted",
            "RUNNER_TEMP": str(tmp_path),
            "BOCA_DOCKER_TEST_LOG": str(log_path),
            "BOCA_DOCKER_TEST_RC": "17",
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        }
    )
    result = subprocess.run(  # noqa: S603 - fixed local script and synthetic input
        [
            "/usr/bin/bash",
            str(ROOT / "scripts/trivy_scan_image.sh"),
            "boca-socios-scan:" + "a" * 40,
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 17  # Scanner/DB/image failure never becomes PASS.
    calls = log_path.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2
    assert calls[0] == "image inspect boca-socios-scan:" + "a" * 40
    assert "run --rm --pull=missing" in calls[1]
    assert "--image-src docker" in calls[1]
    assert "--user" in calls[1]
    assert "--group-add" in calls[1]
    assert "TRIVY_CACHE_DIR=/tmp/trivy-cache" in calls[1]
    assert "--severity HIGH,CRITICAL --ignore-unfixed=false --exit-code 1" in calls[1]
    assert "sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c" in calls[1]
