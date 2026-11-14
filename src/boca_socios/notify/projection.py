"""Read-only, privacy-minimal owner notice projection; no schema creation."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from boca_socios.notify.outbox import DeliveryState, NoticeKind
from boca_socios.storage.database import Database

TELEGRAM_ADMIN_RECEIPT_FILENAME = "boca_telegram_admin_status_v1.json"
TELEGRAM_ADMIN_FRESH_SECONDS = 300
_ADMIN_RECEIPT_LIMIT = 4096
_ADMIN_FIELDS = frozenset(
    {
        "version",
        "source_sha",
        "observation_run_id",
        "installation_run_id",
        "controller_id",
        "worker_id",
        "sender_id",
        "observed_at",
        "configured",
        "paired",
        "sender",
        "human_receipt",
    }
)
TelegramConfiguredState = Literal["ABSENT", "VERIFIED", "UNVERIFIED"]
TelegramPairingState = Literal["NOT_PAIRED", "VERIFIED", "UNVERIFIED"]
TelegramSenderState = Literal["ABSENT", "STOPPED", "RUNNING", "UNVERIFIED"]
TelegramReceiptState = Literal["ABSENT", "INVALID", "FRESH", "STALE"]


@dataclass(frozen=True, slots=True)
class TelegramHostObservation:
    """Redacted facts from a protected local host observation, not activation authority.

    The protected writer verifies these installation/container identities before
    publishing a private 0600 file. The panel never receives the Telegram custody
    volume, provider token, destination, or permission to control the sender.
    """

    source_sha: str
    observation_run_id: str
    installation_run_id: str
    controller_id: str
    worker_id: str
    sender_id: str | None
    observed_at: datetime
    configured: TelegramConfiguredState
    paired: TelegramPairingState
    sender: TelegramSenderState
    human_receipt: Literal["UNVERIFIED"] = "UNVERIFIED"


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


@dataclass(frozen=True, slots=True)
class TelegramAdminSnapshot:
    """Keep host evidence, preparation capability and delivery history independent."""

    observed_at: datetime
    staging_available: bool
    receipt_state: TelegramReceiptState
    host_observation: TelegramHostObservation | None
    history_available: bool
    notices: tuple[LocalNoticeView, ...]


def _unique_admin_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Telegram observation is not verifiable")
        result[key] = value
    return result


def _admin_string(document: dict[str, object], name: str, pattern: str) -> str:
    value = document[name]
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError("Telegram observation is not verifiable")
    return value


def parse_telegram_admin_receipt(
    raw: bytes, *, expected_source_sha: str, now: datetime
) -> TelegramHostObservation:
    """Validate a bounded closed schema; no provider call or secret-file access.

    Receipt source must be the controller's actual installed source. Container
    coordinates are provenance only, never operations accepted from the panel.
    Human receipt remains unverified until a separate receipt contract exists.
    """
    if (
        not 0 < len(raw) <= _ADMIN_RECEIPT_LIMIT
        or re.fullmatch(r"[0-9a-f]{40}", expected_source_sha) is None
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise ValueError("Telegram observation is not verifiable")
    document = json.loads(raw, object_pairs_hook=_unique_admin_fields)
    if (
        not isinstance(document, dict)
        or set(document) != _ADMIN_FIELDS
        or type(document["version"]) is not int
        or document["version"] != 1
        or document["source_sha"] != expected_source_sha
    ):
        raise ValueError("Telegram observation is not verifiable")
    source_sha = _admin_string(document, "source_sha", r"[0-9a-f]{40}")
    observation_run = _admin_string(document, "observation_run_id", r"[1-9][0-9]{0,19}")
    installation_run = _admin_string(document, "installation_run_id", r"[1-9][0-9]{0,19}")
    controller = _admin_string(document, "controller_id", r"[0-9a-f]{64}")
    worker = _admin_string(document, "worker_id", r"[0-9a-f]{64}")
    sender_id = (
        None
        if document["sender_id"] is None
        else _admin_string(document, "sender_id", r"[0-9a-f]{64}")
    )
    timestamp = _admin_string(document, "observed_at", r"[0-9T:.+Z-]{20,40}")
    observed_at = datetime.fromisoformat(timestamp)
    configured = _admin_string(document, "configured", r"ABSENT|VERIFIED|UNVERIFIED")
    paired = _admin_string(document, "paired", r"NOT_PAIRED|VERIFIED|UNVERIFIED")
    sender = _admin_string(document, "sender", r"ABSENT|STOPPED|RUNNING|UNVERIFIED")
    identities = (controller, worker) if sender_id is None else (controller, worker, sender_id)
    if (
        len(set(identities)) != len(identities)
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or observed_at > now
        or (sender == "ABSENT" and sender_id is not None)
        or (sender in ("STOPPED", "RUNNING") and sender_id is None)
        or (paired == "VERIFIED" and configured != "VERIFIED")
        or document["human_receipt"] != "UNVERIFIED"
    ):
        raise ValueError("Telegram observation is not verifiable")
    return TelegramHostObservation(
        source_sha=source_sha,
        observation_run_id=observation_run,
        installation_run_id=installation_run,
        controller_id=controller,
        worker_id=worker,
        sender_id=sender_id,
        observed_at=observed_at.astimezone(UTC),
        configured=cast(TelegramConfiguredState, configured),
        paired=cast(TelegramPairingState, paired),
        sender=cast(TelegramSenderState, sender),
    )


def _admin_file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or not 0 < metadata.st_size <= _ADMIN_RECEIPT_LIMIT
    ):
        raise ValueError("Telegram observation file is not verifiable")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_admin_receipt(path: Path) -> bytes:
    before = _admin_file_identity(path.lstat())
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if _admin_file_identity(os.fstat(descriptor)) != before:
            raise ValueError("Telegram observation file changed")
        raw = os.read(descriptor, _ADMIN_RECEIPT_LIMIT + 1)
        if (
            len(raw) != before[2]
            or _admin_file_identity(os.fstat(descriptor)) != before
            or _admin_file_identity(path.lstat()) != before
        ):
            raise ValueError("Telegram observation file changed")
        return raw
    finally:
        os.close(descriptor)


def load_telegram_admin(
    database_path: Path,
    *,
    staging_available: bool,
    expected_source_sha: str,
    now: datetime,
) -> TelegramAdminSnapshot:
    """Read optional host evidence and recent notices without creating anything.

    An absent or invalid host receipt cannot erase authentic local delivery
    history. An old receipt is retained explicitly as historical evidence; none
    of these reads installs custody, pairs a chat, migrates or starts a sender.
    """
    if (
        not database_path.is_absolute()
        or ".." in database_path.parts
        or type(staging_available) is not bool
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise ValueError("private Telegram administration configuration invalid")
    observation = None
    receipt_state: TelegramReceiptState
    try:
        raw = _read_admin_receipt(database_path.with_name(TELEGRAM_ADMIN_RECEIPT_FILENAME))
    except FileNotFoundError:
        receipt_state = "ABSENT"
    except (OSError, ValueError):
        receipt_state = "INVALID"
    else:
        try:
            observation = parse_telegram_admin_receipt(
                raw, expected_source_sha=expected_source_sha, now=now
            )
        except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
            receipt_state = "INVALID"
        else:
            age = (now - observation.observed_at).total_seconds()
            receipt_state = "FRESH" if age <= TELEGRAM_ADMIN_FRESH_SECONDS else "STALE"
    try:
        notices = list_local_notices(Database(database_path), limit=20)
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError):
        notices, history_available = (), False
    else:
        history_available = True
    return TelegramAdminSnapshot(
        observed_at=now.astimezone(UTC),
        staging_available=staging_available,
        receipt_state=receipt_state,
        host_observation=observation,
        history_available=history_available,
        notices=notices,
    )


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
