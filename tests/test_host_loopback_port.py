"""The protected port probe can only bind Boca's fixed host loopback port."""

from __future__ import annotations

import errno
import socket
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host

SHA = "a" * 40
COMPOSE_SHA = "b" * 64
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64


class ProbeSocket:
    def __init__(self, *, error: int | None = None) -> None:
        self.error = error
        self.addresses: list[tuple[str, int]] = []
        self.closed = False

    def __enter__(self) -> ProbeSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def bind(self, address: tuple[str, int]) -> None:
        self.addresses.append(address)
        if self.error is not None:
            raise OSError(self.error, "sensitive host detail")

    def listen(self, *_args: object) -> None:
        pytest.fail("port probe opened a listener")

    def connect(self, *_args: object) -> None:
        pytest.fail("port probe contacted a service")


def _isolate(monkeypatch: pytest.MonkeyPatch, probe: ProbeSocket) -> None:
    monkeypatch.setattr(host, "_require_dedicated_identity", lambda: 10001)
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: pytest.fail("Docker used"))
    monkeypatch.setattr(host, "_run", lambda *_args, **_kwargs: pytest.fail("subprocess used"))

    def fixed_socket(family: int, kind: int) -> ProbeSocket:
        assert (family, kind) == (socket.AF_INET, socket.SOCK_STREAM)
        return probe

    monkeypatch.setattr(host.socket, "socket", fixed_socket)


def test_fixed_loopback_port_is_free_but_not_reserved(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    probe = ProbeSocket()
    _isolate(monkeypatch, probe)
    host.phase("port-check", "", SHA, COMPOSE_SHA)
    assert probe.addresses == [("127.0.0.1", 8443)]
    assert probe.closed
    assert capsys.readouterr().out == (
        "BOCA_PORT_CHECK state=FREE address=127.0.0.1 port=8443 reserved=no\n"
    )


@pytest.mark.parametrize(("error", "state"), [(errno.EADDRINUSE, "BUSY"), (errno.EACCES, "ERROR")])
def test_busy_or_unavailable_port_fails_closed_without_host_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: int,
    state: str,
) -> None:
    probe = ProbeSocket(error=error)
    _isolate(monkeypatch, probe)
    with pytest.raises(host.PreflightError, match="Boca loopback port unavailable"):
        host.phase("port-check", "", SHA, COMPOSE_SHA)
    assert probe.addresses == [("127.0.0.1", 8443)]
    assert probe.closed
    assert capsys.readouterr().out == (
        f"BOCA_PORT_CHECK state={state} address=127.0.0.1 port=8443 reserved=no\n"
    )


def test_bad_identity_and_coordinates_fail_before_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host.socket, "socket", lambda *_args: pytest.fail("socket opened"))
    monkeypatch.setattr(
        host,
        "_require_dedicated_identity",
        lambda: (_ for _ in ()).throw(host.PreflightError("uid")),
    )
    with pytest.raises(host.PreflightError, match="uid"):
        host.phase("port-check", "", SHA, COMPOSE_SHA)
    for image, sha, extra in ((IMAGE, SHA, ""), ("", "bad", ""), ("", SHA, "untrusted")):
        with pytest.raises(host.PreflightError):
            host.phase("port-check", image, sha, COMPOSE_SHA, extra)


def test_socket_creation_error_is_redacted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(host, "_require_dedicated_identity", lambda: 10001)
    monkeypatch.setattr(
        host.socket,
        "socket",
        lambda *_args: (_ for _ in ()).throw(OSError(errno.EMFILE, "private host path")),
    )
    with pytest.raises(host.PreflightError, match="Boca loopback port unavailable"):
        host.phase("port-check", "", SHA, COMPOSE_SHA)
    assert capsys.readouterr().out == (
        "BOCA_PORT_CHECK state=ERROR address=127.0.0.1 port=8443 reserved=no\n"
    )


def test_workflow_uses_existing_protected_read_only_gate_and_rechecks_before_beta_effects() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    assert "inspect-prerequisites|port-check|preflight" in workflow
    assert "if: inputs.operation == 'port-check'" in workflow
    assert workflow.count("python3 - port-check '' \"$BOCA_SOURCE_SHA\"") == 2
    assert workflow.index("Confirm current main HEAD before host access") < workflow.index(
        "Check only Boca host loopback 8443 without Docker"
    )
    assert (
        workflow.index("Recheck current main immediately before BETA app and key effects")
        < (workflow.index("Recheck Boca loopback 8443 before BETA app and key effects"))
        < workflow.index("Initialize new-only BETA and start isolated controller")
    )
