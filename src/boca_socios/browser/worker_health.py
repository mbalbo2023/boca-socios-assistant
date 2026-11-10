"""Verify the running worker's public Linux and AF_UNIX boundary."""

from __future__ import annotations

import os
import socket
from pathlib import Path

from boca_socios.browser.ipc_protocol import (
    SOCKET_PATH,
    WORKER_UID,
    SyntheticIPCError,
    socket_identity,
)

__all__ = [
    "CGROUP",
    "CPU_MILLI_LIMIT",
    "MEMORY_LIMIT_BYTES",
    "PIDS_LIMIT",
    "WORKER_UID",
    "WorkerBoundaryError",
    "check_worker_health",
    "main",
    "validate_worker_boundary",
]

CGROUP = Path("/sys/fs/cgroup")
MEMORY_LIMIT_BYTES = 768 * 1024 * 1024
PIDS_LIMIT = 128
CPU_MILLI_LIMIT = 1000


class WorkerBoundaryError(RuntimeError):
    """The isolated browser boundary or its lifecycle is not proven safe."""


def validate_worker_boundary(
    *,
    root: Path = CGROUP,
    uid: int | None = None,
    gid: int | None = None,
) -> None:
    """Check effective isolated-worker identity and bounded cgroup v2 limits.

    The host deployment gate must separately enforce Docker ``--network none``.
    A cgroup check does not prove network isolation or start a container.
    """
    effective_uid = os.geteuid() if uid is None else uid
    effective_gid = os.getegid() if gid is None else gid
    if effective_uid != WORKER_UID or effective_gid != WORKER_UID:
        raise WorkerBoundaryError("worker_identity_unverified")
    try:
        memory_limit = int((root / "memory.max").read_text(encoding="ascii").strip())
        pid_limit = int((root / "pids.max").read_text(encoding="ascii").strip())
        cpu = (root / "cpu.max").read_text(encoding="ascii").split()
        if len(cpu) != 2:
            raise ValueError("invalid CPU cgroup")
        cpu_quota, cpu_period = map(int, cpu)
    except (OSError, ValueError):
        raise WorkerBoundaryError("worker_limits_unverified") from None
    if (
        not 0 < memory_limit <= MEMORY_LIMIT_BYTES
        or not 0 < pid_limit <= PIDS_LIMIT
        or not 0 < cpu_quota
        or not 0 < cpu_period
        or cpu_quota * 1000 > cpu_period * CPU_MILLI_LIMIT
    ):
        raise WorkerBoundaryError("worker_limits_unverified")


def check_worker_health(*, root: Path = CGROUP) -> None:
    """Check kernel metadata only; connecting to the socket could dispatch work."""
    validate_worker_boundary(root=root)
    interfaces = socket.if_nameindex()
    if len(interfaces) != 1 or interfaces[0][0] < 1 or interfaces[0][1] != "lo":
        raise WorkerBoundaryError("worker_network_unverified")
    socket_identity(SOCKET_PATH)


def main() -> int:
    try:
        check_worker_health()
    except (OSError, WorkerBoundaryError, SyntheticIPCError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
