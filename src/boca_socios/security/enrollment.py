"""Internal member credential lifecycle; no HTTP route or live-login wiring.

This module stores a synthetic/consented record atomically in the existing
SQLite schema. It does not establish Boca eligibility or a unique external
membership identity. Real enrollment remains disabled pending ADR 0012 review.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

from boca_socios.security.credential_vault import CredentialVault, SealedCredential
from boca_socios.storage.database import Database


class EnrollmentConflict(Exception):
    """An account already occupies a unique database identity."""


class MemberNotFound(Exception):
    """No member exists with the opaque internal identifier."""


class CredentialUnavailable(Exception):
    """The member has no active credential to rotate."""


class MemberEnrollmentService:
    """A deliberately unexposed transactional boundary for member credentials."""

    def __init__(self, database: Database, vault: CredentialVault) -> None:
        self._database = database
        self._vault = vault

    @staticmethod
    def _email(value: str) -> str:
        normalized = value.strip().casefold()
        if (
            len(normalized) > 254
            or normalized.count("@") != 1
            or any(char.isspace() or ord(char) < 32 for char in normalized)
            or not all(normalized.split("@"))
        ):
            raise ValueError("invalid email")
        return normalized

    @staticmethod
    def _password(value: str) -> None:
        if not value or len(value.encode("utf-8")) > 4096:
            raise ValueError("invalid credential length")

    @staticmethod
    def _audit(connection: sqlite3.Connection, action: str, member_id: str) -> None:
        connection.execute(
            "INSERT INTO audit_events(audit_id, action, member_id) VALUES (?, ?, ?)",
            (str(uuid.uuid4()), action, member_id),
        )

    def enroll(
        self,
        *,
        email: str,
        password: str,
        consent_recorded_at: datetime,
        display_name: str = "",
    ) -> str:
        """Create member and sealed credential together, or create neither.

        The caller must establish actual individual consent and eligibility
        before any future reservation. This service cannot verify either.
        """
        normalized = self._email(email)
        self._password(password)
        if consent_recorded_at.tzinfo is None or consent_recorded_at.utcoffset() is None:
            raise ValueError("consent time must have a timezone")
        if len(display_name) > 200 or any(ord(char) < 32 for char in display_name):
            raise ValueError("invalid display name")
        member_id = str(uuid.uuid4())
        sealed = self._vault.seal(password, member_id=member_id)
        consent_time = consent_recorded_at.astimezone(UTC).isoformat()
        try:
            with self._database.connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO members(member_id, email, display_name, consent_recorded_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (member_id, normalized, display_name or None, consent_time),
                )
                connection.execute(
                    """
                    INSERT INTO credentials(member_id, key_id, nonce, ciphertext)
                    VALUES (?, ?, ?, ?)
                    """,
                    (member_id, sealed.key_id, sealed.nonce, sealed.ciphertext),
                )
                self._audit(connection, "member.enrolled", member_id)
        except sqlite3.IntegrityError as exc:
            raise EnrollmentConflict("member enrollment conflicts with existing record") from exc
        return member_id

    def rotate_password(self, member_id: str, new_password: str) -> None:
        """Replace ciphertext with a fresh AEAD nonce, without exposing old text."""
        if not member_id:
            raise ValueError("member ID required")
        self._password(new_password)
        with self._database.connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT key_id, nonce, ciphertext FROM credentials WHERE member_id = ?",
                (member_id,),
            ).fetchone()
            if row is None:
                member = connection.execute(
                    "SELECT 1 FROM members WHERE member_id = ?", (member_id,)
                ).fetchone()
                if member is None:
                    raise MemberNotFound("member not found")
                raise CredentialUnavailable("credential not active")
            # Detect stale/wrong keys or tampering before writing a new record.
            self._vault.open(
                SealedCredential(str(row[0]), bytes(row[1]), bytes(row[2])),
                member_id=member_id,
            )
            sealed = self._vault.seal(new_password, member_id=member_id)
            connection.execute(
                """
                UPDATE credentials
                SET key_id = ?, nonce = ?, ciphertext = ?, updated_at = CURRENT_TIMESTAMP
                WHERE member_id = ?
                """,
                (sealed.key_id, sealed.nonce, sealed.ciphertext, member_id),
            )
            self._audit(connection, "credential.rotated", member_id)

    def revoke_credential(self, member_id: str) -> bool:
        """Delete a credential while retaining identity and ticket-intent quota.

        Full personal-data erasure requires the separately reviewed retention,
        backup and identity-uniqueness design. Revocation is safe to repeat.
        """
        if not member_id:
            raise ValueError("member ID required")
        with self._database.connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            member = connection.execute(
                "SELECT 1 FROM members WHERE member_id = ?", (member_id,)
            ).fetchone()
            if member is None:
                raise MemberNotFound("member not found")
            removed = connection.execute(
                "DELETE FROM credentials WHERE member_id = ?", (member_id,)
            ).rowcount
            if removed:
                self._audit(connection, "credential.revoked", member_id)
            return bool(removed)
