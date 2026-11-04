"""Durable singleton owner authorization; no Chrome token plaintext in SQLite."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from boca_socios.panel.owner_session_store import (
    OwnerBrowserSessionStore,
    OwnerSessionStorageUnavailable,
)
from boca_socios.storage.database import Database


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("ascii")).digest()


def test_explicit_0008_migration_singleton_owner_replacement_and_revoke() -> None:
    with TemporaryDirectory() as temporary:
        db = Database(Path(temporary) / "boca.sqlite3")
        store = OwnerBrowserSessionStore(db, owner_subject="owner")
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.verify_schema()
        assert not db.path.exists()  # A read cannot create the SQLite file.
        db.migrate()
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.verify_schema()
        store.migrate()
        store.verify_schema()
        with db.connection() as connection:
            assert connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall() == [(1,), (8,)]  # Does NOT presume Telegram's 0007.
        first, second, verifier = _digest("cookie1"), _digest("cookie2"), _digest("passkey")
        assert not store.matches(first, verifier)
        store.replace(first, verifier)
        assert store.matches(first, verifier)
        with db.connection() as connection:
            row = connection.execute(
                "SELECT token_sha256, verifier_sha256 FROM owner_browser_session"
            ).fetchone()
        assert row == (first, verifier) and b"cookie1" not in row
        store.replace(second, verifier)
        assert not store.matches(first, verifier)
        assert store.matches(second, verifier)
        store.revoke_matching(first, verifier)  # A stale logout cannot revoke replacement.
        assert store.matches(second, verifier)
        store.revoke_matching(second, verifier)
        assert not store.matches(second, verifier)
        store.migrate()
        store.verify_schema()  # Idempotent, no user-session recreation.


def test_durable_owner_binding_and_corrupt_schema_fail_closed() -> None:
    with TemporaryDirectory() as temporary:
        db = Database(Path(temporary) / "boca.sqlite3")
        store = OwnerBrowserSessionStore(db, owner_subject="owner")
        store.migrate()
        token, binding = _digest("cookie"), _digest("passkey1")
        store.replace(token, binding)
        assert not store.matches(token, _digest("passkey2"))
        other_owner = OwnerBrowserSessionStore(db, owner_subject="another-owner")
        assert not other_owner.matches(token, binding)
        with db.connection() as connection, connection:
            connection.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=8")
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.matches(token, binding)
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.replace(token, binding)
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.migrate()


def test_owner_browser_session_store_rejects_symlink_and_invalid_hashes() -> None:
    with TemporaryDirectory() as temporary:
        directory = Path(temporary)
        db = Database(directory / "real.sqlite3")
        store = OwnerBrowserSessionStore(db, owner_subject="owner")
        store.migrate()
        linked = directory / "linked.sqlite3"
        linked.symlink_to(db.path)
        with pytest.raises(OwnerSessionStorageUnavailable):
            OwnerBrowserSessionStore(Database(linked), owner_subject="owner").verify_schema()
        with pytest.raises(ValueError):
            store.replace(b"short", _digest("binding"))


def test_schema_only_first_install_requires_no_registered_owner_yet() -> None:
    with TemporaryDirectory() as temporary:
        database = Database(Path(temporary) / "boca.sqlite3")
        OwnerBrowserSessionStore.migrate_schema(database)
        OwnerBrowserSessionStore.migrate_schema(database)
        OwnerBrowserSessionStore(database, owner_subject="future-owner").verify_schema()
