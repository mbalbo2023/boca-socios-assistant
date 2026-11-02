"""Standalone, bounded, atomic staging of one reviewed Boca IPC file.

Actions sends this public Python module as a ``python3 -c`` argument over
pinned SSH and the exact *file bytes* on stdin. The host needs no package
installation, SCP pathname traversal, extra port or existing web service.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import BinaryIO

ROOT = Path("/srv/boca-socios")
MARKER = "browser-ipc-attempt.json"
FILES = {
    "base": ("compose.beta.yaml", "beta_compose_sha"),
    "overlay": ("compose.beta.browser.yaml", "overlay_compose_sha"),
    "seccomp": ("seccomp_profile.json", "seccomp_sha"),
}
SHA = re.compile(r"[0-9a-f]{64}\Z")
SOURCE = re.compile(r"[0-9a-f]{40}\Z")
ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
CONTROLLER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
WORKER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z")


class StageError(ValueError):
    """No reviewed, intact new-only Boca staging possible."""


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for name, value in pairs:
        if name in fields:
            raise StageError("duplicate private attempt coordinate")
        fields[name] = value
    return fields


def stage_file(
    slot: str,
    expected_sha: str,
    attempt_id: str,
    source_sha: str,
    controller_image: str,
    browser_image: str,
    data_stream: BinaryIO,
) -> None:
    if (
        slot not in FILES
        or not SHA.fullmatch(expected_sha)
        or not ATTEMPT.fullmatch(attempt_id)
        or not SOURCE.fullmatch(source_sha)
        or not CONTROLLER.fullmatch(controller_image)
        or not WORKER.fullmatch(browser_image)
        or os.geteuid() != 10001
    ):
        raise StageError("invalid immutable browser file staging coordinates")

    # Reject a truncated, altered, or oversized transfer before opening a
    # writable inode. No partial payload can become a final Compose file.
    payload = data_stream.read(32_769)
    if not 0 < len(payload) <= 32_768 or hashlib.sha256(payload).hexdigest() != expected_sha:
        raise StageError("reviewed browser file payload is incomplete or changed")

    filename, marker_key = FILES[slot]
    required = {
        "version": "browser-ipc-new-only-v2",
        "attempt_id": attempt_id,
        "source_sha": source_sha,
        "controller_digest": controller_image,
        "browser_digest": browser_image,
    }
    temporary = f".browser-ipc-{slot}-{attempt_id}.part"
    try:
        dirfd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise StageError("private Boca staging directory is unavailable") from exc
    try:
        directory = os.fstat(dirfd)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != 10001
            or stat.S_IMODE(directory.st_mode) != 0o700
        ):
            raise StageError("private Boca staging directory identity changed")

        if not _read_marker_coordinates(dirfd, required, marker_key, expected_sha):
            raise StageError("reviewed stage digest is not in protected marker")

        allowed = {MARKER, *(value[0] for value in FILES.values())}
        allowed |= {f".browser-ipc-{name}-{attempt_id}.part" for name in FILES}
        if not set(os.listdir(dirfd)) <= allowed:
            raise StageError("private staging directory contains unexpected entries")

        # O_EXCL forbids replacing either an existing final target or a
        # same-attempt partial upload. Hardlink is atomic and cannot clobber.
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=dirfd,
        )
        with os.fdopen(fd, "wb") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())

        os.link(
            temporary,
            filename,
            src_dir_fd=dirfd,
            dst_dir_fd=dirfd,
            follow_symlinks=False,
        )
        os.unlink(temporary, dir_fd=dirfd)
        os.fsync(dirfd)
    except OSError as exc:
        # An interrupted write may leave only the exact same-run .part file.
        # Do not unlink it without the separate positive-ID cleanup contract.
        raise StageError("atomic Boca browser file staging is unverified") from exc
    finally:
        os.close(dirfd)


def _read_marker_coordinates(
    dirfd: int, expected: dict[str, str], field: str, content_sha: str
) -> bool:
    """Authenticate the same private pre-pull marker by a single selected hash."""
    try:
        fd = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
        with os.fdopen(fd, "rb") as handle:
            meta = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(meta.st_mode)
                or meta.st_uid != 10001
                or stat.S_IMODE(meta.st_mode) != 0o600
                or not 0 < meta.st_size <= 1024
            ):
                raise StageError("private attempt marker metadata unverified")
            data = handle.read(1025)
            if len(data) != meta.st_size:
                raise StageError("private attempt marker changed")
        record = json.loads(data.decode("ascii"), object_pairs_hook=_unique)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageError("private attempt marker unreadable") from exc

    flags = {
        "controller_image_absent",
        "browser_image_absent",
        "bridge_absent",
        "ipc_volume_absent",
    }
    if (
        not isinstance(record, dict)
        or set(record)
        != set(expected) | flags | {"beta_compose_sha", "overlay_compose_sha", "seccomp_sha"}
        or any(record.get(key) != value for key, value in expected.items())
        or any(type(record.get(key)) is not bool for key in flags)
        or record["bridge_absent"] is not True
        or record["ipc_volume_absent"] is not True
        or any(
            not SHA.fullmatch(str(record.get(key, "")))
            for key in ("beta_compose_sha", "overlay_compose_sha", "seccomp_sha")
        )
    ):
        raise StageError("private marker is not this protected new-only attempt")
    return record.get(field) == content_sha


def main(argv: list[str] | None = None, data_stream: BinaryIO | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 6:
            raise StageError("stage requires fixed immutable arguments")
        slot, expected_sha, attempt_id, source_sha, controller_image, browser_image = args
        stage_file(
            slot,
            expected_sha,
            attempt_id,
            source_sha,
            controller_image,
            browser_image,
            data_stream if data_stream is not None else sys.stdin.buffer,
        )
    except (StageError, OSError, ValueError, TypeError):
        print("BOCA_BROWSER_FILE_STAGE_NO_GO", file=sys.stderr)
        return 1
    print(f"BOCA_BROWSER_FILE_STAGE_PASS slot={args[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
