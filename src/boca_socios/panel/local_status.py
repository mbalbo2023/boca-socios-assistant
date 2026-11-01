"""Read-only, bounded projection of local simulation intent facts.

This library is deliberately disconnected from the runtime and any HTTP route.
Its result is neither a Boca reservation nor evidence that a controller is up.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Literal
from urllib.parse import quote


class LocalStatusUnavailable(Exception):
    """A local snapshot cannot be certified; details stay out of callers."""


@dataclass(frozen=True, slots=True)
class LocalIntentCounts:
    local_planned: int = 0
    local_queued: int = 0
    local_admitted: int = 0
    local_result_recorded_unverified: int = 0
    local_rejected: int = 0
    local_cancelled: int = 0

    @property
    def total(self) -> int:
        return sum(
            (
                self.local_planned,
                self.local_queued,
                self.local_admitted,
                self.local_result_recorded_unverified,
                self.local_rejected,
                self.local_cancelled,
            )
        )


@dataclass(frozen=True, slots=True)
class LocalStatusSnapshot:
    source: Literal["local_sqlite_intents"]
    external_confirmation: Literal["not_observed"]
    observed_at: datetime
    local_data_age: Literal["empty", "recent", "stale"]
    last_local_update_at: datetime | None
    counts: LocalIntentCounts


_MIGRATIONS = {
    1: "0001_initial.sql",
    2: "0002_notification_outbox.sql",
    3: "0003_reservation_guard.sql",
    4: "0004_credential_key_policy.sql",
    5: "0005_simulation_outcomes.sql",
}
_MAX_INTENTS = 200


def _migration_sql(version: int) -> str:
    return (
        files("boca_socios.storage.migrations")
        .joinpath(_MIGRATIONS[version])
        .read_text(encoding="utf-8")
    )


def _expected_ticket_table() -> str:
    # Reconstruct only in memory; this never migrates the source database.
    with closing(sqlite3.connect(":memory:")) as memory:
        memory.executescript(_migration_sql(1))
        row = memory.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ticket_requests'"
        ).fetchone()
    if row is None or not isinstance(row[0], str):
        raise LocalStatusUnavailable("local status unavailable")
    return row[0]


def _require_known_schema(connection: sqlite3.Connection) -> None:
    rows = connection.execute("SELECT version, checksum FROM schema_migrations LIMIT 6").fetchall()
    if not rows or len(rows) > len(_MIGRATIONS) or 1 not in {version for version, _ in rows}:
        raise LocalStatusUnavailable("local status unavailable")
    for version, checksum in rows:
        if type(version) is not int or version not in _MIGRATIONS:
            raise LocalStatusUnavailable("local status unavailable")
        expected = hashlib.sha256(_migration_sql(version).encode("utf-8")).hexdigest()
        if checksum != expected:
            raise LocalStatusUnavailable("local status unavailable")
    actual = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ticket_requests'"
    ).fetchone()
    if actual != (_expected_ticket_table(),):
        raise LocalStatusUnavailable("local status unavailable")


def _local_timestamp(value: object) -> datetime:
    if type(value) is not str:
        raise LocalStatusUnavailable("local status unavailable")
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
        raise LocalStatusUnavailable("local status unavailable")
    return parsed.replace(tzinfo=UTC)


def read_local_status(
    database_path: Path,
    *,
    observed_at: datetime,
    stale_after: timedelta = timedelta(minutes=15),
) -> LocalStatusSnapshot:
    """Project at most 200 SQLite intents without reading identity or secrets.

    ``stale`` measures the age of the latest local intent update only. A
    recent result does not prove runtime health or external confirmation.
    """
    if (
        not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
    ):
        raise ValueError("observed_at must be timezone aware")
    if not isinstance(stale_after, timedelta) or stale_after <= timedelta(0):
        raise ValueError("stale_after must be positive")
    now = observed_at.astimezone(UTC)
    try:
        if (
            not isinstance(database_path, Path)
            or not database_path.is_absolute()
            or database_path.is_symlink()
            or not database_path.is_file()
        ):
            raise LocalStatusUnavailable("local status unavailable")
        uri = f"file:{quote(str(database_path), safe='/')}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("BEGIN")
            _require_known_schema(connection)
            rows = connection.execute(
                "SELECT status, updated_at FROM ticket_requests LIMIT ?", (_MAX_INTENTS + 1,)
            ).fetchall()
        if len(rows) > _MAX_INTENTS:
            raise LocalStatusUnavailable("local status unavailable")
        counts: Counter[str] = Counter()
        last_update: datetime | None = None
        for status, timestamp in rows:
            if type(status) is not str or status not in {
                "planned",
                "queued",
                "admitted",
                "reserved",
                "rejected",
                "cancelled",
            }:
                raise LocalStatusUnavailable("local status unavailable")
            updated_at = _local_timestamp(timestamp)
            if updated_at > now:
                raise LocalStatusUnavailable("local status unavailable")
            counts[status] += 1
            if last_update is None or updated_at > last_update:
                last_update = updated_at
        age: Literal["empty", "recent", "stale"] = (
            "empty"
            if last_update is None
            else "stale"
            if now - last_update > stale_after
            else "recent"
        )
        return LocalStatusSnapshot(
            source="local_sqlite_intents",
            external_confirmation="not_observed",
            observed_at=now,
            local_data_age=age,
            last_local_update_at=last_update,
            counts=LocalIntentCounts(
                local_planned=counts["planned"],
                local_queued=counts["queued"],
                local_admitted=counts["admitted"],
                local_result_recorded_unverified=counts["reserved"],
                local_rejected=counts["rejected"],
                local_cancelled=counts["cancelled"],
            ),
        )
    except (OSError, sqlite3.Error, ValueError, TypeError):
        raise LocalStatusUnavailable("local status unavailable") from None

