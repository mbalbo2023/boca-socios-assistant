"""Only synthetic bytes on an in-process Unix socket pair."""

from __future__ import annotations

import socket
from itertools import count
from threading import Event, Thread, current_thread

import pytest

from boca_socios import worker_start_capture as capture
from boca_socios.worker_start_capture import CaptureFailure, CaptureResult, attach_output

CID = "1a" * 32
SOCKET = "/synthetic/engine.sock"
UPGRADE = (
    b"HTTP/1.1 101 UPGRADED\r\n"
    b"Content-Type: application/vnd.docker.multiplexed-stream\r\n"
    b"Connection: Upgrade\r\n"
    b"Upgrade: tcp\r\n\r\n"
)


def frame(channel: int, payload: bytes) -> bytes:
    return bytes((channel, 0, 0, 0)) + len(payload).to_bytes(4, "big") + payload


class PairClient(socket.socket):
    """Use a real preconnected AF_UNIX stream, optionally forcing short reads."""

    def __init__(self, fd: int, fragment: int) -> None:
        super().__init__(fileno=fd)
        self.fragment = fragment

    def connect(self, address: object) -> None:
        assert address == SOCKET

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        return super().recv(min(bufsize, self.fragment), flags)


def engine(
    monkeypatch: pytest.MonkeyPatch, fragment: int = 4096
) -> tuple[PairClient, socket.socket]:
    end, peer = socket.socketpair()
    client = PairClient(end.detach(), fragment)
    peer.settimeout(1)

    def open_socket(family: int, kind: int) -> PairClient:
        assert (family, kind) == (socket.AF_UNIX, socket.SOCK_STREAM)
        return client

    monkeypatch.setattr(capture, "socket", open_socket)
    return client, peer


@pytest.mark.parametrize("fragment", [1, 4096])
def test_ack_precedes_start_and_immediate_stderr_remains_separate(
    monkeypatch: pytest.MonkeyPatch, fragment: int
) -> None:
    client, peer = engine(monkeypatch, fragment)
    with peer:
        peer.sendall(UPGRADE + frame(1, b"ValueError: SYNTHETIC\n"))
        with attach_output(SOCKET, CID) as reader:
            request = peer.recv(1024)
            line, *fields = request.split(b"\r\n")
            assert (
                line
                == (
                    f"POST /v1.48/containers/{CID}/attach?stream=1&stdout=1&stderr=1&stdin=0&logs=0 "
                    "HTTP/1.1"
                ).encode()
            )
            assert b"Connection: Upgrade" in fields
            assert b"Upgrade: tcp" in fields
            # The simulated caller starts the exact fixture only after __enter__ returns.
            peer.sendall(frame(2, b"trace line\nModuleNot") + frame(1, b"TypeError: SYNTHETIC\n"))
            peer.sendall(frame(2, b"FoundError: SYNTHETIC\r\n") + frame(1, b"stdout tail"))
            peer.shutdown(socket.SHUT_WR)
            assert reader.finish() is CaptureResult.MODULE_NOT_FOUND_ERROR
            assert reader.finish() is CaptureResult.MODULE_NOT_FOUND_ERROR
        assert client.fileno() == -1
        assert peer.recv(1) == b""


