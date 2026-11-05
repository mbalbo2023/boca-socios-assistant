"""Durable singleton owner authorization; no Chrome token plaintext in SQLite."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from boca_socios.panel.owner_session_store import (
    OwnerBrowserSessionStore,
    OwnerSessionStorageUnavailable,
    session_database_path,
)
from boca_socios.storage.database import Database


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("ascii")).digest()


def test_explicit_separate_session_schema_singleton_replacement_and_revoke() -> None:
    with TemporaryDirectory() as temporary:
        db = Database(Path(temporary) / "boca.sqlite3")
        store = OwnerBrowserSessionStore(db, owner_subject="owner")
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.verify_schema()
        assert not db.path.exists()  # A read cannot create the SQLite file.
        db.migrate()
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.verify_schema()
        previous_legacy = db.path.read_bytes()
        store.migrate()
        store.verify_schema()
        assert store.session_database_path == Path(temporary) / "boca_owner_session.sqlite3"
        assert store.session_database_path.stat().st_mode & 0o777 == 0o600
        with db.connection() as connection:
            assert connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall() == [(1,)]  # Never writes 0008 or a session table into legacy.
            assert (
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='owner_browser_session'"
                ).fetchone()
                is None
            )
        assert db.path.read_bytes() == previous_legacy
        with sqlite3.connect(store.session_database_path) as connection:
            assert connection.execute("SELECT version FROM owner_session_schema").fetchall() == [
                (1,)
            ]
        first, second, verifier = _digest("cookie1"), _digest("cookie2"), _digest("passkey")
        assert not store.matches(first, verifier)
        store.replace(first, verifier)
        assert store.matches(first, verifier)
        with sqlite3.connect(store.session_database_path) as connection:
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
        assert db.path.read_bytes() == previous_legacy


def test_durable_owner_binding_and_corrupt_schema_fail_closed() -> None:
    with TemporaryDirectory() as temporary:
        db = Database(Path(temporary) / "boca.sqlite3")
        db.migrate()
        store = OwnerBrowserSessionStore(db, owner_subject="owner")
        store.migrate()
        token, binding = _digest("cookie"), _digest("passkey1")
        store.replace(token, binding)
        assert not store.matches(token, _digest("passkey2"))
        other_owner = OwnerBrowserSessionStore(db, owner_subject="another-owner")
        assert not other_owner.matches(token, binding)
        with sqlite3.connect(store.session_database_path) as connection, connection:
            connection.execute("UPDATE owner_session_schema SET checksum=?", ("f" * 64,))
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
        db.migrate()
        store = OwnerBrowserSessionStore(db, owner_subject="owner")
        store.migrate()
        session_path = store.session_database_path
        original = directory / "preserved-session.sqlite3"
        session_path.rename(original)
        session_path.symlink_to(original)
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.verify_schema()
        with pytest.raises(ValueError):
            store.replace(b"short", _digest("binding"))
        session_path.unlink()
        original.rename(session_path)
        # A hardlinked or group-readable bearer database is never adopted.
        linked = directory / "extra-hardlink.sqlite3"
        os.link(session_path, linked)
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.verify_schema()
        linked.unlink()
        session_path.chmod(0o640)
        with pytest.raises(OwnerSessionStorageUnavailable):
            store.verify_schema()


def test_schema_only_first_install_requires_no_registered_owner_yet() -> None:
    with TemporaryDirectory() as temporary:
        database = Database(Path(temporary) / "boca.sqlite3")
        database.migrate()
        OwnerBrowserSessionStore.migrate_schema(database)
        OwnerBrowserSessionStore.migrate_schema(database)
        OwnerBrowserSessionStore(database, owner_subject="future-owner").verify_schema()
        with database.connection() as connection:
            assert connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall() == [(1,)]


def test_bootstrap_never_creates_legacy_db_or_repairs_partial_session(tmp_path: Path) -> None:
    db = Database(tmp_path / "boca.sqlite3")
    with pytest.raises(OwnerSessionStorageUnavailable):
        OwnerBrowserSessionStore.migrate_schema(db)
    assert not db.path.exists()
    assert not session_database_path(db.path).exists()
    db.migrate()
    session_path = session_database_path(db.path)
    session_path.touch(mode=0o600)
    with pytest.raises(OwnerSessionStorageUnavailable):
        OwnerBrowserSessionStore.migrate_schema(db)
    assert session_path.stat().st_size == 0
    with db.connection() as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,)]


@pytest.mark.parametrize(
    "extra_sql",
    [
        "CREATE VIEW extra AS SELECT 1",
        "CREATE TRIGGER extra AFTER INSERT ON owner_browser_session BEGIN SELECT 1; END",
    ],
)
def test_session_schema_rejects_extra_views_or_triggers(tmp_path: Path, extra_sql: str) -> None:
    db = Database(tmp_path / "boca.sqlite3")
    db.migrate()
    store = OwnerBrowserSessionStore(db, owner_subject="owner")
    store.migrate()
    with sqlite3.connect(store.session_database_path) as connection:
        connection.execute(extra_sql)
    with pytest.raises(OwnerSessionStorageUnavailable):
        store.verify_schema()
    with pytest.raises(OwnerSessionStorageUnavailable):
        store.migrate()
