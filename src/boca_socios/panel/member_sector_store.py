"""Persistent synthetic sector defaults, linked to existing Boca member IDs.

The legacy controller database is *read only* here: its migration 0008 is
forbidden. The owner must explicitly initialize this private sibling SQLite;
no panel request, constructor, or login silently creates database files.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from boca_socios.domain.sector_preferences import SectorMode, SectorPreference

_BASENAME = "boca_sector_preferences.sqlite3"
_DDL = (
    "CREATE TABLE member_sector_preferences (\n"
    "  member_id TEXT PRIMARY KEY,\n"
    "  mode TEXT NOT NULL CHECK(mode IN ('ALL','ORDERED_ALLOWLIST')),\n"
    "  sector_ids_json TEXT NOT NULL,\n"
    "  version INTEGER NOT NULL CHECK(version >= 1),\n"
    "  updated_at TEXT NOT NULL\n"
    ");\n"
    "CREATE TABLE member_sector_schema (\n"
    "  version INTEGER PRIMARY KEY,\n"
    "  checksum TEXT NOT NULL\n"
    ");\n"
)
_STATEMENTS = tuple(part.strip() for part in _DDL.split(";") if part.strip())
_DIGEST = hashlib.sha256(_DDL.encode("utf-8")).hexdigest()


class MemberSectorStorageUnavailable(RuntimeError):
    """The private preference store cannot be safely used."""


@dataclass(frozen=True, slots=True)
class MemberSectorDefaults:
    member_id: str
    mode: SectorMode
    sector_ids: tuple[str, ...]
    version: int
    updated_at: datetime

    def __post_init__(self) -> None:
        if len(self.sector_ids) > 20 or any(
            not isinstance(item, str) or len(item) > 80 for item in self.sector_ids
        ):
            raise ValueError("at most 20 sector IDs of up to 80 characters are supported")
        self.for_event("__profile_default_validation__")

    def for_event(self, event_id: str) -> SectorPreference:
        """Build one existing per-event simulation rule; never a reservation."""
        return SectorPreference(
            member_id=self.member_id,
            event_id=event_id,
            mode=self.mode,
            sector_ids=self.sector_ids,
            version=self.version,
            updated_at=self.updated_at,
        )


def _identity(path: Path) -> tuple[int, int]:
    try:
        meta = path.lstat()
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_uid != os.geteuid()
            or meta.st_gid != os.getegid()
            or stat.S_IMODE(meta.st_mode) != 0o600
            or meta.st_nlink != 1
        ):
            raise MemberSectorStorageUnavailable("private sector storage identity invalid")
        return meta.st_dev, meta.st_ino
    except OSError:
        raise MemberSectorStorageUnavailable("private sector storage unavailable") from None


def _directory(path: Path) -> None:
    try:
        meta = path.lstat()
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_mode & 0o022:
            raise MemberSectorStorageUnavailable("private sector directory invalid")
    except OSError:
        raise MemberSectorStorageUnavailable("private sector directory unavailable") from None


@contextmanager
def _connect(path: Path, *, write: bool) -> Iterator[sqlite3.Connection]:
    before = _identity(path)
    uri = f"file:{quote(str(path), safe='/')}?mode={'rw' if write else 'ro'}"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA busy_timeout=1000")
            if not write:
                connection.execute("PRAGMA query_only=ON")
            if _identity(path) != before:
                raise MemberSectorStorageUnavailable("private sector storage identity changed")
            yield connection
            if _identity(path) != before:
                raise MemberSectorStorageUnavailable("private sector storage identity changed")
    except (OSError, sqlite3.Error, TypeError, ValueError):
        raise MemberSectorStorageUnavailable("private sector storage unavailable") from None


class MemberSectorStore:
    """Member defaults in a private SQLite sibling; no duplicate member records."""

    def __init__(self, controller_database_path: Path, preferences_path: Path) -> None:
        if (
            not controller_database_path.is_absolute()
            or preferences_path != controller_database_path.with_name(_BASENAME)
        ):
            raise ValueError("member preferences must be in the existing Boca data volume")
        self._controller_path = controller_database_path
        self.path = preferences_path

    @classmethod
    def for_database(cls, controller_database_path: Path) -> MemberSectorStore:
        return cls(controller_database_path, controller_database_path.with_name(_BASENAME))

    def _member_exists(self, member_id: str) -> bool:
        # A member is registered only in the canonical controller database.
        uri = f"file:{quote(str(self._controller_path), safe='/')}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
                connection.execute("PRAGMA trusted_schema=OFF")
                connection.execute("PRAGMA query_only=ON")
                return (
                    connection.execute(
                        "SELECT 1 FROM members WHERE member_id=?", (member_id,)
                    ).fetchone()
                    is not None
                )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise MemberSectorStorageUnavailable("canonical member directory unavailable") from None

    @staticmethod
    def _require_schema(connection: sqlite3.Connection) -> None:
        try:
            ledger = connection.execute(
                "SELECT version,checksum FROM member_sector_schema"
            ).fetchall()
            objects = connection.execute(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
            expected = sorted(
                ("table", name, statement)
                for name, statement in zip(
                    ("member_sector_preferences", "member_sector_schema"), _STATEMENTS, strict=True
                )
            )
            if (
                ledger != [(1, _DIGEST)]
                or objects != expected
                or connection.execute("PRAGMA user_version").fetchone() != (1,)
                or connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
            ):
                raise MemberSectorStorageUnavailable("member sector schema invalid")
        except sqlite3.Error:
            raise MemberSectorStorageUnavailable("member sector schema unavailable") from None

    def migrate(self) -> None:
        """Explicit owner setup; never modifies the controller database."""
        _directory(self.path.parent)
        try:
            _identity(self._controller_path)
            try:
                _identity(self.path)
                existed = True
            except MemberSectorStorageUnavailable:
                if self.path.is_symlink() or self.path.exists():
                    raise
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
                existed = False
            with _connect(self.path, write=True) as connection:
                if existed:
                    self._require_schema(connection)
                else:
                    if connection.execute("SELECT count(*) FROM sqlite_master").fetchone() != (0,):
                        raise MemberSectorStorageUnavailable(
                            "new member sector database is not empty"
                        )
                    connection.execute("BEGIN IMMEDIATE")
                    with connection:
                        for statement in _STATEMENTS:
                            connection.execute(statement)
                        connection.execute(
                            "INSERT INTO member_sector_schema(version,checksum) VALUES (1,?)",
                            (_DIGEST,),
                        )
                        connection.execute("PRAGMA user_version=1")
                        self._require_schema(connection)
        except (OSError, sqlite3.Error):
            raise MemberSectorStorageUnavailable("member sector bootstrap unavailable") from None

    def load(self, member_id: str) -> MemberSectorDefaults | None:
        if not self._member_exists(member_id):
            return None
        if not self.path.is_symlink() and not self.path.exists():
            return None  # The profile may open before explicit installation.
        with _connect(self.path, write=False) as connection:
            self._require_schema(connection)
            row = connection.execute(
                "SELECT mode,sector_ids_json,version,updated_at "
                "FROM member_sector_preferences WHERE member_id=?",
                (member_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            mode, serialized, version, timestamp = row
            sectors = json.loads(serialized)
            if not isinstance(sectors, list) or not all(isinstance(x, str) for x in sectors):
                raise ValueError("invalid stored sector IDs")
            return MemberSectorDefaults(
                member_id,
                SectorMode(mode),
                tuple(sectors),
                version,
                datetime.fromisoformat(timestamp),
            )
        except (ValueError, TypeError, OverflowError):
            raise MemberSectorStorageUnavailable("member sector preference invalid") from None

    def save(
        self,
        member_id: str,
        mode: SectorMode,
        sector_ids: tuple[str, ...],
        updated_at: datetime,
    ) -> MemberSectorDefaults:
        # Validate *before* touching storage, retaining the last valid selection.
        MemberSectorDefaults(member_id, mode, sector_ids, 1, updated_at)
        if not self._member_exists(member_id):
            raise LookupError("registered member not found")
        with _connect(self.path, write=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            with connection:
                self._require_schema(connection)
                current = connection.execute(
                    "SELECT version FROM member_sector_preferences WHERE member_id=?", (member_id,)
                ).fetchone()
                version = 1 if current is None else int(current[0]) + 1
                result = MemberSectorDefaults(member_id, mode, sector_ids, version, updated_at)
                connection.execute(
                    "INSERT INTO member_sector_preferences"
                    "(member_id,mode,sector_ids_json,version,updated_at) VALUES (?,?,?,?,?)"
                    " ON CONFLICT(member_id) DO UPDATE SET"
                    " mode=excluded.mode,sector_ids_json=excluded.sector_ids_json,"
                    " version=excluded.version,updated_at=excluded.updated_at",
                    (
                        member_id,
                        mode.value,
                        json.dumps(sector_ids, separators=(",", ":")),
                        version,
                        updated_at.isoformat(),
                    ),
                )
        return result
