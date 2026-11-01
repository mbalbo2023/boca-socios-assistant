"""A manual host run must use the current main ref, not a queued stale SHA."""

import runpy
import sys
from pathlib import Path

import pytest

from boca_socios.deploy_inputs import DeployInputError, validate_main_ref

SHA = "a" * 40


def test_exact_main_ref_is_accepted() -> None:
    validate_main_ref({"ref": "refs/heads/main", "object": {"type": "commit", "sha": SHA}}, SHA)


@pytest.mark.parametrize(
    "ref",
    [
        {},
        {"ref": "refs/heads/main", "object": {"type": "commit", "sha": "b" * 40}},
        {"ref": "refs/tags/main", "object": {"type": "commit", "sha": SHA}},
        {"ref": "refs/heads/main", "object": {"type": "tag", "sha": SHA}},
        {"ref": "refs/heads/main", "object": {"type": "commit", "sha": "bad"}},
    ],
)
def test_stale_or_malformed_main_ref_is_no_go(ref: object) -> None:
    with pytest.raises(DeployInputError):
        validate_main_ref(ref, SHA)


@pytest.mark.parametrize("payload", ["{", " " * 8193])
def test_main_ref_cli_rejects_malformed_or_oversized_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    response = tmp_path / "main-ref.json"
    response.write_text(payload)
    script = Path(__file__).resolve().parents[1] / "scripts/check_main_ref.py"
    monkeypatch.setattr(sys, "argv", [str(script), str(response), SHA])
    assert runpy.run_path(str(script))["main"]() == 1


def test_current_main_and_first_attempt_are_checked_before_ssh_and_apply() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    assert workflow.index('test "$GITHUB_RUN_ATTEMPT" = 1') < workflow.index(
        "Configure pinned SSH host key"
    )
    checks = [
        start
        for start in range(len(workflow))
        if workflow.startswith("python scripts/check_main_ref.py", start)
    ]
    # The second owner-enrollment main recheck is intentionally after the
    # 15-minute browser proof and before any private-key import.
    assert len(checks) == 14
    assert checks[0] < workflow.index("Configure pinned SSH host key")
    assert (
        workflow.index("Recheck current main before Site custody operation")
        < checks[1]
        < workflow.index("Prepare, install or verify only Boca Site owner-volume custody")
    )
    assert (
        workflow.index("Recheck current main before owner custody operation")
        < checks[2]
        < workflow.index("Prepare, install or verify only Boca owner-volume public passkey custody")
    )
    assert (
        workflow.index("Recheck current main after Chrome proof before owner private-key import")
        < checks[3]
        < workflow.index("Finish one-use Chrome enrollment with offline owner custody")
    )
    assert (
        workflow.index("Check prerequisites for dedicated rootless service preparation")
        < checks[4]
        < workflow.index("Prepare only dedicated Boca rootless user service")
    )
    assert (
        workflow.index("Recheck current main before stopping Boca tests")
        < checks[5]
        < workflow.index("Stop and verify dedicated Boca test services")
    )
    assert (
        workflow.index("Read-only host capacity and Boca namespace before first install")
        < checks[6]
        < workflow.index("Stage only reviewed Boca Compose file")
    )
    assert (
        workflow.index("Validate resolved host Compose model")
        < checks[7]
        < workflow.index("Pull verified digest and start only Boca controller")
    )
    assert (
        workflow.index("Read-only BETA capacity, owner custody and empty app namespace")
        < checks[8]
        < workflow.index("Stage only reviewed served BETA Compose file")
    )
    assert (
        workflow.index("Validate resolved served BETA host Compose model")
        < checks[9]
        < workflow.index("Initialize new-only BETA and start isolated controller")
    )
    assert (
        workflow.index("Recheck current main before BETA acceptance")
        < checks[10]
        < workflow.index("Mark protected BETA acceptance host attempt")
    )
    assert (
        workflow.index("Stop positively identified Boca services after BETA acceptance")
        < checks[11]
        < workflow.rindex('boca-target "$remote_command" < src/boca_socios/host_rootless_setup.py')
    )
    assert (
        workflow.index("Recheck current main before Telegram post-install custody")
        < checks[12]
        < workflow.index("Mark Telegram host attempt before starting existing Boca daemon")
    )
    assert (
        workflow.index("Stop positively identified Boca services after Telegram custody")
        < checks[13]
        < workflow.rindex('boca-target "$remote_command" < src/boca_socios/host_rootless_setup.py')
    )
