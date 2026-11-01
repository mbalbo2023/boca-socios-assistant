"""Explicit local BETA service lifecycle, without listener or external bridge."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from boca_socios.browser.contracts import SyntheticBrowserPort
from boca_socios.integration.beta import BetaCoordinator
from boca_socios.integration.command_host import BetaCommandHost
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import MemberEnrollmentService
from boca_socios.storage.database import Database

_REQUIRED_MIGRATIONS = frozenset({1, 2, 3, 5, 6})
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
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class LocalRuntimeUnavailable(RuntimeError):
    """The Boca-only local service cannot be safely opened."""


def validate_existing_beta_storage(path: Path) -> None:
    """Check the required ledger through SQLite mode=ro; never migrate here.

    SQLite may interact with WAL shared-memory sidecars even on a read-only
    connection, so this is not a no-filesystem-effects forensic inventory.
    """
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise LocalRuntimeUnavailable("local BETA storage is unavailable")
    expected: dict[int, str] = {}
    for resource in files("boca_socios.storage.migrations").iterdir():
        match = _MIGRATION_NAME.fullmatch(resource.name)
        if match is not None:
            expected[int(match.group(1))] = hashlib.sha256(
                resource.read_text(encoding="utf-8").encode("utf-8")
            ).hexdigest()
    try:
        uri = f"file:{quote(str(path), safe='/')}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT version, checksum FROM schema_migrations LIMIT 32"
            ).fetchall()
            versions = {version for version, _ in rows}
            if (
                len(rows) > len(expected)
                or len(versions) != len(rows)
                or not _REQUIRED_MIGRATIONS <= versions
                or any(
                    type(version) is not int or expected.get(version) != checksum
                    for version, checksum in rows
                )
            ):
                raise LocalRuntimeUnavailable("local BETA schema is incompatible")
            tables = {
                str(name)
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not _REQUIRED_TABLES <= tables:
                raise LocalRuntimeUnavailable("local BETA schema is incompatible")
    except (OSError, sqlite3.Error, ValueError, TypeError):
        raise LocalRuntimeUnavailable("local BETA schema is unavailable") from None


class LocalBetaRuntime:
    """Own Boca-only database services and exactly one command host.

    A trusted first-install caller chooses `initialize_new=True` only after
    verifying an empty Boca namespace and approved storage destination. This
    class refuses existing data in that mode. Existing storage is validated
    without applying migrations. There is no network listener or Site client.
    """

    def __init__(
        self,
        *,
        database: Database,
        vault: CredentialVault,
        outbox: SqliteNotificationOutbox,
        commands: BetaCommandHost,
    ) -> None:
        self.database = database
        self.vault = vault
        self.outbox = outbox
        self.commands = commands
        self.members = MemberEnrollmentService(database, vault)
        self._closed = False

    @classmethod
    def start(
        cls,
        *,
        database_path: Path,
        key_file: Path,
        browser: SyntheticBrowserPort,
        initialize_new: bool = False,
        command_timeout_seconds: float = 5.0,
    ) -> LocalBetaRuntime:
        if type(initialize_new) is not bool or not database_path.is_absolute():
            raise ValueError("invalid local BETA storage configuration")
        # Key custody and mode are checked before a first-install write.
        vault = CredentialVault.from_secret_file(key_file)
        if initialize_new:
            if database_path.exists() or database_path.is_symlink():
                raise LocalRuntimeUnavailable("local BETA storage already exists")
        else:
            validate_existing_beta_storage(database_path)
        database = Database(database_path)
        outbox = SqliteNotificationOutbox(database)
        coordinator = BetaCoordinator(
            database=database,
            outbox=outbox,
            browser=browser,
            timeout_seconds=command_timeout_seconds,
        )
        if initialize_new:
            try:
                coordinator.prepare_storage()
            except (OSError, sqlite3.Error, ValueError):
                # Never remove the new file: a partial first install needs
                # explicit Boca-only diagnosis, not a silent retry.
                raise LocalRuntimeUnavailable("local BETA initialization failed") from None
        commands = BetaCommandHost.start(coordinator)
        return cls(database=database, vault=vault, outbox=outbox, commands=commands)

    @property
    def ready(self) -> bool:
        return not self._closed and not self.commands.failed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.commands.close()
