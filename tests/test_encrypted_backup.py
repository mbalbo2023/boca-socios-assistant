"""Offline recovery contract using synthetic records and disposable databases."""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from boca_socios.domain.policy import TicketIntent
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.storage.database import Database
from boca_socios.storage.encrypted_backup import (
    MAGIC,
    BackupError,
    backup_database,
    restore_database,
)


def _source(path: Path) -> tuple[Database, CredentialVault, str]:
    database = Database(path)
    database.migrate()
    database.create_member("member-1", "test@example.invalid", "2026-10-28T12:00:00Z")
    database.create_event("event-1", "Synthetic event")
    database.request_ticket(TicketIntent(member_id="member-1", event_id="event-1"))
    vault = CredentialVault(os.urandom(32))
    password = os.urandom(24).hex()
    database.save_credential("member-1", vault.seal(password, member_id="member-1"))
    return database, vault, password


def test_wal_snapshot_roundtrip_without_plaintext_in_archive(tmp_path: Path) -> None:
    source, vault, password = _source(tmp_path / "source.db")
    archive = tmp_path / "snapshot.enc"
    restored = tmp_path / "restored.db"
    backup_key = os.urandom(32)

    with source.connection() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    backup_database(source.path, archive, backup_key)
    payload = archive.read_bytes()
    assert b"test@example.invalid" not in payload
    assert b"member-1" not in payload
    assert password.encode() not in payload
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600

    restore_database(archive, restored, backup_key)
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600
    recovered = Database(restored)
    with recovered.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM ticket_requests").fetchone() == (1,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    sealed = recovered.get_credential("member-1")
    assert sealed is not None
    assert vault.open(sealed, member_id="member-1") == password


@pytest.mark.parametrize("change", ["wrong_key", "tamper", "truncate"])
def test_authentication_failure_never_publishes_database(tmp_path: Path, change: str) -> None:
    source, _, _ = _source(tmp_path / "source.db")
    archive = tmp_path / "snapshot.enc"
    key = os.urandom(32)
    backup_database(source.path, archive, key)
    if change == "wrong_key":
        key = os.urandom(32)
    elif change == "tamper":
        payload = bytearray(archive.read_bytes())
        payload[-20] ^= 0x01
        archive.write_bytes(payload)
    else:
        archive.write_bytes(archive.read_bytes()[:-8])

    restored = tmp_path / "restored.db"
    with pytest.raises(BackupError):
        restore_database(archive, restored, key)
    assert not restored.exists()
    assert not list(tmp_path.glob(".boca-restore-*"))


def test_refuses_to_overwrite_backup_or_existing_database(tmp_path: Path) -> None:
    source, _, _ = _source(tmp_path / "source.db")
    key = os.urandom(32)
    archive = tmp_path / "snapshot.enc"
    archive.write_bytes(b"existing file")
    with pytest.raises(BackupError):
        backup_database(source.path, archive, key)
    assert archive.read_bytes() == b"existing file"

    archive.unlink()
    backup_database(source.path, archive, key)
    restored = tmp_path / "restored.db"
    restored.write_bytes(b"existing database")
    with pytest.raises(BackupError):
        restore_database(archive, restored, key)
    assert restored.read_bytes() == b"existing database"


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_directory_sync_failure_does_not_publish_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    source, _, _ = _source(tmp_path / "source.db")
    key = os.urandom(32)
    archive = tmp_path / "snapshot.enc"
    if operation == "restore":
        backup_database(source.path, archive, key)
    target = archive if operation == "backup" else tmp_path / "restored.db"

    original_fsync = os.fsync

    def fail_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory sync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory_sync)
    with pytest.raises(BackupError, match="published"):
        if operation == "backup":
            backup_database(source.path, archive, key)
        else:
            restore_database(archive, target, key)
    assert not target.exists()
    assert not list(tmp_path.glob(".boca-backup-*"))
    assert not list(tmp_path.glob(".boca-restore-*"))