@pytest.mark.parametrize(
    ("stream", "expected"),
    [
        (b"", "EMPTY"),
        (frame(1, b"") + frame(2, b""), "EMPTY"),
        (frame(1, b"PermissionError: SYNTHETIC\n"), "STDOUT_ONLY"),
        (frame(2, b"plain stderr\n") + frame(1, b"RuntimeError\n"), "UNCLASSIFIED"),
        (frame(2, b"PermissionError: SYNTHETIC\n"), "PERMISSION_ERROR"),
        (frame(2, b"RuntimeError"), "RUNTIME_ERROR"),
        (frame(2, b"ImportError\r\n"), "IMPORT_ERROR"),
        (frame(2, b"    raise ValueError: SYNTHETIC\n"), "UNCLASSIFIED"),
        (frame(2, b"UnknownTypeError: SYNTHETIC\n"), "UNCLASSIFIED"),
        (frame(2, b"TypeError: x\nmore output"), "UNCLASSIFIED"),
        (frame(2, b"TypeError: x\n\n"), "UNCLASSIFIED"),
        (frame(2, b"PermissionError: x\n") + frame(3, b"TypeError\n"), "TRANSPORT"),
        (frame(0, b"PermissionError\n"), "TRANSPORT"),
        (b"\x02\x00\x01\x00" + b"\0" * 4, "TRANSPORT"),
        (frame(2, b"PermissionError\n") + b"\x01\0", "TRUNCATED"),
        (frame(2, b"PermissionError\n")[:-1], "TRUNCATED"),
        (b"\x02\0\0\0\xff\xff\xff\xff", "LIMIT"),
        (frame(1, b"s" * 33_000) * 2, "LIMIT"),
        (frame(2, b"") * 1024, "LIMIT"),
    ],
    ids=[
        "empty-eof",
        "empty-frames",
        "stdout-spoof",
        "both-unclassified",
        "permission",
        "no-newline",
        "crlf",
        "indented-source",
        "custom-name",
        "last-line",
        "blank-tail",
        "daemon-system-error",
        "unexpected-stdin",
        "reserved-frame-bits",
        "partial-header",
        "partial-payload",
        "oversized-declaration",
        "total-quota",
        "empty-frame-flood",
    ],
)
def test_stream_returns_only_its_terminal_category(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stream: bytes,
    expected: str,
) -> None:
    client, peer = engine(monkeypatch)
    with peer:
        peer.sendall(UPGRADE)
        with attach_output(SOCKET, CID) as reader:
            if stream:
                peer.sendall(stream)
            peer.shutdown(socket.SHUT_WR)
            assert reader.finish().value == expected
            assert client.fileno() == -1
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (UPGRADE.replace(b"101 UPGRADED", b"200 SYNTHETIC"), "TRANSPORT"),
        (UPGRADE.replace(b"multiplexed-stream", b"raw-stream"), "TRANSPORT"),
        (UPGRADE.replace(b"Connection: Upgrade\r\n", b""), "TRANSPORT"),
        (UPGRADE.replace(b"Upgrade: tcp", b"Upgrade: websocket"), "TRANSPORT"),
        (UPGRADE.replace(b"Upgrade: tcp", b"Upgrade: tcp\r\nUpgrade: tcp"), "TRANSPORT"),
        (b"HTTP/1.1 101 UPGRADED\r\n" + b"x" * 8192, "LIMIT"),
        (UPGRADE[:-2], "TRUNCATED"),
    ],
    ids=["status", "tty", "missing-connection", "wrong-upgrade", "duplicate", "oversize", "eof"],
)
def test_failed_handshake_never_enters_the_callers_start_block(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    response: bytes,
    expected: str,
) -> None:
    client, peer = engine(monkeypatch)
    with peer:
        peer.sendall(response)
        peer.shutdown(socket.SHUT_WR)
        with pytest.raises(CaptureFailure) as failure, attach_output(SOCKET, CID):
            pytest.fail("entered start block without a valid multiplexed upgrade")
        assert failure.value.result.value == expected
        assert str(failure.value) == expected
        assert failure.value.__context__ is None
        assert client.fileno() == -1
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("endpoint", "cid"),
    [
        ("tcp://127.0.0.1:2375", CID),
        ("unix:///var/run/docker.sock", CID),
        ("@abstract", CID),
        ("/invalid\0endpoint", CID),
        (SOCKET, CID[:12]),
        (SOCKET, CID + "\r\nGET /"),
        (SOCKET, CID.upper()),
    ],
)
def test_bad_targets_fail_before_opening_a_socket(
    monkeypatch: pytest.MonkeyPatch, endpoint: str, cid: str
) -> None:
    def forbidden_socket(*args: object) -> None:
        pytest.fail("invalid identity or address reached the socket factory")

    monkeypatch.setattr(capture, "socket", forbidden_socket)
    with pytest.raises(capture.CaptureFailure) as failure, capture.attach_output(endpoint, cid):
        pytest.fail("accepted invalid identity or address")
    assert failure.value.result is capture.CaptureResult.TRANSPORT


