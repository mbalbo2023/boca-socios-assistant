"""Read-only, privacy-minimal owner notice projection; no schema creation."""

from __future__ import annotations

import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from uuid import UUID

from boca_socios.notify.outbox import DeliveryState, NoticeKind
from boca_socios.storage.database import Database


@dataclass(frozen=True, slots=True)
class LocalNoticeView:
    idempotency_key: UUID
    kind: NoticeKind
    state: DeliveryState
    attempts: int
    created_at: float
    accepted_at: float | None
    telegram_state: str | None
    provider_message_id: int | None


def list_local_notices(database: Database, limit: int = 20) -> tuple[LocalNoticeView, ...]:
    """Return only allowlisted event class and delivery metadata for an owner panel.

    Callers must authenticate/authorize the owner before invoking this function.
    No member or destination identifier exists in the notification outbox.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("notice limit must be an integer between 1 and 100")
    metadata = database.path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("notice database is not a regular file")
    # A read-only URI avoids creating a DB as a side effect of a panel read.
    with closing(sqlite3.connect(database.path.as_uri() + "?mode=ro", uri=True)) as connection:
        has_telegram = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='telegram_delivery_attempts'"
            ).fetchone()
            is not None
        )
        if has_telegram:
            rows = connection.execute(
                """SELECT n.idempotency_key, n.kind, n.state, n.attempts,
                          n.created_at, n.accepted_at, t.state, t.provider_message_id
                   FROM notification_outbox AS n
                   LEFT JOIN telegram_delivery_attempts AS t
                     ON t.idempotency_key = n.idempotency_key
                   ORDER BY n.sequence DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT idempotency_key, kind, state, attempts, created_at,
                          accepted_at, NULL, NULL
                   FROM notification_outbox ORDER BY sequence DESC LIMIT ?""",
                (limit,),
            ).fetchall()
    return tuple(
        LocalNoticeView(
            idempotency_key=UUID(str(row[0])),
            kind=NoticeKind(str(row[1])),
            state=DeliveryState(str(row[2])),
            attempts=int(str(row[3])),
            created_at=float(str(row[4])),
            accepted_at=None if row[5] is None else float(str(row[5])),
            telegram_state=(
                "needs_review" if row[6] == "prepared" else None if row[6] is None else str(row[6])
            ),
            provider_message_id=None if row[7] is None else int(str(row[7])),
        )
        for row in rows
    )
