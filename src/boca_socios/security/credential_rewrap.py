"""Opt-in internal credential key rewrap; no CLI, endpoint or runtime wiring.

Both externally sourced key versions must remain staged until a separate
restart and backup recovery verification. This code must never see real keys
through GitHub, tests, logs or conversation.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files

from boca_socios.security.credential_vault import CredentialVault, SealedCredential
from boca_socios.storage.database import Database


class KeyPolicyMismatch(Exception):
    """The DB version or a row does not match the expected key version."""


@contextmanager
def _write(database: Database) -> Iterator[sqlite3.Connection]:
    with database.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def _policy(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT key_id FROM credential_key_policy WHERE singleton=1"
    ).fetchone()
    if row is None:
        raise KeyPolicyMismatch("credential key policy is unavailable")
    return str(row[0])


def _require_triggers(connection: sqlite3.Connection) -> None:
    names = {
        str(row[0])
        for row in connection.execute(
            """SELECT name FROM sqlite_master WHERE type='trigger'
               AND name IN ('credential_key_insert', 'credential_key_update')"""
        )
    }
    if names != {"credential_key_insert", "credential_key_update"}:
        raise KeyPolicyMismatch("credential key version guard is unavailable")


def _rows(connection: sqlite3.Connection, max_records: int) -> list[tuple[str, SealedCredential]]:
    records = connection.execute(
        """SELECT member_id, key_id, nonce, ciphertext FROM credentials
           ORDER BY member_id LIMIT ?""",
        (max_records + 1,),
    ).fetchall()
    if len(records) > max_records:
        raise ValueError("credential migration exceeds the reviewed record limit")
    return [
        (str(member), SealedCredential(str(key_id), bytes(nonce), bytes(ciphertext)))
        for member, key_id, nonce, ciphertext in records
    ]


def verify_active_credentials(
    database: Database, vault: CredentialVault, *, max_records: int = 1000
) -> int:
    """Read-only restart check using the newly loaded active key only."""
    if type(max_records) is not int or max_records < 1:
        raise ValueError("max_records must be positive")
    with database.connection() as connection:
        connection.execute("BEGIN")
        _require_triggers(connection)
        if _policy(connection) != vault.key_id:
            raise KeyPolicyMismatch("active credential version does not match supplied key")
        rows = _rows(connection, max_records)
        for member_id, sealed in rows:
            if sealed.key_id != vault.key_id:
                raise KeyPolicyMismatch("mixed credential key versions")
            vault.open(sealed, member_id=member_id)
        return len(rows)


class CredentialKeyRewrapper:
    """A small bounded batch in one SQLite transaction, disabled by default."""

    def __init__(
        self,
        database: Database,
        old_vault: CredentialVault,
        new_vault: CredentialVault,
        *,
        max_records: int = 1000,
    ) -> None:
        if old_vault.key_id == new_vault.key_id:
            raise ValueError("rotation requires different key versions")
        if old_vault.same_material_as(new_vault):
            raise ValueError("rotation requires different key material")
        if type(max_records) is not int or max_records < 1:
            raise ValueError("max_records must be positive")
        self._database = database
        self._old = old_vault
        self._new = new_vault
        self._max_records = max_records

    def migrate(self) -> None:
        """Pin the active version and install triggers atomically.

        Existing rows must be uniformly readable under the old version label;
        rotate() subsequently verifies their ciphertext before any commit.
        """
        self._database.migrate()
        sql = (
            files("boca_socios.storage.migrations")
            .joinpath("0004_credential_key_policy.sql")
            .read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        with _write(self._database) as connection:
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version=4"
            ).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("migration checksum mismatch: credential key policy")
                _require_triggers(connection)
                if _policy(connection) != self._old.key_id:
                    raise KeyPolicyMismatch("credential key policy has moved to another version")
                return
            mixed = connection.execute(
                "SELECT 1 FROM credentials WHERE key_id != ? LIMIT 1", (self._old.key_id,)
            ).fetchone()
            if mixed is not None:
                raise KeyPolicyMismatch("mixed credential key versions")
            # complete_statement handles the BEGIN/END in reviewed trigger DDL.
            statement = ""
            for line in sql.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    connection.execute(statement)
                    statement = ""
            if statement.strip():
                raise ValueError("incomplete credential key policy migration")
            connection.execute(
                "INSERT INTO credential_key_policy(singleton, key_id) VALUES (1, ?)",
                (self._old.key_id,),
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (4, ?)", (digest,)
            )
            _require_triggers(connection)

    def rotate(self) -> int:
        """Atomically re-encrypt all rows and block old-version writes.

        The caller must stop old writers during the operation and keep both
        keys for independent recovery verification. No key is retired here.
        """
        with _write(self._database) as connection:
            _require_triggers(connection)
            if _policy(connection) != self._old.key_id:
                raise KeyPolicyMismatch("credential key policy has moved to another version")
            rows = _rows(connection, self._max_records)
            if any(sealed.key_id != self._old.key_id for _, sealed in rows):
                raise KeyPolicyMismatch("mixed credential key versions")
            # Triggers reject any subsequent write using the old version, even
            # after this transaction releases its SQLite writer lock.
            connection.execute(
                "UPDATE credential_key_policy SET key_id=? WHERE singleton=1", (self._new.key_id,)
            )
            for member_id, previous in rows:
                password = self._old.open(previous, member_id=member_id)
                replacement = self._new.seal(password, member_id=member_id)
                if self._new.open(replacement, member_id=member_id) != password:
                    raise ValueError("replacement credential failed verification")
                connection.execute(
                    """UPDATE credentials SET key_id=?, nonce=?, ciphertext=?,
                       updated_at=CURRENT_TIMESTAMP WHERE member_id=?""",
                    (replacement.key_id, replacement.nonce, replacement.ciphertext, member_id),
                )
            return len(rows)
