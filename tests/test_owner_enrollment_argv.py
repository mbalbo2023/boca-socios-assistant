"""Opaque owner coordinates remain data through production/smoke argv and cleanup."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import subprocess
import textwrap
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from boca_socios import host_cleanup as cleanup
from boca_socios import host_first_deploy as host
from boca_socios import owner_bootstrap as bootstrap
from boca_socios import owner_enrollment as enrollment
from test_host_owner_enroll_cleanup import (
    CAPABILITY_SHA,
    COMPOSE_SHA,
    IMAGE,
    SHA,
    FakeEnrollDocker,
)
from test_host_owner_enroll_cleanup import enroll_case as enroll_case

ROOT = Path(__file__).resolve().parents[1]
RAW_PUBLIC = bytes([251]) * 32
PUBLIC = base64.urlsafe_b64encode(RAW_PUBLIC).rstrip(b"=").decode("ascii")
FINGERPRINT = hashlib.sha256(RAW_PUBLIC).hexdigest()
SUBJECT = "-synthetic-owner"
ORIGIN = "http://localhost:8443"


def _shell_arguments(command: str, executable: str) -> list[str]:
    result = subprocess.run(  # noqa: S603 - reviewed workflow, synthetic env, inert command function
        [
            "/bin/bash",
            "-eu",
            "-c",
            executable + "() { printf '%s\\0' \"$@\"; }\n" + command,
        ],
        env={
            "PATH": os.environ["PATH"],
            "BOCA_IMAGE": IMAGE,
            "BOCA_PANEL_ORIGIN": ORIGIN,
            "BOCA_OWNER_SUBJECT": SUBJECT,
            "temporary": "synthetic-enrollment",
            "private_net": "synthetic-private",
            "stage": "synthetic-stage",
            "private_digest": CAPABILITY_SHA,
            "public": PUBLIC,
            "fingerprint": FINGERPRINT,
        },
        check=True,
        capture_output=True,
        timeout=5,
    )
    assert result.stderr == b""
    return [value.decode("ascii") for value in result.stdout.split(b"\0")[:-1]]


def _smoke_enrollment_arguments() -> list[str]:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    marker = workflow.index('"$BOCA_IMAGE" python -m boca_socios.owner_enrollment')
    start = workflow.rindex("          docker run ", 0, marker)
    end = workflow.index('\n          state="', marker)
    return _shell_arguments(textwrap.dedent(workflow[start:end]), "docker")


@pytest.mark.parametrize("caller", ["host", "smoke"])
def test_dash_prefixed_public_key_from_real_caller_reaches_enrollment_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], caller: str
) -> None:
    assert PUBLIC.startswith("-") and len(PUBLIC) == 43
    command = (
        list(host._owner_enroll_container(IMAGE, SHA, SUBJECT, CAPABILITY_SHA, PUBLIC, FINGERPRINT))
        if caller == "host"
        else _smoke_enrollment_arguments()
    )
    argv = command[command.index("boca_socios.owner_enrollment") + 1 :]
    serve = Mock(return_value=True)
    monkeypatch.setattr(enrollment, "serve", serve)
    assert enrollment.main(argv) == 0
    assert argv == ["--", SUBJECT, CAPABILITY_SHA, PUBLIC, FINGERPRINT]
    serve.assert_called_once_with(
        enrollment.STAGING,
        bootstrap.RecipientReceipt("PREPARED", PUBLIC, FINGERPRINT),
        SUBJECT,
        bytes.fromhex(CAPABILITY_SHA),
    )
    output = capsys.readouterr()
    assert output.out == "BOCA_OWNER_ENROLL state=VERIFIED_FOR_OFFLINE_INSTALL\n"
    assert output.err == ""


def _bootstrap_mocks(monkeypatch: pytest.MonkeyPatch) -> dict[str, Mock]:
    receipt = bootstrap.RecipientReceipt("PREPARED", PUBLIC, FINGERPRINT)
    calls = {
        "prepare": Mock(return_value=receipt),
        "inspect_prepared": Mock(return_value=receipt),
        "install": Mock(return_value=FINGERPRINT),
        "install_staged": Mock(return_value=FINGERPRINT),
        "verify": Mock(return_value=FINGERPRINT),
    }
    for name, mock in calls.items():
        monkeypatch.setattr(bootstrap, name, mock)
    monkeypatch.setattr(bootstrap.sys, "stdin", SimpleNamespace(buffer=BytesIO(b"synthetic")))
    return calls


@pytest.mark.parametrize(
    "operation", ["prepare", "inspect-prepared", "install", "install-staged", "verify"]
)
def test_dash_prefixed_owner_from_production_bootstrap_reaches_cli(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    command = host._owner_container(IMAGE, operation, ORIGIN, SUBJECT)
    calls = _bootstrap_mocks(monkeypatch)
    argv = command[command.index("boca_socios.owner_bootstrap") + 1 :]
    assert bootstrap.main(argv) == 0
    assert argv == ("--", operation, ORIGIN, SUBJECT)
    assert calls[operation.replace("-", "_")].call_count == 1
    assert sum(mock.call_count for mock in calls.values()) == 1


@pytest.mark.parametrize("index", range(6))
def test_each_smoke_bootstrap_call_keeps_dash_owner_as_data(
    monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    lines = [
        line
        for line in (ROOT / ".github/workflows/boca-first-deploy.yml").read_text().splitlines()
        if '"$BOCA_IMAGE" python -m boca_socios.owner_bootstrap' in line
    ]
    assert len(lines) == 6
    command = lines[index].split('"$BOCA_IMAGE" ', 1)[1].split(')"', 1)[0]
    arguments = _shell_arguments(command, "python")
    argv = tuple(arguments[arguments.index("boca_socios.owner_bootstrap") + 1 :])
    calls = _bootstrap_mocks(monkeypatch)
    assert bootstrap.main(argv) == 0
    assert argv[0] == "--" and argv[-1] == SUBJECT
    assert sum(mock.call_count for mock in calls.values()) == 1


def _owner_remote_commands() -> list[str]:
    return [
        line.strip()
        for line in (ROOT / ".github/workflows/boca-first-deploy.yml").read_text().splitlines()
        if "remote_command=" in line and "BOCA_BETA_OWNER_SUBJECT" in line
    ]


@pytest.mark.parametrize("index", range(18))
@pytest.mark.parametrize("optional_flags", [False, True])
def test_each_protected_owner_transport_reaches_host_cli_without_changing_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, index: int, optional_flags: bool
) -> None:
    lines = _owner_remote_commands()
    assert len(lines) == 18
    for name in (
        "boca-compose.sha",
        "boca-beta-compose.sha",
        "boca-browser-overlay.sha",
        "boca-browser-seccomp.sha",
    ):
        (tmp_path / name).write_text(COMPOSE_SHA + "\n")
    environment = {
        "PATH": os.environ["PATH"],
        "RUNNER_TEMP": str(tmp_path),
        "BOCA_IMAGE_REF": IMAGE,
        "BOCA_SOURCE_SHA": SHA,
        "BOCA_BETA_PANEL_ORIGIN": ORIGIN,
        "BOCA_BETA_OWNER_SUBJECT": SUBJECT,
        "BOCA_OWNER_ENVELOPE": "synthetic-owner-envelope",
        "BOCA_OWNER_CAPABILITY_SHA256": CAPABILITY_SHA,
        "BOCA_TELEGRAM_ENVELOPE": "synthetic-telegram-envelope",
        "BOCA_TELEGRAM_EXPECTED_BOT_ID": "12345",
        "BOCA_TELEGRAM_EXPECTED_CHAT_HMAC": "e" * 64,
        "BOCA_BROWSER_IMAGE_REF": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
        + "f" * 64,
        "BOCA_OPERATION": "telegram-test"
        if "BOCA_TELEGRAM_ENVELOPE" in lines[index]
        else "owner-prepare",
        "GITHUB_RUN_ID": "123456",
    }
    script = (
        'phase=browser-telegram-start\nexpected_bot=12345\nexpected_chat="' + "e" * 64 + '"\n'
        'runtime_attempt=123456\nsender_args=(--telegram-attempt-id "$GITHUB_RUN_ID")\n'
        'browser_args=(--browser-image "$BOCA_BROWSER_IMAGE_REF" --browser-overlay-sha "'
        + COMPOSE_SHA
        + '" '
        '--browser-seccomp-sha "'
        + COMPOSE_SHA
        + '" --browser-attempt-id existing)\n'
        + lines[index]
        + '\nprintf "%s" "$remote_command"\n'
    )
    if not optional_flags:
        script = script.replace(lines[index], "sender_args=()\nbrowser_args=()\n" + lines[index])
    transport = subprocess.run(  # noqa: S603 - only builds argv from reviewed workflow; no SSH
        ["/bin/bash", "-eu", "-c", script],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert transport.stderr == ""
    argv = shlex.split(transport.stdout)
    assert argv[:2] == ["python3", "-"]
    phase = Mock()
    monkeypatch.setattr(host, "phase", phase)
    monkeypatch.setattr(host.sys, "argv", ["host_first_deploy.py", *argv[2:]])
    assert host.main() == 0
    phase.assert_called_once()
    assert phase.call_args.args[5] == SUBJECT
    assert phase.call_args.args[1:4] == (IMAGE, SHA, COMPOSE_SHA)
    options = {
        "--browser-image": "browser_image",
        "--browser-overlay-sha": "browser_overlay_sha",
        "--browser-seccomp-sha": "browser_seccomp_sha",
        "--browser-attempt-id": "browser_attempt_id",
        "--telegram-attempt-id": "telegram_attempt_id",
    }
    separator = argv.index("--")
    operands = argv[separator + 1 :]
    assert phase.call_args.args == tuple(operands + [""] * (11 - len(operands)))
    for option, keyword in options.items():
        expected = argv[argv.index(option) + 1] if option in argv else ""
        assert phase.call_args.kwargs.get(keyword, "") == expected
        if option in argv:
            assert argv.index(option) < separator


def _cleanup_command(
    monkeypatch: pytest.MonkeyPatch, docker: FakeEnrollDocker, command: object
) -> None:
    def inspect(*args: str) -> str:
        raw = docker(*args)
        if args[:2] == ("container", "inspect"):
            record = json.loads(raw)
            record["Config"]["Cmd"] = command
            return json.dumps(record)
        return raw

    monkeypatch.setattr(cleanup, "_run", inspect)


@pytest.mark.parametrize("terminated", [False, True])
@pytest.mark.parametrize("subject", [SUBJECT, "--"])
def test_cleanup_recognizes_exact_legacy_and_terminated_enrollment_commands(
    enroll_case: tuple[FakeEnrollDocker, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    terminated: bool,
    subject: str,
) -> None:
    docker, _, marker = enroll_case
    command = ["python", "-m", "boca_socios.owner_enrollment"]
    command += (["--"] if terminated else []) + [subject, CAPABILITY_SHA, PUBLIC, FINGERPRINT]
    _cleanup_command(monkeypatch, docker, command)
    # Legacy argv may have exited before listening; its identified residue still
    # needs selective cleanup. New running argv must follow the same boundary.
    docker.running = terminated
    result = cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    assert result.removed_container and result.removed_network and result.removed_stage
    assert not marker.exists()
    assert docker.volumes == {cleanup.OWNER_VOLUME}


@pytest.mark.parametrize(
    "change",
    ["flag", "duplicate", "misplaced", "extra", "digest", "module", "non-string", "short"],
)
def test_uncertain_enrollment_argv_preserves_every_resource_before_cleanup(
    enroll_case: tuple[FakeEnrollDocker, Path, Path], monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    docker, _, marker = enroll_case
    command: list[object] = [
        "python",
        "-m",
        "boca_socios.owner_enrollment",
        "--",
        SUBJECT,
        CAPABILITY_SHA,
        PUBLIC,
        FINGERPRINT,
    ]
    if change == "flag":
        command[3] = "--other-option"
    elif change == "duplicate":
        command.insert(3, "--")
    elif change == "misplaced":
        command[3], command[4] = command[4], command[3]
    elif change == "extra":
        command.append("unreviewed")
    elif change == "digest":
        command[5] = "0" * 64
    elif change == "module":
        command[2] = "other.module"
    elif change == "non-string":
        command[6] = 123
    else:
        command.pop()
    _cleanup_command(monkeypatch, docker, command)
    with pytest.raises(cleanup.CleanupError):
        cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    assert docker.container and docker.network and docker.image and marker.exists()
    assert docker.volumes == {cleanup.OWNER_VOLUME, cleanup.ENROLL_VOLUME}
    assert not any(
        args[:2]
        in {
            ("container", "stop"),
            ("container", "rm"),
            ("network", "rm"),
            ("volume", "rm"),
            ("image", "rm"),
        }
        for args in docker.commands
    )
