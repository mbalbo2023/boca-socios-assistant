"""Controller transport proof using a disposable local AF_UNIX listener."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from boca_socios.browser import ipc_protocol


def test_controller_probe_connects_once_and_sends_zero_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from boca_socios import host_cutover_ipc_probe as probe

    endpoint = tmp_path / "synthetic.sock"
    tmp_path.chmod(0o711)
    monkeypatch.setattr(ipc_protocol, "SOCKET_PATH", endpoint)
    monkeypatch.setattr(ipc_protocol, "CONTROLLER_UID", os.geteuid())
    monkeypatch.setattr(ipc_protocol, "WORKER_UID", os.geteuid())
    # A real socketpair is available even in the executor that denies socket(AF_UNIX).
    # It exercises SO_PEERCRED, stream closure and zero traffic at the receiving end.
    client, peer = socket.socketpair()
    with client, peer, monkeypatch.context() as local:
        destinations = []

        class PreconnectedSocket:
            def __enter__(self) -> PreconnectedSocket:
                return self

            def __exit__(self, *_args: object) -> None:
                client.close()

            settimeout = staticmethod(client.settimeout)
            getsockopt = staticmethod(client.getsockopt)

            def connect(self, name: str) -> None:
                destinations.append(name)

        local.setattr(socket, "socket", lambda *_args: PreconnectedSocket())
        local.setattr(ipc_protocol, "socket_identity", lambda *_a, **_k: (1, 2))
        probe.check_local_peer()
        assert destinations == [str(endpoint)]
        peer.settimeout(0.5)
        assert peer.recv(1) == b""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    # The hosted Linux gate must additionally bind and connect the named inode.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(endpoint))
        endpoint.chmod(0o622)
        server.listen(1)
        server.settimeout(0.5)
        probe.check_local_peer()
        peer, _name = server.accept()
        with peer:
            peer.settimeout(0.5)
            assert peer.recv(1) == b""
        server.setblocking(False)
        with pytest.raises(BlockingIOError):
            server.accept()


@pytest.mark.parametrize("changed", ["peer", "inode", "local_user", "zero_pid", "deadline"])
def test_kernel_peer_and_deadline_contract(monkeypatch: pytest.MonkeyPatch, changed: str) -> None:
    from boca_socios import host_cutover_ipc_probe as probe

    calls = []
    identities = iter([(1, 2), (1, 3 if changed == "inode" else 2)])
    monkeypatch.setattr(ipc_protocol, "socket_identity", lambda *a, **kw: next(identities))
    monkeypatch.setattr(os, "geteuid", lambda: 10001 if changed != "local_user" else 0)
    monkeypatch.setattr(os, "getegid", lambda: 10001)
    if changed == "deadline":
        monkeypatch.setattr(probe, "monotonic", iter((0.0, 2.0)).__next__)

    class FakeSocket:
        def __init__(self, family: int, kind: int) -> None:
            assert (family, kind) == (socket.AF_UNIX, socket.SOCK_STREAM)

        def __enter__(self) -> FakeSocket:
            return self

        def __exit__(self, *_args: object) -> None:
            calls.append("close")

        def settimeout(self, seconds: float) -> None:
            assert 0 < seconds <= 2

        def connect(self, name: str) -> None:
            assert name == str(ipc_protocol.SOCKET_PATH)
            calls.append("connect")

        def getsockopt(self, level: int, option: int, length: int) -> bytes:
            import struct

            assert (level, option, length) == (socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            return struct.pack("3i", 0, 10002, 0 if changed == "peer" else 10002)

    monkeypatch.setattr(socket, "socket", FakeSocket)
    if changed == "zero_pid":
        probe.check_local_peer()
    elif changed == "deadline":
        with pytest.raises(TimeoutError):
            probe.check_local_peer()
        assert calls == ["close"]
        return
    else:
        with pytest.raises(RuntimeError):
            probe.check_local_peer()
    assert calls == ([] if changed == "local_user" else ["connect", "close"])


def test_cutover_exec_is_fixed_noninteractive_and_uses_only_the_exact_cid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_cutover_ipc_probe as probe

    cid = "a" * 64
    calls = []

    def run(*argv: str, timeout: float) -> str:
        calls.append((argv, timeout))
        return "BOCA_IPC_TRANSPORT status=PEER_VERIFIED"

    monkeypatch.setattr(host, "_run", run)
    probe.verify_controller_peer(cid)
    assert calls == [
        (
            (
                "docker",
                "exec",
                "--user",
                "10001:10001",
                cid,
                "/app/.venv/bin/python",
                "-I",
                "-B",
                "-m",
                "boca_socios.host_cutover_ipc_probe",
            ),
            5,
        )
    ]
    assert capsys.readouterr().out == ""
    with pytest.raises(host.PreflightError):
        probe.verify_controller_peer(cid[:12])
    assert len(calls) == 1
    monkeypatch.setattr(host, "_run", lambda *_a, **_k: "PRIVATE untrusted output")
    with pytest.raises(host.PreflightError) as caught:
        probe.verify_controller_peer(cid)
    assert "PRIVATE" not in str(caught.value)