def test_handshake_cannot_renew_its_deadline_with_each_short_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, peer = engine(monkeypatch, fragment=1)
    ticks = count()
    monkeypatch.setattr(capture, "monotonic", lambda: next(ticks) / 10)
    with peer:
        peer.sendall(UPGRADE)
        with pytest.raises(capture.CaptureFailure) as failure, capture.attach_output(SOCKET, CID):
            pytest.fail("trickling handshake extended its deadline")
        assert failure.value.result is capture.CaptureResult.TIMEOUT
        assert client.fileno() == -1


def test_capture_deadline_starts_at_upgrade_and_overrides_buffered_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, peer = engine(monkeypatch)
    now = 0.0
    monkeypatch.setattr(capture, "monotonic", lambda: now)
    with peer:
        peer.sendall(UPGRADE)
        with capture.attach_output(SOCKET, CID) as reader:
            now = 120.0
            peer.sendall(frame(2, b"PermissionError\n"))
            peer.shutdown(socket.SHUT_WR)
            assert reader.finish() is capture.CaptureResult.TIMEOUT
            assert client.fileno() == -1


def test_stalled_peer_releases_socket_at_capture_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client, peer = engine(monkeypatch)
    monkeypatch.setattr(capture, "_CAPTURE_SECONDS", 0.05)
    with peer:
        peer.sendall(UPGRADE)
        with capture.attach_output(SOCKET, CID) as reader:
            assert reader.finish() is capture.CaptureResult.TIMEOUT
            assert client.fileno() == -1


@pytest.mark.parametrize("problem", [ConnectionResetError, RuntimeError])
def test_local_error_after_upgrade_is_redacted_and_closes_immediately(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], problem: type[Exception]
) -> None:
    client, peer = engine(monkeypatch)

    receive = client.recv

    def interrupted(count: int, flags: int = 0) -> bytes:
        data = receive(count, flags)
        if not flags and count == 8:
            raise problem("SYNTHETIC_CANARY")
        return data

    with peer:
        monkeypatch.setattr(client, "recv", interrupted)
        peer.sendall(UPGRADE)
        with attach_output(SOCKET, CID) as reader:
            peer.sendall(frame(2, b"RuntimeError\n"))
            assert reader.finish() is CaptureResult.TRANSPORT
            assert client.fileno() == -1
    assert capsys.readouterr() == ("", "")


def test_eof_observed_after_capture_deadline_is_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client, peer = engine(monkeypatch)
    now = 0.0
    monkeypatch.setattr(capture, "monotonic", lambda: now)
    receive = client.recv

    def late_eof(count: int, flags: int = 0) -> bytes:
        nonlocal now
        result = receive(count, flags)
        if not result and not flags:
            now = 120.0
        return result

    monkeypatch.setattr(client, "recv", late_eof)
    with peer:
        peer.sendall(UPGRADE)
        with capture.attach_output(SOCKET, CID) as reader:
            peer.sendall(frame(2, b"RuntimeError\n"))
            peer.shutdown(socket.SHUT_WR)
            assert reader.finish() is capture.CaptureResult.TIMEOUT
            assert client.fileno() == -1


def test_early_context_exit_closes_without_waiting_for_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    client, peer = engine(monkeypatch)
    with peer:
        peer.sendall(UPGRADE)
        with attach_output(SOCKET, CID):
            assert client.fileno() >= 0
            assert b"stdin=0" in peer.recv(1024)
        assert client.fileno() == -1
        assert peer.recv(1) == b""


@pytest.mark.parametrize("problem", [OSError, RuntimeError])
def test_local_transport_exception_is_never_chained_or_printed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], problem: type[Exception]
) -> None:
    def unavailable(*args: object) -> None:
        raise problem("SYNTHETIC_CANARY")

    monkeypatch.setattr(capture, "socket", unavailable)
    with pytest.raises(capture.CaptureFailure) as failure, capture.attach_output(SOCKET, CID):
        pytest.fail("entered start block with unavailable socket")
    assert failure.value.result is capture.CaptureResult.TRANSPORT
    assert failure.value.__context__ is None
    assert str(failure.value) == "TRANSPORT"
    assert capsys.readouterr() == ("", "")


