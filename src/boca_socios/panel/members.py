"""Bounded read-only private member and command projections.

This view does not open a writable connection or return credential material.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from uuid import UUID


class MemberListUnavailable(Exception):
    """The private local list could not be read safely."""


@dataclass(frozen=True, slots=True)
class MemberView:
    member_id: str
    display_name: str
    masked_email: str
    credential_active: bool


@dataclass(frozen=True, slots=True)
class CommandView:
    command_id: str
    member_id: str
    state: str
    updated_at: float


class MemberDirectory:
    def __init__(self, database_path: Path) -> None:
        if not database_path.is_absolute():
            raise ValueError("database path must be absolute")
        self._path = database_path

    def _connection(self) -> sqlite3.Connection:
        if self._path.is_symlink() or not self._path.is_file():
            raise MemberListUnavailable("local member list unavailable")
        connection = sqlite3.connect(
            f"file:{quote(str(self._path), safe='/')}?mode=ro", uri=True, timeout=1.0
        )
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        return connection

    @staticmethod
    def _member_id(value: object) -> str:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise MemberListUnavailable("local member list unavailable")
        return value

    def list_members(self) -> tuple[MemberView, ...]:
        try:
            with closing(self._connection()) as connection:
                rows = connection.execute(
                    """SELECT m.member_id,m.display_name,m.email,
                              (c.member_id IS NOT NULL) FROM members m
                       LEFT JOIN credentials c ON c.member_id=m.member_id
                       ORDER BY m.created_at DESC,m.member_id LIMIT 51"""
                ).fetchall()
            if len(rows) > 50:
                raise MemberListUnavailable("local member list exceeds limit")
            result = []
            for member_id, name, email, active in rows:
                identifier = self._member_id(member_id)
                if not isinstance(email, str) or "@" not in email:
                    raise MemberListUnavailable("local member list unavailable")
                local, domain = email.rsplit("@", 1)
                masked = (local[:1] or "•") + "•••@" + domain
                result.append(MemberView(identifier, str(name or ""), masked, bool(active)))
            return tuple(result)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            raise MemberListUnavailable("local member list unavailable") from None

    def active_member(self, member_id: str) -> bool:
        self._member_id(member_id)
        try:
            with closing(self._connection()) as connection:
                return (
                    connection.execute(
                        "SELECT 1 FROM credentials WHERE member_id=?", (member_id,)
                    ).fetchone()
                    is not None
                )
        except (OSError, sqlite3.Error):
            raise MemberListUnavailable("local member list unavailable") from None

    def list_commands(self) -> tuple[CommandView, ...]:
        try:
            with closing(self._connection()) as connection:
                rows = connection.execute(
                    """SELECT c.command_id,t.member_id,c.state,c.updated_at
                       FROM beta_commands c JOIN ticket_requests t ON t.request_id=c.request_id
                       ORDER BY c.updated_at DESC,c.command_id LIMIT 51"""
                ).fetchall()
            if len(rows) > 50:
                raise MemberListUnavailable("local command list exceeds limit")
            return tuple(
                CommandView(
                    self._member_id(command_id),
                    self._member_id(member_id),
                    str(state),
                    float(updated_at),
                )
                for command_id, member_id, state, updated_at in rows
            )
        except (OSError, sqlite3.Error, ValueError, TypeError):
            raise MemberListUnavailable("local command list unavailable") from None

    def command_member(self, command_id: str) -> str | None:
        self._member_id(command_id)
        try:
            with closing(self._connection()) as connection:
                row = connection.execute(
                    """SELECT t.member_id FROM beta_commands c JOIN ticket_requests t
                       ON t.request_id=c.request_id WHERE c.command_id=?""",
                    (command_id,),
                ).fetchone()
            return self._member_id(row[0]) if row is not None else None
        except (OSError, sqlite3.Error, ValueError, TypeError):
            raise MemberListUnavailable("local command unavailable") from None