def test_failed_publication_preserves_a_replaced_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _, _ = _source(tmp_path / "source.db")
    archive = tmp_path / "snapshot.enc"
    replacement = b"another writer's file"
    original_fsync = os.fsync

    def replace_before_failure(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            archive.unlink()
            archive.write_bytes(replacement)
            raise OSError("synthetic directory sync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", replace_before_failure)
    with pytest.raises(BackupError, match="manual recovery"):
        backup_database(source.path, archive, os.urandom(32))
    assert archive.read_bytes() == replacement
    assert not list(tmp_path.glob(".boca-backup-*"))


def test_refuses_symlink_sources_and_destinations(tmp_path: Path) -> None:
    source, _, _ = _source(tmp_path / "source.db")
    key = os.urandom(32)
    alias = tmp_path / "alias.db"
    alias.symlink_to(source.path)
    archive = tmp_path / "snapshot.enc"
    with pytest.raises(BackupError):
        backup_database(alias, archive, key)
    assert not archive.exists()

    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"untouched")
    archive.symlink_to(sentinel)
    with pytest.raises(BackupError):
        backup_database(source.path, archive, key)
    assert sentinel.read_bytes() == b"untouched"
    archive.unlink()
    backup_database(source.path, archive, key)
    alias_archive = tmp_path / "alias.enc"
    alias_archive.symlink_to(archive)
    with pytest.raises(BackupError):
        restore_database(alias_archive, tmp_path / "restored.db", key)


def test_size_limit_fails_closed_in_both_directions(tmp_path: Path) -> None:
    source, _, _ = _source(tmp_path / "source.db")
    archive = tmp_path / "snapshot.enc"
    key = os.urandom(32)
    with pytest.raises(BackupError):
        backup_database(source.path, archive, key, max_bytes=4096)
    assert not archive.exists()
    backup_database(source.path, archive, key)
    with pytest.raises(BackupError):
        restore_database(archive, tmp_path / "restored.db", key, max_bytes=4096)
    assert not (tmp_path / "restored.db").exists()


def test_authenticated_non_database_payload_is_rejected(tmp_path: Path) -> None:
    key = os.urandom(32)
    nonce = os.urandom(12)
    header = MAGIC + nonce
    archive = tmp_path / "snapshot.enc"
    archive.write_bytes(header + AESGCM(key).encrypt(nonce, b"not a SQLite image", header))
    archive.chmod(0o600)
    with pytest.raises(BackupError):
        restore_database(archive, tmp_path / "restored.db", key)
    assert not (tmp_path / "restored.db").exists()


@pytest.mark.parametrize("corruption", ["foreign_key", "migration_checksum"])
def test_inconsistent_source_is_not_backed_up(tmp_path: Path, corruption: str) -> None:
    source, _, _ = _source(tmp_path / "source.db")
    with sqlite3.connect(source.path) as connection:
        if corruption == "foreign_key":
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                "INSERT INTO ticket_requests(request_id, member_id, event_id, quantity) "
                "VALUES ('orphan', 'absent', 'event-1', 1)"
            )
        else:
            connection.execute("UPDATE schema_migrations SET checksum = 'wrong' WHERE version = 1")
    archive = tmp_path / "snapshot.enc"
    with pytest.raises(BackupError):
        backup_database(source.path, archive, os.urandom(32))
    assert not archive.exists()


def test_backup_key_and_private_directory_are_required(tmp_path: Path) -> None:
    source, _, _ = _source(tmp_path / "source.db")
    archive = tmp_path / "snapshot.enc"
    with pytest.raises(ValueError):
        backup_database(source.path, archive, b"short")
    public_dir = tmp_path / "public"
    public_dir.mkdir(mode=0o755)
    with pytest.raises(BackupError):
        backup_database(source.path, public_dir / "snapshot.enc", os.urandom(32))
    assert not (public_dir / "snapshot.enc").exists()
