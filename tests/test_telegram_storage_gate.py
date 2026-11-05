"""Only an existing, exact BETA ledger may gain Telegram schema 0007."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import sqlite3
from contextlib import closing
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios import telegram_storage_gate as gate
from boca_socios.config import Settings
from boca_socios.domain.policy import TicketIntent
from boca_socios.integration.operational import validate_existing_beta_storage
from boca_socios.notify.outbox import NoticeKind, NotificationRequest
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_transport import TelegramAck, TelegramNotice
from boca_socios.runtime import SIMULATION_EVENT_ID, initialize_beta
from boca_socios.security.credential_rewrap import CredentialKeyRewrapper
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.storage.database import Database
from boca_socios.telegram_one_shot import deliver_once


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


def _real_beta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Run the same initializer as `python -m boca_socios.runtime init-beta`."""
    path, key = tmp_path / "boca.sqlite3", tmp_path / "synthetic.key"
    key.write_bytes(base64.b64encode(b"b" * 32))
    key.chmod(0o400)
    initialize_beta(Settings("staging", "simulation", path, key))
    # The local test executor is not UID10001. Keep real dev/inode checks;
    # only the host-specific custody wrapper is replaced, not any schema code.
    monkeypatch.setattr(gate, "_identity", lambda file: (file.stat().st_dev, file.stat().st_ino))
    assert _versions(path) == [1, 2, 3, 5, 6]
    return path, key


def _versions(path: Path) -> list[int]:
    with closing(sqlite3.connect(path)) as connection:
        return [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]


def _dump(path: Path) -> tuple[str, ...]:
    with closing(sqlite3.connect(path)) as connection:
        return tuple(connection.iterdump())


def _optional_key_policy(path: Path, key: Path) -> None:
    CredentialKeyRewrapper(
        Database(path),
        CredentialVault.from_secret_file(key),
        CredentialVault(b"n" * 32, key_id="v2"),
    ).migrate()


def _optional_owner_session(path: Path) -> None:
    """Simulate reviewed opt-in 0008 without owning the panel's migration file."""
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE owner_browser_session (
              singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
              token_sha256 BLOB NOT NULL CHECK (length(token_sha256) = 32),
              verifier_sha256 BLOB NOT NULL CHECK (length(verifier_sha256) = 32),
              owner_sha256 BLOB NOT NULL CHECK (length(owner_sha256) = 32),
              authenticated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, checksum) VALUES (?, ?)",
            (8, gate._OWNER_SESSION_CHECKSUM),
        )


@pytest.mark.parametrize("key_policy", [False, True])
@pytest.mark.parametrize("telegram_first", [False, True])
def test_opt_in_owner_session_schema_is_compatible_without_telegram_creating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key_policy: bool,
    telegram_first: bool,
) -> None:
    path, key = _real_beta(tmp_path, monkeypatch)
    if key_policy:
        _optional_key_policy(path, key)
    if telegram_first:
        gate.migrate(path)
    _optional_owner_session(path)
    before = _dump(path)
    gate.migrate(path)
    gate.verify(path)
    expected = sorted([1, 2, 3, 5, 6, 7, 8, *([4] if key_policy else [])])
    assert _versions(path) == expected
    after = _dump(path)
    assert any('INSERT INTO "schema_migrations" VALUES(8,' in row for row in after)
    assert any("CREATE TABLE owner_browser_session" in row for row in after)
    gate.migrate(path)
    assert _dump(path) == after
    if telegram_first:
        assert before == after


@pytest.mark.parametrize(
    ("invalid", "error"),
    [
        ("checksum", "schema_checksum"),
        ("table_missing", "schema_tables"),
        ("future_9", "schema_ledger"),
    ],
)
def test_opt_in_owner_session_rejects_tampering_and_future_ledgers_before_any_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
    error: str,
) -> None:
    path, key = _real_beta(tmp_path, monkeypatch)
    _optional_key_policy(path, key)
    _optional_owner_session(path)
    if invalid == "checksum":
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE schema_migrations SET checksum='bad' WHERE version=8")
    elif invalid == "table_missing":
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TABLE owner_browser_session")
    elif invalid == "future_9":
        gate.migrate(path)
        with sqlite3.connect(path) as connection:
            connection.execute("INSERT INTO schema_migrations(version,checksum) VALUES(9,'future')")
    before = _dump(path)
    monkeypatch.setattr(
        gate.TelegramDeliveryCoordinator,
        "prepare_storage",
        lambda _: pytest.fail("unreviewed migration reached Telegram DDL"),
    )
    with pytest.raises(gate.StorageGateError, match=error):
        gate.migrate(path)
    assert _dump(path) == before