def test_reader_consumes_and_closes_at_quota_during_start_before_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, peer = engine(monkeypatch)
    with peer:
        peer.sendall(UPGRADE)
        with attach_output(SOCKET, CID) as reader:
            assert b"stdin=0" in peer.recv(1024)
            # The caller has started the fixture and is still supervising health.
            # No call to finish() or close() can do the reading on its behalf.
            peer.sendall(b"\x01\0\0\0\xff\xff\xff\xff")
            assert peer.recv(1) == b""
            assert client.fileno() == -1
            assert reader.finish() is CaptureResult.LIMIT


def test_healthy_cancel_wakes_reader_and_never_claims_its_own_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, peer = engine(monkeypatch)
    waiting = Event()
    receive = client.recv

    def observed_read(size: int, flags: int = 0) -> bytes:
        if size == 8 and not flags:
            waiting.set()
        return receive(size, flags)

    monkeypatch.setattr(client, "recv", observed_read)
    with peer:
        peer.sendall(UPGRADE)
        with attach_output(SOCKET, CID) as reader:
            assert waiting.wait(1)
            assert b"stdin=0" in peer.recv(1024)
            assert reader.close() is True
            assert reader.close() is False
            assert reader.finish() is CaptureResult.TRANSPORT
            assert client.fileno() == -1
        assert peer.recv(1) == b""


def test_already_closed_upgrade_or_thread_start_failure_prevents_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for closed_peer in (True, False):
        client, peer = engine(monkeypatch)
        with peer:
            peer.sendall(UPGRADE)
            if closed_peer:
                peer.shutdown(socket.SHUT_WR)
            else:

                def cannot_start(self: object) -> None:
                    raise RuntimeError("SYNTHETIC_CANARY")

                monkeypatch.setattr(capture.Thread, "start", cannot_start)
            with pytest.raises(CaptureFailure) as failure, attach_output(SOCKET, CID):
                pytest.fail("unarmed reader entered the caller start block")
            assert failure.value.result is CaptureResult.TRANSPORT
            assert failure.value.__context__ is None
            assert client.fileno() == -1
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("line", "wanted"),
    [
        (
            b"boca_socios.browser.ipc_protocol.SyntheticIPCError: ipc_path_unverified",
            "IPC_PATH_UNVERIFIED",
        ),
        (
            b"boca_socios.browser.ipc_protocol.SyntheticIPCError: ipc_directory_unverified",
            "IPC_DIRECTORY_UNVERIFIED",
        ),
        (
            b"boca_socios.browser.ipc_protocol.SyntheticIPCError: ipc_socket_unverified",
            "IPC_SOCKET_UNVERIFIED",
        ),
        (
            b"boca_socios.browser.ipc_protocol.SyntheticIPCError: ipc_peer_unverified",
            "IPC_PEER_UNVERIFIED",
        ),
        (
            b"boca_socios.browser.ipc_protocol.SyntheticIPCError: ipc_frame_unverified",
            "IPC_FRAME_UNVERIFIED",
        ),
        (
            b"boca_socios.browser.on_demand.WorkerBoundaryError: worker_identity_unverified",
            "WORKER_IDENTITY_UNVERIFIED",
        ),
        (
            b"boca_socios.browser.on_demand.WorkerBoundaryError: worker_limits_unverified",
            "WORKER_LIMITS_UNVERIFIED",
        ),
        (b"ModuleNotFoundError: No module named 'playwright'", "MISSING_PLAYWRIGHT"),
        (b"ModuleNotFoundError: No module named 'greenlet'", "MISSING_GREENLET"),
        (b"ModuleNotFoundError: No module named 'pyee'", "MISSING_PYEE"),
        (b"ModuleNotFoundError: No module named 'typing_extensions'", "MISSING_TYPING_EXTENSIONS"),
        (b"ModuleNotFoundError: No module named 'boca_socios'", "MISSING_BOCA_PACKAGE"),
        (b"ModuleNotFoundError: No module named 'boca_socios.browser'", "MISSING_BROWSER_PACKAGE"),
        (
            b"ModuleNotFoundError: No module named 'boca_socios.browser.contracts'",
            "MISSING_BROWSER_CONTRACTS",
        ),
        (
            b"ModuleNotFoundError: No module named 'boca_socios.browser.ipc_protocol'",
            "MISSING_IPC_PROTOCOL",
        ),
        (b"ModuleNotFoundError: No module named 'boca_socios.domain'", "MISSING_DOMAIN_PACKAGE"),
        (
            b"ModuleNotFoundError: No module named 'boca_socios.domain.policy'",
            "MISSING_DOMAIN_POLICY",
        ),
        (
            b"/app/.venv/bin/python: No module named boca_socios.browser.ipc_worker",
            "ENTRY_MODULE_MISSING",
        ),
        (
            b"/app/.venv/bin/python: Error while finding module specification for "
            b"'boca_socios.browser.ipc_worker' (ModuleNotFoundError: No module named 'boca_socios')",
            "MISSING_BOCA_PACKAGE",
        ),
        (
            b"/app/.venv/bin/python: Error while finding module specification for "
            b"'boca_socios.browser.ipc_worker' (ModuleNotFoundError: No module named 'boca_socios.browser')",
            "MISSING_BROWSER_PACKAGE",
        ),
        (b"ModuleNotFoundError: No module named 'private.canary'", "MODULE_NOT_FOUND_ERROR"),
        (b"ModuleNotFoundError: No module named 'playwright' PRIVATE", "MODULE_NOT_FOUND_ERROR"),
        (
            b"boca_socios.browser.ipc_protocol.SyntheticIPCError: ipc_directory_unverified!",
            "UNCLASSIFIED",
        ),
        (
            b" boca_socios.browser.ipc_protocol.SyntheticIPCError: ipc_directory_unverified",
            "UNCLASSIFIED",
        ),
        (
            b"boca_socios.browser.ipc_protocol.SyntheticIPCError: ipc_directory_unverified\r",
            "UNCLASSIFIED",
        ),
        (
            b"/app/.venv/bin/python: No module named boca_socios.browser.ipc_worker\x00private",
            "UNCLASSIFIED",
        ),
        (
            b"/app/.venv/bin/python: Error while finding module specification for "
            b"'boca_socios.browser.ipc_worker' (ModuleNotFoundError: No module named 'boca_socios.browser')"
            + b"\r"
            + b"x" * 512,
            "UNCLASSIFIED",
        ),
    ],
)
def test_only_complete_public_final_line_identifies_fixed_detail(
    monkeypatch: pytest.MonkeyPatch, line: bytes, wanted: str
) -> None:
    _, peer = engine(monkeypatch, fragment=3)
    with peer:
        peer.sendall(UPGRADE)
        with attach_output(SOCKET, CID) as reader:
            peer.sendall(
                frame(2, b"prior\n" + line[:25])
                + frame(1, b"stdout")
                + frame(2, line[25:] + b"\r\n")
            )
            peer.shutdown(socket.SHUT_WR)
            assert reader.finish().value == wanted


