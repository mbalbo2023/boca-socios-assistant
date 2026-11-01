"""Bounded, offline status projection; never a Boca or host observation."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from boca_socios.domain.policy import TicketIntent
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_delivery import TelegramDeliveryCoordinator
from boca_socios.panel.local_status import LocalStatusUnavailable, read_local_status
from boca_socios.storage.database import Database

NOW = datetime(2026, 10, 31, 15, 0, tzinfo=UTC)


def _database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "private" / "boca.sqlite3")
    db.migrate()
    return db


def _intent(db: Database, member: str, event: str) -> None:
    db.create_member(member, f"{member}@invalid.test", "2026-10-31T00:00:00Z")
    db.create_event(event, "Partido privado")
    db.request_ticket(TicketIntent(member, event))


def test_empty_database_is_typed_unknown_age_and_does_not_change_database(tmp_path: Path) -> None:
    db = _database(tmp_path)
    before = db.path.read_bytes()

    snapshot = read_local_status(db.path, observed_at=NOW)

    assert snapshot.source == "local_sqlite_intents"
    assert snapshot.external_confirmation == "not_observed"
    assert snapshot.local_data_age == "empty"
    assert snapshot.last_local_update_at is None
    assert snapshot.counts.total == 0
    assert db.path.read_bytes() == before


def test_only_aggregate_local_states_leave_database_without_identity_or_secrets(
    tmp_path: Path,
) -> None:
    db = _database(tmp_path)
    _intent(db, "private-member-001", "private-match-001")
    _intent(db, "private-member-002", "private-match-002")
    with db.connection() as connection, connection:
        connection.execute(
            "UPDATE ticket_requests SET status='reserved', updated_at='2026-10-31 14:59:00' "
            "WHERE member_id='private-member-001'"
        )
        connection.execute(
            "UPDATE ticket_requests SET status='queued', updated_at='2026-10-31 14:58:00' "
            "WHERE member_id='private-member-002'"
        )
        connection.execute(
            "INSERT INTO credentials(member_id, key_id, nonce, ciphertext) VALUES (?, ?, ?, ?)",
            ("private-member-001", "v1", b"n" * 12, b"secret-ciphertext-sentinel"),
        )

    snapshot = read_local_status(db.path, observed_at=NOW)
    exposed = json.dumps(asdict(snapshot), default=str)

    assert snapshot.local_data_age == "recent"
    assert snapshot.counts.total == 2
    assert snapshot.counts.local_queued == 1
    assert snapshot.counts.local_result_recorded_unverified == 1
    assert snapshot.external_confirmation == "not_observed"
    for private in (
        "private-member",
        "private-match",
        "invalid.test",
        "Partido privado",
        "secret-ciphertext-sentinel",
        str(db.path),
        '"reserved"',
    ):
        assert private not in exposed


def test_stale_refers_only_to_age_of_last_local_intent_write(tmp_path: Path) -> None:
    db = _database(tmp_path)
    _intent(db, "member-1", "event-1")
    with db.connection() as connection, connection:
        connection.execute("UPDATE ticket_requests SET updated_at='2026-10-31 13:00:00'")
    snapshot = read_local_status(db.path, observed_at=NOW, stale_after=timedelta(minutes=30))
    assert snapshot.local_data_age == "stale"
    assert snapshot.last_local_update_at == datetime(2026, 10, 31, 13, 0, tzinfo=UTC)
    assert snapshot.counts.local_planned == 1


def test_missing_or_corrupt_database_fails_without_creating_file(tmp_path: Path) -> None:
    absent = tmp_path / "missing.sqlite3"
    with pytest.raises(LocalStatusUnavailable, match="^local status unavailable$"):
        read_local_status(absent, observed_at=NOW)
    assert not absent.exists()
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not sqlite; private marker")
    with pytest.raises(LocalStatusUnavailable, match="^local status unavailable$"):
        read_local_status(corrupt, observed_at=NOW)


@pytest.mark.parametrize("tamper", ["unknown_version", "checksum", "table_ddl"])
def test_unknown_or_modified_schema_fails_closed(tmp_path: Path, tamper: str) -> None:
    db = _database(tmp_path)
    with db.connection() as connection, connection:
        if tamper == "unknown_version":
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (99, 'unknown')"
            )
        elif tamper == "checksum":
            connection.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=1")
        else:
            connection.execute("ALTER TABLE ticket_requests ADD COLUMN hidden TEXT")
    with pytest.raises(LocalStatusUnavailable, match="^local status unavailable$"):
        read_local_status(db.path, observed_at=NOW)


@pytest.mark.parametrize("tamper", [None, "telegram_checksum", "future_version"])
def test_telegram_migration_is_known_but_corruption_and_future_versions_fail_closed(
    tmp_path: Path, tamper: str | None
) -> None:
    db = _database(tmp_path)
    _intent(db, "private-member", "private-event")
    # The opt-in migration uses only local SQLite; no sender is constructed or called.
    outbox = SqliteNotificationOutbox(db)
    TelegramDeliveryCoordinator(outbox, object(), lambda: NOW.timestamp()).prepare_storage()
    with db.connection() as connection, connection:
        connection.execute("UPDATE ticket_requests SET updated_at='2026-10-31 14:59:00'")
        if tamper == "telegram_checksum":
            connection.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=7")
        elif tamper == "future_version":
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (8, 'unknown')"
            )
    if tamper is None:
        snapshot = read_local_status(db.path, observed_at=NOW)
        assert snapshot.counts.local_planned == 1
        assert snapshot.external_confirmation == "not_observed"
    else:
        with pytest.raises(LocalStatusUnavailable, match="^local status unavailable$"):
            read_local_status(db.path, observed_at=NOW)


@pytest.mark.parametrize("invalid", ["status", "timestamp", "future"])
def test_invalid_local_row_fails_closed(tmp_path: Path, invalid: str) -> None:
    db = _database(tmp_path)
    _intent(db, "member-1", "event-1")
    with db.connection() as connection, connection:
        if invalid == "status":
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute("UPDATE ticket_requests SET status='external-confirmed'")
        elif invalid == "timestamp":
            connection.execute("UPDATE ticket_requests SET updated_at='not-a-time'")
        else:
            connection.execute("UPDATE ticket_requests SET updated_at='2026-11-01 00:00:00'")
    with pytest.raises(LocalStatusUnavailable, match="^local status unavailable$"):
        read_local_status(db.path, observed_at=NOW)


def test_row_budget_fails_closed_without_partial_snapshot(tmp_path: Path) -> None:
    db = _database(tmp_path)
    with db.connection() as connection, connection:
        connection.executemany(
            "INSERT INTO members(member_id, email, consent_recorded_at) VALUES (?, ?, ?)",
            [(f"member-{i}", f"member-{i}@invalid.test", "2026-10-31") for i in range(201)],
        )
        connection.execute("INSERT INTO events(event_id, label) VALUES ('match', 'Private match')")
        connection.executemany(
            "INSERT INTO ticket_requests(request_id, member_id, event_id) VALUES (?, ?, 'match')",
            [(f"request-{i}", f"member-{i}") for i in range(201)],
        )
    with pytest.raises(LocalStatusUnavailable, match="^local status unavailable$"):
        read_local_status(db.path, observed_at=NOW)


def test_caller_clock_and_threshold_must_be_explicitly_valid(tmp_path: Path) -> None:
    db = _database(tmp_path)
    with pytest.raises(ValueError, match="observed_at"):
        read_local_status(db.path, observed_at=datetime(2026, 10, 31))
    with pytest.raises(ValueError, match="stale_after"):
        read_local_status(db.path, observed_at=NOW, stale_after=timedelta(0))


def test_symlink_database_is_rejected(tmp_path: Path) -> None:
    db = _database(tmp_path)
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(db.path)
    with pytest.raises(LocalStatusUnavailable, match="^local status unavailable$"):
        read_local_status(alias, observed_at=NOW)


def test_database_path_uri_characters_are_not_interpreted_as_options(tmp_path: Path) -> None:
    db = Database(tmp_path / "private ? #" / "boca.sqlite3")
    db.migrate()
    assert read_local_status(db.path, observed_at=NOW).counts.total == 0