@pytest.mark.parametrize("key_policy", [False, True])
def test_real_beta_initializer_can_enable_telegram_without_activating_key_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key_policy: bool,
) -> None:
    path, key = _real_beta(tmp_path, monkeypatch)
    database = Database(path)
    vault = CredentialVault.from_secret_file(key)
    database.create_member("fixture-member", "fixture@example.invalid", "synthetic-consent")
    credential = vault.seal("synthetic-only-password", member_id="fixture-member")
    database.save_credential("fixture-member", credential)
    request = database.request_ticket(TicketIntent("fixture-member", SIMULATION_EVENT_ID))
    outbox = SqliteNotificationOutbox(database)
    notice = outbox.enqueue(
        NotificationRequest(uuid4(), NoticeKind.HEARTBEAT), now=10.0, ttl_seconds=600
    )
    if key_policy:
        _optional_key_policy(path, key)
    prior_versions, identity, key_bytes = _versions(path), path.stat().st_ino, key.read_bytes()
    gate.verify(path, require_telegram=False)
    gate.migrate(path)
    gate.verify(path)
    validate_existing_beta_storage(path)
    assert _versions(path) == sorted([*prior_versions, 7])
    assert path.stat().st_ino == identity
    assert key.read_bytes() == key_bytes and key.stat().st_mode & 0o777 == 0o400
    assert database.get_credential("fixture-member") == credential
    assert database.request_ticket(TicketIntent("fixture-member", SIMULATION_EVENT_ID)) == request
    assert outbox.get(notice.idempotency_key) == notice
    with closing(sqlite3.connect(path)) as connection:
        policy = connection.execute(
            "SELECT name FROM sqlite_master WHERE name='credential_key_policy'"
        ).fetchone()
        assert (policy is not None) is key_policy
        assert connection.execute("SELECT COUNT(*) FROM telegram_delivery_attempts").fetchone() == (
            0,
        )
    before = _dump(path)
    gate.migrate(path)
    assert _dump(path) == before and path.stat().st_ino == identity


@pytest.mark.parametrize("missing", [1, 2, 3, 5, 6])
def test_real_beta_gate_rejects_missing_required_migration_before_any_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: int,
) -> None:
    path, _ = _real_beta(tmp_path, monkeypatch)
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version=?", (missing,))
    before = _dump(path)
    monkeypatch.setattr(
        gate.TelegramDeliveryCoordinator,
        "prepare_storage",
        lambda _: pytest.fail("invalid BETA reached DDL"),
    )
    with pytest.raises(gate.StorageGateError, match="schema_ledger"):
        gate.migrate(path)
    assert _dump(path) == before


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6, 7])
def test_real_beta_gate_checks_every_actual_version_hash_before_any_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: int,
) -> None:
    path, key = _real_beta(tmp_path, monkeypatch)
    if version == 4:
        _optional_key_policy(path, key)
    if version == 7:
        gate.migrate(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum='bad' WHERE version=?", (version,)
        )
    before = _dump(path)
    monkeypatch.setattr(
        gate.TelegramDeliveryCoordinator,
        "prepare_storage",
        lambda _: pytest.fail("checksum mismatch reached DDL"),
    )
    with pytest.raises(gate.StorageGateError, match="schema_checksum"):
        gate.migrate(path)
    assert _dump(path) == before


@pytest.mark.parametrize("change", ["unknown", "duplicate", "wrong-type"])
def test_real_beta_gate_rejects_unknown_duplicate_or_malformed_ledger_before_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    path, _ = _real_beta(tmp_path, monkeypatch)
    with sqlite3.connect(path) as connection:
        if change == "unknown":
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES(9,'unknown')"
            )
        else:
            connection.execute("ALTER TABLE schema_migrations RENAME TO old_ledger")
            connection.execute("CREATE TABLE schema_migrations(version,checksum,applied_at)")
            connection.execute("INSERT INTO schema_migrations SELECT * FROM old_ledger")
            if change == "duplicate":
                connection.execute(
                    "INSERT INTO schema_migrations SELECT * FROM old_ledger WHERE version=1"
                )
            else:
                connection.execute("UPDATE schema_migrations SET version='six' WHERE version=6")
    before = _dump(path)
    monkeypatch.setattr(
        gate.TelegramDeliveryCoordinator,
        "prepare_storage",
        lambda _: pytest.fail("unreviewed ledger reached DDL"),
    )
    with pytest.raises(gate.StorageGateError, match="schema_ledger"):
        gate.migrate(path)
    assert _dump(path) == before


def test_real_beta_gate_preserves_existing_accepted_delivery_fence_on_repeated_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _ = _real_beta(tmp_path, monkeypatch)
    gate.migrate(path)
    sent: list[TelegramNotice] = []

    class OfflineSender:
        def preflight(self) -> None:
            pass

        async def send(self, notice: TelegramNotice) -> TelegramAck:
            sent.append(notice)
            return TelegramAck(42)

    assert asyncio.run(deliver_once(path, OfflineSender(), "a" * 40)) == "API_ACCEPTED"
    before, identity = _dump(path), path.stat().st_ino
    gate.migrate(path)
    gate.verify(path)
    assert _dump(path) == before and path.stat().st_ino == identity and len(sent) == 1
    assert _versions(path) == [1, 2, 3, 5, 6, 7]
