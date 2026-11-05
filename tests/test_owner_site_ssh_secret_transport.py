"""Fail-closed guards for protected owner/Site SSH custody (RCA #321).

The workflow is inspected as source.  These tests never connect to SSH, Boca,
the droplet or the configured owner.  Only symbolic names/synthetic fixtures
are used; no actual envelope, subject, key or credential is read.
"""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

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


def test_all_sensitive_owner_site_ssh_commands_are_secret_free() -> None:
    """Shell escaping alone must not transfer bearer/owner fields via argv."""
    steps = _steps()
    sensitive_steps = _ssh_step_names(steps)
    assert len(sensitive_steps) >= 15  # Detect removal/bypass of this inventory.
    assert set(_ENROLLMENT_STEPS) <= set(sensitive_steps)

    unsafe: list[str] = []
    for name in sensitive_steps:
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
        assert not re.search(r"<\s*src/boca_socios/host_first_deploy[.]py", source), name


def test_sensitive_enrollment_ssh_process_drops_runner_secrets() -> None:
    """SSH must not inherit GitHub input/secret values through /proc/environ."""
    steps = _steps()
    for name in _ENROLLMENT_STEPS:
        source = steps[name]
        ssh_lines = [line for line in source.splitlines() if re.search(r"\bssh\s+-F\b", line)]
        assert len(ssh_lines) == 1, name
        invocation = ssh_lines[0]
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
