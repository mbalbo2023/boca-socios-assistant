"""Minimal audited SQLite repository: transactions and DB-level uniqueness."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from importlib.resources import files
from pathlib import Path

from boca_socios.domain.policy import TicketIntent
from boca_socios.security.credential_vault import SealedCredential


class Database:
    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise ValueError("database path must be absolute")
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=5.0)) as connection:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection

    def migrate(self) -> None:
        sql = (
            files("boca_socios.storage.migrations")
            .joinpath("0001_initial.sql")
            .read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        try:
            identity = self._migration_identity()
        except FileNotFoundError:
            identity = None
        existing = identity is not None
        if existing:
            # Do not use immutable=1: a current checksum may be in an active WAL.
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as readonly:
                self._validate_migration(readonly, digest)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Never adopt a file that appeared after the absence check.
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            identity = self._migration_identity()
        self._require_migration_identity(identity)
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True)) as connection:
            self._require_migration_identity(identity)
            if existing:
                # Recheck after opening writable, before changing journal mode.
                self._validate_migration(connection, digest)
            elif connection.execute("SELECT count(*) FROM sqlite_master").fetchone() != (0,):
                raise ValueError("new database changed before migration")
            connection.execute("PRAGMA journal_mode = WAL")
            if not existing:
                connection.execute("BEGIN IMMEDIATE")
                with connection:
                    # Reviewed 0001 has simple statements, no embedded semicolons.
                    for statement in sql.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, checksum) VALUES (1, ?)",
                        (digest,),
                    )
        self._require_migration_identity(identity)
        os.chmod(self.path, 0o600)

    def _migration_identity(self) -> tuple[int, int]:
        metadata = self.path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("database path must not be a symlink")
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("database path must be a regular file")
        return metadata.st_dev, metadata.st_ino

    def _require_migration_identity(self, expected: tuple[int, int] | None) -> None:
        if self._migration_identity() != expected:
            raise ValueError("database identity changed before migration")

    @staticmethod
    def _validate_migration(connection: sqlite3.Connection, digest: str) -> None:
        try:
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version = 1"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise ValueError("existing database migration ledger is invalid") from exc
        if row is None:
            raise ValueError("existing database migration 1 is missing")
        if row[0] != digest:
            raise ValueError("migration checksum mismatch: existing DB must not be rewritten")

    def create_member(
        self, member_id: str, email: str, consent_recorded_at: str, display_name: str = ""
    ) -> None:
        email = email.strip().casefold()
        if not member_id or "@" not in email or not consent_recorded_at:
            raise ValueError("member, valid email and consent time required")
        with self.connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO members(member_id, email, display_name, consent_recorded_at)
                VALUES (?, ?, ?, ?)
                """,
                (member_id, email, display_name or None, consent_recorded_at),
            )

    def save_credential(self, member_id: str, sealed: SealedCredential) -> None:
        if len(sealed.nonce) != 12 or len(sealed.ciphertext) <= 16:
            raise ValueError("malformed encrypted credential")
        with self.connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO credentials(member_id, key_id, nonce, ciphertext)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(member_id) DO UPDATE SET
                  key_id = excluded.key_id,
                  nonce = excluded.nonce,
                  ciphertext = excluded.ciphertext,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (member_id, sealed.key_id, sealed.nonce, sealed.ciphertext),
            )

    def get_credential(self, member_id: str) -> SealedCredential | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT key_id, nonce, ciphertext FROM credentials WHERE member_id = ?",
                (member_id,),
            ).fetchone()
        if row is None:
            return None
        return SealedCredential(key_id=str(row[0]), nonce=bytes(row[1]), ciphertext=bytes(row[2]))

    def create_event(self, event_id: str, label: str) -> None:
        if not event_id or not label:
            raise ValueError("event identifier and label required")
        with self.connection() as connection, connection:
            connection.execute(
                "INSERT INTO events(event_id, label) VALUES (?, ?)",
                (event_id, label),
            )

    def request_ticket(self, intent: TicketIntent) -> str:
        """Create or return the single durable logical intent for member/event.

        INSERT with a targeted uniqueness conflict is atomic under SQLite's
        one-writer transaction model, including when callers race. This is
        local intent idempotency, NOT external Boca reservation idempotency.
        """
        intent.validate()
        request_id = str(uuid.uuid4())
        with self.connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO ticket_requests(request_id, member_id, event_id, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(member_id, event_id) DO NOTHING
                """,
                (request_id, intent.member_id, intent.event_id, intent.quantity),
            )
            row = connection.execute(
                """
                SELECT request_id FROM ticket_requests
                WHERE member_id = ? AND event_id = ?
                """,
                (intent.member_id, intent.event_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("ticket intent was not persisted")
            return str(row[0])
