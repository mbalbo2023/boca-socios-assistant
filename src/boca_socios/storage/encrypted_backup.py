"""Opt-in encrypted SQLite snapshot and offline restore; no runtime or CLI wiring.

The caller supplies an independent backup key from outside the repository.
Only bounded, authenticated archives are written, and restore creates a new
database in a private directory. Neither function replaces an existing file.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import stat
import time
from contextlib import closing
from importlib.resources import files
from pathlib import Path
from typing import NoReturn

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"BOCA-SQLITE-BACKUP\x00\x01"
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
_NONCE_BYTES = 12
_TAG_BYTES = 16
_HEADER_BYTES = len(MAGIC) + _NONCE_BYTES
_DEADLINE_SECONDS = 10.0
_KNOWN_MIGRATIONS = ("0001_initial.sql", "0002_notification_outbox.sql")
_OUTBOX_TABLES = frozenset({"notification_outbox", "notification_claim_windows"})


class BackupError(Exception):
    """A snapshot cannot be safely created or restored."""


def _fail(message: str) -> NoReturn:
    # Do not chain potentially sensitive SQLite or filesystem error details.
    raise BackupError(message) from None


def _arguments(path: Path, key: bytes, max_bytes: int) -> None:
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise ValueError("an absolute file path is required")
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("an independent 32-byte backup key is required")
    if not 0 < max_bytes <= MAX_SNAPSHOT_BYTES:
        raise ValueError("invalid snapshot limit")


def _private_directory(parent: Path) -> int:
    try:
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077:
            os.close(descriptor)
            _fail("backup directory must be private")
        return descriptor
    except OSError:
        _fail("backup directory is unavailable")


def _validate_sqlite(connection: sqlite3.Connection) -> None:
    try:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            _fail("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            _fail("SQLite foreign key check failed")
        rows = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        if not rows or len(rows) > len(_KNOWN_MIGRATIONS):
            _fail("SQLite migration chain is unsupported")
        migrations = files("boca_socios.storage.migrations")
        for version, (stored_version, checksum) in enumerate(rows, start=1):
            if stored_version != version:
                _fail("SQLite migration chain is incomplete or unsupported")
            script = migrations.joinpath(_KNOWN_MIGRATIONS[version - 1]).read_text(encoding="utf-8")
            expected = hashlib.sha256(script.encode("utf-8")).hexdigest()
            if checksum != expected:
                _fail("SQLite migration checksum mismatch")
        outbox_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' "
                "AND name IN ('notification_outbox', 'notification_claim_windows')"
            )
        }
        if outbox_tables != (_OUTBOX_TABLES if len(rows) == 2 else set()):
            _fail("SQLite migration schema is incomplete")
    except sqlite3.DatabaseError:
        _fail("SQLite snapshot is invalid")


def _stage(directory_fd: int, prefix: str) -> tuple[str, int]:
    for _ in range(3):
        name = prefix + secrets.token_hex(16)
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            return name, descriptor
        except FileExistsError:
            continue
        except OSError:
            _fail("private staging file could not be created")
    _fail("private staging file could not be created")


def _publish(directory_fd: int, staged: str, target: str) -> None:
    try:
        staged_stat = os.stat(staged, dir_fd=directory_fd, follow_symlinks=False)
        os.link(
            staged,
            target,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except OSError:
        _fail("destination exists or cannot be published")
    try:
        os.fsync(directory_fd)
    except OSError:
        # The link is already visible. Revoke only the inode that we staged;
        # another writer's replacement must be left for manual recovery.
        try:
            published_stat = os.stat(target, dir_fd=directory_fd, follow_symlinks=False)
            if (published_stat.st_dev, published_stat.st_ino) != (
                staged_stat.st_dev,
                staged_stat.st_ino,
            ):
                _fail("published destination changed; manual recovery required")
            os.unlink(target, dir_fd=directory_fd)
        except OSError:
            _fail("published destination could not be removed")
        _fail("destination exists or cannot be published")


def backup_database(
    database_path: Path,
    archive_path: Path,
    backup_key: bytes,
    *,
    max_bytes: int = MAX_SNAPSHOT_BYTES,
) -> None:
    """Create one authenticated backup of an existing SQLite database.

    An online SQLite backup copies WAL consistently into memory. A progress
    callback aborts growth or writer contention; an encrypted archive is then
    published atomically without overwriting an existing destination.
    """
    _arguments(database_path, backup_key, max_bytes)
    _arguments(archive_path, backup_key, max_bytes)
    if database_path == archive_path:
        raise ValueError("source and archive must differ")
    try:
        metadata = database_path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            _fail("SQLite source must be a regular file")
    except OSError:
        _fail("SQLite source is unavailable")

    directory_fd = _private_directory(archive_path.parent)
    try:
        started = time.monotonic()
        uri = database_path.as_uri() + "?mode=ro"
        try:
            with (
                closing(sqlite3.connect(uri, uri=True, timeout=5.0)) as source,
                closing(sqlite3.connect(":memory:")) as snapshot,
            ):
                page_size = int(source.execute("PRAGMA page_size").fetchone()[0])
                page_count = int(source.execute("PRAGMA page_count").fetchone()[0])
                if page_size * page_count > max_bytes:
                    _fail("SQLite snapshot exceeds size limit")

                def progress(_status: int, _remaining: int, total: int) -> None:
                    if total * page_size > max_bytes:
                        _fail("SQLite snapshot exceeds size limit")
                    if time.monotonic() - started > _DEADLINE_SECONDS:
                        _fail("SQLite snapshot timed out")

                source.backup(snapshot, pages=128, progress=progress, sleep=0.01)
                _validate_sqlite(snapshot)
                # SQLite's backup API preserves the WAL header bytes even in
                # an in-memory connection. VACUUM makes a self-contained
                # rollback-journal image that deserialize can reopen later.
                snapshot.set_progress_handler(
                    lambda: int(time.monotonic() - started > _DEADLINE_SECONDS), 1000
                )
                snapshot.execute("VACUUM")
                _validate_sqlite(snapshot)
                image = snapshot.serialize()
        except sqlite3.DatabaseError:
            _fail("SQLite source cannot be backed up")
        if len(image) > max_bytes:
            _fail("SQLite snapshot exceeds size limit")

        nonce = os.urandom(_NONCE_BYTES)
        header = MAGIC + nonce
        archive = header + AESGCM(backup_key).encrypt(nonce, image, header)
        name, descriptor = _stage(directory_fd, ".boca-backup-")
        try:
            with os.fdopen(descriptor, "wb") as target:
                target.write(archive)
                target.flush()
                os.fsync(target.fileno())
            _publish(directory_fd, name, archive_path.name)
        finally:
            os.unlink(name, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


def _read_archive(directory_fd: int, name: str, max_bytes: int) -> bytes:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        with os.fdopen(descriptor, "rb") as archive:
            metadata = os.fstat(archive.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                _fail("encrypted archive must be a private regular file")
            if (
                not _HEADER_BYTES + _TAG_BYTES
                < metadata.st_size
                <= (_HEADER_BYTES + _TAG_BYTES + max_bytes)
            ):
                _fail("encrypted archive exceeds size limit or is incomplete")
            payload = archive.read(_HEADER_BYTES + _TAG_BYTES + max_bytes + 1)
            if len(payload) != metadata.st_size:
                _fail("encrypted archive changed while reading")
            return payload
    except OSError:
        _fail("encrypted archive is unavailable")


def restore_database(
    archive_path: Path,
    new_database_path: Path,
    backup_key: bytes,
    *,
    max_bytes: int = MAX_SNAPSHOT_BYTES,
) -> None:
    """Authenticate and restore an archive to a previously absent DB path.

    Never call this against a live database. The credential master key is
    intentionally absent: a separate key-custody rehearsal must verify that
    the restored credentials remain decryptable after restart.
    """
    _arguments(archive_path, backup_key, max_bytes)
    _arguments(new_database_path, backup_key, max_bytes)
    if archive_path == new_database_path:
        raise ValueError("archive and restored database must differ")
    archive_directory_fd = _private_directory(archive_path.parent)
    try:
        payload = _read_archive(archive_directory_fd, archive_path.name, max_bytes)
    finally:
        os.close(archive_directory_fd)
    header = payload[:_HEADER_BYTES]
    if not header.startswith(MAGIC):
        _fail("unsupported encrypted archive")
    nonce = header[len(MAGIC) :]
    try:
        image = AESGCM(backup_key).decrypt(nonce, payload[_HEADER_BYTES:], header)
    except (InvalidTag, ValueError):
        _fail("encrypted archive authentication failed")
    if len(image) > max_bytes:
        _fail("SQLite snapshot exceeds size limit")

    target_directory_fd = _private_directory(new_database_path.parent)
    try:
        try:
            with closing(sqlite3.connect(":memory:")) as snapshot:
                snapshot.deserialize(image)
                _validate_sqlite(snapshot)
                name, descriptor = _stage(target_directory_fd, ".boca-restore-")
                os.close(descriptor)
                try:
                    staged_path = new_database_path.parent / name
                    with closing(sqlite3.connect(staged_path, timeout=5.0)) as staged:
                        snapshot.backup(staged)
                        _validate_sqlite(staged)
                    sync_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=target_directory_fd)
                    try:
                        os.fsync(sync_fd)
                    finally:
                        os.close(sync_fd)
                    _publish(target_directory_fd, name, new_database_path.name)
                finally:
                    os.unlink(name, dir_fd=target_directory_fd)
        except sqlite3.DatabaseError:
            _fail("SQLite snapshot cannot be restored")
    finally:
        os.close(target_directory_fd)
