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
    sections = {
        section.splitlines()[0]: section for section in workflow.split("      - name: ")[1:]
    }
    checks_before_effects = {
        "Confirm current main HEAD before host access": "Configure pinned SSH host key",
        "Recheck current main before Site custody operation": "Prepare, install or verify only Boca Site owner-volume custody",
        "Recheck current main before owner custody operation": "Mark owner custody host attempt before starting dedicated daemon",
        "Recheck current main after Chrome proof before owner private-key import": "Finish one-use Chrome enrollment with offline owner custody",
        "Recheck current main before preparing dedicated rootless service": "Prepare only dedicated Boca rootless user service",
        "Recheck current main before stopping Boca tests": "Stop and verify dedicated Boca test services",
        "Recheck current main HEAD before staging": "Mark Boca staging attempt after read-only preflight",
        "Recheck current main HEAD before effectful install": "Pull verified digest and start only Boca controller",
        "Recheck current main before BETA install": "Mark BETA staging attempt after owner-only preflight",
        "Recheck current main immediately before BETA app and key effects": "Initialize new-only BETA and start isolated controller",
        "Recheck current main immediately before browser daemon start": "Mark protected browser daemon start attempt",
        "Recheck current main before new-only browser staging": "Mark browser IPC staging attempt for immediate selective cleanup",
        "Recheck main and only Boca loopback 8443 before browser effects": "Start worker then controller only after healthy private socket proof",
        "Recheck current main before existing browser lifecycle": "Mark existing browser lifecycle attempt",
        "Recheck main before explicit Telegram sender creation": "Mark only new Telegram sender attempt for immediate cleanup",
        "Recheck current main before BETA acceptance": "Mark protected BETA acceptance host attempt",
        "Recheck current main before Telegram post-install custody": "Mark Telegram host attempt before starting existing Boca daemon",
    }
    for check, effect in checks_before_effects.items():
        section = sections[check]
        assert "python scripts/check_main_ref.py" in section
        assert '"$BOCA_SOURCE_SHA"' in section
        assert "continue-on-error" not in section
        assert workflow.index("      - name: " + check) < workflow.index("      - name: " + effect)
    for finalizer in (
        "Stop positively identified Boca services after BETA acceptance",
        "Stop positively identified Boca services after Telegram custody",
    ):
        section = sections[finalizer]
        assert section.index("python scripts/check_main_ref.py") < section.index(
            "python3 - stop-test"
        )
