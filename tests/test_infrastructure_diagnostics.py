"""A rejected, read-only host boundary must keep its safe diagnostic reason."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from boca_socios import host_rootless_setup as rootless

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
INITIAL = "Verify inactive prepared daemon before image-free infrastructure preflight"
PREPARED = f"BOCA_INFRA_DAEMON state=PREPARED source_sha={SHA} containers=absent daemon=stopped\n"


def _diagnostic():
    spec = importlib.util.spec_from_file_location(
        "infra_diagnostic", ROOT / "scripts/check_infrastructure_diagnostic.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _error(reason: str = "reviewed_service_configuration_mismatch") -> str:
    return (
        f"BOCA_INFRA_DAEMON state=NO_GO reason={reason} files=preserved_or_partial"
        " enablement=UNVERIFIED application_database=not_accessed\n"
    )


def _step(name: str) -> str:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    return workflow.split("      - name: " + name + "\n", 1)[1].split("      - name:", 1)[0]


def _run_step(
    name: str,
    tmp_path: Path,
    *,
    code: int = 0,
    stdout: str = "",
    stderr: str = "",
    operation: str = "infrastructure-preflight",
    overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    ssh = bindir / "ssh"
    ssh.write_text(
        '#!/bin/sh\ncat >/dev/null\nprintf "%s" "$FIXTURE_STDOUT"\n'
        'printf "%s" "$FIXTURE_STDERR" >&2\nexit "$FIXTURE_RC"\n'
    )
    ssh.chmod(0o700)
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "BOCA_SOURCE_SHA": SHA,
        "BOCA_OPERATION": operation,
        "BOCA_BUDGET": "1.75cpu-1152m-224pids",
        "FIXTURE_RC": str(code),
        "FIXTURE_STDOUT": stdout,
        "FIXTURE_STDERR": stderr,
        **(overrides or {}),
    }
    script = textwrap.dedent(_step(name).split("        run: |\n", 1)[1])
    return subprocess.run(  # noqa: S603 - checked-in Bash with a local fake SSH
        ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )


def _host_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], reason: str
) -> tuple[int, str, str]:
    def deny(_sha: str) -> None:
        raise rootless.SetupError(reason)

    monkeypatch.setattr(rootless, "_infrastructure_stopped", deny)
    monkeypatch.setattr(sys, "argv", ["host_rootless_setup.py", "infrastructure-check", SHA])
    code = rootless.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_real_setup_error_survives_initial_workflow_without_raw_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    reason = "reviewed_service_configuration_mismatch"
    code, stdout, stderr = _host_error(monkeypatch, capsys, reason)
    result = _run_step(INITIAL, tmp_path, code=code, stdout=stdout, stderr=stderr)
    assert result.returncode == 1
    summary = (tmp_path / "summary").read_text()
    assert f"reason={reason}" in summary
    assert "rc=1" in summary and "state=NO_GO" in summary
    assert "files=preserved_or_partial" not in summary + result.stdout + result.stderr


def test_readonly_inspection_cannot_reach_effect_steps() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert "infrastructure-inspect," in workflow.split("      source_sha:", 1)[0]
    assert "inputs.operation == 'infrastructure-inspect'" in _step(INITIAL)
    names = (
        "Recheck current main immediately before temporary infrastructure daemon start",
        "Mark only temporary infrastructure daemon attempt",
        "Start only verified empty prepared daemon for infrastructure observation",
        "Observe infrastructure and evaluate unchanged reserve before release",
        "Always restore verified stopped daemon after infrastructure attempt",
        "Record pre-release infrastructure result only after verified stop",
    )
    for name in names:
        condition = _step(name).split("        if:", 1)[1].splitlines()[0]
        assert "inputs.operation == 'infrastructure-preflight'" in condition
        assert "infrastructure-inspect" not in condition


@pytest.mark.parametrize("operation", ["infrastructure-preflight", "infrastructure-inspect"])
def test_real_prepared_receipt_reaches_workflow_without_starting_anything(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    operation: str,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        rootless, "_existing_daemon_boundary", lambda _sha: (Path("/home/boca-deploy"), "inactive")
    )
    monkeypatch.setattr(rootless, "_preflight_effective_unit", lambda _h: calls.append("unit"))
    monkeypatch.setattr(rootless, "_require_stopped_runtime", lambda: calls.append("runtime"))
    monkeypatch.setattr(rootless, "_preflight_empty_containers", lambda _h: calls.append("empty"))
    for name in ("_command", "_start_stopped_daemon", "_verified_containers", "prepare"):
        monkeypatch.setattr(rootless, name, lambda *_a, **_k: pytest.fail("unexpected effect"))
    monkeypatch.setattr(sys, "argv", ["host_rootless_setup.py", "infrastructure-check", SHA])
    assert rootless.main() == 0
    actual = capsys.readouterr()
    assert calls == ["unit", "runtime", "empty"]
    assert actual.out == PREPARED and actual.err == ""
    result = _run_step(INITIAL, tmp_path, stdout=actual.out, operation=operation)
    assert result.returncode == 0, result.stderr
    summary = (tmp_path / "summary").read_text()
    assert "state=PREPARED" in summary and "start_attempted=no" in summary
    assert "BOCA_INFRA_PREFLIGHT state=PASS" not in summary
    for name in ("boca-infra-check.receipt", "boca-infra-check.error"):
        assert (tmp_path / name).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("code", [2, 42, 124, 125, 137, 153, 255])
@pytest.mark.parametrize("receipt", ["", PREPARED])
def test_transport_unknown_never_becomes_prepared(tmp_path: Path, code: int, receipt: str) -> None:
    result = _run_step(INITIAL, tmp_path, code=code, stdout=receipt)
    assert result.returncode == 1
    summary = (tmp_path / "summary").read_text()
    assert "state=INDETERMINATE" in summary and f"rc={code}" in summary
    assert "state=PREPARED" not in summary and "state=PASS" not in summary
    if code in {124, 137, 255}:
        expected = {124: "timeout", 137: "terminated", 255: "ssh_error"}[code]
        assert f"transport={expected}" in summary


@pytest.mark.parametrize(
    ("code", "stdout", "stderr"),
    [
        (0, "", ""),
        (0, PREPARED, _error()),
        (1, PREPARED, ""),
        (0, "", _error()),
        (1, PREPARED, _error()),
        (1, "", _error("unreviewed_reason")),
        (1, "", _error("user_service_start_failed_exit_1")),
        (1, "", _error("user_service_stop_failed_exit_1")),
        (1, "", _error("user_service_metadata_failed_exit_0")),
        (1, "", _error("user_service_metadata_failed_exit_1000")),
        (1, "", _error() + _error()),
        (1, "", _error().rstrip("\n")),
        (1, "", _error().replace("\n", "\r\n")),
        (1, "", "SECRET_SENTINEL_PRIVATE\n" + _error()),
        (1, "", _error("x\nSECRET_SENTINEL_PRIVATE")),
        (0, PREPARED.replace(SHA, "b" * 40), ""),
        (0, PREPARED.rstrip("\n"), ""),
        (0, PREPARED + "\n", ""),
        (0, PREPARED + PREPARED, ""),
        (0, PREPARED.replace("\n", "\r\n"), ""),
        (0, "\x1b[32m" + PREPARED, ""),
        (0, PREPARED, "SECRET_SENTINEL_PRIVATE"),
        (0, "x" * 1024, ""),
        (0, "x" * 1025, ""),
        (1, "", "x" * 1024),
        (1, "", "x" * 1025),
    ],
)
def test_noncanonical_or_mixed_streams_fail_without_disclosure(
    tmp_path: Path, code: int, stdout: str, stderr: str
) -> None:
    result = _run_step(INITIAL, tmp_path, code=code, stdout=stdout, stderr=stderr)
    assert result.returncode == 1
    summary = (tmp_path / "summary").read_text()
    assert "state=INDETERMINATE" in summary
    assert "SECRET_SENTINEL_PRIVATE" not in summary + result.stdout + result.stderr
    assert "files=preserved_or_partial" not in summary + result.stdout + result.stderr


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_ssh_capture_is_bounded_before_parser_reads_it(tmp_path: Path, stream: str) -> None:
    result = _run_step(INITIAL, tmp_path, **{stream: "PRIVATE_SENTINEL" * 1000})
    assert result.returncode == 1
    summary = (tmp_path / "summary").read_text()
    assert "state=INDETERMINATE" in summary
    assert "PRIVATE_SENTINEL" not in summary + result.stdout + result.stderr
    for name in ("boca-infra-check.receipt", "boca-infra-check.error"):
        assert (tmp_path / name).stat().st_size <= 4096


@pytest.mark.parametrize(
    "reason",
    [
        "effective_preflight_command_changed",
        "existing_container_metadata_preserved_no_preflight",
        "metadata_or_io_unavailable",
        "user_service_metadata_failed_timeout",
        "user_service_metadata_failed_unavailable",
        "user_service_metadata_failed_exit_7",
        "user_service_metadata_failed_exit_-15",
    ],
)
def test_real_controlled_rejections_preserve_reason_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    reason: str,
) -> None:
    code, stdout, stderr = _host_error(monkeypatch, capsys, reason)
    result = _run_step(INITIAL, tmp_path, code=code, stdout=stdout, stderr=stderr)
    assert result.returncode == 1
    summary = (tmp_path / "summary").read_text()
    assert f"transport=confirmed reason={reason}" in summary and "state=NO_GO" in summary


@pytest.mark.parametrize("kind", ["missing", "fifo", "symlink", "hardlink", "oversized", "nul"])
def test_capture_files_are_untrusted_and_never_echoed(tmp_path: Path, kind: str) -> None:
    output, error = tmp_path / "out", tmp_path / "err"
    output.write_text(PREPARED)
    error.write_bytes(b"")
    if kind == "missing":
        error.unlink()
    elif kind == "fifo":
        error.unlink()
        os.mkfifo(error, 0o600)
    elif kind == "symlink":
        error.unlink()
        error.symlink_to(output)
    elif kind == "hardlink":
        os.link(error, tmp_path / "another")
    elif kind == "oversized":
        error.write_bytes(b"PRIVATE_SENTINEL" * 1000)
    else:
        output.write_bytes(PREPARED.encode() + b"\x00PRIVATE_SENTINEL")
    result = subprocess.run(  # noqa: S603 - local fixed parser, never host access
        [
            sys.executable,
            str(ROOT / "scripts/check_infrastructure_diagnostic.py"),
            SHA,
            "0",
            str(output),
            str(error),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=2,
    )
    assert result.returncode == 1 and "state=INDETERMINATE" in result.stdout
    assert "PRIVATE_SENTINEL" not in result.stdout + result.stderr
    assert error.exists() or kind == "missing"


@pytest.mark.parametrize("budget", ["1.5cpu-1024m-192pids", "1.75cpu-1152m-224pids"])
def test_inspection_gate_needs_readonly_authority_and_no_private_coordinates(
    tmp_path: Path, budget: str
) -> None:
    env = {
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": SHA,
        "BOCA_SERVICE": "controller",
        "BOCA_HOST_READONLY_ENV_READY": "ready",
        "BOCA_BUDGET": budget,
    }
    name = "Require verified protected environment and matching main commit"
    result = _run_step(name, tmp_path, operation="infrastructure-inspect", overrides=env)
    assert result.returncode == 0
    for key, value in {
        "BOCA_HOST_READONLY_ENV_READY": "",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_SHA": "b" * 40,
        "BOCA_SERVICE": "browser-worker",
        "BOCA_BUDGET": "0.5cpu-256m-64pids",
        "BOCA_IMAGE_REF": "unexpected",
        "BOCA_BROWSER_IMAGE_REF": "unexpected",
        "BOCA_RELEASE_RUN_ID": "123",
        "BOCA_SITE_ENVELOPE": "unexpected",
        "BOCA_OWNER_ENVELOPE": "unexpected",
        "BOCA_TELEGRAM_ENVELOPE": "unexpected",
        "BOCA_OWNER_CAPABILITY_SHA256": "b" * 64,
        "BOCA_FAILED_TELEGRAM_RUN_ID": "123",
    }.items():
        result = _run_step(
            name, tmp_path, operation="infrastructure-inspect", overrides={**env, key: value}
        )
        assert result.returncode != 0, key


@pytest.mark.parametrize("code", [-1, 256, 999, False, True, 0.0])
def test_noncanonical_return_codes_cannot_prove_success(code: object) -> None:
    result, receipt = _diagnostic().classify(SHA, code, PREPARED.encode(), b"")
    assert result == 1 and "state=INDETERMINATE" in receipt and "rc=UNKNOWN" in receipt


def test_parser_withholds_invalid_inputs_and_unexpected_bytes(tmp_path: Path) -> None:
    diagnostic = _diagnostic()
    for stdout, stderr in (
        (PREPARED.encode() + b"\x00PRIVATE_SENTINEL", b""),
        (PREPARED.encode(), b"\xffPRIVATE_SENTINEL"),
        (b"", _error().encode() + b"\x00PRIVATE_SENTINEL"),
    ):
        code, receipt = diagnostic.classify(SHA, 0 if stdout else 1, stdout, stderr)
        assert code == 1 and "PRIVATE_SENTINEL" not in receipt
    result = subprocess.run(  # noqa: S603 - fixed local parser with intentionally invalid input
        [
            sys.executable,
            str(ROOT / "scripts/check_infrastructure_diagnostic.py"),
            "PRIVATE_SENTINEL",
            "0",
            str(tmp_path / "out"),
            str(tmp_path / "err"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=2,
    )
    assert result.returncode == 2 and "PRIVATE_SENTINEL" not in result.stdout + result.stderr


def test_inspection_transport_is_one_bounded_readonly_check() -> None:
    initial = _step(INITIAL)
    assert initial.count("timeout --signal=TERM --kill-after=5s 60s ssh ") == 1
    assert "umask 077" in initial and "ulimit -f 4 || exit 125" in initial
    assert "python3 - infrastructure-check" in initial
    assert "infrastructure-start" not in initial and "infrastructure-stop" not in initial
    assert "docker " not in initial and "GITHUB_OUTPUT" not in initial
    record = _step("Record read-only infrastructure inspection without daemon effects")
    assert "inputs.operation == 'infrastructure-inspect'" in record and "always()" not in record
    assert "capacity=not_evaluated" in record and "BOCA_INFRA_PREFLIGHT" not in record
    assert "application=not_started" in record and "application=not_installed" not in record
