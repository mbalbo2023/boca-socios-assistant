"""Read-only, same-lease Boca rootless UID map and file-identity witness.

This module produces *no deploy GO*. Its bounded private mapping and inode
metadata never appear in the public result. No file content, SQLite, key,
process environment, Docker exec or foreign container is inspected.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import select
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_upgrade_postflight_runtime as runtime

if TYPE_CHECKING:
    from boca_socios import host_boca_upgrade_postflight as postflight

_DOCKER_ROOT = Path("/home/boca-deploy/.local/share/docker")
_PROC_ROOT = Path("/proc")
_DIR = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_META = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_FILES = (
    ("boca-socios_boca_data", "boca.sqlite3"),
    ("boca-socios_boca_key", "boca_master_key"),
    ("boca-socios_boca_owner", "boca_owner_session.sqlite3"),
)
_MAP_ROW = re.compile(rb"[ \t]*([0-9]+)[ \t]+([0-9]+)[ \t]+([0-9]+)[ \t]*\n\Z")
_CID = re.compile(r"[a-f0-9]{64}\Z")
_USER_NS = re.compile(r"user:\[([0-9]{1,20})\]\Z")
_LIMIT = 1 << 32


class MappedCustodyNoGo(ValueError):
    """Public fixed-code refusal: no private mapping or inode details."""


def _fail() -> MappedCustodyNoGo:
    return MappedCustodyNoGo("BOCA_MAPPED_CUSTODY NO_GO")


@dataclass(frozen=True, slots=True, repr=False)
class MappedOwner:
    """Private translated host ownership, never serialize in a public receipt."""

    uid: int
    gid: int


def map_container_id(raw: bytes, container_id: int) -> int:
    """Translate a UID/GID only if a complete, disjoint Boca rootless map exists."""
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= 512
        or not raw.endswith(b"\n")
        or type(container_id) is not int
        or container_id != cleanup.EXPECTED_UID
    ):
        raise _fail()
    lines = raw.splitlines(keepends=True)
    if not 2 <= len(lines) <= 8:
        raise _fail()
    rows: list[tuple[int, int, int]] = []
    for line in lines:
        match = _MAP_ROW.fullmatch(line)
        if match is None:
            raise _fail()
        child, host, size = (int(part) for part in match.groups())
        if (
            size == 0
            or child >= _LIMIT
            or host >= _LIMIT
            or child + size > _LIMIT
            or host + size > _LIMIT
        ):
            raise _fail()
        for earlier_child, earlier_host, earlier_size in rows:
            if (
                child < earlier_child + earlier_size
                and earlier_child < child + size
                or host < earlier_host + earlier_size
                and earlier_host < host + size
            ):
                raise _fail()
        rows.append((child, host, size))
    # The rootless namespace's UID/GID 0 must be the Boca host service user.
    if not any(
        child == 0 and host == cleanup.EXPECTED_UID and size == 1 for child, host, size in rows
    ):
        raise _fail()
    translated = [
        host + container_id - child
        for child, host, size in rows
        if child <= container_id < child + size
    ]
    if len(translated) != 1 or translated[0] <= cleanup.EXPECTED_UID:
        raise _fail()
    return translated[0]


def _read_proc_map(procfd: int, kind: str) -> bytes:
    if kind not in ("uid_map", "gid_map"):
        raise _fail()
    fd = os.open(kind, _READ, dir_fd=procfd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise _fail()
        raw = os.read(fd, 513)
        if len(raw) > 512:
            raise _fail()
        return raw
    finally:
        os.close(fd)


def read_proc_mapped_owner(pid: int) -> MappedOwner:
    """Open only the pinned, verified Boca controller PID's two proc map files."""
    if type(pid) is not int or not 1 < pid < 2**31:
        raise _fail()
    directory = -1
    try:
        directory = os.open(_PROC_ROOT / str(pid), _DIR)
        if not stat.S_ISDIR(os.fstat(directory).st_mode):
            raise _fail()
        uid = map_container_id(_read_proc_map(directory, "uid_map"), cleanup.EXPECTED_UID)
        gid = map_container_id(_read_proc_map(directory, "gid_map"), cleanup.EXPECTED_GID)
        return MappedOwner(uid, gid)
    except (OSError, ValueError, TypeError, OverflowError):
        raise _fail() from None
    finally:
        if directory >= 0:
            os.close(directory)


def _namespace_identity(pid: int) -> tuple[int, int]:
    """Pin a real kernel ``nsfs`` user namespace, not a guessed subuid range.

    Only this kernel-managed /proc magic link is followed, after its exact
    ``user:[inode]`` target has been examined. Data and volume ancestors
    continue to use O_PATH/O_NOFOLLOW exclusively.
    """
    proc_fd = -1
    ns_fd = -1
    user_fd = -1
    try:
        proc_fd = os.open(_PROC_ROOT / str(pid), _DIR)
        ns_fd = os.open("ns", _DIR, dir_fd=proc_fd)
        target = os.readlink("user", dir_fd=ns_fd)
        matched = _USER_NS.fullmatch(target)
        if matched is None:
            raise _fail()
        user_fd = os.open("user", os.O_RDONLY | os.O_CLOEXEC, dir_fd=ns_fd)
        item = os.fstat(user_fd)
        if item.st_dev <= 0 or item.st_ino <= 0 or item.st_ino != int(matched.group(1)):
            raise _fail()
        return item.st_dev, item.st_ino
    except Exception:
        raise _fail() from None
    finally:
        for descriptor in (user_fd, ns_fd, proc_fd):
            if descriptor >= 0:
                os.close(descriptor)


