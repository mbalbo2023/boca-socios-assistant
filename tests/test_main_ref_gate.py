"""A manual host run must use the current main ref, not a queued stale SHA."""

import json
import runpy
import shlex
import subprocess
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


@pytest.mark.parametrize(
    ("payload", "accepted"),
    [
        pytest.param(
            json.dumps({"ref": "refs/heads/main", "object": {"type": "commit", "sha": SHA}}),
            True,
            id="current_main",
        ),
        pytest.param(
            json.dumps({"ref": "refs/heads/main", "object": {"type": "commit", "sha": "b" * 40}}),
            False,
            id="stale_main",
        ),
        pytest.param("{", False, id="invalid_json"),
        pytest.param(
            json.dumps({"ref": "refs/heads/main", "object": []}),
            False,
            id="invalid_object",
        ),
    ],
)
def test_installed_telegram_main_guard_uses_clean_step_environment(
    tmp_path: Path, payload: str, accepted: bool
) -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/boca-first-deploy.yml").read_text()
    sections = {
        section.splitlines()[0]: section for section in workflow.split("      - name: ")[1:]
    }
    header, body = sections[
        "Execute installed Telegram transaction under one protected lease"
    ].split("        run: |\n", 1)
    # Start from an empty runner environment, not pytest's PYTHONPATH or editable install.
    environment = {
        "PATH": "/usr/bin:/bin",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_SHA": SHA,
        "BOCA_SOURCE_SHA": "b" * 40,
        "BOCA_TEST_PYTHON": sys.executable,
    }
    for line in header.split("        env:\n", 1)[1].splitlines():
        key, value = line.strip().split(": ", 1)
        if key == "GH_TOKEN":
            environment[key] = "inert-test-token"
        else:
            (scalar,) = shlex.split(value)
            environment[key] = scalar
    (tmp_path / "boca-telegram-main.json").write_text(payload)
    set_options = body.splitlines()[0].strip()
    (checker,) = (line.strip() for line in body.splitlines() if "scripts/check_main_ref.py" in line)
    marker = "BOCA_TEST_AFTER_MAIN_GUARD"
    # Execute only the actual guard, never gh/SSH. -S disables incidental site packages;
    # the unchanged checker must import its package from the step's checkout environment.
    probe = "\n".join(
        (
            set_options,
            'python3() { "$BOCA_TEST_PYTHON" -S -B "$@"; }',
            checker,
            f"printf '%s\\n' '{marker}'",
        )
    )
    result = subprocess.run(  # noqa: S603 - local workflow guard, fictional inputs, no host access
        ["/bin/bash", "--noprofile", "--norc", "-c", probe],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert "ModuleNotFoundError" not in result.stderr
    assert result.returncode == (0 if accepted else 1)
    if accepted:
        assert result.stdout == f"BOCA_MAIN_REF_PASS\n{marker}\n"
        assert result.stderr == ""
    else:
        assert result.stderr.startswith("BOCA_NO_GO: ")
        assert result.stdout == ""
        assert marker not in result.stderr


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
