"""Explicitly migrated, singleton persistent owner authorization for Chrome.

Only SHA-256 digests of a random cookie, the public WebAuthn verifier binding
and the owner subject are persisted. CSRF, operation replay and cookie plaintext
remain process/browser-local. No constructor, lookup or authentication migrates.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing, contextmanager
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from boca_socios.storage.database import Database

_VERSION = 1
_MIGRATION = "0001_owner_browser_session.sql"
_SESSION_FILE = "boca_owner_session.sqlite3"
_EXPECTED_TABLES = ("owner_browser_session", "owner_session_schema")


class OwnerSessionStorageUnavailable(RuntimeError):
    """The durable owner authorization cannot be read or changed safely."""


def session_database_path(controller_database_path: Path) -> Path:
    """Derive one fixed sibling in Boca's existing data volume, never a new mount."""
    if not isinstance(controller_database_path, Path) or not controller_database_path.is_absolute():
        raise ValueError("controller database path must be absolute")
    if controller_database_path.name == _SESSION_FILE:
        raise ValueError("owner session path cannot be its own controller database")
    return controller_database_path.with_name(_SESSION_FILE)


def _identity(path: Path) -> tuple[int, int]:
    """Require a private, singly linked, regular SQLite file owned by this UID."""
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            raise OwnerSessionStorageUnavailable("owner session store identity unavailable")
        return metadata.st_dev, metadata.st_ino
    except OSError:
        raise OwnerSessionStorageUnavailable("owner session store identity unavailable") from None


def _schema() -> tuple[str, tuple[str, ...]]:
    sql = (
        files("boca_socios.panel.owner_session_sql")
        .joinpath(_MIGRATION)
        .read_text(encoding="utf-8")
    )
    statements = tuple(part.strip() for part in sql.split(";") if part.strip())
    if len(statements) != 2 or not all(s.startswith("CREATE TABLE ") for s in statements):
        raise OwnerSessionStorageUnavailable("owner session schema unavailable")
    return hashlib.sha256(sql.encode("utf-8")).hexdigest(), statements


@contextmanager
def _sqlite(path: Path, *, write: bool) -> Iterator[sqlite3.Connection]:
    before = _identity(path)
    uri = f"file:{quote(str(path), safe='/')}?mode={'rw' if write else 'ro'}"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            connection.execute("PRAGMA busy_timeout = 1000")
            connection.execute("PRAGMA trusted_schema = OFF")
            if not write:
                connection.execute("PRAGMA query_only = ON")
            if _identity(path) != before:
                raise OwnerSessionStorageUnavailable("owner session store identity changed")
            yield connection
            if _identity(path) != before:
                raise OwnerSessionStorageUnavailable("owner session store identity changed")
    except (OSError, sqlite3.Error, ValueError, TypeError):
        raise OwnerSessionStorageUnavailable("owner session store unavailable") from None


class OwnerBrowserSessionStore:
    """Exactly one active owner browser session, without server-side TTL.

    The owner may keep the cookie by using Chrome's persistent profile; the
    browser itself bounds each rolling cookie to at most 400 days. A new
    authenticated session replaces the old one in one SQLite transaction.
    """

    def __init__(self, database: Database, *, owner_subject: str) -> None:
        if not isinstance(database, Database) or not owner_subject or len(owner_subject) > 128:
            raise ValueError("owner browser store requires a valid Boca database and owner")
        self._controller_database_path = database.path
        self._session_database_path = session_database_path(database.path)
        self._owner_digest = hashlib.sha256(owner_subject.encode("utf-8")).digest()
        self._digest, self._statements = _schema()

    @property
    def session_database_path(self) -> Path:
        return self._session_database_path

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with _sqlite(self._session_database_path, write=write) as connection:
            yield connection

    def _require_schema(self, connection: sqlite3.Connection) -> None:
        try:
            rows = connection.execute(
                "SELECT version,checksum FROM owner_session_schema ORDER BY version LIMIT 2"
            ).fetchall()
            objects = connection.execute(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
            expected = sorted(
                ("table", name, statement)
                for name, statement in zip(_EXPECTED_TABLES, self._statements, strict=True)
            )
            if (
                rows != [(_VERSION, self._digest)]
                or objects != expected
                or connection.execute("PRAGMA user_version").fetchone() != (_VERSION,)
                or connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
            ):
                raise OwnerSessionStorageUnavailable("owner session schema unavailable")
        except sqlite3.Error:
            raise OwnerSessionStorageUnavailable("owner session schema unavailable") from None

    def migrate(self) -> None:
        """Explicit first-install test/setup call, never called during login or startup."""
        self.migrate_schema(Database(self._controller_database_path))

    @staticmethod
    def migrate_schema(database: Database) -> None:
        """Explicit first-install bootstrap of the *separate* SQLite session file.

        Never migrates, creates or writes controller boca.sqlite3. The caller
        has already initialized it and must hold the installation authority.
        An interrupted/partial session file is preserved and rejected, never
        silently repaired or deleted.
        """
        if not isinstance(database, Database):
            raise ValueError("a Boca Database is required")
        controller_identity = _identity(database.path)
        path = session_database_path(database.path)
        digest, statements = _schema()
        try:
            directory = path.parent.lstat()
            if (
                not stat.S_ISDIR(directory.st_mode)
                or directory.st_uid != os.geteuid()
                or directory.st_mode & 0o022
            ):
                raise OwnerSessionStorageUnavailable("owner session directory unavailable")
            try:
                _identity(path)
                existed = True
            except OwnerSessionStorageUnavailable:
                # Distinguish missing from unsafe: never adopt a symlink,
                # foreign-owned, multi-linked or malformed pre-existing file.
                if path.is_symlink() or path.exists():
                    raise
                descriptor = os.open(
                    path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
                )
                os.close(descriptor)
                existed = False
            session_identity = _identity(path)
            with _sqlite(path, write=True) as connection:
                if existed:
                    OwnerBrowserSessionStore._check_schema(connection, digest, statements)
                else:
                    if connection.execute("SELECT count(*) FROM sqlite_master").fetchone() != (0,):
                        raise OwnerSessionStorageUnavailable("owner session schema unavailable")
                    connection.execute("BEGIN IMMEDIATE")
                    with connection:
                        for statement in statements:
                            connection.execute(statement)
                        connection.execute(
                            "INSERT INTO owner_session_schema(version,checksum) VALUES(?,?)",
                            (_VERSION, digest),
                        )
                        connection.execute(f"PRAGMA user_version = {_VERSION}")
                        OwnerBrowserSessionStore._check_schema(connection, digest, statements)
            if (
                _identity(path) != session_identity
                or _identity(database.path) != controller_identity
            ):
                raise OwnerSessionStorageUnavailable("owner session store identity changed")
        except (OSError, sqlite3.Error, ValueError, TypeError):
            raise OwnerSessionStorageUnavailable("owner session bootstrap unavailable") from None

    @staticmethod
    def _check_schema(
        connection: sqlite3.Connection, digest: str, statements: tuple[str, ...]
    ) -> None:
        """Bootstrap validation of exactly the same strict ledger as normal reads."""
        rows = connection.execute(
            "SELECT version,checksum FROM owner_session_schema ORDER BY version LIMIT 2"
        ).fetchall()
        objects = connection.execute(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        if (
            rows != [(_VERSION, digest)]
            or objects
            != sorted(
                ("table", name, statement)
                for name, statement in zip(_EXPECTED_TABLES, statements, strict=True)
            )
            or connection.execute("PRAGMA user_version").fetchone() != (_VERSION,)
            or connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
        ):
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
