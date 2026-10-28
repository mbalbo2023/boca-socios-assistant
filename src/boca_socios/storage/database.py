"""Minimal audited SQLite repository: transactions and DB-level uniqueness."""

from __future__ import annotations

import hashlib
import os
import sqlite3
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
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError("database path must not be a symlink")
        sql = (
            files("boca_socios.storage.migrations")
            .joinpath("0001_initial.sql")
            .read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(sql)
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version = 1"
            ).fetchone()
            if row is not None and row[0] != digest:
                raise ValueError("migration checksum mismatch: existing DB must not be rewritten")
            if row is None:
                with connection:
                    connection.execute(
                        "INSERT INTO schema_migrations(version, checksum) VALUES (1, ?)",
                        (digest,),
                    )
        os.chmod(self.path, 0o600)

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
        intent.validate()
        request_id = str(uuid.uuid4())
        with self.connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO ticket_requests(request_id, member_id, event_id, quantity)
                VALUES (?, ?, ?, ?)
                """,
                (request_id, intent.member_id, intent.event_id, intent.quantity),
            )
        return request_id
