"""Only a canonical correlation ID may cross the on-demand Unix socket."""

import socket
from pathlib import Path
from runpy import run_path
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


def test_hosted_linux_ci_invokes_the_mandatory_named_wake_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script = "scripts/check_engine_socket_linux.py"
    assert f"run: uv run python {script}" in (root / ".github/workflows/ci.yml").read_text()
    lab = run_path(str(root / script))
    assert "check_bot_control_socket" in lab

    class Marker(Exception):
        """Reached the named-socket gate before running any other checks."""

    required = Mock(side_effect=Marker)
    monkeypatch.setitem(lab["main"].__globals__, "check_bot_control_socket", required)
    with pytest.raises(Marker):
        lab["main"]()
    required.assert_called_once()


@pytest.mark.parametrize(
    "operation",
    [
        "bad",
        "DC33398E-F923-4E85-95BF-A3F4C58C520F",
        "00000000-0000-0000-0000-000000000000",
        "dc33398e-f923-4e85-95bf-a3f4c58c520f\n",
    ],
)
def test_invalid_uuid_never_connects(operation: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object) -> None:
        pytest.fail("an invalid wake attempted a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    with pytest.raises(ValueError):
        bot_control.wake_bot_control(operation)
