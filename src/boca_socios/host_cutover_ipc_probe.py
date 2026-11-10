"""One controller-side AF_UNIX connection for the protected Cutover acceptance."""

from __future__ import annotations

import os
import re
import socket
import struct
import sys
from time import monotonic

_VERIFIED = "BOCA_IPC_TRANSPORT status=PEER_VERIFIED"
_PEERCRED = struct.Struct("3i")


def check_local_peer() -> None:
    """Verify a stable worker-owned listener without sending or reading a frame."""
    from .browser import ipc_protocol

    if os.geteuid() != ipc_protocol.CONTROLLER_UID or os.getegid() != ipc_protocol.CONTROLLER_UID:
        raise RuntimeError("IPC controller identity unverified")
    deadline = monotonic() + 2
    path = ipc_protocol.SOCKET_PATH
    before = ipc_protocol.socket_identity(path, uid=ipc_protocol.WORKER_UID)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError
        endpoint.settimeout(remaining)
        endpoint.connect(str(path))
        credentials = endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED.size)
        pid, uid, gid = _PEERCRED.unpack(credentials)
        # Sibling PID namespaces can correctly hide the peer PID (ADR0101).
        if pid < 0 or uid != ipc_protocol.WORKER_UID or gid != ipc_protocol.WORKER_UID:
            raise RuntimeError("IPC peer identity unverified")
        if ipc_protocol.socket_identity(path, uid=ipc_protocol.WORKER_UID) != before:
            raise RuntimeError("IPC socket identity changed")
        if monotonic() >= deadline:
            raise TimeoutError


def verify_controller_peer(candidate_id: str) -> None:
    """Run the fixed, noninteractive probe in the already attested controller CID."""
    from . import host_first_deploy as host

    if type(candidate_id) is not str or not re.fullmatch(r"[0-9a-f]{64}", candidate_id):
        raise host.PreflightError("Cutover IPC controller ID unverified")
    try:
        receipt = host._run(
            "docker",
            "exec",
            "--user",
            "10001:10001",
            candidate_id,
            "/app/.venv/bin/python",
            "-I",
            "-B",
            "-m",
            "boca_socios.host_cutover_ipc_probe",
            timeout=5,
        )
    except host.PreflightError:
        raise host.PreflightError("Cutover IPC peer unverified") from None
    if receipt != _VERIFIED:
        raise host.PreflightError("Cutover IPC peer unverified")


if __name__ == "__main__":
    try:
        check_local_peer()
    except (OSError, RuntimeError, ValueError, struct.error, AttributeError, ImportError):
        sys.exit(1)
    print(_VERIFIED)
