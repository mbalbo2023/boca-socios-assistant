"""Execute the manual host gate without credentials, network or host access."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

SHA = "a" * 40
WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
GATE_NAME = "Require verified protected environment and matching main commit"


def _gate_script() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    block = workflow.split(f"      - name: {GATE_NAME}\n", 1)[1].split("      - name:", 1)[0]
    script = block.split("        run: |\n", 1)[1]
    return textwrap.dedent(script)


def _run_gate(
    operation: str,
    *,
    read_only_ready: str = "",
    deploy_ready: str = "",
    image: str = "",
    release_run: str = "",
    source_sha: str = SHA,
    run_attempt: str = "1",
) -> subprocess.CompletedProcess[str]:
    # The extracted gate uses only shell builtins and these synthetic values.
    env = {
        "PATH": "/usr/bin:/bin",
        "BOCA_OPERATION": operation,
        "BOCA_HOST_READONLY_ENV_READY": read_only_ready,
        "BOCA_DEPLOY_ENV_READY": deploy_ready,
        "BOCA_IMAGE_REF": image,
        "BOCA_RELEASE_RUN_ID": release_run,
        "BOCA_SOURCE_SHA": source_sha,
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ATTEMPT": run_attempt,
        "BOCA_SERVICE": "controller",
        "BOCA_BUDGET": "0.5cpu-256m-64pids",
    }
    return subprocess.run(  # noqa: S603 - fixed bash interpreter, synthetic local gate
        ["/usr/bin/bash", "-e", "-o", "pipefail"],
        input=_gate_script(),
        text=True,
        capture_output=True,
        timeout=3,
        env=env,
        check=False,
    )


@pytest.mark.parametrize("operation", ["inspect-prerequisites", "preflight"])
def test_read_only_host_gate_does_not_require_deploy_ready(operation: str) -> None:
    assert _run_gate(operation, read_only_ready="ready").returncode == 0
    assert _run_gate(operation, deploy_ready="ready").returncode != 0
    assert _run_gate(operation, read_only_ready="ready", image="not-blank").returncode != 0
    assert _run_gate(operation, read_only_ready="ready", release_run="1").returncode != 0


@pytest.mark.parametrize("operation", ["first-install", "diagnostic"])
def test_read_only_host_ready_cannot_unlock_effectful_coordinates(operation: str) -> None:
    coordinates = {"image": "reviewed-digest", "release_run": "123"}
    assert _run_gate(operation, read_only_ready="ready", **coordinates).returncode != 0
    assert _run_gate(operation, deploy_ready="ready", **coordinates).returncode == 0
    assert _run_gate(operation, deploy_ready="ready", image="").returncode != 0
    assert _run_gate(operation, deploy_ready="ready", release_run="").returncode != 0


def test_unknown_or_stale_host_dispatch_is_no_go() -> None:
    assert (
        _run_gate(
            "unknown",
            read_only_ready="ready",
            deploy_ready="ready",
            image="reviewed-digest",
            release_run="123",
        ).returncode
        != 0
    )
    assert _run_gate("preflight", read_only_ready="ready", run_attempt="2").returncode != 0
    assert _run_gate("preflight", read_only_ready="ready", source_sha="b" * 40).returncode != 0
    assert _run_gate("preflight", read_only_ready="Ready").returncode != 0


def test_host_gate_is_before_checkout_and_ssh() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    gate = workflow.split(f"      - name: {GATE_NAME}\n", 1)[1].split("      - name:", 1)[0]
    assert "BOCA_HOST_READONLY_ENV_READY: ${{ vars.BOCA_HOST_READONLY_ENV_READY }}" in gate
    assert "BOCA_DEPLOY_ENV_READY: ${{ vars.BOCA_DEPLOY_ENV_READY }}" in gate
    assert (
        workflow.index(f"      - name: {GATE_NAME}")
        < workflow.index("      - name: Checkout exact main commit")
        < workflow.index("      - name: Configure pinned SSH host key")
    )
