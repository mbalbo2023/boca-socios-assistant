"""Explicitly migrated, singleton persistent owner authorization for Chrome.

Only SHA-256 digests of a random cookie, the public WebAuthn verifier binding
and the owner subject are persisted. CSRF, operation replay and cookie plaintext
remain process/browser-local. No constructor, lookup or authentication migrates.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing, contextmanager
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from boca_socios.storage.database import Database

_VERSION = 8
_MIGRATION = "0008_owner_browser_session.sql"


class OwnerSessionStorageUnavailable(RuntimeError):
    """The durable owner authorization cannot be read or changed safely."""


class OwnerBrowserSessionStore:
    """Exactly one active owner browser session, without server-side TTL.

    The owner may keep the cookie by using Chrome's persistent profile; the
    browser itself bounds each rolling cookie to at most 400 days. A new
    authenticated session replaces the old one in one SQLite transaction.
    """

    def __init__(self, database: Database, *, owner_subject: str) -> None:
        if not isinstance(database, Database) or not owner_subject or len(owner_subject) > 128:
            raise ValueError("owner browser store requires a valid Boca database and owner")
        self._database = database
        self._owner_digest = hashlib.sha256(owner_subject.encode("utf-8")).digest()
        self._sql = (
            files("boca_socios.storage.migrations").joinpath(_MIGRATION).read_text(encoding="utf-8")
        )
        self._digest = hashlib.sha256(self._sql.encode("utf-8")).hexdigest()
        self._statement = self._sql.strip().removesuffix(";").strip()

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        path: Path = self._database.path
        try:
            meta = path.lstat()
            if not stat.S_ISREG(meta.st_mode) or path.is_symlink():
                raise OwnerSessionStorageUnavailable("owner session store unavailable")
            # mode=ro/rw never creates a file implicitly; no token data in URI.
            uri = f"file:{quote(str(path), safe='/')}?mode={'rw' if write else 'ro'}"
            with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
                connection.execute("PRAGMA busy_timeout = 1000")
                if not write:
                    connection.execute("PRAGMA query_only = ON")
                connection.execute("PRAGMA trusted_schema = OFF")
                yield connection
        except (OSError, sqlite3.Error, ValueError, TypeError):
            raise OwnerSessionStorageUnavailable("owner session store unavailable") from None

    def _require_schema(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = ?", (_VERSION,)
        ).fetchone()
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='owner_browser_session'"
        ).fetchone()
        if row != (self._digest,) or definition != (self._statement,):
            raise OwnerSessionStorageUnavailable("owner session schema unavailable")

    def migrate(self) -> None:
        """Run only during explicit first-install or protected in-place upgrade."""
        self.migrate_schema(self._database)

    @staticmethod
    def migrate_schema(database: Database) -> None:
        """DDL-only initializer: no owner has to exist to create the table."""
        if not isinstance(database, Database):
            raise ValueError("a Boca Database is required")
        sql = (
            files("boca_socios.storage.migrations").joinpath(_MIGRATION).read_text(encoding="utf-8")
        )
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        statement = sql.strip().removesuffix(";").strip()
        database.migrate()
        with database.connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version = ?", (_VERSION,)
            ).fetchone()
            if row is None:
                connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, checksum) VALUES (?, ?)",
                    (_VERSION, digest),
                )
            else:
                definition = connection.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='owner_browser_session'"
                ).fetchone()
                if row != (digest,) or definition != (statement,):
                    raise OwnerSessionStorageUnavailable("owner session schema unavailable")

    def verify_schema(self) -> None:
        """Read-only verification for host preflight; no migration on startup."""
        with self._connect() as connection:
            self._require_schema(connection)

    def replace(self, token_sha256: bytes, verifier_sha256: bytes) -> None:
        """Make a new, verified owner login the ONLY authorized browser token."""
        self._validate_hashes(token_sha256, verifier_sha256)
        with self._connect(write=True) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_schema(connection)
            connection.execute(
                "INSERT INTO owner_browser_session"
                "(singleton,token_sha256,verifier_sha256,owner_sha256)"
                " VALUES (1,?,?,?)"
                " ON CONFLICT(singleton) DO UPDATE SET"
                " token_sha256=excluded.token_sha256,"
                " verifier_sha256=excluded.verifier_sha256,"
                " owner_sha256=excluded.owner_sha256,"
                " authenticated_at=CURRENT_TIMESTAMP",
                (token_sha256, verifier_sha256, self._owner_digest),
            )

    def matches(self, token_sha256: bytes, verifier_sha256: bytes) -> bool:
        self._validate_hashes(token_sha256, verifier_sha256)
        with self._connect() as connection:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT token_sha256,verifier_sha256,owner_sha256"
                " FROM owner_browser_session WHERE singleton = 1"
            ).fetchone()
        return bool(
            row is not None
            and all(isinstance(item, bytes) and len(item) == 32 for item in row)
            and hmac.compare_digest(row[0], token_sha256)
            and hmac.compare_digest(row[1], verifier_sha256)
            and hmac.compare_digest(row[2], self._owner_digest)
        )

    def revoke_matching(self, token_sha256: bytes, verifier_sha256: bytes) -> None:
        """A stale cookie must never delete a replacement owner's authorization."""
        self._validate_hashes(token_sha256, verifier_sha256)
        with self._connect(write=True) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_schema(connection)
            row = connection.execute(
                "SELECT token_sha256,verifier_sha256,owner_sha256"
                " FROM owner_browser_session WHERE singleton = 1"
            ).fetchone()
            if (
                row is not None
                and all(isinstance(item, bytes) and len(item) == 32 for item in row)
                and hmac.compare_digest(row[0], token_sha256)
                and hmac.compare_digest(row[1], verifier_sha256)
                and hmac.compare_digest(row[2], self._owner_digest)
            ):
                connection.execute("DELETE FROM owner_browser_session WHERE singleton = 1")

    @staticmethod
    def _validate_hashes(token_sha256: bytes, verifier_sha256: bytes) -> None:
        if (
            not isinstance(token_sha256, bytes)
            or len(token_sha256) != 32
            or not isinstance(verifier_sha256, bytes)
            or len(verifier_sha256) != 32
        ):
            raise ValueError("owner session digests must be exact SHA-256 values")
