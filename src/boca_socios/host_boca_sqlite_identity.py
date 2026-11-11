"""Read-only identity proof for the *existing* Boca SQLite inode.

Only stat metadata is accessed through O_PATH, dirfd and O_NOFOLLOW. Never
open the database for reading or writing, connect to SQLite, run Docker exec,
or publish device/inode, owner IDs, host paths or private application data.

The public observer combines the existing Boca-only container/OCI and rootless
volume-label attestors with two independently opened file identity snapshots.
An upgrade may retain the private identity under its already-verified lease
and compare it before/after, but this standalone observation is never Cutover GO.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_first_deploy as host

# Must equal host_on_demand_service._HOME / host_on_demand_service._DB.
_EXPECTED_ROOT = Path("/home/boca-deploy/.local/share/docker")
_DB_RELATIVE = Path("volumes/boca-socios_boca_data/_data/boca.sqlite3")
_EXPECTED_FILE = _EXPECTED_ROOT / _DB_RELATIVE
_DIR_FLAGS = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC


class SqliteIdentityError(ValueError):
    """Fixed-category failure. Never propagate private OS/Docker details."""


@dataclass(frozen=True, slots=True, repr=False)
class SqliteIdentity:
    """Private comparison value; intentionally redacted if logged by mistake."""

    device: int
    inode: int
    owner_uid: int
    owner_gid: int
    mode: int
    links: int


def capture_sqlite_identity(rootless_docker_root: Path) -> SqliteIdentity:
    """Stat a single fixed Boca file using descriptor-relative, no-follow IO.

    Caller must first prove the dedicated Docker root, volume labels and
    controller mount under the same Boca lease. No database bytes are read.
    """
    if (
        not isinstance(rootless_docker_root, Path)
        or rootless_docker_root != _EXPECTED_ROOT
        or rootless_docker_root / _DB_RELATIVE != _EXPECTED_FILE
    ):
        raise SqliteIdentityError("sqlite_identity_unverified")
    directory_fd = -1
    try:
        directory_fd = os.open("/", _DIR_FLAGS)
        # Prove every ancestor is a real directory, not a redirected symlink.
        # The caller separately validates DockerRootDir and rootless ownership.
        roots = rootless_docker_root.parts[1:]
        for index, part in enumerate((*roots, *_DB_RELATIVE.parts[:-1])):
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
            parent = os.fstat(directory_fd)
            if not stat.S_ISDIR(parent.st_mode) or (
                index >= len(roots) and stat.S_IMODE(parent.st_mode) & 0o022
            ):
                raise SqliteIdentityError("sqlite_identity_unverified")
        file_fd = os.open(_DB_RELATIVE.name, _FILE_FLAGS, dir_fd=directory_fd)
        try:
            opened = os.fstat(file_fd)
            named = os.stat(_DB_RELATIVE.name, dir_fd=directory_fd, follow_symlinks=False)
        finally:
            os.close(file_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != named.st_dev
            or opened.st_ino != named.st_ino
            or opened.st_mode != named.st_mode
            or opened.st_uid != named.st_uid
            or opened.st_gid != named.st_gid
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or opened.st_ino <= 0
            or opened.st_dev < 0
        ):
            raise SqliteIdentityError("sqlite_identity_unverified")
        return SqliteIdentity(
            device=opened.st_dev,
            inode=opened.st_ino,
            owner_uid=opened.st_uid,
            owner_gid=opened.st_gid,
            mode=stat.S_IMODE(opened.st_mode),
            links=opened.st_nlink,
        )
    except (OSError, ValueError, OverflowError, TypeError):
        raise SqliteIdentityError("sqlite_identity_unverified") from None
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def _attest_boundary(rootless_docker_root: Path) -> None:
    """Reuse exact CID/OCI/mount and Boca data-volume label attestors."""
    # This creates no run; the constant ID is used solely for an in-memory
    # guard receipt that is never printed, uploaded or used as physical proof.
    pair.observe("1")
    host._validate_data_volume()
    if host._checked_docker_storage_dir() != rootless_docker_root:
        raise SqliteIdentityError("sqlite_identity_unverified")


def observe_sqlite_identity(rootless_docker_root: Path) -> str:
    """Return only VERIFIED_STABLE or NO_GO; never return paths or inode IDs.

    No lease is acquired here. The upgrade owner must repeat identity checks
    under its exclusive lease before modifying the exact Boca controller pair.
    """
    try:
        _attest_boundary(rootless_docker_root)
        first = capture_sqlite_identity(rootless_docker_root)
        _attest_boundary(rootless_docker_root)
        second = capture_sqlite_identity(rootless_docker_root)
        if first != second:
            return "NO_GO"
        return "VERIFIED_STABLE"
    except Exception:
        # Docker, filesystem and Python exceptions may embed private paths.
        return "NO_GO"
