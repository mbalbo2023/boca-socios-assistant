"""Explicit, stopped-controller-only upgrade of an EXISTING Boca BETA DB.

This module has no CLI, host probe, startup hook or Docker side effects. The
protected host owner must supply a live, exclusive controller-stop capability;
an input flag, JSON receipt or historic workflow result is not that evidence.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager, closing
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from boca_socios.integration.operational import (
    LocalRuntimeUnavailable,
    validate_existing_beta_storage,
)

DATABASE = Path("/data/boca.sqlite3")
_BOCA_UID = 10001
_BOCA_GID = 10001
_REQUIRED_VERSIONS = frozenset({1, 2, 3, 5, 6})
_REQUIRED_TABLES = frozenset(
    {
        "members",
        "credentials",
        "events",
        "ticket_requests",
        "notification_outbox",
        "reservation_attempts",
        "beta_commands",
        "beta_command_keys",
    }
)
_OWNER_TABLE = "owner_browser_session"
_OWNER_MIGRATION = "0008_owner_browser_session.sql"


class OwnerSessionUpgradeUnavailable(RuntimeError):
    """Host evidence, SQLite custody, schema or postcondition failed closed."""


class UpgradeResult(StrEnum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"


class ControllerStoppedEvidence(ABC):
    """Host-verified exclusive controller-stop lease, NOT a user assertion.

    The protected Boca-only host implementation must inspect actual container
    state and mounted volume, and hold controller stopped/exclusive until the
    context exits. It must verify that the requested device/inode is the Boca
    controller DB and that no controller writer can restart concurrently.

    No production implementation or factory lives here: an untrusted caller
    cannot request an upgrade by submitting ``stopped=True`` or a receipt.
    """

    @abstractmethod
    def exclusive_stop(
        self, *, database_path: Path, device: int, inode: int
    ) -> AbstractContextManager[None]:
        """Revalidate live trusted host state and hold its exclusive stop."""


def _identity(path: Path) -> tuple[int, int]:
    if not path.is_absolute() or path != DATABASE:
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


def _expected_sql() -> tuple[dict[int, str], str]:
    resources = files("boca_socios.storage.migrations")
    checksums: dict[int, str] = {}
    for version in range(1, 9):
        matches = [
            resource
            for resource in resources.iterdir()
            if resource.name.startswith(f"{version:04d}_") and resource.name.endswith(".sql")
        ]
        if len(matches) != 1:
            raise OwnerSessionUpgradeUnavailable("packaged migration set unavailable")
        checksums[version] = hashlib.sha256(matches[0].read_bytes()).hexdigest()
    sql = resources.joinpath(_OWNER_MIGRATION).read_text(encoding="utf-8")
    statement = sql.strip().removesuffix(";").strip()
    return checksums, statement


def _schema_state(connection: sqlite3.Connection, expected: dict[int, str], statement: str) -> bool:
    ledger = connection.execute(
        "SELECT version,checksum FROM schema_migrations ORDER BY version LIMIT 10"
    ).fetchall()
    versions = {version for version, _ in ledger}
    if (
        len(ledger) != len(versions)
        or len(ledger) > len(expected)
        or not _REQUIRED_VERSIONS <= versions
        or any(
            type(version) is not int or expected.get(version) != checksum
            for version, checksum in ledger
        )
    ):
        raise OwnerSessionUpgradeUnavailable("controller migration ledger incompatible")
    tables = {
        name
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if not _REQUIRED_TABLES <= tables:
        raise OwnerSessionUpgradeUnavailable("controller schema incompatible")
    if (4 in versions and "credential_key_policy" not in tables) or (
        7 in versions and "telegram_delivery_attempts" not in tables
    ):
        raise OwnerSessionUpgradeUnavailable("controller optional schema incompatible")
    actual = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (_OWNER_TABLE,)
    ).fetchone()
    if (8 in versions) != (actual is not None):
        raise OwnerSessionUpgradeUnavailable("controller owner schema partially applied")
    if actual is not None and actual != (statement,):
        raise OwnerSessionUpgradeUnavailable("controller owner schema incompatible")
    if connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
        raise OwnerSessionUpgradeUnavailable("controller database integrity unavailable")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise OwnerSessionUpgradeUnavailable("controller database integrity unavailable")
    return 8 in versions


def upgrade_existing_owner_schema_0008(
    evidence: ControllerStoppedEvidence, *, path: Path = DATABASE
) -> UpgradeResult:
    """Add *only* 0008 to the exact installed Boca controller DB, once.

    No controller-stop capability is fabricated here. The trusted host owner
    must supply live evidence and exclusive writer control for the whole block.
    No login, HTTP handler, constructor or normal startup calls this function.
    """
    if not isinstance(evidence, ControllerStoppedEvidence):
        raise OwnerSessionUpgradeUnavailable("trusted controller stop evidence required")
    first_identity = _identity(path)
    with evidence.exclusive_stop(
        database_path=path, device=first_identity[0], inode=first_identity[1]
    ):
        if _identity(path) != first_identity:
            raise OwnerSessionUpgradeUnavailable("controller database identity changed")
        try:
            validate_existing_beta_storage(path)
            expected, statement = _expected_sql()
            # SQLite mode=rw never silently creates a missing database. The
            # entire precondition check is repeated UNDER the writer lock.
            uri = f"file:{quote(str(path), safe='/')}?mode=rw"
            with closing(sqlite3.connect(uri, uri=True, timeout=3.0)) as connection:
                connection.execute("PRAGMA busy_timeout=3000")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA trusted_schema=OFF")
                connection.execute("BEGIN IMMEDIATE")
                with connection:
                    if _identity(path) != first_identity:
                        raise OwnerSessionUpgradeUnavailable("controller database identity changed")
                    already = _schema_state(connection, expected, statement)
                    if not already:
                        connection.execute(statement)
                        connection.execute(
                            "INSERT INTO schema_migrations(version, checksum) VALUES (8, ?)",
                            (expected[8],),
                        )
                    if not _schema_state(connection, expected, statement):
                        raise OwnerSessionUpgradeUnavailable("controller owner schema unavailable")
                    if _identity(path) != first_identity:
                        raise OwnerSessionUpgradeUnavailable("controller database identity changed")
            validate_existing_beta_storage(path)
            if _identity(path) != first_identity:
                raise OwnerSessionUpgradeUnavailable("controller database identity changed")
        except (LocalRuntimeUnavailable, OSError, sqlite3.Error, ValueError, TypeError):
            raise OwnerSessionUpgradeUnavailable("controller storage upgrade unavailable") from None
    return UpgradeResult.ALREADY_APPLIED if already else UpgradeResult.APPLIED
