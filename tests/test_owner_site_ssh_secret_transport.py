"""Fail-closed guards for protected owner/Site SSH custody (RCA #321).

The workflow is inspected as source.  These tests never connect to SSH, Boca,
the droplet or the configured owner.  Only symbolic names/synthetic fixtures
are used; no actual envelope, subject, key or credential is read.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from importlib.resources import files
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from boca_socios import owner_site_ssh_transport as transport
from boca_socios.panel import local_status

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"

_ENROLLMENT_STEPS = (
    "Prepare, install or verify only Boca owner-volume public passkey custody",
    "Start disposable owner enrollment only on Boca loopback 8443",
    "Wait only for one-use Chrome proof to reach offline staging",
    "Finish one-use Chrome enrollment with offline owner custody",
    "Prepare, install or verify only Boca Site owner-volume custody",
)

_SENSITIVE_RUNNER_NAMES = (
    "BOCA_OWNER_ENVELOPE",
    "BOCA_SITE_ENVELOPE",
    "BOCA_BETA_OWNER_SUBJECT",
    "BOCA_BETA_PANEL_ORIGIN",
)


def _steps() -> dict[str, str]:
    """Split only top-level job steps, leaving Bash bodies intact."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    chunks = re.split(r"(?=^      - name: )", workflow, flags=re.MULTILINE)
    result: dict[str, str] = {}
    for chunk in chunks:
        match = re.match(r"^      - name: (.+)$", chunk, flags=re.MULTILINE)
        if match is not None:
            name = match.group(1).strip()
            assert name not in result, f"duplicate protected workflow step: {name}"
            result[name] = chunk
    return result


def _ssh_step_names(steps: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        name
        for name, source in steps.items()
        if "boca-target" in source
        and any(sensitive_name in source for sensitive_name in _SENSITIVE_RUNNER_NAMES)
    )


def test_owner_site_enrollment_ssh_commands_are_secret_free() -> None:
    """Owner/Site custody P0 is private; other BETA phases remain P2 debt."""
    steps = _steps()
    sensitive_steps = _ssh_step_names(steps)
    assert len(sensitive_steps) >= 15  # Preserve the known wider P2 inventory.
    assert set(_ENROLLMENT_STEPS) <= set(sensitive_steps)

    unsafe: list[str] = []
    for name in _ENROLLMENT_STEPS:
        # The remote command is a process argument on the runner and SSH target.
        assignments = re.findall(r"^\s*remote_command=.*$", steps[name], re.MULTILINE)
        if not assignments:
            unsafe.append(name + ": no auditable remote command")
            continue
        for assignment in assignments:
            if any(
                f"${sensitive_name}" in assignment for sensitive_name in _SENSITIVE_RUNNER_NAMES
            ):
                unsafe.append(name + ": direct sensitive runner variable")
            # Site copies BOCA_SITE_ENVELOPE to a local alias before shlex.join.
            if re.search(r"\$\{?envelope\}?\b", assignment):
                unsafe.append(name + ": indirect site ciphertext alias")
    assert not unsafe, "SSH argv exposure (symbolic names only): " + "; ".join(unsafe)


def test_owner_and_site_enrollment_use_bounded_stdin_transport() -> None:
    """Each critical enrollment path must frame payload, not interpolate it."""
    steps = _steps()
    for name in _ENROLLMENT_STEPS:
        source = steps[name]
        assert "ssh_transport" in source, name
        assert re.search(r"\bemit\b", source), name
        assert re.search(r"\bcommand\b", source), name
        assert "boca-target" in source, name
        # The Python script and fields must share the one framed stdin stream.
        assert "emit < src/boca_socios/host_first_deploy.py" in source, name
        assert not re.search(r"\bssh\b[^\n]*<\s*src/boca_socios/host_first_deploy[.]py", source), (
            name
        )


def test_sensitive_enrollment_ssh_process_drops_runner_secrets() -> None:
    """SSH must not inherit GitHub input/secret values through /proc/environ."""
    steps = _steps()
    for name in _ENROLLMENT_STEPS:
        source = steps[name]
        ssh_lines = [line for line in source.splitlines() if re.search(r"\bssh\s+-F\b", line)]
        assert len(ssh_lines) == 1, name
        # Bash pipe continuation may put `env -u ...` on previous lines.
        invocation = source[source.index("| env ") : source.index(ssh_lines[0]) + len(ssh_lines[0])]
        # An empty environment is valid; otherwise every known secret input
        # must be explicitly unset *for the ssh process*, not just the emitter.
        assert "env -i" in invocation or all(
            f"-u {var}" in invocation for var in _SENSITIVE_RUNNER_NAMES
        ), name


