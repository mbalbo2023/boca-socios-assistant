"""Durable local command identity and one-worker claims; no external outcomes."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from typing import Literal
from uuid import UUID, uuid4

from boca_socios.domain.policy import TicketIntent
from boca_socios.storage.database import Database


class CommandState(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class CommandConflict(ValueError):
    """A command identifier is already bound to another local intent."""


class CommandCapacityError(RuntimeError):
    """The bounded pending queue is full."""


@dataclass(frozen=True, slots=True)
class CommandSnapshot:
    command_id: str
    request_id: str
    state: CommandState
    created_at: float
    updated_at: float
    notice_enqueued: bool
    mode: Literal["simulation"] = "simulation"
    external_confirmation: Literal["not_observed"] = "not_observed"


_SELECT = """SELECT c.command_id,c.request_id,c.state,c.created_at,c.updated_at,c.notice_enqueued,
                   t.member_id,t.event_id FROM beta_commands c
                   JOIN ticket_requests t ON t.request_id=c.request_id"""
_LOOKUP = _SELECT + " JOIN beta_command_keys k ON k.command_id=c.command_id WHERE k.command_key=?"


def command_key(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).int == 0:
        raise ValueError("command_id must be a canonical nonzero UUID")
    return value


def _snapshot(row: tuple[object, ...]) -> CommandSnapshot:
    return CommandSnapshot(
        str(row[0]),
        str(row[1]),
        CommandState(str(row[2])),
        float(str(row[3])),
        float(str(row[4])),
        bool(row[5]),
    )


class CommandStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._db.path.as_uri() + "?mode=rw", uri=True)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection

    def migrate(self) -> None:
        sql = files("boca_socios.storage.migrations").joinpath("0006_beta_commands.sql").read_text()
        digest = hashlib.sha256(sql.encode()).hexdigest()
        with self._write() as connection:
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version=6"
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("migration checksum mismatch: beta commands")
                return
            for statement in sql.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES (6,?)", (digest,)
            )

    def enqueue(
        self, key: str, intent: TicketIntent, *, now: float, max_pending: int
    ) -> CommandSnapshot:
        command_key(key)
        intent.validate()
        with self._write() as connection:
            row = connection.execute(_LOOKUP, (key,)).fetchone()
            if row is not None:
                if (row[6], row[7]) != (intent.member_id, intent.event_id):
                    raise CommandConflict("command identity conflicts with its existing intent")
                return _snapshot(row)
            row = connection.execute(
                _SELECT + " WHERE t.member_id=? AND t.event_id=?",
                (intent.member_id, intent.event_id),
            ).fetchone()
            if row is not None:
                count = connection.execute(
                    "SELECT count(*) FROM beta_command_keys WHERE command_id=?", (row[0],)
                ).fetchone()
                if count is None or count[0] >= 64:
                    raise CommandCapacityError("local command alias capacity reached")
                connection.execute(
                    "INSERT INTO beta_command_keys(command_key,command_id) VALUES (?,?)",
                    (key, row[0]),
                )
                return _snapshot(row)
            count = connection.execute(
                "SELECT count(*) FROM beta_commands "
                "WHERE state IN ('accepted','running','stop_requested')"
            ).fetchone()
            if count is None or count[0] >= max_pending:
                raise CommandCapacityError("pending local command capacity reached")
            connection.execute(
                """INSERT INTO ticket_requests(request_id,member_id,event_id,quantity)
                   VALUES (?,?,?,1) ON CONFLICT(member_id,event_id) DO NOTHING""",
                (str(uuid4()), intent.member_id, intent.event_id),
            )
            request = connection.execute(
                "SELECT request_id FROM ticket_requests WHERE member_id=? AND event_id=?",
                (intent.member_id, intent.event_id),
            ).fetchone()
            if request is None:
                raise RuntimeError("local intent was not persisted")
            connection.execute(
                """INSERT INTO beta_commands(command_id,request_id,state,created_at,updated_at)
                   VALUES (?,?,'accepted',?,?)""",
                (key, request[0], now, now),
            )
            connection.execute(
                "INSERT INTO beta_command_keys(command_key,command_id) VALUES (?,?)", (key, key)
            )
            row = connection.execute(_SELECT + " WHERE c.command_id=?", (key,)).fetchone()
            if row is None:
                raise RuntimeError("local command was not persisted")
            return _snapshot(row)

    def get(self, key: str, *, member_id: str | None = None) -> CommandSnapshot | None:
        command_key(key)
        with closing(sqlite3.connect(self._db.path.as_uri() + "?mode=ro", uri=True)) as connection:
            row = connection.execute(_LOOKUP, (key,)).fetchone()
            if row is None or (member_id is not None and row[6] != member_id):
                return None
            return _snapshot(row)

    def claim_next(self, *, now: float) -> tuple[CommandSnapshot, TicketIntent] | None:
        with self._write() as connection:
            # A second coordinator cannot run another browser while one owns a command.
            active = connection.execute(
                "SELECT 1 FROM beta_commands WHERE state IN ('running','stop_requested') LIMIT 1"
            ).fetchone()
            if active is not None:
                return None
            row = connection.execute(
                _SELECT + " WHERE c.state='accepted' ORDER BY c.created_at,c.command_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE beta_commands SET state='running',updated_at=max(updated_at,?) "
                "WHERE command_id=?",
                (now, row[0]),
            )
            current = (row[0], row[1], "running", row[3], max(float(row[4]), now), row[5])
            return _snapshot(current), TicketIntent(str(row[6]), str(row[7]))

    def stop(self, key: str, *, member_id: str, now: float) -> CommandSnapshot | None:
        command_key(key)
        with self._write() as connection:
            row = connection.execute(_LOOKUP, (key,)).fetchone()
            if row is None or row[6] != member_id:
                return None
            state = {"accepted": "stopped", "running": "stop_requested"}.get(str(row[2]))
            if state is not None:
                connection.execute(
                    "UPDATE beta_commands SET state=?,updated_at=max(updated_at,?) "
                    "WHERE command_id=?",
                    (state, now, row[0]),
                )
                row = (*row[:2], state, row[3], max(float(row[4]), now), *row[5:])
            return _snapshot(row)

    def settle(self, key: str, state: CommandState, *, now: float) -> None:
        with self._write() as connection:
            connection.execute(
                """UPDATE beta_commands SET state=?,updated_at=max(updated_at,?)
                   WHERE command_id=? AND state IN ('running','stop_requested','needs_review')""",
                (state.value, now, key),
            )

    def mark_notice(self, key: str, *, now: float) -> None:
        with self._write() as connection:
            connection.execute(
                """UPDATE beta_commands SET notice_enqueued=1,updated_at=max(updated_at,?)
                   WHERE command_id=? AND state='completed'""",
                (now, key),
            )

    def recoverable(self) -> tuple[CommandSnapshot, ...]:
        with closing(sqlite3.connect(self._db.path.as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute(
                _SELECT + " WHERE c.state IN ('running','stop_requested') "
                "OR (c.state='completed' AND c.notice_enqueued=0)"
            ).fetchall()
            return tuple(_snapshot(row) for row in rows)
