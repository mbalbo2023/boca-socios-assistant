"""Protected bootstrap for a SEPARATE Chrome owner-session SQLite file.

The controller's /data/boca.sqlite3 schema and migration ledger are never
written. No CLI, authentication path or startup hook calls this module.
An actual trusted stopped-controller capability and uninterrupted Boca lease
must be supplied by the one reviewed host transaction.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager, closing
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote

from boca_socios.integration.operational import (
    LocalRuntimeUnavailable,
    validate_existing_beta_storage,
)
from boca_socios.panel.owner_session_store import (
    OwnerBrowserSessionStore,
    OwnerSessionStorageUnavailable,
    session_database_path,
)
from boca_socios.storage.database import Database

DATABASE = Path("/data/boca.sqlite3")
_BOCA_UID = 10001
_BOCA_GID = 10001


class OwnerSessionUpgradeUnavailable(RuntimeError):
    """Host evidence, SQLite identity or independent session bootstrap failed closed."""


class SessionBootstrapResult(StrEnum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"


class UpgradeResult(StrEnum):
    """Historical 0008 legacy-migration result; kept only for rejected callers."""

    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"


class ControllerStoppedEvidence(ABC):
    """Concrete host attestation of stopped controller and exclusive Boca job lease.

    Neither a boolean nor JSON receipt authorizes a database bootstrap. The
    protected host implementation must check real container identity, mounts,
    original source/image and no competing writer while holding its lease.
    """

    @abstractmethod
    def exclusive_stop(
        self, *, database_path: Path, device: int, inode: int
    ) -> AbstractContextManager[None]:
        """Revalidate live host state while the same lease protects this operation."""


def _identity(path: Path, *, authorized_path: Path = DATABASE) -> tuple[int, int]:
    if not path.is_absolute() or path != authorized_path:
        raise OwnerSessionUpgradeUnavailable("controller database scope unavailable")
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (
        _BOCA_UID,
        _BOCA_UID,
        _BOCA_GID,
        _BOCA_GID,
    ):
        raise OwnerSessionUpgradeUnavailable("controller runtime identity unavailable")
    try:
        metadata = path.lstat()
    except OSError:
        raise OwnerSessionUpgradeUnavailable("controller database identity unavailable") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != _BOCA_UID
        or metadata.st_gid != _BOCA_GID
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise OwnerSessionUpgradeUnavailable("controller database identity unavailable")
    return metadata.st_dev, metadata.st_ino


def _validate_legacy_session_boundary(path: Path) -> None:
    """Reject orphan 0008/table and inconsistent optional legacy ledgers."""
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        versions = {
            version for (version,) in connection.execute("SELECT version FROM schema_migrations")
        }
        tables = {
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if (
            8 in versions
            or "owner_browser_session" in tables
            or (4 in versions) != ("credential_key_policy" in tables)
            or (7 in versions) != ("telegram_delivery_attempts" in tables)
            or connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
            or connection.execute("PRAGMA foreign_key_check").fetchone() is not None
        ):
            raise OwnerSessionUpgradeUnavailable("legacy controller schema incompatible")


def upgrade_existing_owner_schema_0008(
    evidence: ControllerStoppedEvidence, *, path: Path = DATABASE
) -> UpgradeResult:
    """Permanently deny the obsolete in-place legacy migration (Option A).

    This old API intentionally cannot ever write 0008, including for a future
    apparently compatible controller SHA. Option B is the only authorized
    development path. It is not enough to pass a purported stopped flag.
    """
    raise OwnerSessionUpgradeUnavailable(
        "legacy schema 0008 migration prohibited; use separate Boca session store"
    )


def bootstrap_existing_owner_session(
    evidence: ControllerStoppedEvidence, *, path: Path = DATABASE
) -> SessionBootstrapResult:
    """Initialize only boca_owner_session.sqlite3 under a trusted host lease.

    The original controller DB must remain stopped, regular and its schema
    compatible with the *old installed* binary. The sidecar is new within the
    SAME existing data volume. Missing/partial/unsafe pre-existing state
    returns NO_GO; no repair, backup, deletion, WAL purge or other host action.
    """
    if not isinstance(evidence, ControllerStoppedEvidence):
        raise OwnerSessionUpgradeUnavailable("trusted controller stop evidence required")
    authorized_path = DATABASE
    if path != DATABASE:
        from boca_socios.panel.owner_session_host_attestor import DockerStoppedControllerEvidence

        if not isinstance(evidence, DockerStoppedControllerEvidence):
            raise OwnerSessionUpgradeUnavailable("controller database scope unavailable")
        if evidence.borrowed_lease_fd is None:
            raise OwnerSessionUpgradeUnavailable("outer protected Boca job lease required")
        authorized_path = evidence.host_database_path()
        if path != authorized_path:
            raise OwnerSessionUpgradeUnavailable("controller database scope unavailable")
    initial_identity = _identity(path, authorized_path=authorized_path)
    with evidence.exclusive_stop(
        database_path=path, device=initial_identity[0], inode=initial_identity[1]
    ):
        if _identity(path, authorized_path=authorized_path) != initial_identity:
            raise OwnerSessionUpgradeUnavailable("controller database identity changed")
        try:
            validate_existing_beta_storage(path)
            _validate_legacy_session_boundary(path)
            session_path = session_database_path(path)
            try:
                session_path.lstat()
                existed = True
            except FileNotFoundError:
                existed = False
            # Explicit bootstrap writes ONLY the separate file. Its own checks
            # enforce O_EXCL creation, 0600/UID/GID/nlink, exact DDL and ledger.
            OwnerBrowserSessionStore.migrate_schema(Database(path))
            OwnerBrowserSessionStore(
                Database(path), owner_subject="schema-bootstrap-only"
            ).verify_schema()
            validate_existing_beta_storage(path)
            _validate_legacy_session_boundary(path)
            if _identity(path, authorized_path=authorized_path) != initial_identity:
                raise OwnerSessionUpgradeUnavailable("controller database identity changed")
        except (
            LocalRuntimeUnavailable,
            OwnerSessionStorageUnavailable,
            OSError,
            sqlite3.Error,
            ValueError,
        ):
            raise OwnerSessionUpgradeUnavailable(
                "separate owner session bootstrap unavailable"
            ) from None
    return SessionBootstrapResult.ALREADY_APPLIED if existed else SessionBootstrapResult.APPLIED
