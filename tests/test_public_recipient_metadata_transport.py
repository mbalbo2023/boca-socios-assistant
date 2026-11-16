"""G3b V3 remains a separate explicit Boca first-deploy operation."""

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from boca_socios import host_boca_public_recipient_metadata as metadata

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
STEP_NAME = "Observe exact installed public Telegram recipient metadata READ_ONLY"


def _step() -> str:
    return SOURCE.split(f"      - name: {STEP_NAME}\n", 1)[1].split("      - name:", 1)[0]


def test_exact_explicit_workflow_operation_is_admitted() -> None:
    options = re.search(r"^        options: \[([^\n]+)\]$", SOURCE, re.MULTILINE)
    assert options is not None
    assert "boca-public-recipient-metadata-observe" in options.group(1).split(", ")
    assert SOURCE.count("if: inputs.operation == 'boca-public-recipient-metadata-observe'") == 1
    block = _step()
    assert "--public-recipient-metadata-observe" in block
    assert "boca-public-recipient-metadata-observe" in block
    assert "scripts/boca_protected_memfd_bootstrap.py" in block
    assert "scripts/check_main_ref.py" in block
    assert "BOCA_PUBLIC_RECIPIENT_METADATA_V3" in block
    assert 'if [[ "$remote_rc" -ne 0 ]]' in block
    assert 'if [[ "$verification_rc" -ne 0' in block
    assert "timeout --signal=TERM --kill-after=5s 180s ssh" in block
    assert "ulimit -f 8" in block
    assert "-o ServerAliveInterval=10 -o ServerAliveCountMax=2" in block
    assert 'test "$GITHUB_ACTOR" = mbalbo2023' in SOURCE
    assert 'test "$GITHUB_TRIGGERING_ACTOR" = mbalbo2023' in SOURCE
    assert 'test "$BOCA_SOURCE_SHA" = "$GITHUB_SHA"' in SOURCE
    assert 'test "$BOCA_BUDGET" = 1.5cpu-1024m-192pids' in SOURCE
    assert not any(
        forbidden in block
        for forbidden in (
            "docker start",
            "docker run",
            "docker create",
            "docker restart",
            "docker stop",
            "docker rm",
            "telegram-activate",
            "telegram-migrate",
            "telegram-prepare",
            "chmod ",
            "chown ",
            "gh api -X POST",
        )
    )


@pytest.mark.parametrize(
    ("verification_rc", "verified", "want_success"),
    [
        (0, 'BOCA_PUBLIC_RECIPIENT_METADATA_V3 {"state":"OBSERVED_NO_GO"}', True),
        (1, 'BOCA_PUBLIC_RECIPIENT_METADATA_V3 {"state":"OBSERVED_NO_GO"}', False),
        (0, 'BOCA_PUBLIC_RECIPIENT_METADATA_V3 {"state":"INCOMPLETE_NO_GO"}', False),
        (0, 'BOCA_PUBLIC_RECIPIENT_METADATA_V3 {"state":"OBSERVED_NO_GO"}\nINJECTED', False),
        (0, 'BOCA_INSTALLED_BINDING {"state":"OBSERVED_NO_GO"}', False),
    ],
)
def test_workflow_tail_nonpromotable_without_closed_verifier(
    tmp_path: Path, verification_rc: int, verified: str, want_success: bool
) -> None:
    # Execute the actual decision branch, no SSH/network/host. Simulated
    # verifier output is not evidence of a real remote receipt.
    step = _step()
    start = step.index('          if [[ "$verification_rc" -ne 0')
    tail = textwrap.dedent(step[start:])
    summary = tmp_path / "summary"
    env = {"PATH": os.environ["PATH"], "GITHUB_STEP_SUMMARY": str(summary)}
    completed = subprocess.run(  # noqa: S603 - fixed Bash only, no SSH in extracted branch
        ["/bin/bash", "-c", "set -euo pipefail\n" + tail],
        env={**env, "verification_rc": str(verification_rc), "verified": verified},
        capture_output=True,
        text=True,
        timeout=3,
    )
    assert (completed.returncode == 0) is want_success, completed.stderr
    text = summary.read_text()
    if want_success:
        assert text.startswith(metadata.PREFIX.decode()) and "authority=NO_GO" in text
    else:
        assert '"state":"OBSERVED_NO_GO"' not in text
        assert "state=INCOMPLETE_NO_GO" in text
