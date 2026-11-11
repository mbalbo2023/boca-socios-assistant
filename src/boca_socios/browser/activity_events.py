"""Fixed, optional Chromium lifecycle signals over the existing Boca IPC volume.

This is not a raw browser log. Neither credentials, URLs, DOM nor error text
can enter the file. The worker writes; the controller only reads its ro mount.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Literal

from boca_socios.browser.ipc_protocol import (
    SOCKET_PATH,
    WORKER_UID,
    SyntheticIPCError,
    validate_socket_directory,
)

ACTIVITY_PATH = SOCKET_PATH.with_name("chromium-events.jsonl")
MAX_ACTIVITY_BYTES = 32 * 1024
_FILE_MODE = 0o644
_MAX_LINE_BYTES = 128
_STAGES = frozenset(
    {
        "launch_requested",
        "launched",
        "context_ready",
        "page_ready",
        "context_closed",
        "browser_closed",
        "operation_failed",
    }
)
_WRITE_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class ChromiumStage:
    at: str
    code: str


@dataclass(frozen=True, slots=True)
class ChromiumActivity:
    state: Literal["available", "missing", "degraded"]
    events: tuple[ChromiumStage, ...] = ()


def _file_valid(metadata: os.stat_result, owner_uid: int, owner_gid: int) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == owner_uid
        and metadata.st_gid == owner_gid
        and stat.S_IMODE(metadata.st_mode) == _FILE_MODE
        and metadata.st_nlink == 1
    )


def emit_chromium_event(
    stage: str,
    *,
    path: Path = ACTIVITY_PATH,
    owner_uid: int = WORKER_UID,
    owner_gid: int | None = None,
) -> None:
    """Best-effort signal; no telemetry failure can alter browser behavior."""
    if stage not in _STAGES:
        raise ValueError("unknown fixed Chromium activity code")
    data = (
        json.dumps(
            {"v": 1, "e": stage, "t": datetime.now(UTC).isoformat(timespec="milliseconds")},
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )
    if len(data) > _MAX_LINE_BYTES:
        return
    expected_gid = owner_uid if owner_gid is None else owner_gid
    try:
        with _WRITE_LOCK:
            validate_socket_directory(path.parent, uid=owner_uid, gid=expected_gid)
            try:
                existing = path.lstat()
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if not _file_valid(existing, owner_uid, expected_gid):
                    return
                if existing.st_size + len(data) > MAX_ACTIVITY_BYTES:
                    # Rotate only this dedicated Boca telemetry file. The IPC
                    # socket is never renamed or removed.
                    os.replace(path, path.with_name("chromium-events.previous"))
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
            descriptor = os.open(path, flags, _FILE_MODE)
            try:
                metadata = os.fstat(descriptor)
                if (
                    existing is None
                    and stat.S_ISREG(metadata.st_mode)
                    and metadata.st_uid == owner_uid
                    and metadata.st_gid == expected_gid
                    and metadata.st_nlink == 1
                ):
                    # A strict container umask must not hide fixed codes from
                    # the read-only UID10001 controller mount.
                    os.fchmod(descriptor, _FILE_MODE)
                    metadata = os.fstat(descriptor)
                if (
                    _file_valid(metadata, owner_uid, expected_gid)
                    and metadata.st_size <= MAX_ACTIVITY_BYTES
                ):
                    os.write(descriptor, data)
            finally:
                os.close(descriptor)
    except (OSError, SyntheticIPCError, ValueError):
        # The simulation must neither succeed nor fail because telemetry failed.
        return


def read_chromium_events(
    *,
    path: Path = ACTIVITY_PATH,
    owner_uid: int = WORKER_UID,
    owner_gid: int | None = None,
    observed_at: datetime,
) -> ChromiumActivity:
    """Read bounded worker-written codes without following links or rendering text."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at requires timezone")
    expected_gid = owner_uid if owner_gid is None else owner_gid
    try:
        validate_socket_directory(path.parent, uid=owner_uid, gid=expected_gid)
        try:
            existing = path.lstat()
        except FileNotFoundError:
            return ChromiumActivity("missing")
        if (
            not _file_valid(existing, owner_uid, expected_gid)
            or existing.st_size > MAX_ACTIVITY_BYTES
        ):
            return ChromiumActivity("degraded")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            metadata = os.fstat(descriptor)
            if (
                not _file_valid(metadata, owner_uid, expected_gid)
                or metadata.st_size > MAX_ACTIVITY_BYTES
            ):
                return ChromiumActivity("degraded")
            data = os.read(descriptor, MAX_ACTIVITY_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(data) > MAX_ACTIVITY_BYTES:
            return ChromiumActivity("degraded")
        # A reader can race an append; ignore only the unfinished last line.
        complete = data.rsplit(b"\n", 1)[0] if not data.endswith(b"\n") else data[:-1]
        lines = complete.split(b"\n") if complete else []
        stages = []
        for line in lines:
            if not 1 <= len(line) <= _MAX_LINE_BYTES:
                return ChromiumActivity("degraded")
            entry = json.loads(line)
            if (
                not isinstance(entry, dict)
                or set(entry) != {"v", "e", "t"}
                or type(entry["v"]) is not int
                or entry["v"] != 1
                or type(entry["e"]) is not str
                or entry["e"] not in _STAGES
                or type(entry["t"]) is not str
                or len(entry["t"]) > 40
            ):
                return ChromiumActivity("degraded")
            at = datetime.fromisoformat(entry["t"])
            if (
                at.tzinfo is None
                or at.utcoffset() != timedelta(0)
                or not isfinite(at.timestamp())
                or at > observed_at.astimezone(UTC) + timedelta(minutes=1)
            ):
                return ChromiumActivity("degraded")
            stages.append(ChromiumStage(at=at.astimezone(UTC).isoformat(), code=entry["e"]))
        return ChromiumActivity("available", tuple(stages[-32:]))
    except (OSError, SyntheticIPCError, ValueError, TypeError, UnicodeDecodeError):
        return ChromiumActivity("degraded")
