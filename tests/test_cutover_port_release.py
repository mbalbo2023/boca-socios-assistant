"""Exclusive host-loopback port proof during a verified candidate rollback."""

import errno
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from boca_socios import host_first_deploy as host


def probe(port, *, on_wait=None):
    """Map only Boca's fixed target to an ephemeral Linux loopback fixture."""
    waits = []
    now = 0.0

    class OnlyBind(socket.socket):
        def bind(self, address):
            assert address == ("127.0.0.1", 8443)
            return super().bind(("127.0.0.1", port))

        def listen(self, *args):
            pytest.fail("the host proof must never listen")

        def accept(self, *args):
            pytest.fail("the host proof must never accept a connection")

        def connect(self, *args):
            pytest.fail("the host proof must never connect")

    def advance(delay):
        nonlocal now
        waits.append(delay)
        now += delay
        if on_wait:
            on_wait()

    api = SimpleNamespace(
        AF_INET=socket.AF_INET,
        SOCK_STREAM=socket.SOCK_STREAM,
        SOL_SOCKET=socket.SOL_SOCKET,
        SO_REUSEADDR=socket.SO_REUSEADDR,
        socket=OnlyBind,
    )
    return waits, (
        patch.object(host, "socket", api),
        patch.object(host, "sleep", advance),
        patch.object(host, "monotonic", lambda: now),
    )


@pytest.mark.parametrize("case", ["loopback-listener", "wildcard-listener", "exclusive-bound"])
def test_existing_occupants_fail_without_wait_or_contact(case):
    with socket.socket() as occupant:
        listen = case.endswith("listener")
        if listen:
            occupant.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if case == "wildcard-listener":
            # A wildcard on the loopback interface only: it cannot receive traffic on any NIC.
            occupant.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"lo\0")
            assert occupant.getsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, 16) == b"lo\0"
        occupant.bind(("0.0.0.0" if case == "wildcard-listener" else "127.0.0.1", 0))  # noqa: S104
        if listen:
            occupant.listen(1)
        waits, (network, clock_sleep, clock_now) = probe(occupant.getsockname()[1])
        with network, clock_sleep, clock_now, pytest.raises(host.PreflightError):
            host._browser_port_free(after_candidate_removal=True)
        assert waits == []


@pytest.mark.parametrize("release,rollback", [(False, False), (False, True), (True, True)])
def test_only_an_exclusive_bind_can_authorize_restore(release, rollback):
    with socket.socket() as held:
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("127.0.0.1", 0))
        waits, (network, clock_sleep, clock_now) = probe(
            held.getsockname()[1], on_wait=held.close if release else None
        )
        with network, clock_sleep, clock_now:
            if release:
                host._browser_port_free(after_candidate_removal=rollback)
            else:
                with pytest.raises(host.PreflightError):
                    host._browser_port_free(after_candidate_removal=rollback)
        if rollback:
            assert 0 < sum(waits) <= 65
            if not release:
                assert sum(waits) == 65
        else:
            assert not waits


def test_real_tcp_time_wait_is_never_taken_as_exclusive_ownership():
    # Linux can self-connect a bound TCP socket. Its FIN leaves a real TIME_WAIT
    # on the disposable port without opening a listener or accepting a connection.
    with socket.socket() as client:
        client.settimeout(2)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        client.bind(("127.0.0.1", 0))
        local = client.getsockname()
        client.connect(local)
        client.shutdown(socket.SHUT_WR)
        assert client.recv(1) == b""
    # Only use the fixture's own address as evidence; production never reads /proc.
    rows = (row.split() for row in Path("/proc/net/tcp").read_text().splitlines()[1:])
    assert any(row[1] == f"0100007F:{local[1]:04X}" and row[3] == "06" for row in rows)
    waits, (network, clock_sleep, clock_now) = probe(local[1])
    with network, clock_sleep, clock_now, pytest.raises(host.PreflightError):
        host._browser_port_free(after_candidate_removal=True)
    assert sum(waits) == 65
    with socket.socket() as still_reusable:
        still_reusable.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        still_reusable.bind(local)
    with socket.socket() as exclusive, pytest.raises(OSError) as occupied:
        exclusive.bind(local)
    assert occupied.value.errno == errno.EADDRINUSE


@pytest.mark.parametrize("known,still_visible", [(False, False), (True, False), (True, True)])
def test_time_wait_grace_requires_confirmation_of_the_known_removed_cid(
    monkeypatch, known, still_visible
):
    candidate, original = "c" * 64, "a" * 64
    calls = []
    names = iter([candidate, None])
    monkeypatch.setattr(host, "_cutover_candidate_name_id", lambda: next(names))
    monkeypatch.setattr(host, "_cutover_candidate_postflight", lambda *_a, **_k: False)

    def docker(*args, **kwargs):
        assert args[0] == "docker"
        if args[1] == "rm":
            assert args[2:] == (candidate,)
            return candidate
        assert args[1:] == ("ps", "-a", "-q", "--no-trunc", "--filter", "id=" + candidate)
        return candidate if still_visible else ""

    monkeypatch.setattr(host, "_run", docker)
    monkeypatch.setattr(host, "_browser_port_free", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(host, "_cutover_restore_original", lambda *_a: calls.append("restore"))

    def compensate():
        host._cutover_compensate_candidate(
            original,
            "legacy",
            "old",
            "target",
            "new",
            "123",
            "origin",
            "owner",
            "hash",
            expected_candidate=candidate if known else None,
        )

    if still_visible:
        with pytest.raises(host.PreflightError, match="CID remained"):
            compensate()
        assert calls == []
    else:
        compensate()
        assert calls == (
            [{"after_candidate_removal": True}, "restore"] if known else [{}, "restore"]
        )
