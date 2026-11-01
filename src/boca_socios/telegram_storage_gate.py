"""Explicit additive Telegram schema gate on an existing, stopped BETA DB.

The protected host helper mounts only Boca data with no network. This module
never creates a database and never sends a notice.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import sys
from contextlib import closing
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_delivery import TelegramDeliveryCoordinator
from boca_socios.notify.telegram_transport import TelegramAck, TelegramNotice

DATABASE = Path("/data/boca.sqlite3")
MIGRATIONS = (
    "0001_initial.sql",
    "0002_notification_outbox.sql",
    "0003_reservation_guard.sql",
    "0004_credential_key_policy.sql",
    "0005_simulation_outcomes.sql",
    "0006_beta_commands.sql",
    "0007_telegram_delivery.sql",
)


class StorageGateError(ValueError):
    """A fixed, redacted schema or custody failure."""


def _identity(path: Path) -> tuple[int, int]:
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (10001,) * 4:
        raise StorageGateError("identity")
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 10001
        or metadata.st_gid != 10001
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise StorageGateError("database_identity")
    return metadata.st_dev, metadata.st_ino


def verify(path: Path = DATABASE, *, require_telegram: bool = True) -> None:
    """Require a contiguous exact ledger, real tables and a sound read-only DB."""
    identity = _identity(path)
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=3)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        rows = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version LIMIT 8"
        ).fetchall()
        expected_count = 7 if require_telegram else 6
        if len(rows) != expected_count:
            raise StorageGateError("schema_ledger")
        for index, (version, checksum) in enumerate(rows, 1):
            sql = (
                files("boca_socios.storage.migrations").joinpath(MIGRATIONS[index - 1]).read_bytes()
            )
            if (
                type(version) is not int
                or version != index
                or checksum != hashlib.sha256(sql).hexdigest()
            ):
                raise StorageGateError("schema_checksum")
        required = {"ticket_requests", "notification_outbox", "beta_commands"}
        if require_telegram:
            required.add("telegram_delivery_attempts")
        actual = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?)",
                (*sorted(required), *("",) * (4 - len(required))),
            )
        }
        if actual != required:
            raise StorageGateError("schema_tables")
        if connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
            raise StorageGateError("database_integrity")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StorageGateError("database_integrity")
    if _identity(path) != identity:
        raise StorageGateError("database_changed")


def migrate(path: Path = DATABASE) -> None:
    """Only 1..6 or a verified 1..7 may be present before migration."""
    try:
        verify(path, require_telegram=True)
        return
    except StorageGateError as exc:
        if str(exc) != "schema_ledger":
            raise
    verify(path, require_telegram=False)
    coordinator = TelegramDeliveryCoordinator(
        SqliteNotificationOutbox(path), _NoTransport(), lambda: 0.0, max_per_tick=1
    )
    coordinator.prepare_storage()
    verify(path)


class _NoTransport:
    def preflight(self) -> None:
        raise StorageGateError("transport_forbidden")

    async def send(self, _notice: TelegramNotice) -> TelegramAck:
        raise StorageGateError("transport_forbidden")


def main(argv: tuple[str, ...] | None = None) -> int:
    args = tuple(sys.argv[1:]) if argv is None else argv
    try:
        if args == ("migrate",):
            migrate()
        elif args == ("verify",):
            verify()
        else:
            raise StorageGateError("invalid_phase")
    except Exception:
        print("BOCA_TELEGRAM_STORAGE state=NO_GO", file=sys.stderr)
        return 1
    print(
        f"BOCA_TELEGRAM_STORAGE state={'MIGRATED' if args[0] == 'migrate' else 'VERIFIED'} schema=0007"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
