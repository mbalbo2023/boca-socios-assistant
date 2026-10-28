"""Durable, local authorization gate for one future external attempt.

These tests never open a page or send a request to Boca Socios.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from boca_socios.domain.policy import TicketIntent
from boca_socios.reservation_guard import (
    InvalidReservationClaim,
    ReservationAttemptGuard,
    ReservationResolution,
    ReservationState,
)
from boca_socios.storage.database import Database


def setup_guard(tmp_path: Path) -> tuple[Database, ReservationAttemptGuard, str]:
    database = Database(tmp_path / "boca.sqlite3")
    database.migrate()
    database.create_member("member-1", "test@invalid.test", "2026-10-28T00:00:00Z")
    database.create_event("event-1", "Partido ficticio")
    request_id = database.request_ticket(TicketIntent("member-1", "event-1"))
    guard = ReservationAttemptGuard(database)
    guard.migrate()
    return database, guard, request_id


def test_concurrent_aliases_get_only_one_durable_authorization(tmp_path: Path) -> None:
    database, guard, request_id = setup_guard(tmp_path)
    barrier = Barrier(12)

    def compete(_alias: int) -> object:
        assert database.request_ticket(TicketIntent("member-1", "event-1")) == request_id
        barrier.wait()
        return ReservationAttemptGuard(database).claim(request_id, now=1000)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(compete, range(12)))
    claims = [result for result in results if result is not None]
    assert len(claims) == 1
    assert claims[0].request_id == request_id
    assert "claim_token" not in repr(claims[0])
    assert ReservationAttemptGuard(database).claim(request_id, now=1001) is None
    assert ReservationAttemptGuard(database).get(request_id).state is ReservationState.IN_FLIGHT
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM reservation_attempts").fetchone() == (1,)
        assert connection.execute("SELECT quantity FROM ticket_requests").fetchone() == (1,)


def test_restart_and_deadline_never_reclaim_an_ambiguous_attempt(tmp_path: Path) -> None:
    database, guard, request_id = setup_guard(tmp_path)
    claim = guard.claim(request_id, now=1000, review_after_seconds=30)
    assert claim is not None
    restarted = ReservationAttemptGuard(database)
    restarted.migrate()
    assert restarted.mark_overdue(now=1029) == 0
    assert restarted.claim(request_id, now=1029) is None
    assert restarted.mark_overdue(now=1030) == 1
    assert restarted.mark_overdue(now=1031) == 0
    assert restarted.get(request_id).state is ReservationState.NEEDS_REVIEW
    assert restarted.claim(request_id, now=5000) is None
    with pytest.raises(InvalidReservationClaim):
        restarted.resolve(claim, ReservationResolution.PROVIDER_ACK_REPORTED, now=1031)


def test_acknowledgement_is_reported_once_and_conflicting_resolution_fails(tmp_path: Path) -> None:
    database, guard, request_id = setup_guard(tmp_path)
    claim = guard.claim(request_id, now=1000)
    assert claim is not None
    reported = guard.resolve(claim, ReservationResolution.PROVIDER_ACK_REPORTED, now=1001)
    assert reported.state is ReservationState.PROVIDER_ACK_REPORTED
    assert reported == ReservationAttemptGuard(database).resolve(
        claim, ReservationResolution.PROVIDER_ACK_REPORTED, now=1002
    )
    with pytest.raises(InvalidReservationClaim):
        guard.resolve(claim, ReservationResolution.UNRESOLVED, now=1002)
    assert guard.claim(request_id, now=1003) is None
    assert guard.mark_overdue(now=9999) == 0


def test_unresolved_outcome_requires_manual_reconciliation_and_fences_tokens(
    tmp_path: Path,
) -> None:
    database, guard, request_id = setup_guard(tmp_path)
    claim = guard.claim(request_id, now=1000)
    assert claim is not None
    forged = type(claim)(request_id, uuid4(), claim.review_after)
    with pytest.raises(InvalidReservationClaim):
        guard.resolve(forged, ReservationResolution.PROVIDER_ACK_REPORTED, now=1001)
    unresolved = guard.resolve(claim, ReservationResolution.UNRESOLVED, now=1001)
    assert unresolved.state is ReservationState.NEEDS_REVIEW
    assert guard.resolve(claim, ReservationResolution.UNRESOLVED, now=1002) == unresolved
    assert ReservationAttemptGuard(database).claim(request_id, now=9999) is None


def test_missing_cancelled_and_invalid_inputs_fail_closed(tmp_path: Path) -> None:
    database, guard, request_id = setup_guard(tmp_path)
    for invalid in ("", "member-1", "00000000-0000-0000-0000-000000000000", 7):
        with pytest.raises(ValueError):
            guard.claim(invalid, now=1000)
    for invalid_now in (True, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            guard.claim(request_id, now=invalid_now)
    with pytest.raises(ValueError):
        guard.claim(request_id, now=1000, review_after_seconds=0)
    with pytest.raises(ValueError):
        guard.claim(str(uuid4()), now=1000)
    with database.connection() as connection, connection:
        connection.execute(
            "UPDATE ticket_requests SET status='cancelled' WHERE request_id=?", (request_id,)
        )
    with pytest.raises(ValueError):
        guard.claim(request_id, now=1000)
    assert guard.get(request_id) is None


def test_migration_checksum_and_foreign_key_preserve_the_local_quota(tmp_path: Path) -> None:
    database, guard, request_id = setup_guard(tmp_path)
    assert guard.claim(request_id, now=1000) is not None
    with database.connection() as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM ticket_requests WHERE request_id=?", (request_id,))
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM ticket_requests").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM reservation_attempts").fetchone() == (1,)
    with database.connection() as connection, connection:
        connection.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=3")
    with pytest.raises(ValueError, match="checksum"):
        ReservationAttemptGuard(database).migrate()
