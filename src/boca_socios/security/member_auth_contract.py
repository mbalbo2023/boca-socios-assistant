"""Separate offline-contract boundary for a future owner-authorized Boca login.

No provider endpoint or HTTP client is supplied. This code never logs,
persists, invents or validates a provider bearer token. It can only process
bytes returned by an *injected* transport after an explicit call; without
that transport it fails closed before opening SQLite.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

from boca_socios.security.credential_vault import CredentialVault, SealedCredential
from boca_socios.storage.database import Database


class BocaAuthUnavailable(RuntimeError):
    """An authenticated Boca response is not demonstrably available."""


class BocaAuthState(StrEnum):
    OBSERVED_UNVERIFIED = "observed_unverified"


class BocaLoginTransport(Protocol):
    """Only a separately reviewed owner-operated adapter may implement this."""

    def login(self, *, email: str, password: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class BocaAuthSummary:
    member_id: str
    state: BocaAuthState
    observed_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class OwnerBocaAuthDetails:
    member_id: str
    observed_at: datetime
    _token: str = field(repr=False)
    _refresh_token: str = field(repr=False)

    def copy_full_token(self) -> str:
        return self._token

    def copy_full_refresh_token(self) -> str:
        return self._refresh_token


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate provider response field")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True, repr=False)
class BocaAuthObservation:
    member_id: str
    observed_at: datetime
    _token: str = field(repr=False)
    _refresh_token: str = field(repr=False)

    @classmethod
    def from_provider_response(
        cls, *, member_id: str, provider_payload: bytes, observed_at: datetime
    ) -> BocaAuthObservation:
        """Accept actual supplied JSON fields; no aliases, guesses or defaults."""
        if (
            not isinstance(member_id, str)
            or not member_id
            or not isinstance(provider_payload, bytes)
            or not 0 < len(provider_payload) <= 65_536
            or observed_at.tzinfo is None
            or observed_at.utcoffset() is None
        ):
            raise BocaAuthUnavailable("Boca response unverified")
        try:
            fields = json.loads(provider_payload, object_pairs_hook=_unique_pairs)
            if not isinstance(fields, dict):
                raise ValueError("non-object response")
            access, refresh = fields["token"], fields["refreshToken"]
            if not all(
                isinstance(value, str) and value.strip() and len(value) <= 16_384
                for value in (access, refresh)
            ):
                raise ValueError("missing provider token")
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise BocaAuthUnavailable("Boca response unverified") from None
        return cls(member_id, observed_at, access, refresh)

    def summary(self) -> BocaAuthSummary:
        return BocaAuthSummary(self.member_id, BocaAuthState.OBSERVED_UNVERIFIED, self.observed_at)

    def private_owner_details(self, *, owner_authenticated: bool) -> OwnerBocaAuthDetails:
        if owner_authenticated is not True:
            raise PermissionError("authenticated owner required")
        return OwnerBocaAuthDetails(
            self.member_id, self.observed_at, self._token, self._refresh_token
        )

    def __repr__(self) -> str:
        return f"BocaAuthObservation(member_id={self.member_id!r}, private_values=<redacted>)"


class PrivateBocaAuthMonitor:
    """Distinct from Queue-it: accepts only successful provider observations."""

    def __init__(self, *, max_observations: int = 16) -> None:
        if not 1 <= max_observations <= 64:
            raise ValueError("Boca auth observation limit must be bounded")
        self._limit = max_observations
        self._lock = Lock()
        self._records: dict[str, BocaAuthObservation] = {}

    def observe(self, observation: BocaAuthObservation) -> None:
        if not isinstance(observation, BocaAuthObservation):
            raise TypeError("only a provider response may be observed")
        with self._lock:
            if observation.member_id not in self._records and len(self._records) >= self._limit:
                raise ValueError("Boca auth observation limit reached")
            self._records[observation.member_id] = observation

    def list_summaries(self) -> tuple[BocaAuthSummary, ...]:
        with self._lock:
            observations = tuple(self._records[key] for key in sorted(self._records))
        return tuple(observation.summary() for observation in observations)

    def owner_details(
        self, member_id: str, *, owner_authenticated: bool
    ) -> OwnerBocaAuthDetails | None:
        if owner_authenticated is not True:
            raise PermissionError("authenticated owner required")
        with self._lock:
            observation = self._records.get(member_id)
        return (
            observation.private_owner_details(owner_authenticated=True)
            if observation is not None
            else None
        )


class BocaMemberAuthService:
    """One explicit exchange per call, with one existing encrypted member."""

    def __init__(
        self,
        database: Database,
        vault: CredentialVault,
        *,
        transport: BocaLoginTransport | None = None,
        monitor: PrivateBocaAuthMonitor | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._database = database
        self._vault = vault
        self._transport = transport
        self._monitor = monitor
        self._now = now

    def authenticate(self, member_id: str) -> BocaAuthObservation:
        if self._transport is None:
            raise BocaAuthUnavailable("Boca login transport not configured")
        try:
            if (
                not isinstance(member_id, str)
                or str(UUID(member_id)) != member_id
                or UUID(member_id).int == 0
            ):
                raise ValueError("unknown member")
            email, sealed = self._read_member(self._database.path, member_id)
            password = self._vault.open(sealed, member_id=member_id)
        except Exception:
            raise BocaAuthUnavailable("Boca member credential unavailable") from None
        try:
            response = self._transport.login(email=email, password=password)
            observed = BocaAuthObservation.from_provider_response(
                member_id=member_id, provider_payload=response, observed_at=self._now()
            )
            if self._monitor is not None:
                self._monitor.observe(observed)
            return observed
        except Exception:
            raise BocaAuthUnavailable("Boca response unavailable or unverified") from None

    @staticmethod
    def _read_member(path: Path, member_id: str) -> tuple[str, SealedCredential]:
        if path.is_symlink() or not path.is_file():
            raise BocaAuthUnavailable("Boca member credential unavailable")
        with closing(
            sqlite3.connect(f"file:{quote(str(path), safe='/')}?mode=ro", uri=True, timeout=1.0)
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            row = connection.execute(
                "SELECT m.email,c.key_id,c.nonce,c.ciphertext "
                "FROM members m JOIN credentials c ON c.member_id=m.member_id "
                "WHERE m.member_id=?",
                (member_id,),
            ).fetchone()
        if row is None or not isinstance(row[0], str) or not row[0]:
            raise BocaAuthUnavailable("Boca member credential unavailable")
        return row[0], SealedCredential(str(row[1]), bytes(row[2]), bytes(row[3]))
