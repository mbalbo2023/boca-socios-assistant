"""Send a committed Boca bot request ID to its socket-activated host executor."""

import socket

from boca_socios.panel.lifecycle_intents import canonical_operation_id

CONTROL_SOCKET = "/run/boca-bot-control/control.sock"


def wake_bot_control(operation_id: str) -> None:
    """Write one bounded frame. The host records the result separately in SQLite."""
    frame = canonical_operation_id(operation_id).encode("ascii") + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(1.0)
        connection.connect(CONTROL_SOCKET)
        connection.sendall(frame)
