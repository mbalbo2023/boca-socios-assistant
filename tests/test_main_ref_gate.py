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
    assert len(checks) == 4
    assert checks[0] < workflow.index("Configure pinned SSH host key")
    assert (
        workflow.index("Check prerequisites for dedicated rootless service preparation")
        < checks[1]
        < workflow.index("Prepare only dedicated Boca rootless user service")
    )
    assert (
        workflow.index("Read-only host capacity and Boca namespace before first install")
        < checks[2]
        < workflow.index("Stage only reviewed Boca Compose file")
    )
    assert (
        workflow.index("Validate resolved host Compose model")
        < checks[3]
        < workflow.index("Pull verified digest and start only Boca controller")
    )
