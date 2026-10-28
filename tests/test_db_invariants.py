from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
    with ThreadPoolExecutor(max_workers=12) as executor:
        request_ids = tuple(executor.map(db.request_ticket, (intent for _ in range(36))))
    assert len(request_ids) == 36
    assert len(set(request_ids)) == 1
    with db.connection() as connection:
        rows = connection.execute(
            "SELECT request_id, quantity FROM ticket_requests WHERE member_id = ? AND event_id = ?",
            ("member-a", "event-a"),
        ).fetchall()
    assert rows == [(request_ids[0], 1)]


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
