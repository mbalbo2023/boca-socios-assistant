"""Host-side lifecycle *receipt contract*, with no Docker effects or entrypoint.

Only a future, separately authorized Boca Actions executor may supply the
fresh rootless Docker/engine attestor and hold the canonical Boca job lease.
This module can append CLAIMED, UNCERTAIN and final ACK to the *existing*
controller audit ledger; it never migrates storage, sends SSH, starts/stops a
container, calls Telegram or imports the protected browser implementation.

An injected HostProbe is NOT a trusted capability merely because it satisfies
the Python Protocol. Physical use must provide a reviewed, independently
attesting exact-ID adapter and an exact-run protected GitHub authorization.
No such executable host adapter or workflow is installed by this change.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import quote

from boca_socios.host_boca_cleanup import BocaJobLease, verify_protected_boca_job_lease
from boca_socios.panel.lifecycle_intents import (
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
    host_marker,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ID = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_CONTROLLER_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_WORKER_IMAGE = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
_MIGRATION_FILES = (
    "0001_initial.sql",
    "0002_notification_outbox.sql",
    "0003_reservation_guard.sql",
    "0004_credential_key_policy.sql",
    "0005_simulation_outcomes.sql",
    "0006_beta_commands.sql",
    "0007_telegram_delivery.sql",
)
# Existing BETA installations may legitimately omit opt-in credential key
# migration 0004 and Telegram delivery migration 0007. Neither is installed
# here; any observed optional version still needs its exact packaged checksum.
_REQUIRED_LEGACY = frozenset({1, 2, 3, 5, 6})

Component = Literal["bot", "chromium"]
Target = Literal["start", "stop"]
Final = Literal["APPLIED", "REFUSED"]


class LifecycleHostUnavailable(ValueError):
    """No trustworthy exclusive Boca lifecycle claim or receipt exists."""


@dataclass(frozen=True, slots=True)
class LifecycleHostCoordinates:
    """One immutable protected Actions attempt and *existing* Boca IDs."""

    attempt_id: str
    request_id: str
    component: Component
    target: Target
    source_sha: str
    controller_id: str
    controller_image: str
    worker_id: str
    worker_image: str
    database_path: Path

    def validate(self) -> None:
        if (
            any(
                type(value) is not str
                for value in (
                    self.attempt_id,
                    self.request_id,
                    self.component,
                    self.target,
                    self.source_sha,
                    self.controller_id,
                    self.controller_image,
                    self.worker_id,
                    self.worker_image,
                )
            )
            or not _ATTEMPT.fullmatch(self.attempt_id)
            or not _SHA.fullmatch(self.source_sha)
            or not _ID.fullmatch(self.controller_id)
            or not _ID.fullmatch(self.worker_id)
            or self.worker_id == self.controller_id
            or not _CONTROLLER_IMAGE.fullmatch(self.controller_image)
            or not _WORKER_IMAGE.fullmatch(self.worker_image)
            or self.component not in ("bot", "chromium")
            or self.target not in ("start", "stop")
            or not isinstance(self.database_path, Path)
            or not self.database_path.is_absolute()
            or self.database_path.name != "boca.sqlite3"
        ):
            raise LifecycleHostUnavailable("Boca lifecycle exact coordinates invalid")
        # Reuse the panel's canonical UUID/allowed-action validation. An HTTP
        # request is never authority by itself; it is checked again in SQLite.
        try:
            host_marker(self.request_id, self.component, self.target, "CLAIMED")
        except ValueError:
            raise LifecycleHostUnavailable("Boca lifecycle request UUID invalid") from None


@dataclass(frozen=True, slots=True)
class LifecycleHostSnapshot:
    """Fresh witness that a *future* trusted rootless attestor must construct.

    The flags here are assertions, not cryptographic proof; accepting a
    caller-supplied JSON/boolean or a fake probe in production is prohibited.
    """

    controller_id: str
    controller_project: str
    controller_service: str
    controller_image: str
    controller_sha: str
    worker_id: str
    worker_project: str
    worker_service: str
    worker_image: str
    worker_sha: str
    controller_running: bool
    controller_healthy: bool
    worker_running: bool
    worker_healthy: bool
    bot_engine_running: bool | None
    worker_network_mode: str
    published_controller_port: str
    rootless_uid: int
    controller_data_volume: str
    controller_data_mountpoint: Path
    controller_data_volume_exclusive: bool
    single_boca_project_verified: bool
    rootless_boca_uid_verified: bool

    def require(self, coordinates: LifecycleHostCoordinates) -> bool:
        """Verify fixed identities and return the relevant physical state."""
        if (
            self.controller_id != coordinates.controller_id
            or self.controller_project != "boca-socios"
            or self.controller_service != "controller"
            or self.controller_image != coordinates.controller_image
            or self.controller_sha != coordinates.source_sha
            or self.worker_id != coordinates.worker_id
            or self.worker_project != "boca-socios"
            or self.worker_service != "browser-worker"
            or self.worker_image != coordinates.worker_image
            or self.worker_sha != coordinates.source_sha
            or self.worker_network_mode != "none"
            or self.published_controller_port != "127.0.0.1:8443"
            or type(self.rootless_uid) is not int
            or self.rootless_uid != 10001
            or self.controller_data_volume != "boca-socios_boca_data"
            or self.controller_data_mountpoint != coordinates.database_path.parent
            or type(self.controller_data_volume_exclusive) is not bool
            or not self.controller_data_volume_exclusive
            or any(
                type(value) is not bool
                for value in (
                    self.controller_running,
                    self.controller_healthy,
                    self.worker_running,
                    self.worker_healthy,
                    self.single_boca_project_verified,
                    self.rootless_boca_uid_verified,
                )
            )
            or self.bot_engine_running is not None
            and type(self.bot_engine_running) is not bool
            or not self.controller_running
            or not self.controller_healthy
            or not self.single_boca_project_verified
            or not self.rootless_boca_uid_verified
            or self.worker_healthy
            and not self.worker_running
        ):
            raise LifecycleHostUnavailable("Boca lifecycle exact host witness invalid")
        if coordinates.component == "bot":
            if self.bot_engine_running is None:
                raise LifecycleHostUnavailable("bot motor has no independent state witness")
            # The synthetic IPC command engine is backed by the isolated
            # Chromium worker. START without that worker's *real* healthy
            # state would report a running motor unable to perform commands.
            # STOP must still work if Chromium is absent or unhealthy.
            if coordinates.target == "start" and not (self.worker_running and self.worker_healthy):
                raise LifecycleHostUnavailable("bot requires healthy Chromium IPC worker")
            return self.bot_engine_running
        return self.worker_running and self.worker_healthy


class HostProbe(Protocol):
    """Future reviewed Docker/engine attestor; not implemented or wired here."""

    def observe(
        self, coordinates: LifecycleHostCoordinates, lease: BocaJobLease
    ) -> LifecycleHostSnapshot: ...


@dataclass(frozen=True, slots=True)
class HostLifecycleClaim:
    coordinates: LifecycleHostCoordinates
    was_running: bool


def _identity(path: Path) -> tuple[int, int]:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            raise LifecycleHostUnavailable("Boca lifecycle database identity invalid")
        return metadata.st_dev, metadata.st_ino
    except OSError:
        raise LifecycleHostUnavailable("Boca lifecycle database identity unavailable") from None


@lru_cache(maxsize=1)
def _reviewed_legacy_migrations() -> dict[int, str]:
    """Hash the *packaged, reviewed* migration SQL; never adopt host-supplied hashes."""
    package = files("boca_socios.storage.migrations")
    return {
        version: hashlib.sha256(package.joinpath(filename).read_bytes()).hexdigest()
        for version, filename in enumerate(_MIGRATION_FILES, start=1)
    }


@contextmanager
def _controller_ledger(path: Path) -> Iterator[sqlite3.Connection]:
    """Existing SQLite RW-only; no implicit create, recovery or migration."""
    before = _identity(path)
    try:
        uri = f"file:{quote(str(path), safe='/')}?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            connection.execute("PRAGMA busy_timeout=1000")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA foreign_keys=ON")
            if _identity(path) != before:
                raise LifecycleHostUnavailable("Boca lifecycle database inode changed")
            # Schema attestation and protected CLAIM/ACK must share the same
            # SQLite writer transaction. Otherwise a concurrent owner 0008
            # migration could commit after this check but before CLAIMED.
            connection.execute("BEGIN IMMEDIATE")
            # Legacy controller 0008 is forbidden even if another process
            # previously added a checksum/table that appears valid.
            rows = connection.execute(
                "SELECT version,checksum FROM schema_migrations ORDER BY version LIMIT 9"
            ).fetchall()
            expected = _reviewed_legacy_migrations()
            versions = {version for version, _ in rows}
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if (
                len(rows) > len(expected)
                or len(versions) != len(rows)
                or not _REQUIRED_LEGACY.issubset(versions)
                or any(
                    type(version) is not int
                    or version not in expected
                    or type(checksum) is not str
                    or checksum != expected[version]
                    for version, checksum in rows
                )
                or "audit_events" not in tables
                or "owner_browser_session" in tables
                or connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
            ):
                raise LifecycleHostUnavailable("Boca legacy lifecycle schema incompatible")
            yield connection
            if _identity(path) != before:
                raise LifecycleHostUnavailable("Boca lifecycle database inode changed")
    except LifecycleHostUnavailable:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError):
        raise LifecycleHostUnavailable("Boca lifecycle database unavailable") from None


def _current(
    connection: sqlite3.Connection, coordinates: LifecycleHostCoordinates, expected: str
) -> None:
    """Use exactly the same ledger reader as the unprivileged panel."""
    try:
        state = LifecycleIntentStore._current(connection)
    except (LifecycleStorageUnavailable, sqlite3.Error, ValueError, TypeError):
        raise LifecycleHostUnavailable("Boca lifecycle audit ledger invalid") from None
    if (
        state is None
        or state.operation_id != coordinates.request_id
        or state.component != coordinates.component
        or state.target != coordinates.target
        or state.status != expected
    ):
        raise LifecycleHostUnavailable("Boca lifecycle request is not claimable")


def _append(
    coordinates: LifecycleHostCoordinates,
    lease: BocaJobLease,
    *,
    phase: Literal["CLAIMED", "UNCERTAIN", "APPLIED", "REFUSED"],
    expected: tuple[str, ...],
) -> None:
    verify_protected_boca_job_lease(lease, coordinates.attempt_id)
    marker = host_marker(coordinates.request_id, coordinates.component, coordinates.target, phase)
    with _controller_ledger(coordinates.database_path) as connection, connection:
        # UNCERTAIN may be resolved by a later positive poststate (same
        # reviewed coordinates), but cannot be silently skipped or reset.
        if not any(_current_matches(connection, coordinates, candidate) for candidate in expected):
            raise LifecycleHostUnavailable("Boca lifecycle transition ordering invalid")
        connection.execute("INSERT INTO audit_events(audit_id,action) VALUES (?,?)", marker)
        _current(connection, coordinates, phase)
    verify_protected_boca_job_lease(lease, coordinates.attempt_id)


def _current_matches(
    connection: sqlite3.Connection, coordinates: LifecycleHostCoordinates, status: str
) -> bool:
    try:
        _current(connection, coordinates, status)
    except LifecycleHostUnavailable:
        return False
    return True


def claim_requested(
    coordinates: LifecycleHostCoordinates, *, lease: BocaJobLease, probe: HostProbe
) -> HostLifecycleClaim:
    """Bind exact host prestate and persist CLAIMED before any future effect."""
    coordinates.validate()
    verify_protected_boca_job_lease(lease, coordinates.attempt_id)
    try:
        before = probe.observe(coordinates, lease)
    except Exception:
        # A transport or injected attestor exception might contain foreign
        # container configuration or a secret: never reflect its text.
        raise LifecycleHostUnavailable("Boca lifecycle physical preflight unavailable") from None
    if not isinstance(before, LifecycleHostSnapshot):
        raise LifecycleHostUnavailable("Boca lifecycle physical preflight absent")
    was_running = before.require(coordinates)
    _append(coordinates, lease, phase="CLAIMED", expected=("REQUESTED",))
    return HostLifecycleClaim(coordinates, was_running)


def mark_uncertain(claim: HostLifecycleClaim, *, lease: BocaJobLease) -> None:
    """Persist uncertainty; no next request or retry is allowed without ACK."""
    if not isinstance(claim, HostLifecycleClaim):
        raise LifecycleHostUnavailable("Boca lifecycle claim absent")
    claim.coordinates.validate()
    _append(claim.coordinates, lease, phase="UNCERTAIN", expected=("CLAIMED",))


def acknowledge(
    claim: HostLifecycleClaim,
    *,
    lease: BocaJobLease,
    probe: HostProbe,
    result: Final,
    effect_attempted: bool,
) -> None:
    """Final ACK only after independently re-observed physical poststate.

    REFUSED requires proof that no effect was attempted. A failed or possibly
    partial effect MUST be UNCERTAIN, never converted to a green no-op.
    """
    if (
        not isinstance(claim, HostLifecycleClaim)
        or type(claim.was_running) is not bool
        or type(effect_attempted) is not bool
    ):
        raise LifecycleHostUnavailable("Boca lifecycle final receipt inputs invalid")
    coordinates = claim.coordinates
    coordinates.validate()
    verify_protected_boca_job_lease(lease, coordinates.attempt_id)
    try:
        after = probe.observe(coordinates, lease)
    except Exception:
        raise LifecycleHostUnavailable("Boca lifecycle physical postflight unavailable") from None
    if not isinstance(after, LifecycleHostSnapshot):
        raise LifecycleHostUnavailable("Boca lifecycle physical postflight absent")
    is_running = after.require(coordinates)
    desired = coordinates.target == "start"
    if result == "APPLIED":
        if not effect_attempted or claim.was_running == desired or is_running != desired:
            raise LifecycleHostUnavailable("Boca lifecycle applied effect unverified")
    elif result == "REFUSED":
        if effect_attempted or is_running != claim.was_running:
            raise LifecycleHostUnavailable("Boca lifecycle no-effect refusal unverified")
    else:
        raise LifecycleHostUnavailable("Boca lifecycle final status invalid")
    _append(coordinates, lease, phase=result, expected=("CLAIMED", "UNCERTAIN"))
