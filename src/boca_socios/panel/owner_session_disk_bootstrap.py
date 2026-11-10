"""Option B SQLite bootstrap for the protected Boca cutover.

The historical host entry checks the same open lease description. The V3
data-only container entry runs as the database owner's namespaced UID and
matches the device/inode from the original controller. Both validate the
same reviewed SQL and preserve the legacy database byte-for-byte.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import sqlite3
import stat
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Literal
from urllib.parse import quote

_UID = 10001
_LOCK = Path("/run/user/10001/boca-socios-protected-job.lock")
_MOUNTED_DATABASE = Path("/data/boca.sqlite3")
_SESSION_NAME = "boca_owner_session.sqlite3"
_SESSION_SCHEMA_SHA256 = "38c4c97594143340089395c5230a464372acdd058dbe31169ba4206a1fd83d23"
_LEGACY_CHECKSUMS = {
    1: "3bf62d0bf684cbe597856a0fa58d3754829bceeed857cb13f65e90e2cb4cc099",
    2: "6d90ddc9042a8ebc5d71567e972b21d1ad171f901a14b9dede9c58786b9a064f",
    3: "501c37efbb212950a7b098825e339c975ee8e456475a9d277f267c210ca6e349",
    4: "d406131491133ef44dc7a1d2e56efcdc0b2551098652e840c5dd5d31a351a8ee",
    5: "dda8b58737f1f8386e85d13f7b7d2b47017e664a75be49b5e7756fcd755a3ed1",
    6: "12c8ae9d7ed8d682c6fa02676f685f8f4059ff4ca61788bbd92ed5e05001f74c",
    7: "7df576a79593e9120cf4ef1d4239ef2686734376c61ec7bf404efedc42a6e74e",
}
_REQUIRED_VERSIONS = frozenset({1, 2, 3, 5, 6})
_REQUIRED_TABLES = frozenset(
    {
        "members",
        "credentials",
        "events",
        "ticket_requests",
        "notification_outbox",
        "reservation_attempts",
        "beta_commands",
        "beta_command_keys",
    }
)


class SessionDiskBootstrapUnavailable(RuntimeError):
    """Trusted Boca host evidence or independent session file was unsafe."""


def _uid() -> None:
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (_UID,) * 4:
        raise SessionDiskBootstrapUnavailable("Boca rootless UID/GID unavailable")


def _regular_identity(path: Path) -> tuple[int, int]:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != _UID
        or metadata.st_gid != _UID
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise SessionDiskBootstrapUnavailable("Boca SQLite identity unavailable")
    return metadata.st_dev, metadata.st_ino


def _held_canonical_lease(held_lease_fd: int) -> None:
    """Independent contender must block; borrowed descriptor must own same OFD."""
    if type(held_lease_fd) is not int or held_lease_fd < 0:
        raise SessionDiskBootstrapUnavailable("held Boca lease FD required")
    runtime = _LOCK.parent.lstat()
    meta = os.fstat(held_lease_fd)
    path_meta = _LOCK.lstat()
    if (
        not stat.S_ISDIR(runtime.st_mode)
        or runtime.st_uid != _UID
        or stat.S_IMODE(runtime.st_mode) != 0o700
        or not stat.S_ISREG(meta.st_mode)
        or meta.st_uid != _UID
        or meta.st_gid != _UID
        or stat.S_IMODE(meta.st_mode) != 0o600
        or meta.st_nlink != 1
        or (meta.st_dev, meta.st_ino) != (path_meta.st_dev, path_meta.st_ino)
        or not stat.S_ISREG(path_meta.st_mode)
    ):
        raise SessionDiskBootstrapUnavailable("canonical Boca lease identity unavailable")
    probe = os.open(_LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if (os.fstat(probe).st_dev, os.fstat(probe).st_ino) != (
            meta.st_dev,
            meta.st_ino,
        ):
            raise SessionDiskBootstrapUnavailable("canonical Boca lease changed")
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise SessionDiskBootstrapUnavailable("Boca lease not held")
    finally:
        os.close(probe)
    borrowed = os.dup(held_lease_fd)
    try:
        fcntl.flock(borrowed, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(borrowed)


def _connect(path: Path, *, write: bool) -> sqlite3.Connection:
    uri = f"file:{quote(str(path), safe='/')}?mode={'rw' if write else 'ro'}"
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    connection.execute("PRAGMA busy_timeout=1000")
    connection.execute("PRAGMA trusted_schema=OFF")
    if not write:
        connection.execute("PRAGMA query_only=ON")
    return connection


def _legacy_contract(path: Path, expected: tuple[int, int]) -> None:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.name != "boca.sqlite3"
        or not isinstance(expected, tuple)
        or len(expected) != 2
        or any(type(item) is not int or item < 0 for item in expected)
        or _regular_identity(path) != expected
    ):
        raise SessionDiskBootstrapUnavailable("legacy Boca controller identity unavailable")
    with closing(_connect(path, write=False)) as connection:
        rows = connection.execute(
            "SELECT version,checksum FROM schema_migrations LIMIT 32"
        ).fetchall()
        versions = {version for version, _ in rows}
        tables = {
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if (
            len(versions) != len(rows)
            or len(rows) > len(_LEGACY_CHECKSUMS)
            or not _REQUIRED_VERSIONS <= versions
            or any(
                type(version) is not int or _LEGACY_CHECKSUMS.get(version) != checksum
                for version, checksum in rows
            )
            or not _REQUIRED_TABLES <= tables
            or "owner_browser_session" in tables
            or (4 in versions) != ("credential_key_policy" in tables)
            or (7 in versions) != ("telegram_delivery_attempts" in tables)
            or connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
            or connection.execute("PRAGMA foreign_key_check").fetchone() is not None
        ):
            raise SessionDiskBootstrapUnavailable("legacy Boca schema incompatible")


def _schema_statements(raw: bytes) -> tuple[str, str]:
    if type(raw) is not bytes or len(raw) > 4096:
        raise SessionDiskBootstrapUnavailable("owner session SQL unavailable")
    if hashlib.sha256(raw).hexdigest() != _SESSION_SCHEMA_SHA256:
        raise SessionDiskBootstrapUnavailable("owner session SQL checksum mismatch")
    sql = raw.decode("utf-8")
    statements = tuple(part.strip() for part in sql.split(";") if part.strip())
    if (
        len(statements) != 2
        or not statements[0].startswith("CREATE TABLE owner_browser_session (")
        or not statements[1].startswith("CREATE TABLE owner_session_schema (")
    ):
        raise SessionDiskBootstrapUnavailable("owner session SQL unavailable")
    return statements[0], statements[1]


def _session_contract(connection: sqlite3.Connection, statements: tuple[str, str]) -> None:
    rows = connection.execute(
        "SELECT version,checksum FROM owner_session_schema ORDER BY version LIMIT 2"
    ).fetchall()
    objects = connection.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    if (
        rows != [(1, _SESSION_SCHEMA_SHA256)]
        or objects
        != [
            ("table", "owner_browser_session", statements[0]),
            ("table", "owner_session_schema", statements[1]),
        ]
        or connection.execute("PRAGMA user_version").fetchone() != (1,)
        or connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
    ):
        raise SessionDiskBootstrapUnavailable("owner session schema unavailable")


def bootstrap_attested_session_file(
    legacy_path: Path,
    *,
    held_lease_fd: int,
    expected_db_identity: tuple[int, int],
    session_schema_bytes: bytes,
) -> Literal["APPLIED", "ALREADY_APPLIED"]:
    """One explicit Option B phase after verified park, before candidate start.

    The caller supplies a genuinely held SAME-OFD Boca lease and the exact
    legacy dev/inode from its Docker attestor. This function itself cannot
    park controllers, inspect foreign workloads, deploy or delete anything.
    """

    def verify_host() -> None:
        _uid()
        _held_canonical_lease(held_lease_fd)

    return _bootstrap_session(
        legacy_path, expected_db_identity, session_schema_bytes, verify_custody=verify_host
    )


def bootstrap_mounted_session(device: int, inode: int) -> Literal["APPLIED", "ALREADY_APPLIED"]:
    """Fixed data-only entry for a reviewed, network-none container under the host lease."""
    from importlib.resources import files

    sql = (
        files("boca_socios.panel.owner_session_sql")
        .joinpath("0001_owner_browser_session.sql")
        .read_bytes()
    )
    return _bootstrap_session(_MOUNTED_DATABASE, (device, inode), sql, verify_custody=_uid)


def _bootstrap_session(
    legacy_path: Path,
    expected_db_identity: tuple[int, int],
    session_schema_bytes: bytes,
    *,
    verify_custody: Callable[[], None],
) -> Literal["APPLIED", "ALREADY_APPLIED"]:
    try:
        verify_custody()
        statements = _schema_statements(session_schema_bytes)
        _legacy_contract(legacy_path, expected_db_identity)
        parent = legacy_path.parent
        directory = parent.lstat()
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != _UID
            or directory.st_mode & 0o022
        ):
            raise SessionDiskBootstrapUnavailable("Boca data directory unavailable")
        session_path = parent / _SESSION_NAME
        try:
            session_path.lstat()
            existed = True
        except FileNotFoundError:
            descriptor = os.open(
                session_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
            )
            os.close(descriptor)
            existed = False
        session_identity = _regular_identity(session_path)
        with closing(_connect(session_path, write=True)) as connection:
            if existed:
                _session_contract(connection, statements)
            else:
                if connection.execute("SELECT count(*) FROM sqlite_master").fetchone() != (0,):
                    raise SessionDiskBootstrapUnavailable("owner session schema unavailable")
                connection.execute("BEGIN IMMEDIATE")
                with connection:
                    connection.execute(statements[0])
                    connection.execute(statements[1])
                    connection.execute(
                        "INSERT INTO owner_session_schema(version,checksum) VALUES(1,?)",
                        (_SESSION_SCHEMA_SHA256,),
                    )
                    connection.execute("PRAGMA user_version=1")
                    _session_contract(connection, statements)
        verify_custody()
        _legacy_contract(legacy_path, expected_db_identity)
        if _regular_identity(session_path) != session_identity:
            raise SessionDiskBootstrapUnavailable("owner session inode changed")
        return "ALREADY_APPLIED" if existed else "APPLIED"
    except (OSError, sqlite3.Error, UnicodeError, ValueError, TypeError, OverflowError):
        raise SessionDiskBootstrapUnavailable(
            "independent Boca session bootstrap unavailable"
        ) from None
