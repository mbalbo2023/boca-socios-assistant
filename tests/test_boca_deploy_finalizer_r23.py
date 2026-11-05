"""Governed Boca install dispatches must have a same-job cleanup finalizer.

These tests execute only the pre-SSH Bash guard with synthetic coordinates.
They never access Docker, the droplet, credentials, or the Boca website.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
GUARD = "Reject legacy install routes without same-lease Boca-only postflight"
LEGACY_INSTALLS = (
    "first-install",
    "beta-install",
    "beta-browser-install",
    "site-install",
    "owner-install",
    "telegram-install",
)


def _guard_script() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    block = workflow.split(f"      - name: {GUARD}\n", 1)[1].split("      - name:", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


def _run_guard(operation: str, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], str]:
    summary = tmp_path / "summary.txt"
    env = {
        "PATH": "/usr/bin:/bin",
        "BOCA_OPERATION": operation,
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    run = subprocess.run(  # noqa: S603 - fixed bash and synthetic runner-only shell
        ["/usr/bin/bash", "-e", "-o", "pipefail"],
        input=_guard_script(),
        text=True,
        capture_output=True,
        timeout=3,
        env=env,
        check=False,
    )
    return run, summary.read_text(encoding="utf-8") if summary.exists() else ""


@pytest.mark.parametrize("operation", LEGACY_INSTALLS)
def test_legacy_multi_ssh_install_fails_before_any_host_setup(
    operation: str, tmp_path: Path
) -> None:
    run, summary = _run_guard(operation, tmp_path)
    assert run.returncode != 0
    assert "BOCA_POSTDEPLOY state=NO_GO" in summary
    assert "legacy_install_without_same_lease_finalizer" in summary
    assert "preserve" in summary.lower()
    # The preflight is a local shell-only failure, with no SSH/Docker invocations.
    assert "ssh" not in run.stdout.lower()
    assert "docker" not in run.stdout.lower()


@pytest.mark.parametrize(
    "operation",
    (
        "cutover-a-apply",
        "cutover-a-observe",
        "port-check",
        "diagnostic",
        "beta-start",
        "beta-browser-status",
        "owner-enroll",
        "telegram-verify",
    ),
)
def test_guard_preserves_cutover_and_nondeploy_operations(operation: str, tmp_path: Path) -> None:
    run, summary = _run_guard(operation, tmp_path)
    assert run.returncode == 0, (run.stderr, summary)
    assert "state=ACCEPT" not in summary
    assert "state=NO_GO" not in summary


def test_guard_is_before_ssh_and_cutover_go_is_still_independent() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert (
        workflow.index(f"      - name: {GUARD}")
        < workflow.index("      - name: Checkout exact main commit")
        < workflow.index("      - name: Configure pinned SSH host key")
    )
    assert (
        workflow.index("      - name: Require independently approved Cutover A GO")
        < workflow.index("      - name: Apply exactly one reviewed Cutover A host transaction")
        < workflow.index(
            "      - name: Fail closed on absent or ambiguous Cutover A host terminal receipt"
        )
    )
    assert (
        "BOCA_CUTOVER_A_GO_BINDING_SHA256: ${{ vars.BOCA_CUTOVER_A_GO_BINDING_SHA256 }}" in workflow
    )
    assert "if: ${{ always() && inputs.operation == 'cutover-a-apply' }}" in workflow
    assert "python scripts/check_cutover_a_go.py --assert-host-receipt" in workflow


def test_guard_has_no_secret_or_host_dependency() -> None:
    script = _guard_script()
    for forbidden in ("ssh ", "docker ", "gh api", "curl ", "BOT_TOKEN", "OWNER_KEY"):
        assert forbidden not in script
    assert "if: inputs.operation == 'cutover-a-apply'" in WORKFLOW.read_text(encoding="utf-8")
