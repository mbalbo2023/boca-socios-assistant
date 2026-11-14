"""Fixed commands and a separate bounded private observation on existing AF_UNIX.

Requests accept no URL, identity, account, cookie, token or arbitrary text.
Only an explicit observation response can carry the typed, received Queue-it
projection. Kernel peer credentials and socket custody protect that channel.
Neither IPC side opens an IP socket.
"""

from __future__ import annotations

import asyncio
import os
import socket
import stat
import struct
from pathlib import Path

from boca_socios.browser.queue_page_observation import (
    MAX_OBSERVATION_PAYLOAD,
    QueuePageObservation,
)

CONTROLLER_UID = 10001
WORKER_UID = 10002
SOCKET_PATH = Path("/run/boca-browser-ipc/synthetic.sock")
DIRECTORY_MODE = 0o711  # owner rwx, clients traverse only; no directory listing
SOCKET_MODE = 0o622  # other users can connect; SO_PEERCRED authorizes UID/GID
MAX_FRAME_BYTES = 64
REQUEST = b"BOCA_SYNTHETIC_V1_RUN"
# An opt-in Chromium fixture observation is not a reservation request.  Keep
# these frames distinct from REQUEST/SUCCESS even during a simulation.
PROBE_FIXTURE = b"BOCA_SYNTHETIC_V1_PROBE_FIXTURE"
FIXTURE_OBSERVED = b"BOCA_SYNTHETIC_V1_FIXTURE_OBSERVED"
# A separately opted-in single-document HTTP(S) observation is not a
# transaction.  No status, URL, identity or response body crosses this frame.
PROBE_SITE = b"BOCA_SYNTHETIC_V1_PROBE_SITE"
OBSERVE_QUEUE = b"BOCA_SYNTHETIC_V1_OBSERVE_QUEUE"
SITE_HTTP_OK = b"BOCA_SYNTHETIC_V1_SITE_HTTP_OK"
SITE_HTTP_NON_OK = b"BOCA_SYNTHETIC_V1_SITE_HTTP_NON_OK"
SUCCESS = b"BOCA_SYNTHETIC_V1_RESERVED_IN_SIMULATOR"
BUSY = b"BOCA_SYNTHETIC_V1_BUSY"
NO_GO = b"BOCA_SYNTHETIC_V1_NO_GO"


class SyntheticIPCError(RuntimeError):
    """Fail-closed local transport or worker, with a fixed nonsecret reason."""


def validate_socket_directory(path: Path, *, uid: int = WORKER_UID, gid: int | None = None) -> None:
    """Reject symlinked, redirected, broad or foreign IPC mount directories."""
    expected_gid = uid if gid is None else gid
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
            or metadata.st_gid != expected_gid
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
    # Linux pid_vnr() returns 0 when the peer is invisible in this PID
    # namespace. Authenticate the exact kernel-mapped UID/GID; a PID, even
    # positive, does not prove container identity. See ADR0101.
    if pid < 0 or actual_uid != uid or actual_gid != gid:
        raise SyntheticIPCError("ipc_peer_unverified")


def framed(payload: bytes) -> bytes:
    if (
        payload
        not in {
            REQUEST,
            PROBE_FIXTURE,
            FIXTURE_OBSERVED,
            PROBE_SITE,
            OBSERVE_QUEUE,
            SITE_HTTP_OK,
            SITE_HTTP_NON_OK,
            SUCCESS,
            BUSY,
            NO_GO,
        }
        or len(payload) > MAX_FRAME_BYTES
    ):
        raise SyntheticIPCError("ipc_frame_unverified")
    return len(payload).to_bytes(2, "big") + payload


def framed_private_observation(payload: bytes) -> bytes:
    """Typed private response only; never use this for controller requests."""
    try:
        QueuePageObservation.from_payload(payload)
    except (ValueError, TypeError):
        raise SyntheticIPCError("ipc_observation_unverified") from None
    return len(payload).to_bytes(2, "big") + payload


async def _read_bounded_frame(reader: asyncio.StreamReader, maximum: int) -> bytes:
    try:
        length = int.from_bytes(await reader.readexactly(2), "big")
        if not 0 < length <= maximum:
            raise SyntheticIPCError("ipc_frame_unverified")
        return await reader.readexactly(length)
    except asyncio.IncompleteReadError:
        raise SyntheticIPCError("ipc_frame_unverified") from None


async def read_frame(reader: asyncio.StreamReader) -> bytes:
    return await _read_bounded_frame(reader, MAX_FRAME_BYTES)


async def read_private_observation_frame(reader: asyncio.StreamReader) -> bytes:
    return await _read_bounded_frame(reader, MAX_OBSERVATION_PAYLOAD)