def read_container_mapped_owner(controller_id: str) -> MappedOwner:
    """Kernel PIDFD+namespace-bound mapper; caller must prove the exact pair.

    The CID is never accepted from a user form. Production callers reattest
    the exact live Boca pair and held lease immediately before/after this
    sensor. A missing pidfd or unreadable namespace is NO_GO, not a fallback.
    """
    fd = -1
    try:
        if type(controller_id) is not str or _CID.fullmatch(controller_id) is None:
            raise _fail()

        def current_pid() -> int:
            raw = cleanup._docker("inspect", "--format", "{{json .State.Pid}}", controller_id)
            value = json.loads(raw)
            if type(value) is not int or not 1 < value < 2**31:
                raise _fail()
            return value

        pid = current_pid()
        fd = os.pidfd_open(pid)
        watcher = select.poll()
        watcher.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
        if watcher.poll(0):
            raise _fail()
        first_namespace = _namespace_identity(pid)
        if first_namespace == _namespace_identity(os.getpid()):
            raise _fail()
        first_owner = read_proc_mapped_owner(pid)
        if (
            _namespace_identity(pid) != first_namespace
            or read_proc_mapped_owner(pid) != first_owner
            or current_pid() != pid
            or watcher.poll(0)
        ):
            raise _fail()
        return first_owner
    except Exception:
        raise _fail() from None
    finally:
        if fd >= 0:
            os.close(fd)


def read_controller_mapped_owner(
    expected: postflight.PostflightExpected, lease: cleanup.BocaJobLease
) -> MappedOwner:
    """Bind proc PID to authenticated exact Boca CID before AND after reading."""
    try:
        if (
            type(expected.controller_id) is not str
            or _CID.fullmatch(expected.controller_id) is None
        ):
            raise _fail()
        runtime._attest_live_pair(expected, lease)
        cleanup.verify_protected_boca_job_lease(lease, expected.plan.attempt_id)

        mapped = read_container_mapped_owner(expected.controller_id)
        runtime._attest_live_pair(expected, lease)
        cleanup.verify_protected_boca_job_lease(lease, expected.plan.attempt_id)
        return mapped
    except Exception:
        raise _fail() from None


def _file_identity(root: Path, volume: str, name: str, owner: MappedOwner) -> str:
    """Pin no-follow inodes with O_PATH, hash private metadata, no content read."""
    directory = -1
    try:
        directory = os.open("/", _DIR)
        root_length = len(root.parts) - 1
        for index, part in enumerate((*root.parts[1:], "volumes", volume, "_data")):
            child = os.open(part, _DIR, dir_fd=directory)
            os.close(directory)
            directory = child
            folder = os.fstat(directory)
            if not stat.S_ISDIR(folder.st_mode) or (
                index >= root_length and stat.S_IMODE(folder.st_mode) & 0o022
            ):
                raise _fail()
        fd = os.open(name, _META, dir_fd=directory)
        try:
            opened = os.fstat(fd)
            named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        finally:
            os.close(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid, opened.st_gid)
            != (named.st_dev, named.st_ino, named.st_mode, named.st_uid, named.st_gid)
            or opened.st_nlink != named.st_nlink
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) not in (0o400, 0o600)
            or (opened.st_uid, opened.st_gid) != (owner.uid, owner.gid)
            or opened.st_dev < 0
            or opened.st_ino <= 0
        ):
            raise _fail()
        private = (
            volume,
            name,
            opened.st_dev,
            opened.st_ino,
            opened.st_uid,
            opened.st_gid,
            stat.S_IMODE(opened.st_mode),
            opened.st_nlink,
        )
        return hashlib.sha256(
            b"BOCA_MAPPED_INODE_V1\0" + json.dumps(private, separators=(",", ":")).encode()
        ).hexdigest()
    except Exception:
        raise _fail() from None
    finally:
        if directory >= 0:
            os.close(directory)


def capture_mapped_custody(
    rootless_docker_root: Path = _DOCKER_ROOT,
    owner: MappedOwner | None = None,
    *,
    trusted_root: Path = _DOCKER_ROOT,
) -> tuple[str, str, str]:
    """Hash exact three private Boca file identities after caller's volume proof."""
    if (
        not isinstance(rootless_docker_root, Path)
        or not isinstance(trusted_root, Path)
        or rootless_docker_root != trusted_root
        or not rootless_docker_root.is_absolute()
        or rootless_docker_root == Path("/")
        or type(owner) is not MappedOwner
    ):
        raise _fail()
    try:
        return tuple(
            _file_identity(rootless_docker_root, volume, file, owner) for volume, file in _FILES
        )  # type: ignore[return-value]
    except Exception:
        raise _fail() from None


def observe_boca_mapped_file_custody(
    expected: postflight.PostflightExpected,
    lease: cleanup.BocaJobLease,
    volume_attestor: Callable[[], None],
) -> str:
    """Technical read-only witness; even VERIFIED_MAPPED is NOT deploy GO."""
    try:
        if not callable(volume_attestor):
            raise _fail()
        cleanup.verify_protected_boca_job_lease(lease, expected.plan.attempt_id)
        runtime._attest_live_pair(expected, lease)
        first_owner = read_controller_mapped_owner(expected, lease)
        volume_attestor()
        first = capture_mapped_custody(runtime._ROOT, first_owner, trusted_root=runtime._ROOT)
        volume_attestor()
        second_owner = read_controller_mapped_owner(expected, lease)
        if first_owner != second_owner:
            raise _fail()
        second = capture_mapped_custody(runtime._ROOT, second_owner, trusted_root=runtime._ROOT)
        if first != second:
            raise _fail()
        volume_attestor()
        runtime._attest_live_pair(expected, lease)
        cleanup.verify_protected_boca_job_lease(lease, expected.plan.attempt_id)
        return "VERIFIED_MAPPED"
    except Exception:
        return "NO_GO"