def test_controller_legacy_migration_inventory_excludes_owner_session_0008() -> None:
    """Option B stays in a sibling SQLite, never the installed legacy ledger."""
    resources = files("boca_socios.storage.migrations")
    names = {entry.name for entry in resources.iterdir() if entry.name.endswith(".sql")}
    assert "0008_owner_browser_session.sql" not in names
    assert all(not name.startswith("0008_") for name in names)
    assert 8 not in local_status._MIGRATIONS  # noqa: SLF001 - contract regression

    owner_resources = files("boca_socios.panel.owner_session_sql")
    assert owner_resources.joinpath("0001_owner_browser_session.sql").is_file()


_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
_SHA = "b" * 40
_COMPOSE_SHA = "c" * 64
_OWNER_ENVELOPE = "O" * 200  # Synthetic only, not an actual encrypted envelope.
_SITE_ENVELOPE = "S" * 200


def _synthetic_env(phase: str) -> dict[str, str]:
    operation = "owner-enroll" if phase in transport.ENROLL_PHASES else phase
    return {
        "BOCA_OPERATION": operation,
        "BOCA_OWNER_SITE_TRANSPORT_PHASE": phase,
        "BOCA_IMAGE_REF": _IMAGE,
        "BOCA_SOURCE_SHA": _SHA,
        "BOCA_OWNER_SITE_COMPOSE_SHA": _COMPOSE_SHA,
        "BOCA_BETA_PANEL_ORIGIN": "http://localhost:8443",
        "BOCA_BETA_OWNER_SUBJECT": "-synthetic-owner",
        "BOCA_OWNER_ENVELOPE": _OWNER_ENVELOPE if phase == "owner-install" else "",
        "BOCA_SITE_ENVELOPE": _SITE_ENVELOPE if phase == "site-install" else "",
        "BOCA_OWNER_CAPABILITY_SHA256": "d" * 64,
    }


@pytest.mark.parametrize(
    "phase",
    sorted(transport.OWNER_PHASES | transport.ENROLL_PHASES | transport.SITE_PHASES),
)
def test_frame_delivers_exact_owner_site_cli_operands_without_os_argv(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    """Local Python child receives reconstructed args, but its OS argv is static."""
    env = _synthetic_env(phase)
    raw = transport.build_frame(b"import json,sys\nprint(json.dumps(sys.argv[1:]))\n", env)
    command = shlex.split(transport.remote_command())
    assert command[:2] == ["python3", "-c"]
    assert all(
        value not in transport.remote_command() for value in (_OWNER_ENVELOPE, _SITE_ENVELOPE)
    )
    assert env["BOCA_BETA_OWNER_SUBJECT"] not in transport.remote_command()
    child = subprocess.run(  # noqa: S603 - local Python only, inert synthetic script
        command,
        input=raw,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        timeout=5,
        check=True,
    )
    assert child.stderr == b""
    assert json.loads(child.stdout) == transport.phase_arguments(env)

    # Exercise the unchanged host parser with an inert phase mock.  No Docker.
    called: list[tuple[object, ...]] = []
    monkeypatch.setattr(host, "phase", lambda *args, **_kwargs: called.append(args))
    monkeypatch.setattr(host.sys, "argv", ["host_first_deploy.py", *transport.phase_arguments(env)])
    assert host.main() == 0
    assert len(called) == 1 and called[0][0] == phase
    assert called[0][1:4] == (_IMAGE, _SHA, _COMPOSE_SHA)


@pytest.mark.parametrize("failure", ["truncated", "corrupted", "unknown-phase"])
def test_bounded_owner_site_frame_fails_closed_without_echo(failure: str) -> None:
    """Malformed stdin never runs the payload or prints sensitive coordinates."""
    env = _synthetic_env("owner-install")
    frame = transport.build_frame(b"print('UNEXPECTED_EXECUTION')\n", env)
    if failure == "truncated":
        frame = frame[:-1]
    elif failure == "corrupted":
        frame = frame[:-1] + (b"!" if frame[-1:] != b"!" else b"?")
    else:
        raw = json.loads(frame[len(transport.MAGIC) + 4 :])
        raw["argv"][1] = "unsupported-phase"
        encoded = json.dumps(raw).encode()
        frame = transport.MAGIC + len(encoded).to_bytes(4, "big") + encoded
    child = subprocess.run(  # noqa: S603 - local Python only, no host/network
        shlex.split(transport.remote_command()),
        input=frame,
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert child.returncode == 2 and child.stdout == b""
    assert child.stderr == b"BOCA_NO_GO: owner_site_stdin_frame_invalid\n"
    assert _OWNER_ENVELOPE.encode() not in child.stderr


@pytest.mark.parametrize("phase", ["site-install", "owner-install", "owner-enroll-start"])
def test_owner_site_transport_rejects_mismatched_phase_or_missing_bearer(phase: str) -> None:
    env = _synthetic_env(phase)
    env["BOCA_OPERATION"] = "site-install" if phase != "site-install" else "owner-install"
    with pytest.raises(transport.OwnerSiteTransportError):
        transport.phase_arguments(env)
