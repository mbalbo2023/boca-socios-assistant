"""Strict optional *offline* Boca official-news snapshot for the private panel.

The caller supplies the already trusted dedicated Boca data directory. This
reader cannot establish publication authenticity, fetch an official page or
authorize a queue/ticket operation; every returned notice remains unverified
and non-actionable. It does not create, migrate, replace or update any file.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .official_catalog import (
    OfficialCatalogError,
    OfficialNotice,
    build_observed_catalog,
    load_observed_notice,
)

OFFICIAL_SNAPSHOT_NAME = "boca_official_notices.jsonl"
_MAX_NOTICES = 20
_MAX_NOTICE_BYTES = 16_384
_MAX_SNAPSHOT_BYTES = _MAX_NOTICES * (_MAX_NOTICE_BYTES + 1)
_PRIVATE_FILE_MODES = frozenset({0o400, 0o600})


class OfficialSnapshotError(OfficialCatalogError):
    """Snapshot unavailable, mutable, malformed or outside the trusted boundary."""


def _identity(info: os.stat_result) -> tuple[int, ...]:
    """Include mutable metadata to reject an in-place edit during a read."""
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _open_parent_no_symlinks(path: Path) -> int:
    """Walk every directory component with openat, never following a symlink."""
    if not path.is_absolute() or ".." in path.parts or not hasattr(os, "O_NOFOLLOW"):
        raise OfficialSnapshotError("snapshot path is not canonical and confined")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open("/", flags)
    except OSError:
        raise OfficialSnapshotError("snapshot directory unavailable") from None
    try:
        for component in path.parts[1:]:
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except OSError:
                raise OfficialSnapshotError("snapshot directory unavailable") from None
            os.close(descriptor)
            descriptor = next_descriptor
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise OfficialSnapshotError("snapshot directory owner or mode invalid")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _check_file(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise OfficialSnapshotError("snapshot must be a regular file")
    if info.st_uid != os.geteuid():
        raise OfficialSnapshotError("snapshot owner does not match controller")
    if stat.S_IMODE(info.st_mode) not in _PRIVATE_FILE_MODES:
        raise OfficialSnapshotError("snapshot mode must be owner-private")
    if info.st_nlink != 1:
        raise OfficialSnapshotError("snapshot has an unsafe link count")
    if info.st_size < 0 or info.st_size > _MAX_SNAPSHOT_BYTES:
        raise OfficialSnapshotError("snapshot capacity exceeded")


def _read_snapshot(parent_fd: int) -> bytes | None:
    try:
        before = os.stat(OFFICIAL_SNAPSHOT_NAME, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        # Optional *file* absent; missing/inaccessible data volume is NOT absence.
        return None
    except OSError:
        raise OfficialSnapshotError("snapshot file metadata unavailable") from None
    _check_file(before)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    try:
        file_fd = os.open(OFFICIAL_SNAPSHOT_NAME, flags, dir_fd=parent_fd)
    except OSError:
        raise OfficialSnapshotError("snapshot file open failed") from None
    try:
        opened = os.fstat(file_fd)
        _check_file(opened)
        if _identity(before) != _identity(opened):
            raise OfficialSnapshotError("snapshot changed before opening")
        parts: list[bytes] = []
        remaining = _MAX_SNAPSHOT_BYTES + 1
        while remaining:
            part = os.read(file_fd, min(65_536, remaining))
            if not part:
                break
            parts.append(part)
            remaining -= len(part)
        raw = b"".join(parts)
        after = os.fstat(file_fd)
        try:
            named = os.stat(OFFICIAL_SNAPSHOT_NAME, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            raise OfficialSnapshotError("snapshot changed during reading") from None
        if (
            len(raw) > _MAX_SNAPSHOT_BYTES
            or len(raw) != opened.st_size
            or _identity(opened) != _identity(after)
            or _identity(opened) != _identity(named)
        ):
            raise OfficialSnapshotError("snapshot changed during reading")
        return raw
    except OSError:
        raise OfficialSnapshotError("snapshot read failed") from None
    finally:
        os.close(file_fd)


def load_official_snapshot(path: Path) -> tuple[OfficialNotice, ...]:
    """Load a bounded, owner-private JSONL snapshot, or empty if absent.

    A present but malformed/unsafe snapshot is an explicit error; the caller
    may isolate that error to informational routes, but must never silently
    promote the snapshot to live availability or executable bot commands.
    """
    if not isinstance(path, Path) or not path.is_absolute() or path.name != OFFICIAL_SNAPSHOT_NAME:
        raise OfficialSnapshotError("snapshot path is not canonical and confined")
    parent_fd = _open_parent_no_symlinks(path.parent)
    try:
        raw = _read_snapshot(parent_fd)
    finally:
        os.close(parent_fd)
    if raw is None or raw == b"":
        return ()
    if b"\r" in raw or b"\x00" in raw:
        raise OfficialSnapshotError("snapshot JSON Lines framing invalid")
    body = raw[:-1] if raw.endswith(b"\n") else raw
    lines = body.split(b"\n")
    if len(lines) > _MAX_NOTICES:
        raise OfficialSnapshotError("snapshot capacity exceeded")
    if not body or any(not line or len(line) > _MAX_NOTICE_BYTES for line in lines):
        raise OfficialSnapshotError("snapshot JSON Lines framing invalid")
    try:
        notices = tuple(load_observed_notice(line.decode("utf-8")) for line in lines)
        return build_observed_catalog(notices)
    except (UnicodeError, OfficialCatalogError):
        raise OfficialSnapshotError("snapshot notice invalid or duplicated") from None
