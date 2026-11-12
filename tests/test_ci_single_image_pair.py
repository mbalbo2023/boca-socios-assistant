"""One exact unprivileged image pair must supply every PR Docker gate."""

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def _source(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_pr_has_only_two_image_builds_and_required_contexts() -> None:
    ci = _source("ci.yml")
    assert "name: quality-and-tests" in ci
    assert "name: image-build" in ci
    assert ci.count("docker build") == 2
    for filename in ("release-image.yml", "image-security.yml"):
        assert "  pull_request:" not in _source(filename)
    deploy = _source("boca-first-deploy.yml")
    pr = deploy.split("  deploy:\n", 1)[0]
    assert "docker build" not in pr
    assert "first-deploy-pr-validation" in pr


def test_path_specific_public_isolation_cannot_add_a_third_pr_build() -> None:
    public = _source("boca-source-status.yml")
    assert "  pull_request:" not in public
    browser = public.split("  browser-isolation:\n", 1)[1]
    assert "if: github.event_name == 'workflow_dispatch'" in browser
    ci = _source("ci.yml").split("  image:\n", 1)[1]
    marker = "      - name: Verify OS denial and Chromium sandbox without a public request\n"
    assert marker in ci
    probe = ci.split(marker, 1)[1].split("      - name:", 1)[0]
    assert "if: github.event_name == 'pull_request'" in probe
    assert "scripts/run_public_observer_isolated.sh --offline-check" in probe
    assert "--one-get" not in probe and "--capture-25" not in probe
    assert '--tag "boca-observer:$SOURCE_SHA"' in ci
    assert '--label "org.boca.public-image=${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in ci


@pytest.mark.parametrize(
    ("mode", "event", "attempt", "allowed"),
    [
        ("--offline-check", "pull_request", "1", True),
        ("--offline-check", "pull_request", "2", True),
        ("--offline-check", "pull_request", "3", False),
        ("--offline-check", "push", "2", False),
        ("--offline-check", "workflow_dispatch", "2", False),
        ("--one-get", "workflow_dispatch", "1", True),
        ("--one-get", "workflow_dispatch", "2", False),
        ("--capture-25", "workflow_dispatch", "1", True),
        ("--capture-25", "workflow_dispatch", "2", False),
        ("--one-get", "pull_request", "1", False),
        ("--capture-25", "pull_request", "2", False),
        ("--offline-check", "pull_request", "0", False),
        ("--offline-check", "pull_request", "", False),
    ],
)
def test_public_observer_replay_guard_allows_only_second_offline_pr_attempt(
    mode: str, event: str, attempt: str, allowed: bool
) -> None:
    script = (ROOT / "scripts/run_public_observer_isolated.sh").read_text()
    # Execute the actual dispatch guards, stopping before any Docker effect.
    guard = script.split('root="$(pwd -P)"', 1)[0]
    env = os.environ | {
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": attempt,
        "GITHUB_SHA": "c" * 40,
        "GITHUB_EVENT_NAME": event,
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_REF": "refs/heads/main",
        "BOCA_OBSERVER_IMAGE": "boca-observer:" + "c" * 40,
    }
    result = subprocess.run(  # noqa: S603 - actual guard only; no Docker/network
        ["/usr/bin/bash", "-c", guard, "observer", mode],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is allowed


def test_same_image_pair_is_labeled_scanned_and_exercised_before_cleanup() -> None:
    image = _source("ci.yml").split("  image:\n", 1)[1]
    assert (
        image.count(
            "org.opencontainers.image.source=https://github.com/mbalbo2023/boca-socios-assistant"
        )
        == 2
    )
    assert image.count('--label "org.opencontainers.image.revision=$SOURCE_SHA"') == 2
    assert image.count("run: bash scripts/trivy_scan_image.sh") == 2
    for marker in (
        "Verify source revision label",
        "Verify browser source revision label",
        "Measure disposable dual-image logical and archive bytes",
        "Verify all full Playwright browser bundles without blackbox execution",
        "Require the reviewed browser IPC worker command",
        "Verify isolated Chromium launch offline without owner modules",
        "Prove Docker-created service labels are discoverable by Compose on disposable runner",
        "Exercise sealed Site intake in a disposable Boca owner volume",
        "Exercise sealed HTTP owner passkey custody in a disposable Boca volume",
        "Smoke disposable Chrome listener and offline staged owner import",
        "Run synthetic loopback HTTP acceptance inside capped disposable controller",
        "Verify offline sender readiness and never-started production network inspect",
    ):
        assert f"      - name: {marker}\n" in image
    final_consumer = image.index("Verify offline sender readiness")
    assert final_consumer < image.index("Clean disposable browser runner resources")
    assert final_consumer < image.index("Remove only new lifecycle resources")
    assert "docker login" not in image and "docker push" not in image
    assert "packages: write" not in _source("ci.yml")
    assert "workflow_run:" not in _source("ci.yml")


def test_release_and_host_effects_remain_manual_and_independent() -> None:
    release = _source("release-image.yml")
    publish = release.split("  publish:\n", 1)[1]
    assert "github.event_name == 'workflow_dispatch'" in publish
    assert "environment: boca-image-release" in publish
    assert publish.count("docker build") == 2
    assert publish.count("run: bash scripts/trivy_scan_image.sh") == 2
    assert "download-artifact" not in publish and "gh run download" not in publish
    assert "cache-from" not in publish
    assert len(re.findall(r"name: boca-(?:browser-)?release-manifest\n", publish)) == 2
    deploy = _source("boca-first-deploy.yml").split("  deploy:\n", 1)[1]
    assert "github.event_name == 'workflow_dispatch'" in deploy
    assert "environment: boca-first-deploy" in deploy


@pytest.mark.parametrize(
    "substituted",
    ["", "boca-release-validation:", "boca-browser-release-validation:", "boca-observer:"],
)
def test_scan_alias_proof_rejects_either_substituted_image(
    tmp_path: Path, substituted: str
) -> None:
    """Scanning an alias to another image must fail before the scanner runs."""
    source = _source("ci.yml")
    marker = "      - name: Require scan aliases to identify the exact built pair\n"
    assert marker in source
    step = source.split(marker, 1)[1].split("      - name:", 1)[0]
    body = textwrap.dedent(step.split("        run: |\n", 1)[1])
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "ref = sys.argv[-1]\n"
        "changed = os.environ['SUBSTITUTED']\n"
        "print('sha256:' + ('b' if changed and ref.startswith(changed) else 'a') * 64)\n",
        encoding="utf-8",
    )
    docker.chmod(0o700)
    env = os.environ | {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GITHUB_SHA": "c" * 40,
        "BOCA_IMAGE": "boca-socios-ci:" + "c" * 40,
        "BOCA_BROWSER_IMAGE": "boca-browser-ci:" + "c" * 40,
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "SUBSTITUTED": substituted,
    }
    result = subprocess.run(  # noqa: S603 - checked-in shell with disposable Docker fixture
        ["/usr/bin/bash", "-e", "-c", body], env=env, capture_output=True, text=True, check=False
    )
    assert (result.returncode == 0) is (not substituted)
