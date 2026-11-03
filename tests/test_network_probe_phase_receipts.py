"""RCA #275: fixed, privacy-safe failure phases for the protected probe."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_first_deploy as host


def _empty_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {"network": False, "inspection_count": 0, "removed": False}
    monkeypatch.setattr(host, "ROOT", tmp_path)
    monkeypatch.setattr(host, "_safe_dir", lambda _path: True)
    monkeypatch.setattr(host, "_site_daemon_empty", lambda: None)
    monkeypatch.setattr(host, "collect_snapshot", lambda: object())
    monkeypatch.setattr(host, "validate_site_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda _s: None)

    def names(kind: str, *_args: str) -> set[str]:
        return (
            {host.OWNER_VOLUME}
            if kind == "volume"
            else ({host.ENROLL_NETWORK} if state["network"] else set())
        )

    def run(*args: str, **_kw: object) -> str:
        if args[:3] == ("docker", "network", "create"):
            state["network"] = True
            return "a" * 64
        if args == ("docker", "network", "rm", host.ENROLL_NETWORK):
            state["network"] = False
            state["removed"] = True
            return host.ENROLL_NETWORK
        raise AssertionError(f"unexpected command {args[0:3]}")

    def inspect(_container: str, *, icc_true: bool = False) -> None:
        assert icc_true is True
        state["inspection_count"] += 1

    monkeypatch.setattr(host, "_names", names)
    monkeypatch.setattr(host, "_run", run)
    monkeypatch.setattr(host, "_owner_enroll_network", inspect)
    return state


@pytest.mark.parametrize(
    ("phase", "method"),
    [
        ("preflight_boundary", "_safe_dir"),
        ("preflight_namespace", "_site_daemon_empty"),
        ("preflight_owner_volume", "_validate_owner_volume"),
        ("preflight_storage", "_validate_storage_capacity"),
    ],
)
def test_probe_preflights_emit_only_fixed_failure_phase(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    phase: str,
    method: str,
) -> None:
    _empty_probe(monkeypatch, tmp_path)

    if method == "_safe_dir":
        monkeypatch.setattr(host, method, lambda _path: False)
    else:

        def denied(*_args: object) -> None:
            raise host.PreflightError("PRIVATE_HOST_DETAILS_MUST_NOT_LEAK")

        monkeypatch.setattr(host, method, denied)

    with pytest.raises(host.PreflightError):
        host._network_probe(icc_true=True)
    output = capsys.readouterr()
    assert output.out == (f"BOCA_NETWORK_PROBE result=NO_GO reason={phase} cleanup=INDETERMINATE\n")
    assert "PRIVATE_HOST_DETAILS_MUST_NOT_LEAK" not in output.out + output.err


def test_probe_network_inspection_has_fixed_reason_and_cleans_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    state = _empty_probe(monkeypatch, tmp_path)

    def inspect_once(_container: str, *, icc_true: bool = False) -> None:
        assert icc_true
        state["inspection_count"] += 1
        if state["inspection_count"] == 1:
            raise host.PreflightError("PRIVATE_INSPECTION_PAYLOAD")

    monkeypatch.setattr(host, "_owner_enroll_network", inspect_once)
    with pytest.raises(host.PreflightError, match="Boca network probe NO_GO"):
        host._network_probe(icc_true=True)
    assert state["removed"] is True
    output = capsys.readouterr()
    assert output.out == "BOCA_NETWORK_PROBE result=NO_GO reason=network_inspect cleanup=VERIFIED\n"
    assert "PRIVATE_INSPECTION_PAYLOAD" not in output.out + output.err


def test_probe_network_create_without_classifiable_docker_stderr_has_phase(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _empty_probe(monkeypatch, tmp_path)

    def failed_create(*_args: str, **_kwargs: object) -> str:
        raise host.PreflightError("UNTRUSTED_NETWORK_PAYLOAD")

    monkeypatch.setattr(host, "_run", failed_create)
    with pytest.raises(host.PreflightError, match="Boca network probe NO_GO"):
        host._network_probe(icc_true=True)
    output = capsys.readouterr()
    assert output.out == "BOCA_NETWORK_PROBE result=NO_GO reason=network_create cleanup=VERIFIED\n"
    assert "UNTRUSTED_NETWORK_PAYLOAD" not in output.out + output.err


def test_probe_cleanup_failure_can_never_claim_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    state = _empty_probe(monkeypatch, tmp_path)

    def inspect(_container: str, *, icc_true: bool = False) -> None:
        assert icc_true
        state["inspection_count"] += 1
        if state["inspection_count"] == 2:
            raise host.PreflightError("PRIVATE_CLEANUP_PAYLOAD")

    monkeypatch.setattr(host, "_owner_enroll_network", inspect)
    with pytest.raises(host.PreflightError, match="Boca network probe NO_GO"):
        host._network_probe(icc_true=True)
    assert state["network"] is True  # uncertain object is deliberately preserved
    output = capsys.readouterr()
    assert output.out == "BOCA_NETWORK_PROBE result=NO_GO reason=cleanup cleanup=INDETERMINATE\n"
    assert "PRIVATE_CLEANUP_PAYLOAD" not in output.out + output.err


def test_workflow_distinguishes_invalid_receipt_and_ssh_failures_without_new_dispatch() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text(encoding="utf-8")
    for reason in (
        "preflight_boundary",
        "preflight_namespace",
        "preflight_owner_volume",
        "preflight_storage",
        "network_create",
        "network_inspect",
        "cleanup",
        "ssh_timeout",
        "ssh_terminated",
        "ssh_rc_unexpected",
        "receipt_invalid",
    ):
        assert reason in workflow
    assert "if: startsWith(inputs.operation, 'network-probe')" in workflow
    assert "if: always() && startsWith(inputs.operation, 'network-probe')" in workflow
    assert "docker system prune" not in workflow
    assert "--network=host" not in workflow


@pytest.mark.parametrize(
    ("remote_status", "host_receipt", "expected_status", "reason"),
    [
        (124, "BOCA_NETWORK_PROBE result=PASS reason=none cleanup=VERIFIED", 1, "ssh_timeout"),
        (137, "BOCA_NETWORK_PROBE result=PASS reason=none cleanup=VERIFIED", 1, "ssh_terminated"),
        (
            255,
            "BOCA_NETWORK_PROBE result=PASS reason=none cleanup=VERIFIED",
            1,
            "ssh_rc_unexpected",
        ),
        (1, "BOCA_NETWORK_PROBE result=PASS reason=none cleanup=VERIFIED", 1, "receipt_invalid"),
        (
            0,
            "BOCA_NETWORK_PROBE result=NO_GO reason=network_create cleanup=VERIFIED",
            1,
            "receipt_invalid",
        ),
        (
            0,
            "BOCA_NETWORK_PROBE result=PASS reason=network_create cleanup=VERIFIED",
            1,
            "receipt_invalid",
        ),
        (
            0,
            "BOCA_NETWORK_PROBE result=PASS reason=none cleanup=INDETERMINATE",
            1,
            "receipt_invalid",
        ),
        (1, "BOCA_NETWORK_PROBE result=NO_GO reason=none cleanup=VERIFIED", 1, "receipt_invalid"),
        (1, "", 1, "receipt_invalid"),
        (0, "garbled remote output: PRIVATE_DETAILS", 1, "receipt_invalid"),
        (
            1,
            "BOCA_NETWORK_PROBE result=NO_GO reason=network_create cleanup=VERIFIED",
            1,
            "network_create",
        ),
        (0, "BOCA_NETWORK_PROBE result=PASS reason=none cleanup=VERIFIED", 0, "none"),
    ],
)
def test_workflow_receipt_gate_executes_offline_and_rejects_unsupported_statuses(
    tmp_path: Path, remote_status: int, host_receipt: str, expected_status: int, reason: str
) -> None:
    """Execute only the step's local shell with a fake `timeout`, never remote SSH."""
    repository = Path(__file__).resolve().parents[1]
    workflow = (repository / ".github/workflows/boca-first-deploy.yml").read_text()
    snippet = (
        workflow.split(
            "      - name: Boca rootless network probe without app image or published port\n",
            1,
        )[1]
        .split("        run: |\n", 1)[1]
        .split("      - name: Always verify absence of Boca temporary diagnostic network\n", 1)[0]
    )
    script = textwrap.dedent(snippet)
    (tmp_path / "boca-compose.sha").write_text("fixture_sha\n", encoding="utf-8")
    result_file = tmp_path / "summary.txt"
    env = dict(os.environ)
    env.update(
        {
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(result_file),
            "BOCA_OPERATION": "network-probe-icc-true",
            "BOCA_SOURCE_SHA": "fixture_sha",
            "FAKE_PROBE_RC": str(remote_status),
            "FAKE_HOST_OUTPUT": host_receipt,
        }
    )
    fake_timeout = 'timeout() { printf \'%s\\n\' "$FAKE_HOST_OUTPUT"; return "$FAKE_PROBE_RC"; }\n'
    result = subprocess.run(  # noqa: S603 - local offline shell, fake timeout, no SSH process
        ["/bin/bash", "-c", fake_timeout + script],
        cwd=repository,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    summary = result_file.read_text(encoding="utf-8")
    assert result.returncode == expected_status
    assert f"reason={reason}" in summary
    assert "PRIVATE_DETAILS" not in summary + result.stdout + result.stderr
    if remote_status not in (0, 1) or reason == "receipt_invalid":
        assert "result=PASS" not in summary + result.stdout
