"""Only a canonical correlation ID may cross the on-demand Unix socket."""

import os
import socket
from pathlib import Path
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from boca_socios.panel import bot_control


def test_socket_delivers_one_bounded_ascii_frame_without_peer_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = str(uuid4())
    left, right = socket.socketpair()
    with left, right:
        right.settimeout(0.2)
        client = MagicMock(wraps=left)
        client.__enter__.return_value = client
        client.__exit__.side_effect = lambda *_: left.close()
        client.connect = Mock()
        factory = Mock(return_value=client)
        monkeypatch.setattr(socket, "socket", factory)
        bot_control.wake_bot_control(operation)
        assert right.recv(128) == operation.encode("ascii") + b"\n"
        assert right.recv(1) == b""
        factory.assert_called_once_with(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect.assert_called_once_with("/run/boca-bot-control/control.sock")
        assert 0 < client.settimeout.call_args.args[0] <= 1
        client.recv.assert_not_called()


def test_real_named_socket_uses_one_connection_and_closes_after_delivery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert bot_control.CONTROL_SOCKET == "/run/boca-bot-control/control.sock"
    operation = str(uuid4())
    try:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except PermissionError:
        if os.getenv("GITHUB_ACTIONS") == "true":
            raise
        pytest.skip("This sandbox denies named Unix sockets; the wire contract uses socketpair.")
    with listener as server:
        monkeypatch.setattr(bot_control, "CONTROL_SOCKET", str(tmp_path / "control.sock"))
        server.bind(bot_control.CONTROL_SOCKET)
        server.listen(1)
        server.settimeout(0.2)
        bot_control.wake_bot_control(operation)
        with server.accept()[0] as connection:
            connection.settimeout(0.2)
            assert connection.recv(128) == operation.encode("ascii") + b"\n"
            assert connection.recv(1) == b""


@pytest.mark.parametrize(
    "operation",
    ["bad", str(uuid4()).upper(), "00000000-0000-0000-0000-000000000000", str(uuid4()) + "\n"],
)
def test_invalid_uuid_never_connects(operation: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object) -> None:
        pytest.fail("an invalid wake attempted a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    with pytest.raises(ValueError):
        bot_control.wake_bot_control(operation)
