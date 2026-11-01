"""Migration rejection must precede schema/journal/permission mutations."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from boca_socios.storage.database import Database

CHECKS = TestCase()


def _legacy(path: Path, *, ledger: bool = True) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE sentinel(value TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('synthetic')")
        if ledger:
            connection.execute(
                "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT)"
            )
            connection.execute("INSERT INTO schema_migrations VALUES (1, 'wrong')")
    path.chmod(0o640)


def _snapshot(path: Path) -> tuple[bytes, int, tuple[str, ...]]:
    return path.read_bytes(), path.stat().st_mode, tuple(sorted(p.name for p in path.parent.iterdir()))


def test_checksum_rejection_precedes_schema_wal_and_chmod(tmp_path: Path) -> None:
    path = tmp_path / "existing.sqlite"
    _legacy(path)
    before = _snapshot(path)
    with CHECKS.assertRaisesRegex(ValueError, "checksum"):
        Database(path).migrate()
    assert _snapshot(path) == before
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("SELECT * FROM sentinel").fetchall() == [("synthetic",)]
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='members'"
        ).fetchone() == (0,)


def test_unversioned_database_is_not_adopted(tmp_path: Path) -> None:
    path = tmp_path / "foreign.sqlite"
    _legacy(path, ledger=False)
    before = _snapshot(path)
    with CHECKS.assertRaisesRegex(ValueError, "migration"):
        Database(path).migrate()
    assert _snapshot(path) == before


def test_corrupt_and_non_sqlite_files_are_not_modified(tmp_path: Path) -> None:
    for index, data in enumerate((b"not a database", b"SQLite format 3\x00" + b"x" * 128)):
        path = tmp_path / f"invalid-{index}.sqlite"
        path.write_bytes(data)
        path.chmod(0o640)
        before = _snapshot(path)
        with CHECKS.assertRaises((ValueError, sqlite3.DatabaseError)):
            Database(path).migrate()
        assert _snapshot(path) == before


def test_fresh_creation_and_repeat_preserve_data_and_migration(tmp_path: Path) -> None:
    path = tmp_path / "new" / "boca.sqlite"
    db = Database(path)
    db.migrate()
    db.create_member("synthetic", "synthetic@example.invalid", "synthetic")
    with db.connection() as connection:
        first = connection.execute("SELECT * FROM schema_migrations").fetchall()
    db.migrate()
    with db.connection() as connection:
        assert connection.execute("SELECT * FROM schema_migrations").fetchall() == first
        assert connection.execute("SELECT count(*) FROM members").fetchone() == (1,)
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    assert path.stat().st_mode & 0o777 == 0o600


def test_write_connection_rechecks_checksum_after_readonly_preflight(tmp_path: Path) -> None:
    path = tmp_path / "changed.sqlite"
    db = Database(path)
    db.migrate()
    original_connect = sqlite3.connect
    with closing(original_connect(path)) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
    path.chmod(0o640)
    mutated = False

    def connect(database: object, **kwargs: object) -> sqlite3.Connection:
        nonlocal mutated
        if "mode=rw" in str(database) and not mutated:
            mutated = True
            with closing(original_connect(path)) as other, other:
                other.execute("UPDATE schema_migrations SET checksum='changed'")
        return original_connect(database, **kwargs)  # type: ignore[arg-type]

    with patch("boca_socios.storage.database.sqlite3.connect", side_effect=connect):
        with CHECKS.assertRaisesRegex(ValueError, "checksum"):
            db.migrate()
    assert mutated
    with closing(original_connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    assert path.stat().st_mode & 0o777 == 0o640


def test_symlink_rejection_does_not_change_target(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite"
    _legacy(target)
    path = tmp_path / "alias.sqlite"
    path.symlink_to(target)
    before = _snapshot(target)
    with CHECKS.assertRaisesRegex(ValueError, "symlink"):
        Database(path).migrate()
    assert _snapshot(target) == before
