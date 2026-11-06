"""Code-only assertions for two one-shot Boca-only physical remediation routes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"


def test_exact_one_incident_one_prepare_and_independent_protected_actions() -> None:
    flow = WORKFLOW.read_text()
    assert "cutover-a-stage-recover" in flow
    assert "cutover-a-image-retire" in flow
    assert 'test "$BOCA_PROTECTED_ACTION_CONTEXT" = 42236673419' in flow
    assert 'test "$BOCA_INCIDENT_PREPARE_RUN_ID" = 42217108000' in flow
    assert "repos/$GITHUB_REPOSITORY/actions/runs/42237830418" in flow
    assert "python scripts/check_main_ref.py" in flow
    assert 'test "$GITHUB_RUN_ATTEMPT" = 1' in flow
    assert "id: cutover_stage_recovery_host" in flow
    assert "id: cutover_image_retire_host" in flow
    # Each effect is gated behind its own mutually exclusive workflow input.
    assert "if: inputs.operation == 'cutover-a-stage-recover'" in flow
    assert "if: inputs.operation == 'cutover-a-image-retire'" in flow


def test_stage_effect_is_one_reviewed_zip_and_requires_physical_ack() -> None:
    flow = WORKFLOW.read_text()
    stage = flow.split("- name: Build deterministic reviewed Boca stage recovery memfd package", 1)[
        1
    ].split("- name: Attest one historical Boca image release", 1)[0]
    assert "scripts/build_protected_boca_bundle.py" in stage
    assert "scripts/boca_protected_memfd_bootstrap.py" in stage
    assert "cutover-stage-recover" in stage
    assert '< "$reviewed"' in stage
    assert "PYTHONPATH: src:." in stage
    assert "python3 -m scripts.host_cutover_stage_recovery verify" in stage
    assert "physical_ACK_missing_or_invalid retry=NO_GO" in stage
    assert "docker rm" not in stage
    assert "docker image rm" not in stage
    assert "prune" not in stage


def test_stage_runner_verifier_imports_both_packages_outside_host() -> None:
    """Regression #42243714580: source imports must precede physical ACK parsing."""
    env = {**os.environ, "PYTHONPATH": "src:."}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.host_cutover_stage_recovery",
            "verify",
            "42236673419",
            "42217108000",
        ],
        cwd=ROOT,
        env=env,
        input=b"",
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 3  # Missing test ACK must still be NO_GO.
    assert b"ModuleNotFoundError" not in result.stderr
    assert b"ImportError" not in result.stderr


def test_docker_effect_is_one_exact_historical_image_and_requires_ack() -> None:
    flow = WORKFLOW.read_text()
    image = flow.split("- name: Attest one historical Boca image release", 1)[1].split(
        "- name: Apply one exact-ID Boca owner lifecycle request", 1
    )[0]
    assert "actions/runs/41559973013" in image
    assert "item['id'] == 13196392925" in image
    assert "historical-retire-host" in image
    assert "historical-retire-verify" in image
    assert "src/boca_socios/host_boca_cleanup.py" in image
    assert "physical_ACK_missing_or_invalid retry=NO_GO" in image
    assert "docker system prune" not in image
    assert "docker image prune" not in image
    assert "docker container prune" not in image


def test_manual_effects_unreachable_in_pr_validation() -> None:
    flow = WORKFLOW.read_text()
    pr, deploy = flow.split("  deploy:\n", 1)
    assert "cutover_stage_recovery_host" not in pr
    assert "cutover_image_retire_host" not in pr
    assert "github.event_name == 'workflow_dispatch'" in deploy
    assert "github.ref == 'refs/heads/main'" in deploy
    assert "github.actor == 'mbalbo2023'" in deploy
    assert "environment: boca-first-deploy" in deploy