def test_wire_vocabulary_accepts_only_its_exact_public_values() -> None:
    class Impersonator(str):
        def __eq__(self, other: object) -> bool:
            return True

    assert all(capture.is_capture_result(item.value) for item in CaptureResult)
    assert capture.is_capture_result(CaptureResult.EMPTY)
    for invalid in (
        "private",
        "",
        "IPC_PATH_UNVERIFIED\n",
        None,
        [],
        b"TIMEOUT",
        Impersonator("private"),
    ):
        assert not capture.is_capture_result(invalid)


def test_healthy_cancel_joins_reader_even_if_local_shutdown_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, peer = engine(monkeypatch)
    waiting = Event()
    receivers: list[Thread] = []
    receive = client.recv

    def observe(size: int, flags: int = 0) -> bytes:
        if not flags and size == 8:
            receivers.append(current_thread())
            waiting.set()
        return receive(size, flags)

    def broken_shutdown(how: int) -> None:
        raise OSError("SYNTHETIC_CANARY")

    monkeypatch.setattr(client, "recv", observe)
    monkeypatch.setattr(client, "shutdown", broken_shutdown)
    with peer:
        peer.sendall(UPGRADE)
        with attach_output(SOCKET, CID) as reader:
            assert waiting.wait(1)
            assert reader.close()
            assert receivers and all(not thread.is_alive() for thread in receivers)
            assert client.fileno() == -1
            assert reader.finish() is CaptureResult.TRANSPORT
