"""Only an existing, exact BETA ledger may gain Telegram schema 0007."""

from __future__ import annotations

import hashlib
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from boca_socios import telegram_storage_gate as gate


def _existing(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        for version, filename in enumerate(gate.MIGRATIONS[:6], 1):
            sql = files("boca_socios.storage.migrations").joinpath(filename).read_text()
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (?, ?)",
                (version, hashlib.sha256(sql.encode()).hexdigest()),
            )
    path.chmod(0o600)


def test_migrate_existing_beta_once_without_recreating_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boca.sqlite3"
    _existing(path)
    identity = path.stat().st_ino
    monkeypatch.setattr(gate, "_identity", lambda _path: (1, identity))
    gate.migrate(path)
    gate.verify(path)
    gate.migrate(path)
    assert path.stat().st_ino == identity
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone() == (7,)


def test_unknown_or_checksum_mismatch_never_migrates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boca.sqlite3"
    _existing(path)
    monkeypatch.setattr(gate, "_identity", lambda _path: (1, 1))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE schema_migrations SET checksum='bad' WHERE version=6")
    with pytest.raises(gate.StorageGateError):
        gate.migrate(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone() == (6,)

    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO schema_migrations(version, checksum) VALUES (8, 'unknown')")
    with pytest.raises(gate.StorageGateError):
        gate.migrate(path)
