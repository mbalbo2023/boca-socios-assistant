"""One local authorization for a future external reservation attempt.

No provider, browser, identity verification, payment or automatic retry is
implemented here. A crash after the claim is committed is ambiguous and
requires manual reconciliation before any separately reviewed retry design.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from math import isfinite
from uuid import UUID, uuid4

from boca_socios.storage.database import Database


class ReservationState(StrEnum):
    IN_FLIGHT = "in_flight"
    NEEDS_REVIEW = "needs_review"
    PROVIDER_ACK_REPORTED = "provider_ack_reported"
    SIMULATION_COMPLETED = "simulation_completed"
    SIMULATION_FAILED = "simulation_failed"


class ReservationResolution(StrEnum):
    UNRESOLVED = "unresolved"
    PROVIDER_ACK_REPORTED = "provider_ack_reported"
    SIMULATION_COMPLETED = "simulation_completed"
    SIMULATION_FAILED = "simulation_failed"


class InvalidReservationClaim(Exception):
    """A missing, stale or conflicting claim cannot change the attempt."""


@dataclass(frozen=True, slots=True, repr=False)
class ReservationClaim:
    request_id: str
    claim_token: UUID
    review_after: float

    def __repr__(self) -> str:
        return "ReservationClaim(<claim omitted>)"


@dataclass(frozen=True, slots=True)
class ReservationSnapshot:
    request_id: str
    state: ReservationState
    started_at: float
    review_after: float
    closed_at: float | None


class ReservationAttemptGuard:
    """Durable single-flight gate, deliberately disconnected from the runtime."""

    def __init__(self, database: Database) -> None:
        self._database = database

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def migrate(self) -> None:
        """Apply the additive schema with its checksum and DDL in one transaction."""
        self._database.migrate()
        sql = (
            files("boca_socios.storage.migrations")
            .joinpath("0003_reservation_guard.sql")
            .read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        with self._write() as connection:
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version=3"
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("migration checksum mismatch: reservation guard")
                return
            # This reviewed migration has only DDL without embedded semicolons.
            for statement in sql.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (3, ?)", (digest,)
            )

    def migrate_simulation(self) -> None:
        """Opt in to local simulation outcomes without rewriting migration 0003."""
        self.migrate()
        sql = (
            files("boca_socios.storage.migrations")
            .joinpath("0005_simulation_outcomes.sql")
            .read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        with self._write() as connection:
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version=5"
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("migration checksum mismatch: simulation outcomes")
                return
            for statement in sql.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (5, ?)", (digest,)
            )

    @staticmethod
    def _request_id(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("request_id must be a canonical UUID")
        try:
            parsed = UUID(value)
        except ValueError as exc:
            raise ValueError("request_id must be a canonical UUID") from exc
        if str(parsed) != value or parsed.int == 0:
            raise ValueError("request_id must be a canonical UUID")
        return value

    @staticmethod
    def _time(value: float) -> float:
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError("time must be finite nonnegative Unix seconds")
        return float(value)

    @staticmethod
    def _snapshot(row: tuple[object, ...]) -> ReservationSnapshot:
        return ReservationSnapshot(
            request_id=str(row[0]),
            state=ReservationState(str(row[1])),
            started_at=float(str(row[2])),
            review_after=float(str(row[3])),
            closed_at=None if row[4] is None else float(str(row[4])),
        )

    def get(self, request_id: str) -> ReservationSnapshot | None:
        key = self._request_id(request_id)
        with self._database.connection() as connection:
            row = connection.execute(
                """SELECT request_id, state, started_at, review_after, closed_at
                   FROM reservation_attempts WHERE request_id=?""",
                (key,),
            ).fetchone()
            return None if row is None else self._snapshot(row)

    def claim(
        self, request_id: str, *, now: float, review_after_seconds: float = 120
    ) -> ReservationClaim | None:
        """Commit one permission before I/O, or return None forever after.

        The caller must separately prove account eligibility, admission and
        provider authorization; this gate cannot establish any of them.
        """
        return self._claim(
            request_id, now=now, review_after_seconds=review_after_seconds, simulation=False
        )

    def claim_simulation(
        self, request_id: str, *, now: float, review_after_seconds: float = 120
    ) -> ReservationClaim | None:
        """Consume a local synthetic attempt; never a provider authorization."""
        return self._claim(
            request_id, now=now, review_after_seconds=review_after_seconds, simulation=True
        )

    def _claim(
        self, request_id: str, *, now: float, review_after_seconds: float, simulation: bool
    ) -> ReservationClaim | None:
        key = self._request_id(request_id)
        started = self._time(now)
        duration = self._time(review_after_seconds)
        deadline = started + duration
        if duration <= 0 or not isfinite(deadline) or deadline <= started:
            raise ValueError("review deadline must be finite and after start")
        with self._write() as connection:
            request = connection.execute(
                "SELECT status FROM ticket_requests WHERE request_id=?", (key,)
            ).fetchone()
            if request is None or request[0] != "planned":
                raise ValueError("an active local ticket intent is required")
            token = uuid4()
            statement = (
                """INSERT INTO reservation_attempts
                   (request_id, claim_token, state, started_at, review_after, attempt_kind)
                   VALUES (?, ?, 'in_flight', ?, ?, 'simulation')
                   ON CONFLICT(request_id) DO NOTHING"""
                if simulation
                else """INSERT INTO reservation_attempts
                   (request_id, claim_token, state, started_at, review_after)
                   VALUES (?, ?, 'in_flight', ?, ?)
                   ON CONFLICT(request_id) DO NOTHING"""
            )
            cursor = connection.execute(statement, (key, str(token), started, deadline))
            if cursor.rowcount == 0:
                return None
            if cursor.rowcount != 1:
                raise RuntimeError("reservation authorization was not persisted")
            return ReservationClaim(key, token, deadline)

    def resolve(
        self, claim: ReservationClaim, resolution: ReservationResolution, *, now: float
    ) -> ReservationSnapshot:
        """Record the caller's report; this is not proof of an external ticket."""
        if not isinstance(claim, ReservationClaim) or type(claim.claim_token) is not UUID:
            raise ValueError("a valid claim is required")
        key = self._request_id(claim.request_id)
        if not isinstance(resolution, ReservationResolution):
            raise ValueError("an explicit resolution is required")
        resolved_at = self._time(now)
        targets = {
            ReservationResolution.PROVIDER_ACK_REPORTED: ReservationState.PROVIDER_ACK_REPORTED,
            ReservationResolution.UNRESOLVED: ReservationState.NEEDS_REVIEW,
            ReservationResolution.SIMULATION_COMPLETED: ReservationState.SIMULATION_COMPLETED,
            ReservationResolution.SIMULATION_FAILED: ReservationState.SIMULATION_FAILED,
        }
        target = targets[resolution]
        with self._write() as connection:
            row = connection.execute(
                """SELECT claim_token, request_id, state, started_at, review_after, closed_at
                   FROM reservation_attempts WHERE request_id=?""",
                (key,),
            ).fetchone()
            if row is None or row[0] != str(claim.claim_token):
                raise InvalidReservationClaim("missing or stale reservation claim")
            current = self._snapshot(row[1:])
            upgraded = (
                connection.execute("SELECT 1 FROM schema_migrations WHERE version=5").fetchone()
                is not None
            )
            kind = (
                connection.execute(
                    "SELECT attempt_kind FROM reservation_attempts WHERE request_id=?", (key,)
                ).fetchone()[0]
                if upgraded
                else "external"
            )
            synthetic = resolution in {
                ReservationResolution.SIMULATION_COMPLETED,
                ReservationResolution.SIMULATION_FAILED,
            }
            if (synthetic and kind != "simulation") or (
                resolution is ReservationResolution.PROVIDER_ACK_REPORTED and kind != "external"
            ):
                raise InvalidReservationClaim("attempt kind does not permit this resolution")
            if current.state is target:
                return current
            if (
                current.state is not ReservationState.IN_FLIGHT
                or resolved_at >= current.review_after
            ):
                raise InvalidReservationClaim("reservation attempt requires manual review")
            if resolved_at < current.started_at:
                raise ValueError("resolution precedes claim")
            connection.execute(
                """UPDATE reservation_attempts SET state=?, closed_at=?
                   WHERE request_id=? AND state='in_flight' AND claim_token=?""",
                (target.value, resolved_at, key, str(claim.claim_token)),
            )
            return ReservationSnapshot(
                key, target, current.started_at, current.review_after, resolved_at
            )

    def mark_overdue(self, *, now: float) -> int:
        """Move stale claims to manual review, without granting a new claim."""
        at = self._time(now)
        with self._write() as connection:
            cursor = connection.execute(
                """UPDATE reservation_attempts SET state='needs_review', closed_at=?
                   WHERE state='in_flight' AND review_after <= ?""",
                (at, at),
            )
            return cursor.rowcount
