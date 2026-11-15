"""The incident selector has no caller coordinates or operational effects."""

import os
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"


def classification_from_real_step(bundle, receipt, remote_rc, directory, run_id, workflow_sha):
    """Only SSH's bytes/status are substituted; shell and ZIP verifier remain real."""
    directory.mkdir()
    (directory / "receipt").write_bytes(receipt)
    source = WORKFLOW.read_text()
    step = source.split("      - name: Observe fixed Telegram incident READ_ONLY\n", 1)[1].split(
        "      - name:", 1
    )[0]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    script = "set -euo pipefail\nverification_rc=0" + script.split("verification_rc=0", 1)[1]
    summary = directory / "summary"
    result = subprocess.run(  # noqa: S603 - reviewed shell tail; synthetic receipt, no SSH
        ["/bin/bash", "-c", script],
        cwd=directory,
        env={
            "PATH": os.environ["PATH"],
            "bundle": str(bundle),
            "receipt_dir": str(directory),
            "remote_rc": str(remote_rc),
            "GITHUB_RUN_ID": run_id,
            "GITHUB_SHA": workflow_sha,
            "GITHUB_STEP_SUMMARY": str(summary),
            "PYTHONPATH": "/nonexistent-untrusted-checkout",
        },
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert not result.stderr
    return result.returncode, summary.read_bytes()


def test_incident_workflow_fixed_admission_and_isolated_verifier():
    source = WORKFLOW.read_text()
    assert "boca-telegram-incident-observe" in source.split("options: [", 1)[1].split("]", 1)[0]
    step = source.split("      - name: Observe fixed Telegram incident READ_ONLY\n", 1)[1].split(
        "      - name:", 1
    )[0]
    for required in (
        "--telegram-incident-observe",
        "check_main_ref.py",
        "180s",
        "--kill-after=5s",
        "-I -S -B",
        "verify",
        "$GITHUB_SHA",
    ):
        assert required in step
    assert step.count(" ssh ") == 1
    assert "OBSERVED_NO_GO" in step and "INCOMPLETE_NO_GO" in step
    assert not any(
        effect in step
        for effect in (
            "docker start",
            "docker stop",
            "docker rm",
            "protected_boca_job_lease",
            "sudo",
        )
    )
