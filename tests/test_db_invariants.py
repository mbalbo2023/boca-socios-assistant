from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Barrier

import pytest

from boca_socios.domain.policy import TicketIntent
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.storage.database import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    repository = Database(tmp_path / "boca" / "state.sqlite3")
    repository.migrate()
    repository.create_member("member-a", "MemberA@example.test", "2026-10-28T00:00:00Z")
    repository.create_event("event-a", "Synthetic match")
    return repository


def test_exactly_one_ticket_per_member_per_event(db: Database) -> None:
    first = db.request_ticket(TicketIntent(member_id="member-a", event_id="event-a"))
    assert first
    assert db.request_ticket(TicketIntent(member_id="member-a", event_id="event-a")) == first
    with pytest.raises(ValueError, match="exactly one"):
        db.request_ticket(TicketIntent(member_id="member-a", event_id="event-a", quantity=2))
    with pytest.raises(ValueError, match="exactly one"):
        db.request_ticket(TicketIntent(member_id="member-a", event_id="event-a", quantity=True))
    with db.connection() as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM ticket_requests WHERE member_id = ? AND event_id = ?",
            ("member-a", "event-a"),
        ).fetchone()
    assert row == (1,)


def test_concurrent_retries_return_same_logical_request(db: Database) -> None:
    intent = TicketIntent(member_id="member-a", event_id="event-a")
    barrier = Barrier(12)

    def compete(_: int) -> str:
        barrier.wait(timeout=10)
        return db.request_ticket(intent)

    with ThreadPoolExecutor(max_workers=12) as executor:
        request_ids = tuple(executor.map(compete, range(36)))
    assert len(request_ids) == 36
    assert len(set(request_ids)) == 1
    with db.connection() as connection:
        rows = connection.execute(
            "SELECT request_id, quantity FROM ticket_requests WHERE member_id = ? AND event_id = ?",
            ("member-a", "event-a"),
        ).fetchall()
    assert rows == [(request_ids[0], 1)]


def test_retry_preserves_existing_workflow_state(db: Database) -> None:
    intent = TicketIntent("member-a", "event-a")
    first = db.request_ticket(intent)
    with db.connection() as connection, connection:
        connection.execute(
            """
            UPDATE ticket_requests SET status = 'queued', updated_at = ?
            WHERE request_id = ?
            """,
            ("2026-10-28T13:00:00Z", first),
        )
    assert db.request_ticket(intent) == first
    with db.connection() as connection:
        row = connection.execute(
            "SELECT status, updated_at FROM ticket_requests WHERE request_id = ?", (first,)
        ).fetchone()
    assert row == ("queued", "2026-10-28T13:00:00Z")


def test_db_lock_failure_can_recover_with_safe_retry(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = TicketIntent("member-a", "event-a")

    @contextmanager
    def fast_timeout_connection() -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(db.path, timeout=0.02)) as connection:
            connection.execute("PRAGMA busy_timeout = 20")
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection

    monkeypatch.setattr(db, "connection", fast_timeout_connection)
    with closing(sqlite3.connect(db.path)) as locked:
        locked.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            db.request_ticket(intent)
        locked.rollback()

    first = db.request_ticket(intent)
    assert db.request_ticket(intent) == first
    with db.connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM ticket_requests WHERE member_id = ? AND event_id = ?",
            (intent.member_id, intent.event_id),
        ).fetchone()
    assert count == (1,)


def test_distinct_members_do_not_share_an_intent(db: Database) -> None:
    db.create_member("member-b", "MemberB@example.test", "2026-10-28T00:00:00Z")
    first = db.request_ticket(TicketIntent("member-a", "event-a"))
    second = db.request_ticket(TicketIntent("member-b", "event-a"))
    assert first != second
    assert db.request_ticket(TicketIntent("member-b", "event-a")) == second


def test_blank_identity_does_not_produce_ticket_request(db: Database) -> None:
    with pytest.raises(ValueError, match="required"):
        db.request_ticket(TicketIntent(member_id=" ", event_id="event-a"))


def test_db_constraint_rejects_quantity_over_one(db: Database) -> None:
    with db.connection() as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO ticket_requests(request_id, member_id, event_id, quantity)
                VALUES ('unsafe', 'member-a', 'event-a', 2)
                """
            )


def test_credential_is_only_ciphertext_in_database(db: Database) -> None:
    vault = CredentialVault(os.urandom(32))
    password = "a-placeholder-password-used-only-in-tests"
    db.save_credential("member-a", vault.seal(password, member_id="member-a"))
    row = db.get_credential("member-a")
    assert row is not None
    assert password.encode() not in row.ciphertext
    assert vault.open(row, member_id="member-a") == password
    with db.connection() as connection:
        raw = connection.execute(
            "SELECT ciphertext FROM credentials WHERE member_id = 'member-a'"
        ).fetchone()[0]
    assert password.encode() not in raw


def test_db_is_private_and_migration_is_idempotent(db: Database) -> None:
    db.migrate()
    assert db.path.stat().st_mode & 0o077 == 0


def test_foreign_keys_fail_closed(db: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.request_ticket(TicketIntent(member_id="unknown", event_id="event-a"))
