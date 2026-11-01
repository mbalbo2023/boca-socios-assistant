"""Fixed, bounded AF_UNIX framing for *synthetic-only* browser commands.

No field accepts a URL, identity, account, cookie, token, or arbitrary text.
Neither side opens an IP socket. The eventual shared Docker volume and exact
user-namespace mapping require a separately approved deployment gate.
"""

from __future__ import annotations

import asyncio
import os
import socket
import stat
import struct
from pathlib import Path

CONTROLLER_UID = 10001
WORKER_UID = 10002
SOCKET_PATH = Path("/run/boca-browser-ipc/synthetic.sock")
DIRECTORY_MODE = 0o711  # owner rwx, clients traverse only; no directory listing
SOCKET_MODE = 0o622  # other users can connect; SO_PEERCRED authorizes UID/GID
MAX_FRAME_BYTES = 64
REQUEST = b"BOCA_SYNTHETIC_V1_RUN"
SUCCESS = b"BOCA_SYNTHETIC_V1_RESERVED_IN_SIMULATOR"
BUSY = b"BOCA_SYNTHETIC_V1_BUSY"
NO_GO = b"BOCA_SYNTHETIC_V1_NO_GO"


class SyntheticIPCError(RuntimeError):
    """Fail-closed local transport or worker, with a fixed nonsecret reason."""


def validate_socket_directory(path: Path, *, uid: int = WORKER_UID) -> None:
    """Reject symlinked, redirected, broad or foreign IPC mount directories."""
    if (
        not path.is_absolute()
        or ".." in path.parts
        or str(path) != os.path.normpath(str(path))
        or len(os.fsencode(path / "synthetic.sock")) >= 104
    ):
        raise SyntheticIPCError("ipc_path_unverified")
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != uid
            or metadata.st_gid != uid
            or stat.S_IMODE(metadata.st_mode) != DIRECTORY_MODE
            or path.resolve(strict=True) != path
        ):
            raise SyntheticIPCError("ipc_directory_unverified")
    except (OSError, RuntimeError):
        raise SyntheticIPCError("ipc_directory_unverified") from None


def socket_identity(path: Path, *, uid: int = WORKER_UID) -> tuple[int, int]:
    """Prove a single named worker-owned socket; never follow a symlink."""
    if path.name != SOCKET_PATH.name:
        raise SyntheticIPCError("ipc_path_unverified")
    validate_socket_directory(path.parent, uid=uid)
    try:
        metadata = path.lstat()
    except OSError:
        raise SyntheticIPCError("ipc_socket_unverified") from None
    if (
        not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != uid
        or metadata.st_gid != uid
        or stat.S_IMODE(metadata.st_mode) != SOCKET_MODE
        or metadata.st_nlink != 1
    ):
        raise SyntheticIPCError("ipc_socket_unverified")
    return metadata.st_dev, metadata.st_ino


def verify_peer(writer: asyncio.StreamWriter, *, uid: int, gid: int) -> None:
    """Verify kernel SO_PEERCRED, not user-controlled fields in the message."""
    endpoint = writer.get_extra_info("socket")
    if endpoint is None or not hasattr(socket, "SO_PEERCRED"):
        raise SyntheticIPCError("ipc_peer_unverified")
    try:
        raw = endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, actual_uid, actual_gid = struct.unpack("3i", raw)
    except (OSError, ValueError, struct.error):
        raise SyntheticIPCError("ipc_peer_unverified") from None
    if pid <= 0 or actual_uid != uid or actual_gid != gid:
        raise SyntheticIPCError("ipc_peer_unverified")


def framed(payload: bytes) -> bytes:
    if payload not in {REQUEST, SUCCESS, BUSY, NO_GO} or len(payload) > MAX_FRAME_BYTES:
        raise SyntheticIPCError("ipc_frame_unverified")
    return len(payload).to_bytes(2, "big") + payload


async def read_frame(reader: asyncio.StreamReader) -> bytes:
    try:
        length = int.from_bytes(await reader.readexactly(2), "big")
        if not 0 < length <= MAX_FRAME_BYTES:
            raise SyntheticIPCError("ipc_frame_unverified")
        return await reader.readexactly(length)
    except asyncio.IncompleteReadError:
        raise SyntheticIPCError("ipc_frame_unverified") from None
